"""The per-project Maestro workspace, by default <rn-project>/.maestro/smoke/

  config.json    app ids per platform, Metro port
  cases.json     the last parsed test-case sheet
  manifest.json  case key -> {status: automated|manual|blocked|todo, flow, reason, ...}
  flows/         one Maestro flow per test case, grouped by section
  subflows/      shared steps (launch, login, navigation)
  .env           test data / credentials passed to flows as ${VAR} (git-ignored)
  runs/<stamp>/  results-<platform>.json, evidence/, logs/, maestro artifacts, the exported .xlsx
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .util import TEMPLATES_DIR, UserError, fold, now_iso, read_json, write_json

GITIGNORE = ".env\nruns/\ninspect/\n.metro.pid\n"
STATUSES = ("automated", "manual", "blocked", "todo")
RELINK_THRESHOLD = 0.85


class Workspace:
    def __init__(self, project: Optional[str] = None, root: Optional[str] = None):
        self.project = Path(project or ".").expanduser().resolve()
        self.root = Path(root).expanduser().resolve() if root else self.project / ".maestro" / "smoke"

    # ------------------------------------------------------------------ paths
    @property
    def flows_dir(self) -> Path:
        return self.root / "flows"

    @property
    def subflows_dir(self) -> Path:
        return self.root / "subflows"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def inspect_dir(self) -> Path:
        return self.root / "inspect"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def cases_path(self) -> Path:
        return self.root / "cases.json"

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def env_path(self) -> Path:
        return self.root / ".env"

    def rel(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def flow_path(self, rel: str) -> Path:
        path = Path(rel)
        return path if path.is_absolute() else (self.root / path).resolve()

    # ------------------------------------------------------------------ setup
    def ensure(self) -> List[str]:
        created = []
        for directory in (self.flows_dir, self.subflows_dir, self.runs_dir):
            if not directory.exists():
                directory.mkdir(parents=True)
                created.append(self.rel(directory) + "/")
        gitignore = self.root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(GITIGNORE, encoding="utf-8")
            created.append(".gitignore")
        example = self.root / ".env.example"
        if not example.exists():
            shutil.copyfile(TEMPLATES_DIR / "env.example", example)
            created.append(".env.example")
        for template in sorted((TEMPLATES_DIR / "subflows").glob("*.yaml")):
            target = self.subflows_dir / template.name
            if not target.exists():
                shutil.copyfile(template, target)
                created.append(self.rel(target))
        example_flow = self.flows_dir / "_example" / "example-flow.yaml"
        if not example_flow.exists():
            example_flow.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATES_DIR / "flow-example.yaml", example_flow)
            created.append(self.rel(example_flow))
        if not self.config_path.exists():
            self.save_config({"app": {}, "metro": {"port": 8081}})
            created.append("config.json")
        if not self.manifest_path.exists():
            self.save_manifest({"version": 1, "cases": {}})
            created.append("manifest.json")
        return created

    # ------------------------------------------------------------------ documents
    def load_config(self) -> dict:
        return read_json(self.config_path, {"app": {}, "metro": {"port": 8081}})

    def save_config(self, config: dict) -> None:
        write_json(self.config_path, config)

    def app_id(self, platform: str) -> str:
        app_id = ((self.load_config().get("app") or {}).get(platform) or {}).get("appId")
        if not app_id:
            raise UserError(f"No {platform} app id configured. Run: rnsmoke init --{platform}-app-id <bundle-or-package-id>")
        return app_id

    def metro_port(self) -> int:
        return int((self.load_config().get("metro") or {}).get("port") or 8081)

    def load_manifest(self) -> dict:
        manifest = read_json(self.manifest_path, None) or {"version": 1, "cases": {}}
        manifest.setdefault("cases", {})
        return manifest

    def save_manifest(self, manifest: dict) -> None:
        write_json(self.manifest_path, manifest)

    def load_cases(self) -> dict:
        doc = read_json(self.cases_path, None)
        if not doc:
            raise UserError("No parsed test cases yet. Run: rnsmoke cases --input <test-case .xlsx/.csv>")
        return doc

    def save_cases(self, doc: dict) -> None:
        write_json(self.cases_path, doc)

    def env_vars(self) -> Dict[str, str]:
        values: Dict[str, str] = {}
        if not self.env_path.exists():
            return values
        for raw in self.env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                values[key] = value
        return values

    # ------------------------------------------------------------------ runs
    def new_run_dir(self) -> Path:
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = self.runs_dir / stamp
        path.mkdir(parents=True, exist_ok=False)
        return path

    def latest_run_dir(self) -> Optional[Path]:
        if not self.runs_dir.exists():
            return None
        runs = sorted(p for p in self.runs_dir.iterdir() if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}_", p.name))
        return runs[-1] if runs else None

    def resolve_run_dir(self, value: Optional[str], create: bool = False) -> Path:
        if value in (None, "", "new"):
            if create:
                return self.new_run_dir()
            value = "latest"
        if value == "latest":
            latest = self.latest_run_dir()
            if latest is None:
                raise UserError(f"No runs yet in {self.runs_dir}. Run `rnsmoke run` first.")
            return latest
        path = Path(value).expanduser()
        if not path.is_absolute() and not path.exists():
            path = self.runs_dir / value
        if not path.exists():
            raise UserError(f"Run directory not found: {value}")
        return path.resolve()

    # ------------------------------------------------------------------ manifest operations
    def relink(self, cases: List[dict]) -> List[Tuple[str, str]]:
        """Re-attach manifest entries whose case text was slightly edited in the sheet."""
        manifest = self.load_manifest()
        entries = manifest["cases"]
        current = {c["key"]: c for c in cases}
        orphans = {k: v for k, v in entries.items() if k not in current}
        moved: List[Tuple[str, str]] = []
        for case in cases:
            entry = entries.get(case["key"])
            if entry is not None:
                entry.update(id=case["id"], row=case["row"])
                continue
            best, score = None, 0.0
            probe = fold(case["description"]) + " | " + fold(case["expected"])
            for key, orphan in orphans.items():
                if fold(orphan.get("section")) != fold(case["section"]):
                    continue
                ratio = difflib.SequenceMatcher(
                    None, fold(orphan.get("description")) + " | " + fold(orphan.get("expected")), probe).ratio()
                if ratio > score:
                    best, score = key, ratio
            if best is not None and score >= RELINK_THRESHOLD:
                entry = orphans.pop(best)
                entries.pop(best, None)
                entry.update(id=case["id"], row=case["row"], description=case["description"],
                             expected=case["expected"], relinked_from=best, needs_review=True)
                entries[case["key"]] = entry
                moved.append((case["id"], best))
        self.save_manifest(manifest)
        return moved

    def mark(self, cases: List[dict], status: str, flow: Optional[str] = None, reason: Optional[str] = None,
             platforms: Optional[List[str]] = None, requires: Optional[List[str]] = None,
             uncovered: Optional[str] = None) -> str:
        if status not in STATUSES:
            raise UserError(f"Unknown status '{status}'")
        rel = None
        if status == "automated":
            if not flow:
                raise UserError("--flow is required to mark a case as automated")
            path = Path(flow).expanduser()
            if not path.is_absolute():
                path = path.resolve() if path.exists() else (self.root / flow).resolve()
            if not path.exists():
                raise UserError(f"Flow file not found: {flow} (paths are relative to {self.root})")
            rel = self.rel(path)
        manifest = self.load_manifest()
        for case in cases:
            entry = manifest["cases"].get(case["key"], {})
            entry.update(id=case["id"], row=case["row"], section=case["section"],
                         description=case["description"], expected=case["expected"],
                         status=status, updated_at=now_iso())
            entry.pop("needs_review", None)
            if rel:
                entry["flow"] = rel
            if status == "todo":
                entry.pop("flow", None)
            if reason is not None:
                entry["reason"] = reason
            elif status == "automated":
                entry.pop("reason", None)
            if platforms:
                entry["platforms"] = platforms
            if requires is not None:
                entry["requires"] = requires
            if uncovered:
                entry["coverage"], entry["uncovered"] = "partial", uncovered
            elif status == "automated" and flow:
                entry.pop("coverage", None)
                entry.pop("uncovered", None)
            manifest["cases"][case["key"]] = entry
        self.save_manifest(manifest)
        return rel or ""

    def status_report(self) -> dict:
        doc = self.load_cases()
        manifest = self.load_manifest()
        keys = {c["key"] for c in doc["cases"]}
        rows = []
        for case in doc["cases"]:
            entry = manifest["cases"].get(case["key"]) or {}
            status = entry.get("status", "todo")
            problems = []
            if status == "automated":
                flow = entry.get("flow")
                path = self.flow_path(flow) if flow else None
                if not path:
                    problems.append("no flow path")
                elif not path.exists():
                    problems.append(f"flow file missing: {flow}")
                else:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    if "takeScreenshot" not in text:
                        problems.append("flow has no takeScreenshot step (no evidence)")
                    if "appId" not in text.split("\n---", 1)[0]:
                        problems.append("flow header has no appId")
            if entry.get("needs_review"):
                problems.append(f"relinked from {entry.get('relinked_from')} after the case text changed - review the flow")
            rows.append({"id": case["id"], "key": case["key"], "row": case["row"], "section": case["section"],
                         "status": status, "flow": entry.get("flow"), "reason": entry.get("reason"),
                         "requires": entry.get("requires"), "coverage": entry.get("coverage", "full"),
                         "problems": problems, "description": case["description"]})
        warnings = []
        for subflow in sorted(self.subflows_dir.glob("*.yaml")) if self.subflows_dir.exists() else []:
            if "FIRST_SCREEN_TEXT" in subflow.read_text(encoding="utf-8", errors="replace"):
                warnings.append(f"subflows/{subflow.name} still waits for the FIRST_SCREEN_TEXT placeholder - "
                                "replace it with text from the app's first screen")
        return {"source": doc["source"], "cases": rows, "warnings": warnings,
                "orphans": sorted(k for k in manifest["cases"] if k not in keys)}


def select_cases(cases: List[dict], selectors: Optional[Iterable[str]] = None,
                 sections: Optional[Iterable[str]] = None) -> List[dict]:
    """Select by id (TC-007), id range (TC-001..TC-010), key, row:<n> and/or section name."""
    tokens = [t.strip() for s in (selectors or []) for t in str(s).split(",") if t.strip()]
    wanted_sections = [fold(s) for s in (sections or []) if s]
    if not tokens and not wanted_sections:
        return list(cases)
    by_id = {fold(c["id"]): i for i, c in enumerate(cases)}
    chosen: Dict[int, dict] = {}
    for token in tokens:
        if ".." in token:
            start, end = (fold(x) for x in token.split("..", 1))
            if start not in by_id or end not in by_id:
                raise UserError(f"Unknown id in range '{token}'")
            for i in range(by_id[start], by_id[end] + 1):
                chosen[i] = cases[i]
            continue
        match = None
        if fold(token) in by_id:
            match = by_id[fold(token)]
        elif token.lower().startswith("row:"):
            row = int(token.split(":", 1)[1])
            match = next((i for i, c in enumerate(cases) if c["row"] == row), None)
        else:
            match = next((i for i, c in enumerate(cases) if c["key"] == token), None)
        if match is None:
            raise UserError(f"Unknown test case '{token}' (use ids like TC-007, a key, or row:<n>)")
        chosen[match] = cases[match]
    names = {fold(c["section"]) for c in cases}
    for wanted in wanted_sections:
        # exact section name first ("Home" must not pull in "Home - My Booking"), else substring
        exact = wanted in names
        for i, case in enumerate(cases):
            section = fold(case["section"])
            if section == wanted or (not exact and wanted in section):
                chosen[i] = case
    if wanted_sections and not chosen:
        raise UserError(f"No section matches {', '.join(sections or [])}")
    return [chosen[i] for i in sorted(chosen)]
