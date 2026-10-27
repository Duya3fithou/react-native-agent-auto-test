"""Static look at a React Native project: app ids, versions, build entry points, testability hints.

Secrets are never printed: from .env files only keys that look like app identifiers are read.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import devices
from .util import UserError, read_json

SOURCE_DIRS = ("src", "app", "screens", "components", "navigation", "features", "modules")
SOURCE_EXT = {".js", ".jsx", ".ts", ".tsx"}
ID_ENV_KEYS = re.compile(r"^(PRODUCT_BUNDLE_IDENTIFIER|BUNDLE_ID|IOS_BUNDLE_ID|APP_ID|APPLICATION_ID|ANDROID_APP_ID|"
                         r"PACKAGE_NAME|ANDROID_PACKAGE|APP_IDENTIFIER)$")
REVERSE_DNS = re.compile(r"^[A-Za-z][\w-]*(\.[A-Za-z0-9_-]+)+$")
EXTENSION_HINT = re.compile(r"(extension|widget|tests?|intents|notificationservice|share|clip)$", re.I)


def _unique(values) -> List[str]:
    seen, out = set(), []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _env_ids(project: Path) -> Dict[str, Dict[str, str]]:
    found: Dict[str, Dict[str, str]] = {}
    for env_file in sorted(project.glob(".env*")):
        if not env_file.is_file() or env_file.name.endswith((".example", ".sample")):
            continue
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, value = (x.strip().strip("'\"") for x in line.split("=", 1))
            if ID_ENV_KEYS.match(key) and REVERSE_DNS.match(value):
                found.setdefault(env_file.name, {})[key] = value
    return found


def _ios(project: Path) -> dict:
    ios_dir = project / "ios"
    if not ios_dir.exists():
        return {}
    data: dict = {
        "workspace": next((p.name for p in sorted(ios_dir.glob("*.xcworkspace"))), None),
        "project": next((p.name for p in sorted(ios_dir.glob("*.xcodeproj"))), None),
        "schemes": sorted({p.stem for p in ios_dir.glob("*.xcodeproj/xcshareddata/xcschemes/*.xcscheme")}),
        "bundle_ids": [], "marketing_versions": [], "build_numbers": [],
        "pods_installed": (ios_dir / "Pods").exists(),
    }
    for pbx in ios_dir.glob("*.xcodeproj/project.pbxproj"):
        text = pbx.read_text(encoding="utf-8", errors="replace")
        ids = [v.strip('"') for v in re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);", text)]
        data["bundle_ids"] += [i for i in ids if "$(" not in i and "${" not in i and not EXTENSION_HINT.search(i.split(".")[-1])]
        data["marketing_versions"] += re.findall(r"MARKETING_VERSION = ([^;]+);", text)
        data["build_numbers"] += re.findall(r"CURRENT_PROJECT_VERSION = ([^;]+);", text)
    for key in ("bundle_ids", "marketing_versions", "build_numbers"):
        data[key] = _unique(data[key])
    return data


def _android(project: Path) -> dict:
    gradle = next((p for p in (project / "android/app/build.gradle", project / "android/app/build.gradle.kts")
                   if p.exists()), None)
    if not gradle:
        return {}
    text = gradle.read_text(encoding="utf-8", errors="replace")
    base = re.findall(r'applicationId\s*=?\s*["\']([\w.]+)["\']', text)
    env_based = re.findall(r'applicationId\s*=?\s*\w+\.get\(\s*["\'](\w+)["\']', text)
    suffixes = _unique(re.findall(r'applicationIdSuffix\s*=?\s*["\']([\w.]+)["\']', text))
    flavors: List[str] = []
    block = re.search(r"productFlavors\s*\{", text)
    if block:
        depth, i, start = 1, block.end(), block.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        flavors = re.findall(r"^\s*(?:create\(\")?(\w+)\"?\)?\s*\{", text[start:i], re.M)
    ids = list(base)
    for app_id in base:
        ids += [app_id + (s if s.startswith(".") else "." + s) for s in suffixes]
    return {
        "gradle": str(gradle.relative_to(project)),
        "application_ids": _unique(ids),
        "application_id_from_env": env_based,
        "suffixes": suffixes,
        "flavors": flavors,
        "version_name": next(iter(re.findall(r'versionName\s*=?\s*["\']([^"\']+)["\']', text)), None),
        "version_code": next(iter(re.findall(r"versionCode\s*=?\s*(\d+)", text)), None),
    }


def _expo(project: Path) -> dict:
    app_json = read_json(project / "app.json", {}) or {}
    expo = app_json.get("expo") or {}
    data = {"ios": (expo.get("ios") or {}).get("bundleIdentifier"),
            "android": (expo.get("android") or {}).get("package")}
    for name in ("app.config.js", "app.config.ts"):
        cfg = project / name
        if cfg.exists():
            text = cfg.read_text(encoding="utf-8", errors="replace")
            data["ios"] = data["ios"] or next(iter(re.findall(r"bundleIdentifier\s*:\s*['\"]([\w.]+)", text)), None)
            data["android"] = data["android"] or next(iter(re.findall(r"package\s*:\s*['\"]([\w.]+)", text)), None)
    return {k: v for k, v in data.items() if v}


def _source_stats(project: Path) -> dict:
    files: List[Path] = []
    for name in SOURCE_DIRS:
        root = project / name
        if root.is_dir():
            files += [p for p in root.rglob("*") if p.suffix in SOURCE_EXT and "node_modules" not in p.parts]
    for name in ("App.js", "App.tsx", "App.jsx", "App.ts"):
        if (project / name).exists():
            files.append(project / name)
    test_ids = labels = 0
    screens: List[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        test_ids += len(re.findall(r"\btestID\s*=", text))
        labels += len(re.findall(r"\baccessibilityLabel\s*=", text))
        screens += re.findall(r"\.Screen\b[^>]*?\bname=\{?\s*['\"]?([\w.\-]+)", text, re.S)
    i18n: List[str] = []
    skip = {"node_modules", "ios", "android", ".git", "Pods", "build", "vendor", ".yarn", ".maestro", "dist"}
    for root, dirs, names in os.walk(project):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        if re.search(r"(locale|i18n|lang|translation)", root[len(str(project)):], re.I):
            i18n += [str((Path(root) / n).relative_to(project)) for n in names if n.endswith(".json")]
        if len(i18n) >= 10:
            break
    return {"source_files": len(files), "testID_count": test_ids, "accessibilityLabel_count": labels,
            "screens": _unique(screens)[:150], "i18n_files": i18n}


def analyze(project: Path, check_devices: bool = True) -> dict:
    project = Path(project).expanduser().resolve()
    pkg = read_json(project / "package.json", None)
    if pkg is None:
        raise UserError(f"{project} has no package.json - point --project at the React Native app root.")
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    manager = next((m for f, m in (("yarn.lock", "yarn"), ("pnpm-lock.yaml", "pnpm"), ("bun.lockb", "bun"),
                                   ("package-lock.json", "npm")) if (project / f).exists()), "npm")
    scripts = {k: v for k, v in (pkg.get("scripts") or {}).items()
               if re.search(r"ios|android|start|build|e2e|maestro|detox|env|apk|aab", f"{k} {v}", re.I)}
    ios, android, expo, env_ids = _ios(project), _android(project), _expo(project), _env_ids(project)
    env_values = [v for values in env_ids.values() for v in values.values()]
    candidates = {
        "ios": _unique(ios.get("bundle_ids", []) + [expo.get("ios")] + env_values),
        "android": _unique(android.get("application_ids", []) + [expo.get("android")] + env_values),
    }
    installed: Dict[str, List[dict]] = {"ios": [], "android": []}
    if check_devices:
        for platform in ("ios", "android"):
            for device in devices.list_devices(platform):
                for app_id in candidates[platform]:
                    info = devices.app_info(device, app_id)
                    if info.get("installed"):
                        installed[platform].append({"device": device.label(), **info})
    return {
        "project": str(project),
        "name": pkg.get("name"),
        "version": pkg.get("version"),
        "react_native": deps.get("react-native"),
        "expo": deps.get("expo"),
        "package_manager": manager,
        "node_modules": (project / "node_modules").exists(),
        "scripts": scripts,
        "ios": ios,
        "android": android,
        "expo_config": expo,
        "env_app_ids": env_ids,
        "app_id_candidates": candidates,
        "installed": installed,
        "maestro_dir_exists": (project / ".maestro").exists(),
        "source": _source_stats(project),
    }


def summarize(data: dict) -> str:
    lines = [f"Project : {data['project']}  ({data.get('name')} {data.get('version')})",
             f"RN      : {data.get('react_native')}" + (f"  Expo {data['expo']}" if data.get("expo") else "")
             + f"  | package manager: {data['package_manager']}  | node_modules: {'yes' if data['node_modules'] else 'NO'}"]
    ios, android = data.get("ios") or {}, data.get("android") or {}
    if ios:
        lines.append(f"iOS     : {ios.get('workspace') or ios.get('project')}  schemes={ios.get('schemes')}  "
                     f"bundle ids={ios.get('bundle_ids')}  pods={'yes' if ios.get('pods_installed') else 'no'}")
    if android:
        lines.append(f"Android : ids={android.get('application_ids')}  flavors={android.get('flavors')}  "
                     f"suffixes={android.get('suffixes')}"
                     + (f"  id-from-env={android['application_id_from_env']}" if android.get("application_id_from_env") else ""))
    if data.get("env_app_ids"):
        lines.append("Env ids : " + json.dumps(data["env_app_ids"]))
    lines.append(f"Candidate app ids: ios={data['app_id_candidates']['ios']}  android={data['app_id_candidates']['android']}")
    for platform in ("ios", "android"):
        for item in data["installed"][platform]:
            lines.append(f"Installed on {platform}: {item['id']} {item.get('version') or ''} ({item.get('build') or '?'})"
                         f"{' DEBUG (needs Metro)' if item.get('debug') else ' release'} on {item['device']}")
    if not any(data["installed"].values()):
        lines.append("Installed: no candidate app id found on any booted simulator / connected emulator")
    lines.append("Scripts : " + ", ".join(f"{k}" for k in data["scripts"]))
    src = data["source"]
    lines.append(f"Source  : {src['source_files']} files, testID x{src['testID_count']}, "
                 f"accessibilityLabel x{src['accessibilityLabel_count']}, {len(src['screens'])} screens"
                 + (f", i18n: {src['i18n_files'][:3]}" if src["i18n_files"] else ", no local i18n files (copy may come from the server)"))
    return "\n".join(lines)
