"""Command line entry point: `scripts/rnsmoke <command>` (or `python3 -m rnsmoke <command>`)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .util import UserError, git_user_name, info, read_json, short, warn
from .workspace import Workspace, select_cases


def _ws(args) -> Workspace:
    return Workspace(args.project, args.workspace)


def _csv(value: Optional[str]) -> List[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# --------------------------------------------------------------------------- commands

def cmd_doctor(args) -> int:
    from . import doctor

    items = doctor.check(args.platform)
    if args.json:
        _print_json(items)
    else:
        print(doctor.render(items))
    problems = doctor.blocking(items)
    if problems and not args.json:
        print(f"\n{len(problems)} blocking problem(s): {', '.join(p['name'] for p in problems)}")
    return 1 if problems else 0


def cmd_analyze(args) -> int:
    from . import project

    data = project.analyze(Path(args.project))
    _print_json(data) if args.json else print(project.summarize(data))
    return 0


def cmd_init(args) -> int:
    ws = _ws(args)
    created = ws.ensure()
    config = ws.load_config()
    apps = config.setdefault("app", {})
    detected = None
    if not (args.ios_app_id or args.android_app_id) and not apps:
        from . import project

        detected = project.analyze(ws.project)
        for platform in ("ios", "android"):
            installed = [i["id"] for i in detected["installed"][platform]]
            candidates = installed or detected["app_id_candidates"][platform]
            if candidates:
                apps[platform] = {"appId": candidates[0], "detected": True}
    if args.ios_app_id:
        apps["ios"] = {"appId": args.ios_app_id}
    if args.android_app_id:
        apps["android"] = {"appId": args.android_app_id}
    if args.metro_port:
        config.setdefault("metro", {})["port"] = args.metro_port
    ws.save_config(config)
    print(f"Workspace: {ws.root}")
    for item in created:
        print(f"  created {item}")
    for platform, app in apps.items():
        flag = "  (auto-detected - verify!)" if app.get("detected") else ""
        print(f"  {platform} appId = {app['appId']}{flag}")
    if not apps:
        print("  No app id detected. Set it: rnsmoke init --ios-app-id <bundle id> --android-app-id <package>")
    if not ws.env_path.exists():
        print(f"  Put test accounts / data in {ws.env_path} (see .env.example); it is git-ignored.")
    return 0


def cmd_cases(args) -> int:
    from . import testcases

    ws = _ws(args)
    ws.ensure()
    doc = testcases.load_cases(Path(args.input), args.sheet)
    ws.save_cases(doc)
    moved = ws.relink(doc["cases"])
    print(testcases.summarize(doc))
    if moved:
        print(f"Relinked {len(moved)} edited case(s) to their existing flows (review them): "
              + ", ".join(cid for cid, _ in moved))
    report = ws.status_report()
    counts = {}
    for row in report["cases"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("Coverage: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"Saved: {ws.cases_path}")
    return 0


def cmd_template(args) -> int:
    from . import template

    cases = None
    if args.from_json:
        data = read_json(Path(args.from_json).expanduser(), None)
        if data is None:
            raise UserError(f"Cannot read {args.from_json}")
        cases = data.get("cases") if isinstance(data, dict) else data
        if not isinstance(cases, list):
            raise UserError("--from must contain a JSON list of cases (or {\"cases\": [...]})")
    path = template.write_template(Path(args.out), args.title, cases, args.version)
    print(f"Wrote {path}" + (f" with {len(cases)} case(s)" if cases else " (blank template)"))
    return 0


def cmd_status(args) -> int:
    ws = _ws(args)
    report = ws.status_report()
    if args.json:
        _print_json(report)
        return 0
    rows = report["cases"]
    print(f"Workspace: {ws.root}")
    print(f"Cases    : {len(rows)} from sheet '{report['source']['sheet']}' of {Path(report['source']['path']).name}")
    sections = {}
    for row in rows:
        stats = sections.setdefault(row["section"], {s: 0 for s in ("automated", "manual", "blocked", "todo")})
        stats[row["status"]] = stats.get(row["status"], 0) + 1
    print(f"\n{'Section':<40} {'total':>5} {'auto':>5} {'manual':>6} {'block':>5} {'todo':>5}")
    totals = {"automated": 0, "manual": 0, "blocked": 0, "todo": 0}
    for section, stats in sections.items():
        for k in totals:
            totals[k] += stats.get(k, 0)
        print(f"{short(section, 40):<40} {sum(stats.values()):>5} {stats['automated']:>5} {stats['manual']:>6} "
              f"{stats['blocked']:>5} {stats['todo']:>5}")
    print(f"{'TOTAL':<40} {len(rows):>5} {totals['automated']:>5} {totals['manual']:>6} {totals['blocked']:>5} "
          f"{totals['todo']:>5}")
    todo = [r["id"] for r in rows if r["status"] == "todo"]
    if todo:
        print(f"\nTODO ({len(todo)}): {', '.join(todo)}")
    for warning in report.get("warnings") or []:
        print(f"\nWARNING: {warning}")
    problems = [r for r in rows if r["problems"]]
    if problems:
        print("\nProblems:")
        for row in problems:
            for problem in row["problems"]:
                print(f"  {row['id']}: {problem}")
    if report["orphans"]:
        print(f"\n{len(report['orphans'])} manifest entr(y/ies) no longer match any case (sheet edited?): "
              + ", ".join(report["orphans"][:10]))
    if args.verbose:
        print()
        for row in rows:
            extra = row.get("flow") or row.get("reason") or ""
            print(f"  {row['id']:<10} {row['status']:<9} {short(row['section'], 24):<24} "
                  f"{short(row['description'], 60):<60} {short(extra, 60)}")
    return 0


def cmd_mark(args) -> int:
    ws = _ws(args)
    cases = select_cases(ws.load_cases()["cases"], args.ids, args.section)
    if not cases:
        raise UserError("Select cases with ids (TC-001, TC-001..TC-005) and/or --section")
    if args.flow:
        status, reason = "automated", None
    elif args.manual:
        status, reason = "manual", args.manual
    elif args.blocked:
        status, reason = "blocked", args.blocked
    elif args.todo:
        status, reason = "todo", None
    else:
        raise UserError("Choose one of --flow FILE | --manual REASON | --blocked REASON | --todo")
    rel = ws.mark(cases, status, flow=args.flow, reason=reason, platforms=_csv(args.platforms) or None,
                  requires=_csv(args.requires) if args.requires is not None else None, uncovered=args.partial)
    print(f"Marked {len(cases)} case(s) as {status}{' -> ' + rel if rel else ''}: {', '.join(c['id'] for c in cases)}")
    return 0


def cmd_device_setup(args) -> int:
    from . import devices
    from .util import TEMPLATES_DIR, require_maestro, run

    maestro = require_maestro()
    device = devices.resolve_device(args.platform, args.device)
    flows = sorted((TEMPLATES_DIR / "device").glob(f"{args.platform}-*.yaml"))
    if not flows:
        print(f"No device setup needed for {args.platform}.")
        return 0
    failed = 0
    for flow in flows:
        res = run([maestro, "test", "--udid", device.id, str(flow)], timeout=600)
        ok = res.returncode == 0
        failed += not ok
        print(f"[{'OK' if ok else 'FAILED'}] {flow.stem} on {device.label()}")
        if not ok:
            print("  " + short(res.stdout.strip().splitlines()[-1] if res.stdout.strip() else res.stderr, 300))
            print(f"  Do it by hand if your OS version differs: see the comments in {flow}")
    return 1 if failed else 0


def cmd_inspect(args) -> int:
    from . import hierarchy

    ws = _ws(args)
    env = ws.env_vars()
    if args.flow:
        try:
            env.update(APP_ID=ws.app_id(args.platform), PLATFORM=args.platform)
        except UserError:
            pass
    flow = Path(args.flow).expanduser().resolve() if args.flow else None
    if flow and not flow.exists():
        flow = ws.flow_path(args.flow)
    result = hierarchy.inspect(args.platform, ws.inspect_dir, args.device, flow, env)
    print(f"Device: {result['device']}")
    if result.get("flow"):
        print(f"Navigation flow exit code: {result['flow']['exit_code']}")
    print(f"{len(result['elements'])} element(s) with text / id / accessibility label:")
    for line in result["elements"]:
        print("  " + line)
    if result.get("screenshot"):
        print(f"Screenshot: {result['screenshot']}")
    print(f"Saved: {result['elements_file']}")
    return 0


def cmd_metro(args) -> int:
    from . import metro

    ws = _ws(args)
    port = args.port or ws.metro_port()
    pid_file, log_file = ws.root / ".metro.pid", ws.runs_dir / "metro.log"
    if args.action == "status":
        print(f"Metro on port {port}: {'running' if metro.is_running(port) else 'not running'}")
        return 0 if metro.is_running(port) else 1
    if args.action == "stop":
        metro.stop(pid_file, port)
        return 0
    ws.ensure()
    metro.start(ws.project, pid_file, log_file, port, _csv(args.prewarm))
    return 0


def cmd_run(args) -> int:
    from . import runner

    ws = _ws(args)
    if args.failed and not args.run_dir:
        args.run_dir = "latest"         # re-running failures only makes sense inside an existing run
    doc = runner.run(ws, args.platform, device_id=args.device, only=args.only, sections=args.section,
                     failed_only=args.failed, run_dir_arg=args.run_dir, retries=args.retries,
                     batch_size=args.batch_size, video=args.video, flow_timeout=args.timeout,
                     skip_metro_check=args.skip_metro_check, reinstall_driver=args.reinstall_driver,
                     dry_run=args.dry_run)
    bad = [r for r in doc.get("results", {}).values() if r["status"] in ("fail", "error")]
    return 1 if bad and not args.dry_run else 0


def _load_runs(run_dir: Path) -> List[dict]:
    runs = [d for d in (read_json(p, None) for p in run_dir.glob("results-*.json")) if d]
    order = {"ios": 0, "android": 1}               # same order as the IOS / ANDROID columns
    return sorted(runs, key=lambda d: (order.get(d.get("platform"), 9), d.get("platform") or ""))


def cmd_results(args) -> int:
    from . import runner

    ws = _ws(args)
    run_dir = ws.resolve_run_dir(args.run_dir)
    runs = _load_runs(run_dir)
    if args.json:
        _print_json(runs)
        return 0
    print(f"Run: {run_dir}")
    for doc in runs:
        print(runner.summary_text(doc))
        for rec in doc["results"].values():
            if rec["status"] in ("fail", "error") and (rec.get("evidence") or rec.get("log")):
                print(f"    {rec['id']}: evidence={rec.get('evidence')} log={rec.get('log')} step={rec.get('failed_step')}")
    return 0


def cmd_set_result(args) -> int:
    from . import runner

    ws = _ws(args)
    run_dir = ws.resolve_run_dir(args.run_dir)
    cases = select_cases(read_json(run_dir / "cases.json", None)["cases"], args.ids)
    for case in cases:
        runner.set_result(run_dir, args.platform, case, args.status, args.message)
    print(f"Updated {len(cases)} case(s) in {run_dir.name}/results-{args.platform}.json -> {args.status}")
    return 0


def cmd_rclone_setup(args) -> int:
    import shutil
    import subprocess

    from . import upload

    binary = shutil.which("rclone")
    if not binary:
        raise UserError("rclone is not installed: brew install rclone  (or https://rclone.org/install/)")
    remote = args.remote
    if upload.rclone_remote_ready(remote) and not args.reconnect:
        print(f"rclone remote '{remote}:' is already set up (use --reconnect to sign in again).")
        return 0
    print("A browser window will open: sign in with your company Google account and click Allow.\n"
          "(rclone's own Google app, scope drive.file = only files rclone creates; no admin setup needed)")
    cmd = ([binary, "config", "reconnect", f"{remote}:"] if upload.rclone_remote_ready(remote)
           else [binary, "config", "create", remote, "drive", "scope=drive.file"])
    proc = subprocess.run(cmd, timeout=900)
    if proc.returncode != 0 or not upload.rclone_remote_ready(remote):
        raise UserError("rclone setup did not complete (browser sign-in cancelled or blocked)")
    code, out, err = upload._rclone_cmd(["lsd", f"{remote}:"], timeout=120)
    if code != 0:
        raise UserError(f"rclone cannot reach Google Drive: {short(err or out, 300)}")
    print(f"Google Drive connected through rclone remote '{remote}:'. Use: rnsmoke export --upload rclone")
    return 0


def cmd_drive_login(args) -> int:
    from . import gdrive

    client_file = args.client_file
    if not client_file:
        try:
            gdrive.load_client()
        except UserError:
            downloaded = gdrive.find_downloaded_client()
            if not downloaded:
                raise
            print(f"Using the OAuth client downloaded at {downloaded}")
            client_file = str(downloaded)
    if client_file:
        print(f"OAuth client saved to {gdrive.import_client(Path(client_file))}")
    record = gdrive.login(open_browser=not args.no_browser)
    print(f"Signed in to Google Drive as {record.get('account')} (scope: drive.file)")
    return 0


def cmd_upload(args) -> int:
    from . import upload

    ws = _ws(args)
    if args.list_hosts:
        for name, host in upload.HOSTS.items():
            print(f"{name:<10} {host.summary}")
        return 0
    run_dir = ws.resolve_run_dir(args.run_dir)
    runs = _load_runs(run_dir)
    if args.platforms:
        runs = [r for r in runs if r.get("platform") in _csv(args.platforms)]
    if args.dry_run:
        plan = upload.plan_uploads(run_dir, runs, args.host)
        for item in plan:
            print(f"{item['action'][:60]:<60} {item['bytes'] / 1024:>8.0f} KB  {item['file']}")
        todo = [i for i in plan if i["action"] == "upload"]
        print(f"\n{len(todo)} file(s), {sum(i['bytes'] for i in todo) / 1048576:.1f} MB would be uploaded to "
              f"{args.host} - anyone allowed by that host's link settings can open them: "
              f"{upload.HOSTS[args.host].summary}")
        return 0
    links = upload.upload_evidence(run_dir, runs, args.host, expire=args.expire, force=args.force,
                                   share=args.share)
    for rel, url in links.items():
        print(f"{rel}\t{url}")
    print(f"Cached in {run_dir / upload.CACHE_FILE}; `rnsmoke export --upload {args.host}` reuses these links.")
    return 0


def cmd_export(args) -> int:
    from . import report

    ws = _ws(args)
    run_dir = ws.resolve_run_dir(args.run_dir)
    cases_doc = read_json(run_dir / "cases.json", None) or ws.load_cases()
    runs = _load_runs(run_dir)
    if args.platforms:
        runs = [r for r in runs if r.get("platform") in _csv(args.platforms)]
    run_date = dt.date.fromisoformat(args.date) if args.date else None
    tester = args.tester or f"Maestro automation ({git_user_name()})".replace(" ()", "")
    links = None
    if args.upload:
        from . import upload

        links = upload.upload_evidence(run_dir, runs, args.upload, expire=args.expire, share=args.share)
    result = report.export(cases_doc, runs, run_dir, input_path=args.input, out_path=args.out,
                           tab_name=args.tab_name, tester=tester, build=args.build, run_date=run_date,
                           fill_ids=not args.no_fill_ids, only_new_tab=args.only_new_tab, also_xls=args.xls,
                           links=links)
    check = report.verify(Path(result["output"]), result["sheet"], cases_doc)
    if check != result["counts"]:
        warn(f"Verification mismatch: wrote {result['counts']} but read back {check}")
    print(f"Excel : {result['output']}")
    if result.get("xls"):
        print(f"XLS   : {result['xls']}")
    print(f"Tab   : '{result['sheet']}' (cloned from '{result['source_sheet']}')")
    print("Result: " + ", ".join(f"{k}={v}" for k, v in sorted(result["counts"].items())))
    if result.get("evidence_links"):
        print("Evidence links: " + ", ".join(f"{k}={v}" for k, v in sorted(result["evidence_links"].items())))
    if result["summary_cells"]:
        print("Summary cells: " + "; ".join(result["summary_cells"]))
    return 0


# --------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rnsmoke", description="Maestro smoke tests for React Native + Excel report")
    parser.add_argument("--version", action="version", version=f"rnsmoke {__version__}")
    parser.add_argument("-C", "--project", default=".", help="React Native project root (default: .)")
    parser.add_argument("--workspace", help="Workspace dir (default: <project>/.maestro/smoke)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="check tools and devices")
    p.add_argument("--platform", choices=("all", "ios", "android"), default="all")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("analyze", help="inspect the RN project (app ids, builds, installed apps)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("init", help="create .maestro/smoke and set app ids")
    p.add_argument("--ios-app-id")
    p.add_argument("--android-app-id")
    p.add_argument("--metro-port", type=int)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("cases", help="parse the test-case sheet (.xlsx/.csv)")
    p.add_argument("--input", required=True)
    p.add_argument("--sheet", help="tab name (default: the visible/active test-case tab)")
    p.set_defaults(func=cmd_cases)

    p = sub.add_parser("template", help="write a standard checklist (blank or from generated cases)")
    p.add_argument("--out", required=True, help=".xlsx or .csv")
    p.add_argument("--from", dest="from_json", help="JSON list of {section, description, expected, ...}")
    p.add_argument("--title", default="Smoke Test Checklist")
    p.add_argument("--version", default="v1.0")
    p.set_defaults(func=cmd_template)

    p = sub.add_parser("status", help="automation coverage per section")
    p.add_argument("--json", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("mark", help="link cases to a flow or mark them manual / blocked / todo")
    p.add_argument("ids", nargs="*", help="TC-001, TC-001..TC-005, row:12 or case keys")
    p.add_argument("--section", action="append", help="select every case of a section (repeatable)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--flow", help="flow file (relative to the workspace)")
    group.add_argument("--manual", metavar="REASON")
    group.add_argument("--blocked", metavar="REASON")
    group.add_argument("--todo", action="store_true")
    p.add_argument("--platforms", help="ios,android (default: from the Platform column)")
    p.add_argument("--requires", help="env vars the flow needs, e.g. TEST_EMAIL,TEST_PASSWORD")
    p.add_argument("--partial", metavar="NOT_COVERED", help="flow covers only part of the expected result")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("device-setup", help="one-time simulator tweaks (iOS: disable strong-password sheet)")
    p.add_argument("--platform", choices=("ios", "android"), required=True)
    p.add_argument("--device")
    p.set_defaults(func=cmd_device_setup)

    p = sub.add_parser("inspect", help="list on-screen elements (+ screenshot) to write selectors")
    p.add_argument("--platform", choices=("ios", "android"), required=True)
    p.add_argument("--device")
    p.add_argument("--flow", help="run this flow first to reach the screen")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("metro", help="start/stop/status of the Metro bundler")
    p.add_argument("action", choices=("start", "stop", "status"))
    p.add_argument("--port", type=int)
    p.add_argument("--prewarm", help="pre-build bundles for ios,android")
    p.set_defaults(func=cmd_metro)

    p = sub.add_parser("run", help="run the automated cases with Maestro")
    p.add_argument("--platform", choices=("ios", "android"), required=True)
    p.add_argument("--device", help="simulator UDID / emulator serial or name")
    p.add_argument("--only", action="append", help="case ids/ranges (repeatable or comma separated)")
    p.add_argument("--section", action="append")
    p.add_argument("--failed", action="store_true", help="re-run only fail/error cases (default run dir: latest)")
    p.add_argument("--run-dir", help="'latest' or a path to add to an existing run (default: new run)")
    p.add_argument("--retries", type=int, default=1)
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--video", action="store_true", help="record a video per case (runs flows one by one)")
    p.add_argument("--timeout", type=int, default=600, help="seconds per flow")
    p.add_argument("--skip-metro-check", action="store_true")
    p.add_argument("--reinstall-driver", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("results", help="summarise a run")
    p.add_argument("--run-dir", default="latest")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_results)

    p = sub.add_parser("set-result", help="reclassify cases after triage (never to PASS)")
    p.add_argument("ids", nargs="+")
    p.add_argument("--platform", choices=("ios", "android"), required=True)
    p.add_argument("--status", choices=("fail", "blocked", "manual", "error"), required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--run-dir", default="latest")
    p.set_defaults(func=cmd_set_result)

    p = sub.add_parser("rclone-setup", help="one-time Google Drive sign-in through rclone (no admin setup)")
    p.add_argument("--remote", default=os.environ.get("RNSMOKE_RCLONE_REMOTE", "rnsmoke-gdrive"))
    p.add_argument("--reconnect", action="store_true", help="sign in again (expired / other account)")
    p.set_defaults(func=cmd_rclone_setup)

    p = sub.add_parser("drive-login", help="one-time Google sign-in for --upload gdrive (scope: drive.file)")
    p.add_argument("--no-browser", action="store_true", help="only print the sign-in URL")
    p.add_argument("--client-file", help="company 'Desktop app' OAuth client JSON to install first")
    p.set_defaults(func=cmd_drive_login)

    p = sub.add_parser("upload", help="upload evidence (gdrive, or a public free host) and cache the URLs")
    p.add_argument("--run-dir", default="latest")
    p.add_argument("--host", default="gdrive",
                   help="gdrive (default, Google Drive with your OAuth client) | rclone | droplr | catbox | "
                        "litterbox | imgbb")
    p.add_argument("--expire", help="litterbox: 1h|12h|24h|72h; imgbb: e.g. 30d")
    p.add_argument("--share", choices=("none", "domain", "anyone"), default="none",
                   help="gdrive: also share the run folder (default: private)")
    p.add_argument("--platforms", help="limit to ios / android evidence")
    p.add_argument("--force", action="store_true", help="upload again even if a cached link exists")
    p.add_argument("--dry-run", action="store_true", help="list what would be published; no network")
    p.add_argument("--list-hosts", action="store_true")
    p.set_defaults(func=cmd_upload)

    p = sub.add_parser("export", help="write the Excel report with a new dated tab")
    p.add_argument("--run-dir", default="latest")
    p.add_argument("--input", help="original .xlsx/.csv (default: the parsed source)")
    p.add_argument("--out", help="output .xlsx (default: <run-dir>/<input name> - <DDMM>.xlsx)")
    p.add_argument("--tab-name", help="default: run date as DDMM, e.g. 2710")
    p.add_argument("--date", help="run date YYYY-MM-DD (default: run start date)")
    p.add_argument("--tester", help='"Tested by" value')
    p.add_argument("--build", help='"Build version" value (default: app version from the run)')
    p.add_argument("--platforms", help="limit to ios / android results")
    p.add_argument("--no-fill-ids", action="store_true", help="do not write TC-xxx into an empty Test ID column")
    p.add_argument("--only-new-tab", action="store_true", help="write a workbook containing only the new tab")
    p.add_argument("--xls", action="store_true", help="also convert to legacy .xls (needs LibreOffice)")
    p.add_argument("--upload", metavar="HOST", help="upload evidence to HOST (rclone | gdrive | droplr | catbox | litterbox "
                                                    "| imgbb) and put the URLs in the IOS / ANDROID cells")
    p.add_argument("--expire", help="with --upload: litterbox 1h|12h|24h|72h, imgbb e.g. 30d")
    p.add_argument("--share", choices=("none", "domain", "anyone"), default="none",
                   help="with --upload gdrive: share the run folder (default: private)")
    p.set_defaults(func=cmd_export)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except UserError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
