#!/usr/bin/env python3
"""Validate and atomically store one authorized xbskill session bundle locally."""

from __future__ import annotations

import argparse
import copy
import importlib.util
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


def load_ontology_module():
    script = Path(__file__).resolve().parents[2] / "xb-memory" / "scripts" / "memory_ontology.py"
    require(script.is_file(), f"E_DEPENDENCY: missing ontology writer: {script}")
    spec = importlib.util.spec_from_file_location("xb_memory_ontology", script)
    require(spec is not None and spec.loader is not None, f"E_DEPENDENCY: cannot load ontology writer: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_topics():
    path = Path(__file__).resolve().parents[2] / "xb-memory/scripts/topic_coordinates.py"
    require(path.is_file(), f"E_DEPENDENCY: missing topic support: {path}")
    spec = importlib.util.spec_from_file_location("xb_topic_coordinates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def validate_bundle(bundle: dict, *, attached_topic=False) -> None:
    schema_version = bundle.get("schema_version")
    require(schema_version in {1, 2}, "E_BUNDLE_SCHEMA: schema_version must be 1 or 2")
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

    classification = bundle.get("classification", [])
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
    if schema_version == 2:
        require(not classification, "E_ONTOLOGY_PROJECTION: schema 2 classification is generated from ontology_delta")
        require(not updates, "E_ONTOLOGY_PROJECTION: schema 2 context_updates are replaced by ontology queries")
    for update in updates:
        require(isinstance(update, dict), "E_CONTEXT: update must be an object")
        target = update.get("target")
        content = update.get("content")
        require(isinstance(target, str) and target.startswith("context/"), "E_CONTEXT: target must be under context/")
        require(target.endswith(".md"), "E_CONTEXT: target must be markdown")
        require(isinstance(content, str) and content.strip(), "E_CONTEXT: content must be non-empty")

    for field in ("session_markdown", "progress_markdown"):
        require(isinstance(bundle.get(field), str) and bundle[field].strip(), f"E_BUNDLE_SCHEMA: {field} missing")
    if schema_version == 1:
        require(isinstance(bundle.get("classification_markdown"), str) and bundle["classification_markdown"].strip(), "E_BUNDLE_SCHEMA: classification_markdown missing")
    else:
        delta = bundle.get("ontology_delta")
        require(isinstance(delta, dict), "E_ONTOLOGY: ontology_delta missing")
        require(delta.get("session_id") == session_id, "E_ONTOLOGY: ontology session_id differs from bundle")
        require(delta.get("authorized_current_session") is True, "E_ONTOLOGY: ontology authorization missing")
        try:
            ontology = load_ontology_module()
            ontology.validate_delta(delta, allow_unknown_supersedes=True)
        except (ValueError, OSError) as exc:
            raise StoreError(f"E_ONTOLOGY: {exc}") from exc
        transcript_by_turn = {item["turn"]: item for item in transcript}
        for group_name in ("entities", "assertions"):
            for item in delta[group_name]:
                if group_name == "assertions" and not attached_topic:
                    require(item["qualifiers"].get("memory_kind") != "topic_coordinates",
                            "E_TOPIC_SCHEMA: use topic_registration for topic assertions")
                for ref in item["source_refs"]:
                    message = transcript_by_turn.get(ref["turn"])
                    require(message is not None, f"E_ONTOLOGY_SOURCE: missing transcript turn {ref['turn']}")
                    require(message["role"] == ref["role"], f"E_ONTOLOGY_SOURCE: role differs at turn {ref['turn']}")
                    require(ref["excerpt"] in message["content"], f"E_ONTOLOGY_SOURCE: excerpt is not present at turn {ref['turn']}")


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
    require(memory_root.is_relative_to(project), "E_PATH: memory root escapes project")
    topics = load_topics()
    row = None
    if "topic_registration" in bundle:
        validate_bundle(bundle)
        bundle = copy.deepcopy(bundle)
        row = topics.attach(bundle)
        validate_bundle(bundle, attached_topic=True)
    startup = bundle.get("startup_check")
    if startup is not None:
        require(isinstance(startup, dict) and startup.get("query_executed") is True
                and startup.get("project_root") == str(project)
                and startup.get("status") in {"matched", "no_match", "no_archive", "legacy_review_required",
                                              "ask_location", "ambiguous", "material_missing", "material_unrecorded"}
                and isinstance(startup.get("task"), str)
                and any(m["role"] == "user" and m["content"] == startup["task"] for m in bundle["transcript"]),
                "E_STARTUP_RECEIPT: query receipt must match the current project and user task")
    memory_root.mkdir(parents=True, exist_ok=True)
    with topics.update_lock(memory_root / "progress.md"):
        return store_session(memory_root, bundle, topics, row)


def store_session(memory_root, bundle, topics, row):
    session_id = bundle["session_id"]
    session_rel = Path("sessions") / session_id

    classification_markdown = bundle.get("classification_markdown", "")
    ontology_summary: dict[str, object] = {}
    ontology_writes: dict[Path, str] = {}
    assertions = []
    progress = bundle["progress_markdown"]
    if bundle["schema_version"] == 2:
        ontology = load_ontology_module()
        try:
            ontology_writes, ontology_summary = ontology.plan_ontology_writes(memory_root, bundle["ontology_delta"])
            classification_markdown = ontology.render_classification(bundle["ontology_delta"])
            entities = json.loads(ontology_writes[memory_root / "ontology/entities.json"])["entities"]
            assertions = json.loads(ontology_writes[memory_root / "ontology/assertions.json"])["assertions"]
            index = json.loads(ontology_writes[memory_root / "ontology/index.json"])
            candidates = topics.ontology_rows(entities, assertions, index["effective_assertion_ids"])
            if candidates:
                progress = topics.card(candidates[0], progress, bundle.get("startup_check") is not None)
        except (ValueError, OSError) as exc:
            raise StoreError(f"E_ONTOLOGY: {exc}") from exc

    writes: dict[Path, str] = {
        safe_target(memory_root, str(session_rel / "transcript.md")): render_transcript(
            bundle["transcript"], session_id, bundle["completeness"], bundle.get("completeness_gaps", [])
        ),
        safe_target(memory_root, str(session_rel / "session.md")): bundle["session_markdown"].rstrip() + "\n",
        safe_target(memory_root, str(session_rel / "classification.md")): classification_markdown.rstrip() + "\n",
        safe_target(memory_root, "progress.md"): progress.rstrip() + "\n",
    }
    for update in bundle.get("context_updates", []):
        target = safe_target(memory_root, update["target"])
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        writes[target] = append_update(existing, session_id, update["content"])
    for target, content in ontology_writes.items():
        resolved = target.resolve()
        try:
            resolved.relative_to(memory_root)
        except ValueError as exc:
            raise StoreError(f"E_PATH: ontology target escapes memory root: {resolved}") from exc
        writes[resolved] = content

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

    effects = topics.apply_effects(bundle["topic_registration"], row, session_id,
                                   bundle["ontology_delta"]["generated_at"], assertions, memory_root) if row else {}
    errors = any(effect["status"] == "error" for effect in effects.values())
    return {
        "status": "saved_with_topic_errors" if errors else "saved",
        "startup_query": "recorded" if bundle.get("startup_check") is not None else "not_recorded",
        "topic_effects": effects,
        "session_id": session_id,
        "session_directory": str((memory_root / session_rel).resolve()),
        "completeness": bundle["completeness"],
        "classification_count": (
            len(bundle.get("classification", []))
            if bundle["schema_version"] == 1
            else len(bundle["ontology_delta"]["assertions"])
        ),
        "updated_context": [update["target"] for update in bundle.get("context_updates", [])],
        "network_writes": False,
        **ontology_summary,
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
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["status"] == "saved_with_topic_errors" else 0


if __name__ == "__main__":
    raise SystemExit(main())
