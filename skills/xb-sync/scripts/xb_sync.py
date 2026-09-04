#!/usr/bin/env python3
"""Discover, register, and safely reconcile xbskill memory roots across local agents.

Design rules (see ../SKILL.md):
- Read-only by default; every mutating action needs --apply and prints a plan first.
- Never overwrite: identical relpath with different content goes to a conflicts inbox.
- progress.md and memory-settings.md are project-local and never copied.
- ontology/ stores are never auto-merged; cross-root retrieval is done by fan-out query.
- Stdlib only, Python 3.10+.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import stat
import uuid
from pathlib import Path

PRIVATE_DIRS = {".codex", ".claude", ".kimi", ".zcode", ".kimi_openclaw", "doubao"}
PRUNE_DIRS = PRIVATE_DIRS | {".git", "node_modules", "__pycache__", ".venv", "venv"}
NEVER_COPY = {"progress.md", "memory-settings.md", "memory-homes.json"}
REGISTRY_VERSION = 1


def eprint(*args):
    print(*args, file=sys.stderr)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def checked(path: Path) -> Path:
    path = Path(os.path.abspath(path.expanduser()))
    if any(part.lower() in PRIVATE_DIRS for part in path.parts):
        raise ValueError(f"E_PRIVATE_PATH: {path}")
    for item in [path, *path.parents]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"E_LINK: {item}")
    return path


def is_memory_root(path: Path) -> bool:
    path = checked(path)
    return path.is_dir() and path.name == "xbskill" and path.parent.name == "memory"


def find_roots(scan_root: Path, max_depth: int = 8) -> list[Path]:
    scan_root = checked(scan_root)
    if max_depth < 0:
        raise ValueError("E_DEPTH: max-depth must be nonnegative")
    found = []
    def onerror(error):
        raise error
    for dirpath, dirnames, _ in os.walk(scan_root, followlinks=False, onerror=onerror):
        current = checked(Path(dirpath))
        if is_memory_root(current):
            found.append(current)
            dirnames[:] = []
            continue
        keep = []
        for name in dirnames:
            child = current / name
            if name.lower() in PRUNE_DIRS or len(child.relative_to(scan_root).parts) > max_depth:
                print(f"EXCLUDED_SCAN: {child}")
                continue
            checked(child)
            keep.append(name)
        dirnames[:] = keep
    return sorted(set(found))


def tree_hashes(root: Path) -> dict[str, str]:
    root = checked(root)
    if not root.is_dir():
        raise ValueError(f"E_ROOT_MISSING: {root}")
    result = {}
    def onerror(error):
        raise error
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=onerror):
        for name in dirnames + filenames:
            checked(Path(dirpath) / name)
        for name in filenames:
            p = Path(dirpath) / name
            if not p.is_file():
                raise ValueError(f"E_FILE_TYPE: {p}")
            result[p.relative_to(root).as_posix()] = sha256_file(p)
    return result


def root_report(root: Path) -> dict:
    root = checked(root)
    tree_hashes(root)
    report = {
        "root": str(root),
        "exists": root.is_dir(),
        "sessions": [],
        "context_files": [],
        "loose_files": [],
        "has_ontology_store": (root / "ontology" / "entities.json").is_file(),
        "has_progress": (root / "progress.md").is_file(),
    }
    if not root.is_dir():
        return report
    sessions_dir = root / "sessions"
    if sessions_dir.is_dir():
        report["sessions"] = sorted(
            d.name for d in sessions_dir.iterdir() if d.is_dir()
        )
    context_dir = root / "context"
    if context_dir.is_dir():
        report["context_files"] = sorted(
            p.relative_to(root).as_posix()
            for p in context_dir.rglob("*")
            if p.is_file()
        )
    report["loose_files"] = sorted(
        p.name
        for p in root.iterdir()
        if p.is_file() and p.name not in NEVER_COPY
    )
    return report


def load_registry(path: Path, allow_new: bool = False) -> dict:
    path = checked(path)
    if not path.is_file():
        if allow_new:
            return {"version": REGISTRY_VERSION, "canonical": None, "roots": []}
        raise ValueError(f"E_REGISTRY_MISSING: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("version") != REGISTRY_VERSION or not isinstance(data.get("roots"), list):
        raise ValueError(f"E_REGISTRY_SCHEMA: {path}")
    seen = set()
    for entry in data["roots"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not Path(entry["path"]).is_absolute():
            raise ValueError("E_REGISTRY_SCHEMA: absolute root path required")
        root = checked(Path(entry["path"]))
        if not root.is_dir():
            raise ValueError(f"E_ROOT_MISSING: {root}")
        if not is_memory_root(root):
            raise ValueError(f"E_HOME_INVALID: {root}")
        key = os.path.normcase(str(root))
        if key in seen:
            raise ValueError(f"E_REGISTRY_SCHEMA: duplicate root {root}")
        seen.add(key)
    if data.get("canonical"):
        if os.path.normcase(str(checked(Path(data["canonical"])))) not in seen:
            raise ValueError("E_REGISTRY_SCHEMA: canonical must be registered")
    return data


def save_registry(path: Path, data: dict) -> None:
    path = checked(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with tmp.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    checked(path)
    os.replace(tmp, path)


def register_roots(registry: dict, roots: list[Path]) -> list[str]:
    known = {r["path"] for r in registry["roots"]}
    added = []
    for root in roots:
        key = str(root.resolve())
        if key not in known:
            registry["roots"].append(
                {
                    "path": key,
                    "role": "satellite",
                    "added_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "last_seen": dt.datetime.now().isoformat(timespec="seconds"),
                }
            )
            added.append(key)
        else:
            for r in registry["roots"]:
                if r["path"] == key:
                    r["last_seen"] = dt.datetime.now().isoformat(timespec="seconds")
    return added


def get_roots_from_registry(registry: dict) -> list[Path]:
    return [Path(r["path"]) for r in registry.get("roots", [])]


def cmd_discover(args) -> int:
    scan_root = checked(Path(args.scan_root))
    if not scan_root.is_dir():
        eprint(f"E_PATH: scan root not found: {scan_root}")
        return 2
    roots = find_roots(scan_root, max_depth=args.max_depth)
    print(f"# discover report (scan_root={scan_root.resolve()})")
    print(f"memory roots found: {len(roots)}")
    for root in roots:
        rep = root_report(root)
        print(
            f"- {rep['root']} | sessions={len(rep['sessions'])} "
            f"context_files={len(rep['context_files'])} "
            f"ontology_store={rep['has_ontology_store']} progress={rep['has_progress']}"
        )
    if args.registry:
        reg_path = Path(args.registry)
        registry = load_registry(reg_path, allow_new=True)
        added = register_roots(registry, roots)
        if args.apply:
            save_registry(reg_path, registry)
        else:
            print("dry-run registry; add --apply to register")
        print(f"registry: {reg_path.resolve()} (newly registered: {len(added)})")
    else:
        print("registry: not requested (pass --registry <path> to register)")
    return 0


def cmd_status(args) -> int:
    registry = load_registry(Path(args.registry))
    roots = get_roots_from_registry(registry)
    print(f"# status report (registry={Path(args.registry).resolve()})")
    print(f"canonical: {registry.get('canonical') or '(not set)'}")
    missing = [str(r) for r in roots if not r.is_dir()]
    for r in roots:
        rep = root_report(r)
        if not rep["exists"]:
            print(f"- {r} | MISSING on disk")
            continue
        print(
            f"- {rep['root']} | sessions={len(rep['sessions'])} "
            f"context_files={len(rep['context_files'])} "
            f"loose_files={len(rep['loose_files'])} "
            f"ontology_store={rep['has_ontology_store']}"
        )
    if missing:
        eprint(f"E_ROOT_MISSING: {len(missing)} registered root(s) not on disk")
        return 1
    return 0


def plan_sync(home: Path, satellites: list[Path]) -> dict:
    home_hashes = tree_hashes(home)
    virtual = dict(home_hashes)
    plan = {"copy": [], "skip_identical": [], "conflict": [], "excluded": [], "ontology_manual": [], "quarantine": []}
    for sat in satellites:
        sat_hashes = tree_hashes(sat)
        source_id = hashlib.sha256(str(checked(sat)).encode()).hexdigest()
        sessions = {r.split("/")[1] for r in sat_hashes if r.startswith("sessions/") and len(r.split("/")) >= 3}
        collisions = set()
        conflict_prefixes = {}
        for sid in sessions:
            prefix = f"sessions/{sid}/"
            incoming = {r: h for r, h in sat_hashes.items() if r.startswith(prefix)}
            present = {r: h for r, h in virtual.items() if r.startswith(prefix)}
            if present and present != incoming:
                collisions.add(sid)
                conflict_prefix = f"conflicts/{source_id}/"
                previous_group = {r[len(conflict_prefix):]: h for r, h in virtual.items() if r.startswith(conflict_prefix + prefix)}
                if previous_group and previous_group != incoming:
                    group_hash = hashlib.sha256(json.dumps(incoming, sort_keys=True).encode()).hexdigest()
                    conflict_prefix = f"conflicts/{source_id}/versions/{group_hash}/"
                conflict_prefixes[sid] = conflict_prefix
        for rel, digest in sorted(sat_hashes.items()):
            parts = rel.split("/")
            kind, target = "copy", rel
            if parts[0] == "ontology":
                kind = "ontology_manual"
            elif parts[0] in {"imports", "conflicts"} or parts[0] in NEVER_COPY or parts[0].startswith("."):
                kind = "excluded"
            elif parts[0] == "sessions" and len(parts) >= 3:
                if parts[1] in collisions:
                    kind, target = "conflict", conflict_prefixes[parts[1]] + rel
            else:
                kind, target = "quarantine", f"imports/{source_id}/{rel}"
            if kind not in {"excluded", "ontology_manual"}:
                previous = virtual.get(target)
                if previous == digest:
                    kind = "skip_identical"
                elif previous is not None:
                    target = f"conflicts/{source_id}/versions/{digest}/{rel}"
                    kind = "skip_identical" if virtual.get(target) == digest else "conflict"
                virtual[target] = digest
            plan[kind].append({"from": str(sat), "rel": rel, "target": target, "sha256": digest})
    return plan


def print_plan(plan: dict, home: Path) -> None:
    print(json.dumps({"home": str(home), "plan": plan}, ensure_ascii=False, indent=2))


def apply_sync(plan: dict, home: Path) -> int:
    created = []
    try:
        # Verify every input before writing, including skipped/excluded entries.
        for group in plan.values():
            for item in group:
                src = checked(Path(item["from"]) / item["rel"])
                if sha256_file(src) != item["sha256"]:
                    raise ValueError(f"E_SOURCE_CHANGED: {src}")
        for kind in ("copy", "conflict", "quarantine"):
            for item in plan[kind]:
                src = checked(Path(item["from"]) / item["rel"])
                data = src.read_bytes()
                if hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise ValueError(f"E_SOURCE_CHANGED: {src}")
                dst = checked(home / item["target"])
                dst.parent.mkdir(parents=True, exist_ok=True)
                checked(dst)
                try:
                    with dst.open("xb") as f:
                        created.append(str(dst))
                        f.write(data)
                except FileExistsError:
                    raise ValueError(f"E_RACE: {dst}")
                if sha256_file(dst) != item["sha256"]:
                    raise ValueError(f"E_VERIFY: {dst}")
        receipt = checked(home / "imports" / "receipts" / (uuid.uuid4().hex + ".json"))
        receipt.parent.mkdir(parents=True, exist_ok=True)
        with receipt.open("x", encoding="utf-8", newline="\n") as f:
            json.dump({"created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "home": str(home), "plan": plan}, f, ensure_ascii=False, indent=2)
        print(f"COLLECTED copied_files={len(created)} receipt={receipt}")
    except (OSError, ValueError):
        print(json.dumps({"status": "partial_failure", "created_files": created, "next": "inspect partial files; keep sources; rerun dry-run"}))
        raise
    return 0


def cmd_sync(args) -> int:
    registry = load_registry(Path(args.registry))
    selected = args.home or registry.get("canonical")
    if not selected:
        eprint("E_NO_HOME: pass --home <path> or set canonical in the registry first")
        return 2
    home = checked(Path(selected))
    if not is_memory_root(home):
        eprint(f"E_HOME_INVALID: canonical home must be a <project>/memory/xbskill directory: {home}")
        return 2
    if home not in [checked(r) for r in get_roots_from_registry(registry)]:
        raise ValueError(f"E_HOME_UNREGISTERED: {home}")
    satellites = [r for r in get_roots_from_registry(registry) if r.resolve() != home.resolve()]
    plan = plan_sync(home, satellites)
    print_plan(plan, home)
    if not args.apply:
        print("dry-run only. Re-run with --apply after the user confirms this plan.")
        return 0
    result = apply_sync(plan, home)
    registry["canonical"] = str(home)
    for entry in registry["roots"]:
        entry["role"] = "canonical" if checked(Path(entry["path"])) == home else "satellite"
    save_registry(Path(args.registry), registry)
    print("CANONICAL_REGISTERED: runtime save/restore still requires explicit project selection")
    return result


def cmd_query(args) -> int:
    if args.memory_script:
        script = Path(args.memory_script)
    else:
        script = Path(__file__).resolve().parent.parent.parent / "xb-memory" / "scripts" / "memory_ontology.py"
    if not script.is_file():
        eprint(f"E_DEPENDENCY: xb-memory script not found: {script}")
        return 2
    request = checked(Path(args.request))
    if not request.is_file():
        eprint(f"E_PATH: query request file not found: {request}")
        return 2
    json.loads(request.read_text(encoding="utf-8-sig"))
    registry = load_registry(Path(args.registry))
    roots = get_roots_from_registry(registry)
    results, errors, skipped = [], [], []
    for root in roots:
        tree_hashes(root)
        if not (root / "ontology").is_dir():
            skipped.append({"root": str(root), "reason": "ontology_not_initialized"})
            continue
        try:
            proc = subprocess.run(
                [sys.executable, "-B", str(script), "query", "--project-root", str(root.parent.parent), "--request", str(request)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=args.timeout,
            )
            if proc.returncode:
                errors.append({"root": str(root), "code": "E_QUERY", "detail": proc.stderr.strip() or proc.stdout.strip()})
                continue
            packet = json.loads(proc.stdout)
            if not isinstance(packet, dict) or packet.get("status") not in {"matched", "no_match"} or any(not isinstance(packet.get(k), list) for k in ("entities", "assertions", "conflicts")) or packet.get("schema_version") != 1:
                raise ValueError("invalid ContextPacket")
            results.append({"root": str(root), "queried_at": dt.datetime.now(dt.timezone.utc).isoformat(), "packet": packet})
        except (subprocess.TimeoutExpired, ValueError) as exc:
            errors.append({"root": str(root), "code": "E_QUERY", "detail": str(exc)})
    print(json.dumps({"status": "partial_failure" if errors else "complete", "results": results, "errors": errors, "skipped": skipped,
        "policy": "parallel candidates; retain root, dates, scope, sensitivity and lifecycle; no identity merge"}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="scan a directory for memory/xbskill roots")
    p.add_argument("--scan-root", required=True)
    p.add_argument("--max-depth", type=int, default=8)
    p.add_argument("--registry", help="register found roots into this JSON file")
    p.add_argument("--apply", action="store_true", help="persist the registry after review")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("status", help="report registered roots")
    p.add_argument("--registry", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("sync", help="reconcile satellites into the canonical home")
    p.add_argument("--registry", required=True)
    p.add_argument("--home", help="canonical <project>/memory/xbskill; overrides registry canonical")
    p.add_argument("--apply", action="store_true", help="execute the printed plan (default: dry-run)")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("query", help="fan out an xb-memory query request to all registered roots")
    p.add_argument("--registry", required=True)
    p.add_argument("--request", required=True, help="query request JSON file for memory_ontology.py")
    p.add_argument("--memory-script", help="override path to xb-memory's memory_ontology.py")
    p.add_argument("--timeout", type=int, choices=range(1, 61), default=20, metavar="1..60")
    p.set_defaults(func=cmd_query)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        eprint(f"E_SYNC: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
