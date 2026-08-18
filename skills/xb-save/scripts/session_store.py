#!/usr/bin/env python3
"""Validate and atomically store one authorized xbskill session bundle locally."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{4}-[a-z0-9][a-z0-9-]{0,63}$")
CATEGORIES = {
    "self", "leader", "colleague", "relationship", "company", "company_tone",
    "goal", "project_progress", "decision", "communication_style", "work_event", "uncertain",
}
EVIDENCE_LEVELS = {"user_statement", "observable_event", "assistant_inference", "user_decision"}
ACTIONS = {"appended", "candidate_only", "excluded", "needs_identity"}
COMPLETENESS = {"complete", "partial", "user_excluded"}
ROLE_VALUES = {"user", "assistant"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_\-]{20,}\b"),
)


class StoreError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StoreError(message)


def load_bundle(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"E_BUNDLE_READ: {path}: {exc}") from exc
    require(isinstance(value, dict), "E_BUNDLE_SCHEMA: root must be an object")
    return value


def safe_target(root: Path, relative: str) -> Path:
    rel = Path(relative)
    require(not rel.is_absolute(), f"E_PATH: absolute target is forbidden: {relative}")
    require(".." not in rel.parts, f"E_PATH: parent traversal is forbidden: {relative}")
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise StoreError(f"E_PATH: target escapes memory root: {target}") from exc
    return target


def validate_bundle(bundle: dict) -> None:
    require(bundle.get("schema_version") == 1, "E_BUNDLE_SCHEMA: schema_version must be 1")
    session_id = bundle.get("session_id")
    require(isinstance(session_id, str) and SESSION_RE.fullmatch(session_id), "E_SESSION_ID: invalid session_id")
    require(bundle.get("authorized_current_session") is True, "E_AUTHORIZATION: current-session authorization missing")
    require(bundle.get("network_writes") is False, "E_NETWORK: network_writes must be false")
    require(bundle.get("completeness") in COMPLETENESS, "E_COMPLETENESS: invalid completeness")
    gaps = bundle.get("completeness_gaps", [])
    require(isinstance(gaps, list) and all(isinstance(item, str) for item in gaps), "E_COMPLETENESS: gaps must be strings")
    if bundle.get("completeness") == "complete":
        require(not gaps, "E_COMPLETENESS: complete session cannot declare gaps")

    transcript = bundle.get("transcript")
    require(isinstance(transcript, list) and transcript, "E_TRANSCRIPT: transcript must be a non-empty list")
    expected_turn = 1
    for message in transcript:
        require(isinstance(message, dict), "E_TRANSCRIPT: message must be an object")
        require(message.get("turn") == expected_turn, "E_TRANSCRIPT: turns must be contiguous from 1")
        require(message.get("role") in ROLE_VALUES, "E_TRANSCRIPT: role must be user or assistant")
        content = message.get("content")
        require(isinstance(content, str) and content.strip(), "E_TRANSCRIPT: content must be non-empty text")
        for pattern in SECRET_PATTERNS:
            require(pattern.search(content) is None, "E_SECRET: transcript contains a credential/private-key pattern; exclude it first")
        expected_turn += 1

    classification = bundle.get("classification")
    require(isinstance(classification, list), "E_CLASSIFICATION: classification must be a list")
    seen_ids: set[str] = set()
    for item in classification:
        require(isinstance(item, dict), "E_CLASSIFICATION: item must be an object")
        item_id = item.get("item_id")
        require(isinstance(item_id, str) and item_id and item_id not in seen_ids, "E_CLASSIFICATION: item_id missing or duplicate")
        seen_ids.add(item_id)
        require(item.get("category") in CATEGORIES, f"E_CLASSIFICATION: invalid category for {item_id}")
        require(item.get("evidence_level") in EVIDENCE_LEVELS, f"E_CLASSIFICATION: invalid evidence_level for {item_id}")
        require(item.get("action") in ACTIONS, f"E_CLASSIFICATION: invalid action for {item_id}")
        for field in ("subject", "content", "source", "confidence", "target", "reversal"):
            require(isinstance(item.get(field), str) and item[field].strip(), f"E_CLASSIFICATION: {item_id}.{field} missing")

    updates = bundle.get("context_updates", [])
    require(isinstance(updates, list), "E_CONTEXT: context_updates must be a list")
    for update in updates:
        require(isinstance(update, dict), "E_CONTEXT: update must be an object")
        target = update.get("target")
        content = update.get("content")
        require(isinstance(target, str) and target.startswith("context/"), "E_CONTEXT: target must be under context/")
        require(target.endswith(".md"), "E_CONTEXT: target must be markdown")
        require(isinstance(content, str) and content.strip(), "E_CONTEXT: content must be non-empty")

    for field in ("session_markdown", "classification_markdown", "progress_markdown"):
        require(isinstance(bundle.get(field), str) and bundle[field].strip(), f"E_BUNDLE_SCHEMA: {field} missing")


def render_transcript(messages: list[dict], session_id: str, completeness: str, gaps: list[str]) -> str:
    lines = [f"# 会话全文：{session_id}", "", f"- 完整性：{completeness}"]
    if gaps:
        lines.append(f"- 缺口：{'；'.join(gaps)}")
    lines.append("")
    for message in messages:
        label = "用户" if message["role"] == "user" else "助手"
        lines.extend((f"## 第 {message['turn']} 轮 · {label}", "", message["content"].rstrip(), ""))
    return "\n".join(lines).rstrip() + "\n"


def append_update(existing: str, session_id: str, content: str) -> str:
    marker = f"## 会话增量 {session_id}"
    prefix = existing.rstrip()
    if marker in existing:
        pattern = re.compile(
            rf"^{re.escape(marker)}\n\n.*?(?=^## 会话增量 |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        replacement = f"{marker}\n\n{content.strip()}\n\n"
        updated, count = pattern.subn(replacement, existing, count=1)
        require(count == 1, f"E_CONTEXT_FORMAT: cannot update existing session block: {session_id}")
        return updated.rstrip() + "\n"
    return f"{prefix}\n\n{marker}\n\n{content.strip()}\n" if prefix else f"# xbskill 上下文档案\n\n{marker}\n\n{content.strip()}\n"


def atomic_store(project_root: Path, bundle: dict) -> dict:
    project = project_root.resolve()
    require(project.is_dir(), f"E_PROJECT_ROOT: project root does not exist: {project}")
    memory_root = (project / "memory" / "xbskill").resolve()
    require(memory_root == (project / "memory" / "xbskill").resolve(), "E_PATH: memory root resolution failed")
    session_id = bundle["session_id"]
    session_rel = Path("sessions") / session_id

    writes: dict[Path, str] = {
        safe_target(memory_root, str(session_rel / "transcript.md")): render_transcript(
            bundle["transcript"], session_id, bundle["completeness"], bundle.get("completeness_gaps", [])
        ),
        safe_target(memory_root, str(session_rel / "session.md")): bundle["session_markdown"].rstrip() + "\n",
        safe_target(memory_root, str(session_rel / "classification.md")): bundle["classification_markdown"].rstrip() + "\n",
        safe_target(memory_root, "progress.md"): bundle["progress_markdown"].rstrip() + "\n",
    }
    for update in bundle.get("context_updates", []):
        target = safe_target(memory_root, update["target"])
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        writes[target] = append_update(existing, session_id, update["content"])

    memory_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".session-store-", dir=memory_root))
    backup = stage / "backup"
    replaced: list[Path] = []
    try:
        staged: dict[Path, Path] = {}
        for index, (target, content) in enumerate(writes.items()):
            temp_path = stage / f"write-{index}.tmp"
            temp_path.write_text(content, encoding="utf-8")
            require(temp_path.read_text(encoding="utf-8") == content, f"E_VERIFY: staged readback failed: {target}")
            staged[target] = temp_path
        for index, (target, temp_path) in enumerate(staged.items()):
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup_path = backup / f"backup-{index}.bin"
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup_path)
            os.replace(temp_path, target)
            replaced.append(target)
        for target, expected in writes.items():
            require(target.read_text(encoding="utf-8") == expected, f"E_VERIFY: final readback failed: {target}")
    except Exception:
        for index, target in reversed(list(enumerate(writes))):
            backup_path = backup / f"backup-{index}.bin"
            if backup_path.exists():
                shutil.copy2(backup_path, target)
            elif target in replaced and target.exists():
                target.unlink()
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    return {
        "status": "saved",
        "session_id": session_id,
        "session_directory": str((memory_root / session_rel).resolve()),
        "completeness": bundle["completeness"],
        "classification_count": len(bundle["classification"]),
        "updated_context": [update["target"] for update in bundle.get("context_updates", [])],
        "network_writes": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args(argv)
    try:
        bundle = load_bundle(Path(args.bundle).resolve())
        validate_bundle(bundle)
        result = atomic_store(Path(args.project_root), bundle)
    except (StoreError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
