"""Run Maestro flows for the selected test cases and record per-case results + evidence.

Flows run in batches (one `maestro test` invocation per batch keeps the device
driver warm). Flows that are missing from a batch report, or that fail, are
re-run one by one so a single crash or flaky step does not poison the rest.

Per-case statuses written to runs/<stamp>/results-<platform>.json:
  pass | fail            the flow ran; fail = an assertion/step failed (app bug OR flow bug - triage it)
  error                  infrastructure problem (driver, Metro, syntax, app not launchable) - not an app verdict
  manual | blocked       from the manifest (not automatable / missing test data)
  not_automated          no flow yet
  skipped                case does not apply to this platform
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import devices, metro
from .util import UserError, fold, info, now_iso, read_json, require_maestro, short, slugify, warn, write_json
from .workspace import Workspace, select_cases

RAN = ("pass", "fail")
INFRA_PATTERNS = (
    (r"unknown property|parsing failed|unable to parse|invalid command|mapping values|cannot deserialize|"
     r"could not deserialize|unrecognized field|while parsing a|while scanning a", "Invalid Maestro flow syntax"),
    (r"flow file .*(not found|does not exist)|no such file", "Flow file (or a runFlow subflow) not found"),
    (r"unable to launch app|failed to launch|is not installed|app not installed|no app with", "The app could not be launched"),
    (r"no (connected )?devices?|device .*(not found|offline|unauthorized)", "Device not available"),
    (r"failed to connect|connection refused|io exception|xctest.*(fail|timed out)|driver.*(fail|timed out|not ready)|"
     r"deadline exceeded|unavailable:", "Maestro lost the connection to the device driver"),
)
NOT_RETRYABLE = ("Invalid Maestro flow syntax", "Flow file (or a runFlow subflow) not found")
DEV_SERVER_TEXT = ("could not connect to development server", "no bundle url present", "unable to load script",
                   "metro has encountered an error", "no script url provided")
REDBOX_TEXT = ("render error", "unhandled js exception", "invariant violation", "referenceerror:", "typeerror:",
               "syntaxerror:", "uncaught error")


@dataclass
class FlowJob:
    path: Path
    rel: str
    name: str
    cases: List[dict]
    attempts: int = 0
    last: Optional["Outcome"] = None


@dataclass
class Outcome:
    status: str
    message: str = ""
    duration: float = 0.0
    failed_step: Optional[str] = None
    artifacts: Optional[Path] = None
    screenshot: Optional[Path] = None
    video: Optional[Path] = None
    log: Optional[Path] = None
    retryable: bool = True


def flow_name(path: Path) -> str:
    """The name Maestro reports for a flow: `name:` from the header, else the file stem."""
    text = path.read_text(encoding="utf-8", errors="replace")
    header = text.split("\n---", 1)[0] if "\n---" in text else ""
    match = re.search(r"^name:\s*(.+?)\s*$", header, re.M)
    return match.group(1).strip().strip("\"'") if match else path.stem


def parse_junit(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    found = []
    for tc in root.iter("testcase"):
        failure = tc.find("failure")
        if failure is None:
            failure = tc.find("error")
        status = (tc.get("status") or "").upper()
        failed = failure is not None or status in ("ERROR", "FAILURE", "FAILED")
        message = ""
        if failure is not None:
            message = (failure.text or failure.get("message") or "").strip()
        found.append({"name": tc.get("name") or "", "file": tc.get("file") or "", "failed": failed,
                      "skipped": status == "SKIPPED", "message": message, "time": float(tc.get("time") or 0)})
    return found


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", fold(text))


def find_artifacts(out_dir: Path, name: str) -> Optional[Path]:
    stamps = sorted((p for p in out_dir.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime) if out_dir.exists() else []
    for stamp in reversed(stamps):
        children = [p for p in stamp.iterdir() if p.is_dir()]
        for child in children:
            if child.name == name:
                return child
        for child in children:
            if _alnum(child.name) == _alnum(name):
                return child
    return None


def pick_screenshot(artifacts: Optional[Path], status: str) -> Optional[Path]:
    if not artifacts:
        return None

    def pngs(sub: str) -> List[Path]:
        folder = artifacts / sub
        return sorted(folder.glob("*.png"), key=lambda p: p.stat().st_mtime) if folder.exists() else []

    taken, failure = pngs("takeScreenshot"), pngs("screenshots")
    preferred = [p for p in taken if p.stem.lower().startswith("evidence")]
    order = (preferred, taken, failure) if status == "pass" else (failure, preferred, taken)
    for group in order:
        if group:
            return group[-1]
    return None


def describe_failed_step(artifacts: Optional[Path]) -> Optional[str]:
    commands = read_json(artifacts / "commands.json", None) if artifacts else None
    if not isinstance(commands, list):
        return None
    failed = [c for c in commands if ((c.get("metadata") or {}).get("status") == "FAILED")]
    if not failed:
        return None
    entry = failed[-1]
    command = entry.get("command") or {}
    if not command:
        return None
    kind, body = next(iter(command.items()))
    kind = re.sub(r"Command$", "", kind)
    selector = _first_selector(body)
    seq = (entry.get("metadata") or {}).get("sequenceNumber")
    prefix = f"#{seq + 1} " if isinstance(seq, int) else ""
    return f'{prefix}{kind}' + (f' "{short(selector, 80)}"' if selector else "")


def _first_selector(body) -> Optional[str]:
    if isinstance(body, dict):
        for key in ("textRegex", "idRegex", "text", "id", "link", "selector"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        for value in body.values():
            found = _first_selector(value)
            if found:
                return found
    elif isinstance(body, list):
        for value in body:
            found = _first_selector(value)
            if found:
                return found
    return None


def classify_failure(message: str, artifacts: Optional[Path], log_text: str) -> Outcome:
    screen = ""
    if artifacts and (artifacts / "screen-hierarchy").exists():
        for file in sorted((artifacts / "screen-hierarchy").glob("*.json"))[-2:]:
            screen += file.read_text(encoding="utf-8", errors="replace").lower()
    if any(text in screen for text in DEV_SERVER_TEXT):
        return Outcome("error", "App shows a Metro/dev-server error screen - start Metro (`rnsmoke metro start`) "
                                f"or install a release build. ({short(message, 120)})")
    lowered = fold(message) or fold(log_text[-2000:])
    for pattern, hint in INFRA_PATTERNS:
        if re.search(pattern, lowered):
            return Outcome("error", f"{hint}: {short(message or log_text[-400:], 300)}",
                           retryable=hint not in NOT_RETRYABLE)
    if any(text in screen for text in REDBOX_TEXT):
        return Outcome("fail", f"{message} (the app shows a JavaScript error screen)")
    return Outcome("fail", message or "Flow failed (see Maestro log)")


def _log_failure_reason(log_text: str, name: str) -> str:
    for line in log_text.splitlines():
        match = re.search(r"\[Failed\]\s+(.+?)\s+\((?:\d+m\s*)?\d+s\)\s+\((.*)\)\s*$", line)
        if match and _alnum(match.group(1)) == _alnum(name):
            return match.group(2)
    return ""


def _invocation_error(log_text: str) -> str:
    lines = [l.strip() for l in log_text.splitlines()
             if l.strip() and not re.match(r"^[│╭╰─\s]", l.strip()) and not l.startswith("$ ")]
    noise = ("maestro cloud", "debug tests faster", "run your flows on", "waiting for flows")
    lines = [l for l in lines if not any(n in l.lower() for n in noise)]
    return short(" | ".join(lines[-3:]), 400)


class Executor:
    """Wraps `maestro test` invocations for one device."""

    def __init__(self, maestro: str, device: devices.Device, run_dir: Path, env: Dict[str, str],
                 flow_timeout: int, video: bool, reinstall_driver: bool):
        self.maestro, self.device, self.run_dir, self.env = maestro, device, run_dir, env
        self.flow_timeout, self.video = flow_timeout, video
        self.reinstall_next = reinstall_driver
        self.counter = 0

    def _spawn(self, cmd: List[str], log: Path, timeout: int):
        log.parent.mkdir(parents=True, exist_ok=True)
        shown = []
        for i, arg in enumerate(cmd):
            shown.append(re.sub(r"=.*", "=***", arg) if i and cmd[i - 1] == "-e" else arg)
        with log.open("w", encoding="utf-8") as fh:
            fh.write("$ " + " ".join(shlex.quote(a) for a in shown) + "\n")
            fh.flush()
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
            try:
                return proc.wait(timeout=timeout), False
            except subprocess.TimeoutExpired:
                self._kill(proc)
                return -9, True
            except KeyboardInterrupt:
                self._kill(proc)
                raise

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def execute(self, jobs: List[FlowJob]) -> Dict[int, Outcome]:
        self.counter += 1
        single = len(jobs) == 1
        tag = (f"s{self.counter:03d}-{slugify(jobs[0].cases[0]['id'], 24)}" if single else f"b{self.counter:03d}")
        out_dir = self.run_dir / "maestro" / self.device.platform / tag
        junit = out_dir / "report.xml"
        log = self.run_dir / "logs" / self.device.platform / f"{tag}.log"
        cmd = [self.maestro, "test", "--udid", self.device.id, "--format", "junit", "--output", str(junit),
               "--test-output-dir", str(out_dir)]
        if not self.reinstall_next:
            cmd.append("--no-reinstall-driver")
        for key, value in self.env.items():
            cmd += ["-e", f"{key}={value}"]
        cmd += [str(job.path) for job in jobs]

        recorder = None
        if self.video and single:
            recorder = devices.Recorder(self.device, self.run_dir / "evidence" / self.device.platform /
                                        f"{slugify(jobs[0].cases[0]['id'], 40)}.mp4")
            recorder.start()
        started = time.time()
        rc, timed_out = self._spawn(cmd, log, self.flow_timeout * len(jobs))
        video = recorder.stop() if recorder else None
        self.reinstall_next = False

        log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        reports = parse_junit(junit)
        outcomes: Dict[int, Outcome] = {}
        for idx, job in enumerate(jobs):
            # Reports come back in execution order; consume them so equal names map one-to-one.
            pos = next((i for i, r in enumerate(reports) if _alnum(r["name"]) == _alnum(job.name)), None)
            if pos is None:
                same_file = [i for i, r in enumerate(reports) if r["file"] == job.path.name]
                pos = same_file[0] if len(same_file) == 1 else None
            report = reports.pop(pos) if pos is not None else None
            if report is None or report["skipped"]:
                continue
            artifacts = find_artifacts(out_dir, report["name"] or job.name)
            if report["failed"]:
                message = report["message"] or _log_failure_reason(log_text, job.name)
                outcome = classify_failure(message, artifacts, log_text)
            else:
                outcome = Outcome("pass")
            outcome.duration = report["time"]
            outcome.artifacts = artifacts
            outcome.failed_step = describe_failed_step(artifacts) if outcome.status != "pass" else None
            outcome.screenshot = pick_screenshot(artifacts, outcome.status)
            outcome.video = video
            outcome.log = log
            outcomes[idx] = outcome

        if single and 0 not in outcomes:
            if timed_out:
                outcomes[0] = Outcome("error", f"Timed out after {self.flow_timeout}s", log=log, video=video)
            else:
                message = _invocation_error(log_text) or f"maestro exited with code {rc}"
                outcome = classify_failure(message, None, log_text)
                if outcome.status == "fail":
                    outcome.status = "error"
                outcome.log, outcome.duration = log, time.time() - started
                outcomes[0] = outcome
        if any(o.status == "error" and "driver" in o.message.lower() for o in outcomes.values()) or (
                rc not in (0, 1) and not outcomes):
            self.reinstall_next = True
        return outcomes


def _case_record(case: dict, entry: dict, status: str, message: str = "", **extra) -> dict:
    record = {"id": case["id"], "section": case["section"], "row": case["row"], "status": status,
              "message": message, "finished_at": now_iso()}
    if entry.get("coverage") == "partial":
        record["coverage"], record["uncovered"] = "partial", entry.get("uncovered")
    record.update({k: v for k, v in extra.items() if v is not None})
    return record


def run(ws: Workspace, platform: str, device_id: Optional[str] = None, only: Optional[List[str]] = None,
        sections: Optional[List[str]] = None, failed_only: bool = False, run_dir_arg: Optional[str] = None,
        retries: int = 1, batch_size: int = 10, video: bool = False, flow_timeout: int = 600,
        skip_metro_check: bool = False, reinstall_driver: bool = False, dry_run: bool = False) -> dict:
    maestro = require_maestro()
    app_id = ws.app_id(platform)
    device = devices.resolve_device(platform, device_id)
    app = devices.app_info(device, app_id)
    if not app.get("installed"):
        raise UserError(f"{app_id} is not installed on {device.label()}. Build/install the app first "
                        "(see reference/build-and-install.md), or fix the app id with `rnsmoke init`.")
    port = ws.metro_port()
    if app.get("debug") and not skip_metro_check:
        if platform == "android":
            devices.adb_reverse(device, port)
        if not metro.is_running(port):
            raise UserError(f"{app_id} is a debug build that loads JavaScript from Metro, but Metro is not running "
                            f"on port {port}. Start it with `rnsmoke metro start` (or pass --skip-metro-check "
                            "if the build bundles its JS).")

    fresh = run_dir_arg in (None, "", "new")
    run_dir = ws.runs_dir / "<new run>" if dry_run and fresh else ws.resolve_run_dir(run_dir_arg, create=fresh)
    snapshot = run_dir / "cases.json"
    if snapshot.exists():
        cases_doc = read_json(snapshot)
    else:
        cases_doc = ws.load_cases()
        if not dry_run:
            write_json(snapshot, cases_doc)
    manifest = ws.load_manifest()["cases"]
    results_path = run_dir / f"results-{platform}.json"
    doc = read_json(results_path, None) or {"version": 1, "platform": platform, "started_at": now_iso(), "results": {}}
    doc.update(device=device.to_dict(), app=app, workspace=str(ws.root), cases_file="cases.json")

    selected = select_cases(cases_doc["cases"], only, sections)
    if failed_only:
        selected = [c for c in selected if (doc["results"].get(c["key"]) or {}).get("status") in ("fail", "error")]
        if not selected:
            info("No failed/error cases in this run - nothing to re-run.")
            return doc

    env = ws.env_vars()
    env.update(APP_ID=app_id, PLATFORM=platform)
    jobs: Dict[str, FlowJob] = {}
    for case in selected:
        entry = manifest.get(case["key"]) or {}
        status = entry.get("status", "todo")
        record = None
        if status in ("manual", "blocked"):
            record = _case_record(case, entry, status, entry.get("reason") or status)
        elif status != "automated" or not entry.get("flow"):
            record = _case_record(case, entry, "not_automated", entry.get("reason") or "No Maestro flow for this case yet")
        elif platform not in (entry.get("platforms") or case.get("platforms") or [platform]):
            record = _case_record(case, entry, "skipped", f"Not applicable on {platform}")
        else:
            path = ws.flow_path(entry["flow"])
            missing_vars = [v for v in entry.get("requires") or [] if not env.get(v)]
            if not path.exists():
                record = _case_record(case, entry, "error", f"Flow file missing: {entry['flow']}", flow=entry["flow"])
            elif missing_vars:
                record = _case_record(case, entry, "blocked",
                                      f"Missing test data {', '.join(missing_vars)} (set in {ws.rel(ws.env_path)})",
                                      flow=entry["flow"])
            else:
                job = jobs.setdefault(str(path), FlowJob(path, ws.rel(path), flow_name(path), []))
                job.cases.append(case)
        if record is not None:
            doc["results"][case["key"]] = record

    queue = list(jobs.values())
    info(f"[{platform}] {device.label()} | app {app_id} {app.get('version') or ''} ({app.get('build') or '?'})"
         f"{' debug' if app.get('debug') else ''}")
    info(f"[{platform}] {len(selected)} case(s) selected, {len(queue)} flow(s) to run -> {run_dir}")
    if dry_run:
        for job in queue:
            info(f"  would run {job.rel}  ({', '.join(c['id'] for c in job.cases)})")
        return doc
    write_json(results_path, doc)

    executor = Executor(maestro, device, run_dir, env, flow_timeout, video, reinstall_driver)
    progress = run_dir / f"progress-{platform}.log"

    def record(job: FlowJob, outcome: Outcome) -> None:
        job.last = outcome
        for case in job.cases:
            evidence = None
            target_dir = run_dir / "evidence" / platform
            if outcome.screenshot and outcome.screenshot.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / f"{slugify(case['id'], 40)}.png"
                shutil.copyfile(outcome.screenshot, target)
                evidence = target.relative_to(run_dir).as_posix()
            video_rel = None
            if outcome.video and outcome.video.exists():
                video_rel = outcome.video.relative_to(run_dir).as_posix()
                evidence = evidence or video_rel
            doc["results"][case["key"]] = _case_record(
                case, manifest.get(case["key"]) or {}, outcome.status, outcome.message, flow=job.rel,
                duration_s=round(outcome.duration, 1), attempts=job.attempts, failed_step=outcome.failed_step,
                evidence=evidence, video=video_rel,
                artifacts=outcome.artifacts.relative_to(run_dir).as_posix() if outcome.artifacts else None,
                log=outcome.log.relative_to(run_dir).as_posix() if outcome.log else None)
            line = f"  {outcome.status.upper():5} {case['id']:<10} {short(case['section'], 28):<28} {short(case['description'], 70)}"
            if outcome.status != "pass":
                line += f"\n        -> {short(outcome.message, 220)}"
            info(line)
            with progress.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        write_json(results_path, doc)

    def execute(batch: List[FlowJob]) -> List[FlowJob]:
        outcomes = executor.execute(batch)
        missing = []
        for idx, job in enumerate(batch):
            job.attempts += 1
            if idx in outcomes:
                record(job, outcomes[idx])
            else:
                missing.append(job)
        return missing

    size = 1 if video else max(1, batch_size)
    for start in range(0, len(queue), size):
        batch = queue[start:start + size]
        info(f"[{platform}] batch {start // size + 1}/{(len(queue) + size - 1) // size}: {len(batch)} flow(s)")
        for job in execute(batch):
            info(f"  (no report for {job.rel} in the batch - running it alone)")
            for leftover in execute([job]):
                record(leftover, Outcome("error", "Maestro produced no result for this flow", retryable=False))

    for _ in range(max(0, retries)):
        again = [j for j in queue if j.last and j.last.status in ("fail", "error") and j.last.retryable]
        if not again:
            break
        info(f"[{platform}] retrying {len(again)} failed flow(s) one by one")
        for job in again:
            for leftover in execute([job]):
                record(leftover, Outcome("error", "Maestro produced no result for this flow", retryable=False))

    doc["finished_at"] = now_iso()
    write_json(results_path, doc)
    info(summary_text(doc))
    return doc


def summary_text(doc: dict) -> str:
    counts: Dict[str, int] = {}
    for rec in doc["results"].values():
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    order = ("pass", "fail", "error", "blocked", "manual", "not_automated", "skipped")
    parts = [f"{k}={counts[k]}" for k in order if counts.get(k)]
    lines = [f"[{doc.get('platform')}] results: " + (", ".join(parts) or "none")]
    for rec in doc["results"].values():
        if rec["status"] in ("fail", "error"):
            lines.append(f"  {rec['status'].upper():5} {rec['id']:<10} {short(rec.get('message'), 160)}")
    return "\n".join(lines)


def set_result(run_dir: Path, platform: str, case: dict, status: str, message: str) -> dict:
    """Manual reclassification after triage. PASS can only come from a real Maestro run."""
    if status not in ("fail", "blocked", "manual", "error"):
        raise UserError("set-result accepts fail | blocked | manual | error (PASS must come from a Maestro run)")
    path = run_dir / f"results-{platform}.json"
    doc = read_json(path, None)
    if not doc:
        raise UserError(f"No results for {platform} in {run_dir}")
    record = doc["results"].get(case["key"]) or {"id": case["id"], "section": case["section"], "row": case["row"]}
    previous = record.get("status")
    record.update(status=status, message=message, overridden=True, overridden_from=previous, finished_at=now_iso())
    if status == "fail":
        record["actual"] = message
    doc["results"][case["key"]] = record
    write_json(path, doc)
    return record
