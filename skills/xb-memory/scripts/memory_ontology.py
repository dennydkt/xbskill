#!/usr/bin/env python3
"""Validate, merge, query, and audit xbskill conversation ontology memory."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{4}-[A-Za-z0-9_\-\u3400-\u9fff]{1,96}$")
ENTITY_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*:[a-z0-9][a-z0-9._-]{0,95}$")
ASSERTION_ID_RE = re.compile(r"^a:[a-z0-9][a-z0-9._:-]{2,127}$")
REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
ENTITY_TYPES = {
    "person", "organization", "project", "goal", "work_item", "artifact",
    "decision", "event", "constraint", "capability", "preference", "role", "topic",
}
ENTITY_STATUSES = {"active", "candidate", "needs_identity", "retired"}
EPISTEMIC = {
    "user_statement", "observable_event", "assistant_inference", "user_decision", "artifact_evidence",
}
CONFIDENCE = {"high", "medium", "low"}
LIFECYCLE = {"active", "candidate", "disputed", "superseded", "expired"}
RETENTION = {"long_term", "session_only"}
SENSITIVITY = {"normal", "restricted"}
ROLES = {"user", "assistant"}
VALUE_TYPES = {"string", "number", "boolean", "date", "datetime", "duration", "status"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_\-]{20,}\b"),
)
SCRIPT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = SCRIPT_ROOT / "references" / "predicate-registry.json"


class OntologyError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OntologyError(message)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OntologyError(f"E_JSON_READ: {path}: {exc}") from exc


def load_registry() -> dict[str, dict[str, Any]]:
    require(REGISTRY_PATH.is_file(), f"E_DEPENDENCY: missing predicate registry: {REGISTRY_PATH}")
    data = load_json(REGISTRY_PATH)
    require(isinstance(data, dict) and data.get("schema_version") == 1, "E_REGISTRY: unsupported registry")
    predicates = data.get("predicates")
    require(isinstance(predicates, dict) and predicates, "E_REGISTRY: predicates must be a non-empty object")
    return predicates


def parse_datetime(value: Any, field: str, nullable: bool = False) -> dt.datetime | None:
    if value is None and nullable:
        return None
    require(isinstance(value, str) and value.strip(), f"E_TIME: {field} must be an ISO date-time")
    text = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OntologyError(f"E_TIME: invalid {field}: {value}") from exc
    require(parsed.tzinfo is not None, f"E_TIME: {field} must include a timezone")
    return parsed


def check_secret(value: str, field: str) -> None:
    for pattern in SECRET_PATTERNS:
        require(pattern.search(value) is None, f"E_SECRET: {field} contains a credential/private-key pattern")


def validate_source_ref(ref: Any, session_id: str, field: str) -> None:
    require(isinstance(ref, dict), f"E_SOURCE: {field} must be an object")
    require(set(ref) == {"session_id", "turn", "role", "excerpt"}, f"E_SOURCE: {field} has invalid fields")
    require(ref.get("session_id") == session_id, f"E_SOURCE: {field}.session_id must match delta")
    require(isinstance(ref.get("turn"), int) and ref["turn"] >= 1, f"E_SOURCE: {field}.turn invalid")
    require(ref.get("role") in ROLES, f"E_SOURCE: {field}.role invalid")
    excerpt = ref.get("excerpt")
    require(isinstance(excerpt, str) and 0 < len(excerpt.strip()) <= 280, f"E_SOURCE: {field}.excerpt invalid")
    check_secret(excerpt, f"{field}.excerpt")


def validate_entity(entity: Any, session_id: str, seen: set[str]) -> None:
    required = {
        "entity_id", "entity_type", "canonical_name", "aliases", "scope",
        "sensitivity", "status", "source_refs",
    }
    require(isinstance(entity, dict) and set(entity) == required, "E_ENTITY: invalid entity fields")
    entity_id = entity.get("entity_id")
    require(isinstance(entity_id, str) and ENTITY_ID_RE.fullmatch(entity_id), f"E_ENTITY: invalid entity_id: {entity_id}")
    require(entity_id not in seen, f"E_ENTITY: duplicate entity_id: {entity_id}")
    seen.add(entity_id)
    require(entity.get("entity_type") in ENTITY_TYPES, f"E_ENTITY: invalid type for {entity_id}")
    name = entity.get("canonical_name")
    require(isinstance(name, str) and 0 < len(name.strip()) <= 160, f"E_ENTITY: invalid canonical_name for {entity_id}")
    check_secret(name, f"entity {entity_id}.canonical_name")
    aliases = entity.get("aliases")
    require(isinstance(aliases, list) and len(aliases) == len(set(aliases)), f"E_ENTITY: aliases invalid for {entity_id}")
    require(all(isinstance(item, str) and 0 < len(item.strip()) <= 160 for item in aliases), f"E_ENTITY: alias invalid for {entity_id}")
    require(isinstance(entity.get("scope"), str) and entity["scope"].strip(), f"E_ENTITY: scope missing for {entity_id}")
    require(entity.get("sensitivity") in SENSITIVITY, f"E_ENTITY: sensitivity invalid for {entity_id}")
    require(entity.get("status") in ENTITY_STATUSES, f"E_ENTITY: status invalid for {entity_id}")
    refs = entity.get("source_refs")
    require(isinstance(refs, list) and refs, f"E_ENTITY: source_refs missing for {entity_id}")
    for index, ref in enumerate(refs):
        validate_source_ref(ref, session_id, f"entity {entity_id}.source_refs[{index}]")


def object_key(value: dict[str, Any]) -> str:
    if value["kind"] == "entity":
        return f"entity:{value['entity_id']}"
    return f"literal:{value.get('value_type')}:{canonical_json(value.get('value'))}"


def validate_assertion(
    assertion: Any,
    session_id: str,
    entity_map: dict[str, dict[str, Any]],
    known_entity_map: dict[str, dict[str, Any]],
    seen: set[str],
    registry: dict[str, dict[str, Any]],
    sensitive_authorized: bool,
) -> None:
    required = {
        "assertion_id", "subject_id", "predicate", "object", "epistemic_status",
        "confidence", "lifecycle", "retention", "sensitivity", "scope", "observed_at",
        "valid_from", "valid_until", "source_refs", "reversal", "supersedes", "qualifiers",
    }
    require(isinstance(assertion, dict) and set(assertion) == required, "E_ASSERTION: invalid assertion fields")
    assertion_id = assertion.get("assertion_id")
    require(isinstance(assertion_id, str) and ASSERTION_ID_RE.fullmatch(assertion_id), f"E_ASSERTION: invalid assertion_id: {assertion_id}")
    require(assertion_id not in seen, f"E_ASSERTION: duplicate assertion_id: {assertion_id}")
    seen.add(assertion_id)
    all_entities = {**known_entity_map, **entity_map}
    subject_id = assertion.get("subject_id")
    require(subject_id in all_entities, f"E_ASSERTION: unknown subject_id for {assertion_id}: {subject_id}")
    predicate = assertion.get("predicate")
    require(predicate in registry, f"E_ASSERTION: unregistered predicate for {assertion_id}: {predicate}")
    rule = registry[predicate]
    subject_type = all_entities[subject_id]["entity_type"]
    require(subject_type in rule.get("subjects", []), f"E_ASSERTION: predicate {predicate} rejects subject type {subject_type}")

    value = assertion.get("object")
    require(isinstance(value, dict) and value.get("kind") in {"entity", "literal"}, f"E_ASSERTION: object invalid for {assertion_id}")
    object_mode = rule.get("object")
    if value["kind"] == "entity":
        require(set(value) == {"kind", "entity_id"}, f"E_ASSERTION: entity object fields invalid for {assertion_id}")
        target_id = value.get("entity_id")
        require(target_id in all_entities, f"E_ASSERTION: unknown object entity for {assertion_id}: {target_id}")
        require(object_mode in {"entity", "either"}, f"E_ASSERTION: {predicate} requires a literal object")
        target_type = all_entities[target_id]["entity_type"]
        require(target_type in rule.get("objects", []), f"E_ASSERTION: predicate {predicate} rejects object type {target_type}")
        if predicate in {"same_as", "different_from"}:
            require(subject_type == target_type, f"E_ASSERTION: {predicate} requires matching entity types")
    else:
        require(set(value) == {"kind", "value", "value_type"}, f"E_ASSERTION: literal object fields invalid for {assertion_id}")
        require(object_mode in {"literal", "either"}, f"E_ASSERTION: {predicate} requires an entity object")
        require(value.get("value_type") in VALUE_TYPES, f"E_ASSERTION: invalid value_type for {assertion_id}")
        literal = value.get("value")
        require(isinstance(literal, (str, int, float, bool)) and not isinstance(literal, type(None)), f"E_ASSERTION: literal missing for {assertion_id}")
        if isinstance(literal, str):
            require(literal.strip(), f"E_ASSERTION: empty literal for {assertion_id}")
            check_secret(literal, f"assertion {assertion_id}.object.value")

    require(assertion.get("epistemic_status") in EPISTEMIC, f"E_ASSERTION: epistemic_status invalid for {assertion_id}")
    require(assertion.get("confidence") in CONFIDENCE, f"E_ASSERTION: confidence invalid for {assertion_id}")
    require(assertion.get("lifecycle") in LIFECYCLE, f"E_ASSERTION: lifecycle invalid for {assertion_id}")
    require(assertion.get("retention") in RETENTION, f"E_ASSERTION: retention invalid for {assertion_id}")
    require(assertion.get("sensitivity") in SENSITIVITY, f"E_ASSERTION: sensitivity invalid for {assertion_id}")
    require(isinstance(assertion.get("scope"), str) and assertion["scope"].strip(), f"E_ASSERTION: scope missing for {assertion_id}")
    observed = parse_datetime(assertion.get("observed_at"), f"{assertion_id}.observed_at")
    valid_from = parse_datetime(assertion.get("valid_from"), f"{assertion_id}.valid_from", nullable=True)
    valid_until = parse_datetime(assertion.get("valid_until"), f"{assertion_id}.valid_until", nullable=True)
    if valid_from and valid_until:
        require(valid_until >= valid_from, f"E_TIME: valid_until precedes valid_from for {assertion_id}")
    require(observed is not None, f"E_TIME: observed_at missing for {assertion_id}")
    refs = assertion.get("source_refs")
    require(isinstance(refs, list) and refs, f"E_ASSERTION: source_refs missing for {assertion_id}")
    for index, ref in enumerate(refs):
        validate_source_ref(ref, session_id, f"assertion {assertion_id}.source_refs[{index}]")
    if assertion["epistemic_status"] in {"user_statement", "user_decision"}:
        require(any(ref["role"] == "user" for ref in refs), f"E_EPISTEMIC_SOURCE: {assertion['epistemic_status']} lacks a user source: {assertion_id}")
    reversal = assertion.get("reversal")
    require(isinstance(reversal, str) and 0 < len(reversal.strip()) <= 400, f"E_ASSERTION: reversal invalid for {assertion_id}")
    supersedes = assertion.get("supersedes")
    require(isinstance(supersedes, list) and len(supersedes) == len(set(supersedes)), f"E_ASSERTION: supersedes invalid for {assertion_id}")
    require(assertion_id not in supersedes, f"E_ASSERTION: assertion cannot supersede itself: {assertion_id}")
    qualifiers = assertion.get("qualifiers")
    require(isinstance(qualifiers, dict), f"E_ASSERTION: qualifiers invalid for {assertion_id}")
    require(all(isinstance(key, str) and isinstance(val, (str, int, float, bool, type(None))) for key, val in qualifiers.items()), f"E_ASSERTION: qualifier value invalid for {assertion_id}")

    if assertion["epistemic_status"] == "assistant_inference":
        require(assertion["lifecycle"] != "active", f"E_INFERENCE_PROMOTION: assistant inference cannot be active: {assertion_id}")
    if all_entities[subject_id].get("status") == "needs_identity":
        require(assertion["lifecycle"] == "candidate", f"E_IDENTITY: unresolved subject must remain candidate: {assertion_id}")
    if value["kind"] == "entity" and all_entities[value["entity_id"]].get("status") == "needs_identity":
        require(assertion["lifecycle"] == "candidate", f"E_IDENTITY: unresolved object must remain candidate: {assertion_id}")
    if assertion["sensitivity"] == "restricted" and assertion["retention"] == "long_term":
        require(sensitive_authorized, f"E_SENSITIVE_AUTH: restricted long-term assertion lacks extra authorization: {assertion_id}")


def validate_delta(
    delta: Any,
    known_entities: dict[str, dict[str, Any]] | None = None,
    known_assertions: dict[str, dict[str, Any]] | None = None,
    allow_unknown_supersedes: bool = False,
) -> dict[str, Any]:
    required = {
        "schema_version", "session_id", "generated_at", "authorized_current_session",
        "authorized_sensitive_long_term", "entities", "assertions",
    }
    require(isinstance(delta, dict) and set(delta) == required, "E_DELTA_SCHEMA: invalid root fields")
    require(delta.get("schema_version") == 1, "E_DELTA_SCHEMA: schema_version must be 1")
    session_id = delta.get("session_id")
    require(isinstance(session_id, str) and SESSION_RE.fullmatch(session_id), "E_DELTA_SCHEMA: invalid session_id")
    parse_datetime(delta.get("generated_at"), "generated_at")
    require(delta.get("authorized_current_session") is True, "E_AUTHORIZATION: ontology delta lacks current-session authorization")
    require(isinstance(delta.get("authorized_sensitive_long_term"), bool), "E_DELTA_SCHEMA: sensitive authorization must be boolean")
    entities = delta.get("entities")
    assertions = delta.get("assertions")
    require(isinstance(entities, list), "E_DELTA_SCHEMA: entities must be a list")
    require(isinstance(assertions, list), "E_DELTA_SCHEMA: assertions must be a list")
    entity_seen: set[str] = set()
    for entity in entities:
        validate_entity(entity, session_id, entity_seen)
    entity_map = {item["entity_id"]: item for item in entities}
    known_entities = known_entities or {}
    known_assertions = known_assertions or {}
    for entity_id, entity in entity_map.items():
        if entity_id in known_entities:
            require(known_entities[entity_id].get("entity_type") == entity.get("entity_type"), f"E_ENTITY_ID_COLLISION: type changed for {entity_id}")
    registry = load_registry()
    assertion_seen: set[str] = set()
    for assertion in assertions:
        validate_assertion(
            assertion, session_id, entity_map, known_entities, assertion_seen, registry,
            bool(delta["authorized_sensitive_long_term"]),
        )
    available_assertions = set(known_assertions) | assertion_seen
    for assertion in assertions:
        for old_id in assertion["supersedes"]:
            require(ASSERTION_ID_RE.fullmatch(old_id) is not None, f"E_SUPERSEDES: invalid assertion ID for {assertion['assertion_id']}: {old_id}")
            if not allow_unknown_supersedes:
                require(old_id in available_assertions, f"E_SUPERSEDES: unknown assertion for {assertion['assertion_id']}: {old_id}")
    return delta


def empty_entities_store() -> dict[str, Any]:
    return {"schema_version": 1, "entities": []}


def empty_assertions_store() -> dict[str, Any]:
    return {"schema_version": 1, "assertions": []}


def load_store(memory_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    ontology_root = memory_root / "ontology"
    entities_path = ontology_root / "entities.json"
    assertions_path = ontology_root / "assertions.json"
    entities_store = load_json(entities_path) if entities_path.is_file() else empty_entities_store()
    assertions_store = load_json(assertions_path) if assertions_path.is_file() else empty_assertions_store()
    require(isinstance(entities_store, dict) and entities_store.get("schema_version") == 1 and isinstance(entities_store.get("entities"), list), "E_STORE_SCHEMA: invalid entities store")
    require(isinstance(assertions_store, dict) and assertions_store.get("schema_version") == 1 and isinstance(assertions_store.get("assertions"), list), "E_STORE_SCHEMA: invalid assertions store")
    return entities_store, assertions_store


def ref_key(ref: dict[str, Any]) -> str:
    return canonical_json(ref)


def merge_entity(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    require(old["entity_type"] == new["entity_type"], f"E_ENTITY_ID_COLLISION: type changed for {old['entity_id']}")
    merged = dict(old)
    aliases = list(old.get("aliases", []))
    for value in [new["canonical_name"], *new.get("aliases", [])]:
        if value != old["canonical_name"] and value not in aliases:
            aliases.append(value)
    merged["aliases"] = sorted(aliases)
    refs = {ref_key(item): item for item in old.get("source_refs", [])}
    refs.update({ref_key(item): item for item in new.get("source_refs", [])})
    merged["source_refs"] = [refs[key] for key in sorted(refs)]
    if old.get("status") in {"candidate", "needs_identity"} and new.get("status") == "active":
        merged["status"] = "active"
        merged["canonical_name"] = new["canonical_name"]
    elif new.get("status") == "retired":
        merged["status"] = "retired"
    if old.get("sensitivity") == "restricted" or new.get("sensitivity") == "restricted":
        merged["sensitivity"] = "restricted"
    return merged


LEGACY_HEADER_ALIASES = {
    "item_id": {"item_id"},
    "category": {"category", "类别"},
    "subject": {"subject", "主体"},
    "content": {"content", "内容"},
    "evidence_level": {"evidence_level", "证据层级"},
    "source": {"source", "来源"},
    "confidence": {"confidence", "置信度"},
    "target": {"target", "目标"},
    "action": {"action", "动作"},
    "reversal": {"reversal", "推翻信号"},
}
LEGACY_CATEGORY_MODEL = {
    "goal": ("project", "goal", "has_goal", False),
    "communication_style": ("person", "preference", "prefers", False),
    "project_progress": ("project", "event", "produces", False),
    "company": ("topic", "event", "about", True),
    "assistant_inference": ("topic", "topic", "about", True),
    "work_event": ("topic", "event", "about", True),
}
LEGACY_RESTRICTED_TERMS = (
    "身份证", "手机号", "住址", "病情", "病史", "健康", "薪资", "工资", "离职", "跳槽", "私人关系",
)
TASK_STOP_TERMS = {"继续", "当前", "任务", "项目", "什么", "怎么", "需要", "还有", "处理", "相关", "工作", "这个"}


def split_markdown_row(line: str) -> list[str]:
    body = line.strip().strip("|")
    cells: list[str] = []
    cell: list[str] = []
    index = 0
    while index < len(body):
        if body[index:index + 2] == "\\|":
            cell.append("|")
            index += 2
            continue
        if body[index] == "|":
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(body[index])
        index += 1
    cells.append("".join(cell).strip())
    return cells


def parse_legacy_classification(text: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    rows: list[dict[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("|"):
            index += 1
            continue
        headers = split_markdown_row(line)
        resolved: dict[str, int] = {}
        for canonical, aliases in LEGACY_HEADER_ALIASES.items():
            for position, header in enumerate(headers):
                if header in aliases:
                    resolved[canonical] = position
                    break
        if set(resolved) != set(LEGACY_HEADER_ALIASES):
            index += 1
            continue
        require(index + 1 < len(lines) and re.fullmatch(r"\|?[\s:|\-]+\|?", lines[index + 1].strip()) is not None,
                "E_LEGACY_TABLE: classification header lacks a Markdown separator")
        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            cells = split_markdown_row(lines[index])
            require(len(cells) == len(headers), f"E_LEGACY_TABLE: malformed row at line {index + 1}")
            row = {name: cells[position] for name, position in resolved.items()}
            require(all(row[name] for name in ("item_id", "category", "subject", "content")),
                    f"E_LEGACY_TABLE: required value missing at line {index + 1}")
            row["line"] = str(index + 1)
            rows.append(row)
            index += 1
    require(rows, "E_LEGACY_TABLE: no supported classification rows found")
    item_ids = [row["item_id"] for row in rows]
    require(len(item_ids) == len(set(item_ids)), "E_LEGACY_TABLE: duplicate item_id")
    return rows


def parse_legacy_transcript(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    turn: int | None = None
    role: str | None = None
    content: list[str] = []

    def flush() -> None:
        nonlocal content
        body = "\n".join(content).strip()
        if turn is not None and role is not None and body:
            messages.append({"turn": turn, "role": role, "content": body})
        content = []

    for line in text.splitlines():
        heading = re.match(r"^##\s+第\s*(\d+)\s*轮(?:\s*·\s*(用户|助手))?", line.strip())
        if heading:
            flush()
            turn = int(heading.group(1))
            role = {"用户": "user", "助手": "assistant"}.get(heading.group(2))
            continue
        role_heading = re.match(r"^\*\*(用户|助手)\*\*[：:]?\s*$", line.strip())
        if role_heading and turn is not None:
            flush()
            role = {"用户": "user", "助手": "assistant"}[role_heading.group(1)]
            continue
        if turn is not None and role is not None:
            content.append(line)
    flush()
    require(messages, "E_LEGACY_TRANSCRIPT: no user or assistant turns found")
    return messages


def legacy_turn_hints(source: str) -> set[int]:
    hints: set[int] = set()
    for start, end in re.findall(r"(?:turns?|R)\s*(\d+)\s*[–—-]\s*(\d+)", source, flags=re.IGNORECASE):
        low, high = sorted((int(start), int(end)))
        hints.update(range(low, high + 1))
    for value in re.findall(r"(?:turns?|R)\s*(\d+)", source, flags=re.IGNORECASE):
        hints.add(int(value))
    return hints


def legacy_terms(text: str) -> set[str]:
    terms = {item.lower() for item in re.findall(r"[A-Za-z0-9_]{2,}", text)}
    for segment in re.findall(r"[\u3400-\u9fff]{2,}", text):
        terms.update(segment[index:index + 2] for index in range(len(segment) - 1))
    return terms


def best_legacy_source(row: dict[str, str], messages: list[dict[str, Any]]) -> dict[str, Any]:
    hints = legacy_turn_hints(row["source"])
    candidates = [item for item in messages if not hints or item["turn"] in hints]
    require(candidates, f"E_LEGACY_SOURCE: source turn missing for item {row['item_id']}: {row['source']}")
    wanted = legacy_terms(f"{row['subject']} {row['content']}")
    scored = []
    for message in candidates:
        score = len(wanted.intersection(legacy_terms(message["content"])))
        scored.append((score, message["role"] == "user", -message["turn"], message))
    _score, _prefer_user, _turn_order, chosen = max(scored, key=lambda item: item[:3])
    anchors = sorted((term for term in wanted if term in chosen["content"].lower()), key=lambda item: (-len(item), item))
    anchor_at = chosen["content"].lower().find(anchors[0]) if anchors else 0
    start = max(0, anchor_at - 80)
    excerpt = chosen["content"][start:start + 280].strip()
    require(excerpt and excerpt in chosen["content"], f"E_LEGACY_SOURCE: exact excerpt unavailable for item {row['item_id']}")
    return {"turn": chosen["turn"], "role": chosen["role"], "excerpt": excerpt}


def legacy_timestamp(session_id: str) -> str:
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})-", session_id)
    require(match is not None, f"E_LEGACY_SESSION: session_id lacks date-time prefix: {session_id}")
    year, month, day, hour, minute = (int(value) for value in match.groups())
    try:
        return dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone(dt.timedelta(hours=8))).isoformat()
    except ValueError as exc:
        raise OntologyError(f"E_LEGACY_SESSION: invalid date-time prefix: {session_id}") from exc


def legacy_id(kind: str, session_id: str, item_id: str, label: str) -> str:
    digest = hashlib.sha256(f"{session_id}\n{item_id}\n{label}".encode("utf-8")).hexdigest()[:20]
    return f"{kind}:legacy-{digest}"


def clipped_name(value: str) -> str:
    text = value.strip()
    return text if len(text) <= 160 else text[:159] + "…"


def build_legacy_candidate_delta(project_root: Path, session_id: str) -> dict[str, Any]:
    require(SESSION_RE.fullmatch(session_id) is not None, f"E_LEGACY_SESSION: invalid session_id: {session_id}")
    memory_root = project_memory_root(project_root)
    session_root = memory_root / "sessions" / session_id
    classification_path = session_root / "classification.md"
    transcript_path = session_root / "transcript.md"
    ontology_path = session_root / "ontology.json"
    require(classification_path.is_file(), f"E_LEGACY_FILE: missing classification: {classification_path}")
    require(transcript_path.is_file(), f"E_LEGACY_FILE: missing transcript: {transcript_path}")
    require(not ontology_path.exists(), f"E_ALREADY_MIGRATED: ontology already exists: {ontology_path}")
    classification = classification_path.read_text(encoding="utf-8")
    transcript = transcript_path.read_text(encoding="utf-8")
    check_secret(classification, "legacy classification")
    check_secret(transcript, "legacy transcript")
    rows = parse_legacy_classification(classification)
    messages = parse_legacy_transcript(transcript)
    scope = f"project:{project_root.resolve().name}"
    observed_at = legacy_timestamp(session_id)
    entities: dict[str, dict[str, Any]] = {}
    assertions: list[dict[str, Any]] = []

    for row in rows:
        model = LEGACY_CATEGORY_MODEL.get(row["category"], ("topic", "topic", "about", True))
        subject_type, claim_type, predicate, reverse_relation = model
        source = best_legacy_source(row, messages)
        source_ref = {"session_id": session_id, **source}
        subject_label = row["subject"].strip()
        if subject_label.lower() in {"self", "自己", "用户", "用户本人"}:
            subject_id = "person:self"
            subject_type = "person"
            subject_name = "用户本人"
            subject_status = "active"
        else:
            subject_id = legacy_id(subject_type, session_id, row["item_id"], subject_label)
            subject_name = subject_label
            subject_status = "candidate"
        claim_id = legacy_id(claim_type, session_id, row["item_id"], row["content"])
        sensitive = "restricted" if any(term in f"{subject_label} {row['content']}" for term in LEGACY_RESTRICTED_TERMS) else "normal"
        retention = "session_only" if sensitive == "restricted" else "long_term"
        for entity_id, entity_type, name, status in (
            (subject_id, subject_type, subject_name, subject_status),
            (claim_id, claim_type, row["content"], "candidate"),
        ):
            entities.setdefault(entity_id, {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "canonical_name": clipped_name(name),
                "aliases": [],
                "scope": scope,
                "sensitivity": sensitive,
                "status": status,
                "source_refs": [source_ref],
            })
        assertion_subject = claim_id if reverse_relation else subject_id
        assertion_object = subject_id if reverse_relation else claim_id
        assertions.append({
            "assertion_id": "a:" + legacy_id("legacy", session_id, row["item_id"], row["category"]).split(":", 1)[1],
            "subject_id": assertion_subject,
            "predicate": predicate,
            "object": {"kind": "entity", "entity_id": assertion_object},
            "epistemic_status": "assistant_inference",
            "confidence": "low",
            "lifecycle": "candidate",
            "retention": retention,
            "sensitivity": sensitive,
            "scope": scope,
            "observed_at": observed_at,
            "valid_from": None,
            "valid_until": None,
            "source_refs": [source_ref],
            "reversal": row["reversal"] if row["reversal"] not in {"", "-", "—"} else "用户复核旧分类后修订或否定此项",
            "supersedes": [],
            "qualifiers": {
                "migration_source": "classification.md",
                "legacy_line": int(row["line"]),
                "legacy_item_id": row["item_id"],
                "legacy_category": row["category"],
                "legacy_content": row["content"],
                "legacy_evidence_level": row["evidence_level"],
                "legacy_confidence": row["confidence"],
                "legacy_source": row["source"],
                "legacy_target": row["target"],
                "legacy_action": row["action"],
                "review_required": True,
            },
        })
    delta = {
        "schema_version": 1,
        "session_id": session_id,
        "generated_at": observed_at,
        "authorized_current_session": True,
        "authorized_sensitive_long_term": False,
        "entities": [entities[key] for key in sorted(entities)],
        "assertions": assertions,
    }
    validate_delta(delta, allow_unknown_supersedes=True)
    return delta


def build_index(entities: list[dict[str, Any]], assertions: list[dict[str, Any]]) -> dict[str, Any]:
    registry = load_registry()
    entity_map = {item["entity_id"]: item for item in entities}
    superseded = {old_id for item in assertions for old_id in item.get("supersedes", [])}
    effective = [
        item for item in assertions
        if item["assertion_id"] not in superseded and item.get("lifecycle") not in {"superseded", "expired"}
    ]
    by_type: dict[str, list[str]] = {}
    for entity in entities:
        by_type.setdefault(entity["entity_type"], []).append(entity["entity_id"])
    by_subject: dict[str, list[str]] = {}
    by_predicate: dict[str, list[str]] = {}
    for assertion in effective:
        by_subject.setdefault(assertion["subject_id"], []).append(assertion["assertion_id"])
        by_predicate.setdefault(assertion["predicate"], []).append(assertion["assertion_id"])

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for assertion in effective:
        if registry.get(assertion["predicate"], {}).get("cardinality") == "one":
            grouped.setdefault((assertion["subject_id"], assertion["predicate"], assertion["scope"]), []).append(assertion)
    conflicts: list[dict[str, Any]] = []
    for (subject_id, predicate, scope), items in sorted(grouped.items()):
        conflicting_ids: set[str] = set()
        for left_index, left in enumerate(items):
            left_start = parse_datetime(left.get("valid_from"), "valid_from", nullable=True)
            left_end = parse_datetime(left.get("valid_until"), "valid_until", nullable=True)
            for right in items[left_index + 1:]:
                if object_key(left["object"]) == object_key(right["object"]):
                    continue
                right_start = parse_datetime(right.get("valid_from"), "valid_from", nullable=True)
                right_end = parse_datetime(right.get("valid_until"), "valid_until", nullable=True)
                latest_start = max(value for value in (left_start, right_start) if value is not None) if left_start or right_start else None
                earliest_end = min(value for value in (left_end, right_end) if value is not None) if left_end or right_end else None
                if latest_start is None or earliest_end is None or latest_start <= earliest_end:
                    conflicting_ids.update((left["assertion_id"], right["assertion_id"]))
        if conflicting_ids:
            ids = sorted(conflicting_ids)
            digest = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:16]
            conflicts.append({
                "conflict_id": f"c:{digest}",
                "subject_id": subject_id,
                "predicate": predicate,
                "scope": scope,
                "assertion_ids": ids,
                "resolution": "needs_time_scope_or_authoritative_evidence",
            })
    return {
        "schema_version": 1,
        "entity_count": len(entities),
        "assertion_count": len(assertions),
        "effective_assertion_ids": sorted(item["assertion_id"] for item in effective),
        "superseded_assertion_ids": sorted(superseded),
        "by_entity_type": {key: sorted(value) for key, value in sorted(by_type.items())},
        "by_subject": {key: sorted(value) for key, value in sorted(by_subject.items())},
        "by_predicate": {key: sorted(value) for key, value in sorted(by_predicate.items())},
        "conflicts": conflicts,
        "entity_labels": {key: entity_map[key]["canonical_name"] for key in sorted(entity_map)},
    }


def render_classification(delta: dict[str, Any]) -> str:
    lines = [f"# 本体分类投影：{delta['session_id']}", "", "此页由 `ontology.json` 生成，用于人工浏览；会话本体是结构化真源。", ""]
    if not delta["assertions"]:
        lines.append("本次无可复用本体断言。")
        return "\n".join(lines).rstrip() + "\n"
    for item in delta["assertions"]:
        obj = item["object"].get("entity_id") if item["object"]["kind"] == "entity" else item["object"].get("value")
        source = item["source_refs"][0]
        lines.extend((
            f"## {item['assertion_id']}", "",
            f"- 三元组：`{item['subject_id']}` — `{item['predicate']}` → `{obj}`",
            f"- 证据：{item['epistemic_status']} / {item['confidence']} / {source['session_id']} turn {source['turn']}",
            f"- 状态：{item['lifecycle']} / {item['retention']} / {item['sensitivity']}",
            f"- 推翻：{item['reversal']}", "",
        ))
    return "\n".join(lines).rstrip() + "\n"


def plan_ontology_writes(memory_root: Path, delta: dict[str, Any]) -> tuple[dict[Path, str], dict[str, Any]]:
    entities_store, assertions_store = load_store(memory_root)
    known_entities = {item["entity_id"]: item for item in entities_store["entities"]}
    known_assertions = {item["assertion_id"]: item for item in assertions_store["assertions"]}
    validate_delta(delta, known_entities, known_assertions)

    long_term_assertions = [item for item in delta["assertions"] if item["retention"] == "long_term"]
    long_term_entity_ids = {item["subject_id"] for item in long_term_assertions}
    long_term_entity_ids.update(
        item["object"]["entity_id"] for item in long_term_assertions if item["object"]["kind"] == "entity"
    )
    for entity in delta["entities"]:
        if entity["entity_id"] not in long_term_entity_ids:
            continue
        existing = known_entities.get(entity["entity_id"])
        known_entities[entity["entity_id"]] = merge_entity(existing, entity) if existing else entity
    for assertion in long_term_assertions:
        existing = known_assertions.get(assertion["assertion_id"])
        if existing:
            require(canonical_json(existing) == canonical_json(assertion), f"E_ASSERTION_IMMUTABLE: content changed for {assertion['assertion_id']}")
        else:
            known_assertions[assertion["assertion_id"]] = assertion

    entities = [known_entities[key] for key in sorted(known_entities)]
    assertions = [known_assertions[key] for key in sorted(known_assertions)]
    index = build_index(entities, assertions)
    meta = {
        "schema_version": 1,
        "ontology_version": "1.0.0",
        "entity_count": len(entities),
        "assertion_count": len(assertions),
        "last_session_id": delta["session_id"],
        "index_sha256": hashlib.sha256(pretty_json(index).encode("utf-8")).hexdigest(),
    }
    session_rel = Path("sessions") / delta["session_id"] / "ontology.json"
    writes = {
        memory_root / session_rel: pretty_json(delta),
        memory_root / "ontology" / "entities.json": pretty_json({"schema_version": 1, "entities": entities}),
        memory_root / "ontology" / "assertions.json": pretty_json({"schema_version": 1, "assertions": assertions}),
        memory_root / "ontology" / "index.json": pretty_json(index),
        memory_root / "ontology" / "meta.json": pretty_json(meta),
    }
    return writes, {
        "ontology_entity_count": len(entities),
        "ontology_assertion_count": len(assertions),
        "session_entity_count": len(delta["entities"]),
        "session_assertion_count": len(delta["assertions"]),
        "long_term_assertion_count": len(long_term_assertions),
        "session_only_assertion_count": len(delta["assertions"]) - len(long_term_assertions),
        "restricted_assertion_count": sum(item["sensitivity"] == "restricted" for item in delta["assertions"]),
        "restricted_long_term_assertion_count": sum(
            item["sensitivity"] == "restricted" and item["retention"] == "long_term"
            for item in delta["assertions"]
        ),
        "candidate_assertion_count": sum(item["lifecycle"] == "candidate" for item in delta["assertions"]),
        "sensitive_long_term_authorized": delta["authorized_sensitive_long_term"],
        "conflict_count": len(index["conflicts"]),
    }


def atomic_write_set(memory_root: Path, writes: dict[Path, str]) -> None:
    memory_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".ontology-store-", dir=memory_root))
    backup = stage / "backup"
    replaced: list[Path] = []
    items = list(writes.items())
    try:
        staged: dict[Path, Path] = {}
        for index, (target, content) in enumerate(items):
            temp_path = stage / f"write-{index}.tmp"
            temp_path.write_text(content, encoding="utf-8", newline="\n")
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
        for target, expected in items:
            require(target.read_text(encoding="utf-8") == expected, f"E_VERIFY: final readback failed: {target}")
    except Exception:
        for index, (target, _content) in reversed(list(enumerate(items))):
            backup_path = backup / f"backup-{index}.bin"
            if backup_path.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, target)
            elif target in replaced and target.exists():
                target.unlink()
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def validate_store(memory_root: Path) -> dict[str, Any]:
    ontology_root = memory_root / "ontology"
    required_paths = [ontology_root / name for name in ("entities.json", "assertions.json", "index.json", "meta.json")]
    for path in required_paths:
        require(path.is_file(), f"E_NOT_INITIALIZED: missing ontology store file: {path}")
    entities_store, assertions_store = load_store(memory_root)
    entity_map = {item["entity_id"]: item for item in entities_store["entities"]}
    assertion_map = {item["assertion_id"]: item for item in assertions_store["assertions"]}
    require(len(entity_map) == len(entities_store["entities"]), "E_STORE_SCHEMA: duplicate entity IDs")
    require(len(assertion_map) == len(assertions_store["assertions"]), "E_STORE_SCHEMA: duplicate assertion IDs")
    registry = load_registry()
    for entity in entity_map.values():
        require(entity.get("entity_type") in ENTITY_TYPES, f"E_STORE_SCHEMA: invalid entity type: {entity.get('entity_id')}")
    for assertion in assertion_map.values():
        require(assertion.get("subject_id") in entity_map, f"E_STORE_SCHEMA: unknown subject: {assertion.get('assertion_id')}")
        require(assertion.get("predicate") in registry, f"E_STORE_SCHEMA: unknown predicate: {assertion.get('predicate')}")
        if assertion.get("object", {}).get("kind") == "entity":
            require(assertion["object"].get("entity_id") in entity_map, f"E_STORE_SCHEMA: unknown object entity: {assertion.get('assertion_id')}")
    expected = build_index(entities_store["entities"], assertions_store["assertions"])
    actual = load_json(ontology_root / "index.json")
    require(canonical_json(actual) == canonical_json(expected), "E_INDEX_DRIFT: ontology index differs from stores")
    meta = load_json(ontology_root / "meta.json")
    require(meta.get("entity_count") == len(entity_map) and meta.get("assertion_count") == len(assertion_map), "E_META_DRIFT: ontology meta counts differ")
    require(meta.get("index_sha256") == hashlib.sha256(pretty_json(expected).encode("utf-8")).hexdigest(), "E_META_DRIFT: index digest differs")
    return {
        "status": "valid",
        "entity_count": len(entity_map),
        "assertion_count": len(assertion_map),
        "conflict_count": len(expected["conflicts"]),
    }


def validate_request(value: Any) -> dict[str, Any]:
    required = {
        "schema_version", "request_id", "task", "entity_ids", "entity_types", "predicates",
        "as_of", "max_assertions", "include_candidates", "include_disputed",
        "include_restricted", "authorized_sensitive_read",
    }
    require(isinstance(value, dict) and set(value) == required, "E_QUERY_SCHEMA: invalid request fields")
    require(value.get("schema_version") == 1, "E_QUERY_SCHEMA: schema_version must be 1")
    require(isinstance(value.get("request_id"), str) and REQUEST_ID_RE.fullmatch(value["request_id"]), "E_QUERY_SCHEMA: invalid request_id")
    require(isinstance(value.get("task"), str) and value["task"].strip(), "E_QUERY_SCHEMA: task missing")
    require(isinstance(value.get("entity_ids"), list) and all(isinstance(item, str) for item in value["entity_ids"]), "E_QUERY_SCHEMA: entity_ids invalid")
    require(isinstance(value.get("entity_types"), list) and all(item in ENTITY_TYPES for item in value["entity_types"]), "E_QUERY_SCHEMA: entity_types invalid")
    registry = load_registry()
    require(isinstance(value.get("predicates"), list) and all(item in registry for item in value["predicates"]), "E_QUERY_SCHEMA: predicates invalid")
    parse_datetime(value.get("as_of"), "as_of", nullable=True)
    require(isinstance(value.get("max_assertions"), int) and 1 <= value["max_assertions"] <= 50, "E_QUERY_SCHEMA: max_assertions must be 1..50")
    for field in ("include_candidates", "include_disputed", "include_restricted", "authorized_sensitive_read"):
        require(isinstance(value.get(field), bool), f"E_QUERY_SCHEMA: {field} must be boolean")
    if value["include_restricted"]:
        require(value["authorized_sensitive_read"], "E_SENSITIVE_AUTH: restricted query lacks explicit read authorization")
    return value


def task_terms(task: str) -> list[str]:
    terms = {item.strip().lower() for item in re.split(r"[\s,，。；;：:、/\\()（）\[\]{}]+", task) if len(item.strip()) >= 2}
    for segment in re.findall(r"[\u3400-\u9fff]{2,}", task):
        for width in (2, 3, 4):
            terms.update(segment[index:index + width] for index in range(len(segment) - width + 1))
    terms.difference_update(TASK_STOP_TERMS)
    return sorted(terms, key=lambda item: (-len(item), item))


def assertion_relevance(
    assertion: dict[str, Any],
    entity_map: dict[str, dict[str, Any]],
    request: dict[str, Any],
) -> int:
    involved = {assertion["subject_id"]}
    if assertion["object"]["kind"] == "entity":
        involved.add(assertion["object"]["entity_id"])
    involved_types = {entity_map[item]["entity_type"] for item in involved if item in entity_map}
    if request["entity_ids"] and not involved.intersection(request["entity_ids"]):
        return 0
    if request["entity_types"] and not involved_types.intersection(request["entity_types"]):
        return 0
    if request["predicates"] and assertion["predicate"] not in request["predicates"]:
        return 0
    score = 0
    score += 100 * len(involved.intersection(request["entity_ids"]))
    score += 40 * len(involved_types.intersection(request["entity_types"]))
    if assertion["predicate"] in request["predicates"]:
        score += 60
    qualifiers = assertion.get("qualifiers", {})
    haystack_parts = [assertion["predicate"], assertion["scope"], *qualifiers.keys(), *qualifiers.values()]
    for entity_id in involved:
        entity = entity_map.get(entity_id, {})
        haystack_parts.extend([entity.get("canonical_name", ""), *entity.get("aliases", [])])
    if assertion["object"]["kind"] == "literal":
        haystack_parts.append(str(assertion["object"].get("value", "")))
    haystack = " ".join(str(item).lower() for item in haystack_parts)
    task_lower = request["task"].lower()
    for entity_id in involved:
        entity = entity_map.get(entity_id, {})
        for label in [entity.get("canonical_name", ""), *entity.get("aliases", [])]:
            if label and label.lower() in task_lower:
                score += 50
    score += 10 * sum(1 for term in task_terms(request["task"]) if term in haystack)
    return score


def query_memory(memory_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    validate_request(request)
    validate_store(memory_root)
    entities_store, assertions_store = load_store(memory_root)
    index = load_json(memory_root / "ontology" / "index.json")
    entity_map = {item["entity_id"]: item for item in entities_store["entities"]}
    effective_ids = set(index["effective_assertion_ids"])
    as_of = parse_datetime(request.get("as_of"), "as_of", nullable=True) or dt.datetime.now(dt.timezone.utc)
    selected: list[tuple[int, dict[str, Any]]] = []
    omitted = {"irrelevant": 0, "lifecycle": 0, "time": 0, "sensitivity": 0, "budget": 0}
    for assertion in assertions_store["assertions"]:
        if assertion["assertion_id"] not in effective_ids:
            omitted["lifecycle"] += 1
            continue
        lifecycle = assertion["lifecycle"]
        if lifecycle == "candidate" and not request["include_candidates"]:
            omitted["lifecycle"] += 1
            continue
        if lifecycle == "disputed" and not request["include_disputed"]:
            omitted["lifecycle"] += 1
            continue
        if assertion["sensitivity"] == "restricted" and not request["include_restricted"]:
            omitted["sensitivity"] += 1
            continue
        if as_of:
            valid_from = parse_datetime(assertion.get("valid_from"), "valid_from", nullable=True)
            valid_until = parse_datetime(assertion.get("valid_until"), "valid_until", nullable=True)
            if (valid_from and as_of < valid_from) or (valid_until and as_of > valid_until):
                omitted["time"] += 1
                continue
        score = assertion_relevance(assertion, entity_map, request)
        if score <= 0:
            omitted["irrelevant"] += 1
            continue
        selected.append((score, assertion))
    selected.sort(key=lambda item: (item[0], item[1]["observed_at"], item[1]["assertion_id"]), reverse=True)
    if len(selected) > request["max_assertions"]:
        omitted["budget"] = len(selected) - request["max_assertions"]
        selected = selected[: request["max_assertions"]]
    assertion_ids = {item[1]["assertion_id"] for item in selected}
    entity_ids: set[str] = set()
    for _score, assertion in selected:
        entity_ids.add(assertion["subject_id"])
        if assertion["object"]["kind"] == "entity":
            entity_ids.add(assertion["object"]["entity_id"])
    conflicts = [item for item in index["conflicts"] if assertion_ids.intersection(item["assertion_ids"])]
    legacy_sessions = {
        assertion["source_refs"][0]["session_id"]
        for _score, assertion in selected
        if assertion.get("qualifiers", {}).get("migration_source") == "classification.md"
    }

    def context_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rendered = []
        for ref in refs:
            if ref["session_id"] in legacy_sessions:
                rendered.append({
                    "session_id": ref["session_id"],
                    "turn": ref["turn"],
                    "role": ref["role"],
                    "excerpt_sha256": hashlib.sha256(ref["excerpt"].encode("utf-8")).hexdigest(),
                    "excerpt_omitted": "legacy_candidate_provenance_only",
                })
            else:
                rendered.append(ref)
        return rendered

    rendered_entities = []
    for key in sorted(entity_ids):
        rendered = dict(entity_map[key])
        rendered["source_refs"] = context_refs(rendered["source_refs"])
        rendered_entities.append(rendered)
    rendered_assertions = []
    for score, assertion in selected:
        rendered = dict(assertion, relevance_score=score)
        rendered["source_refs"] = context_refs(rendered["source_refs"])
        rendered_assertions.append(rendered)
    return {
        "schema_version": 1,
        "status": "matched" if selected else "no_match",
        "request_id": request["request_id"],
        "task": request["task"],
        "as_of": as_of.isoformat(),
        "entities": rendered_entities,
        "assertions": rendered_assertions,
        "conflicts": conflicts,
        "omissions": omitted,
        "refresh_triggers": sorted({item[1]["reversal"] for item in selected}),
        "source_policy": "session_and_turn_coordinates_only; legacy candidate excerpts require explicit provenance review; current user facts override old action assumptions",
    }


def project_memory_root(project_root: Path) -> Path:
    project = project_root.expanduser().resolve()
    require(project.is_dir(), f"E_PROJECT_ROOT: project root does not exist: {project}")
    return (project / "memory" / "xbskill").resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate_delta_parser = sub.add_parser("validate-delta")
    validate_delta_parser.add_argument("--delta", required=True)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--project-root", required=True)
    apply_parser.add_argument("--delta", required=True)
    validate_store_parser = sub.add_parser("validate-store")
    validate_store_parser.add_argument("--project-root", required=True)
    query_parser = sub.add_parser("query")
    query_parser.add_argument("--project-root", required=True)
    query_parser.add_argument("--request", required=True)
    migrate_parser = sub.add_parser("migrate-legacy")
    migrate_parser.add_argument("--project-root", required=True)
    migrate_parser.add_argument("--session-id", required=True)
    migrate_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-delta":
            delta = validate_delta(load_json(Path(args.delta).expanduser().resolve()), allow_unknown_supersedes=True)
            result = {"status": "valid", "session_id": delta["session_id"], "entity_count": len(delta["entities"]), "assertion_count": len(delta["assertions"])}
        elif args.command == "apply":
            memory_root = project_memory_root(Path(args.project_root))
            delta = load_json(Path(args.delta).expanduser().resolve())
            writes, result = plan_ontology_writes(memory_root, delta)
            atomic_write_set(memory_root, writes)
            result = {"status": "applied", "session_id": delta["session_id"], **result}
        elif args.command == "validate-store":
            result = validate_store(project_memory_root(Path(args.project_root)))
        elif args.command == "query":
            memory_root = project_memory_root(Path(args.project_root))
            request = load_json(Path(args.request).expanduser().resolve())
            result = query_memory(memory_root, request)
        else:
            project_root = Path(args.project_root).expanduser().resolve()
            output = Path(args.output).expanduser().resolve()
            require(not output.exists(), f"E_OUTPUT_EXISTS: refusing to overwrite: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            delta = build_legacy_candidate_delta(project_root, args.session_id)
            output.write_text(pretty_json(delta), encoding="utf-8", newline="\n")
            require(load_json(output) == delta, f"E_VERIFY: migration candidate readback failed: {output}")
            result = {
                "status": "candidate_created",
                "session_id": args.session_id,
                "output": str(output),
                "entity_count": len(delta["entities"]),
                "assertion_count": len(delta["assertions"]),
                "all_assertions_candidate": all(item["lifecycle"] == "candidate" for item in delta["assertions"]),
                "review_required": True,
            }
    except (OntologyError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(pretty_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
