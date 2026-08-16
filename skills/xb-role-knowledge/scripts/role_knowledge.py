#!/usr/bin/env python3
"""Validate and resolve executable role-knowledge units for xbskill.

This tool uses only the Python standard library. It never discovers network
sources or executes content from a knowledge packet.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SCOPE_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CALENDAR_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARTIFACT_FIELD_RE = re.compile(r"^[^\s.<>]{1,80}(?:\.[^\s.<>]{1,80})+$")
FAMILIES = {"data", "product_rd", "function", "finance", "marketing"}
STATUSES = {"candidate", "active", "stale", "rejected"}
STAGES = {"S0_new", "S1_working", "S2_system"}
SLOTS = (
    "observe",
    "competing_explanations",
    "distinguish",
    "branches",
    "actions",
    "artifacts",
    "validation",
    "boundaries",
    "reality_feedback",
)
PACKET_SLOTS = SLOTS + ("permissions", "risk_gates", "stage_adaptation")
PERMISSION_KEYS = ("propose", "decide", "authorize", "execute", "verify", "accept_risk")
RISK_GATE_KEYS = ("stop", "escalate", "calibrate")
PERMISSION_POLICIES: dict[str, dict[str, Any]] = {
    "propose": {
        "policy_version": 1,
        "control_type": "permission",
        "permission": "propose",
        "actor_class": "ai_assistant_or_human_proposer",
        "ai_allowed": True,
        "human_authority_required": False,
        "approval_required_before_action": False,
        "execution_allowed": False,
    },
    "decide": {
        "policy_version": 1,
        "control_type": "permission",
        "permission": "decide",
        "actor_class": "accountable_human_decision_owner",
        "ai_allowed": False,
        "human_authority_required": True,
        "approval_required_before_action": False,
        "execution_allowed": False,
    },
    "authorize": {
        "policy_version": 1,
        "control_type": "permission",
        "permission": "authorize",
        "actor_class": "designated_human_authorizer",
        "ai_allowed": False,
        "human_authority_required": True,
        "approval_required_before_action": False,
        "execution_allowed": False,
    },
    "execute": {
        "policy_version": 1,
        "control_type": "permission",
        "permission": "execute",
        "actor_class": "authorized_human_executor",
        "ai_allowed": False,
        "human_authority_required": True,
        "approval_required_before_action": True,
        "execution_allowed": True,
    },
    "verify": {
        "policy_version": 1,
        "control_type": "permission",
        "permission": "verify",
        "actor_class": "accountable_human_or_independent_verifier",
        "ai_allowed": False,
        "human_authority_required": True,
        "approval_required_before_action": False,
        "execution_allowed": False,
    },
    "accept_risk": {
        "policy_version": 1,
        "control_type": "permission",
        "permission": "accept_risk",
        "actor_class": "accountable_human_risk_owner",
        "ai_allowed": False,
        "human_authority_required": True,
        "approval_required_before_action": False,
        "execution_allowed": False,
    },
}
RISK_GATE_POLICIES: dict[str, dict[str, Any]] = {
    "stop": {
        "policy_version": 1,
        "control_type": "risk_gate",
        "gate": "stop",
        "required_action": "stop_and_preserve_recoverability",
        "execution_allowed": False,
        "human_clearance_required": True,
    },
    "escalate": {
        "policy_version": 1,
        "control_type": "risk_gate",
        "gate": "escalate",
        "required_action": "escalate_to_named_human_authority",
        "execution_allowed": False,
        "human_clearance_required": True,
    },
    "calibrate": {
        "policy_version": 1,
        "control_type": "risk_gate",
        "gate": "calibrate",
        "required_action": "calibrate_with_evidence_and_human_owner",
        "execution_allowed": False,
        "human_clearance_required": True,
    },
}
SCORES = ("G", "C", "A", "P", "S", "E", "R", "V")
EVIDENCE_KINDS = {
    "deterministic_positive", "deterministic_negative", "deterministic_stage_pair",
    "deterministic_overturn", "blind_failure", "blind_answer", "independent_review",
}
BLIND_SCENARIO_KINDS = {"positive_s0", "positive_s2", "negative", "overturn"}
ACTUAL_CONSTRAINT_KINDS = {"legal_entity", "jurisdiction", "system_version", "rule_scope"}
ORG_CATEGORY_RE = re.compile(
    r"(?:国企|央企|中央企业|地方国企|省属企业|市属企业|国有企业|国有控股|国资企业|"
    r"国营企业|外企|外资企业|外商投资|外商独资|中外合资|民企|民营企业|私企|私营企业|"
    r"事业单位|政府机关|公共部门|大型企业|跨国公司|非营利组织|"
    r"(?<![a-z0-9])(?:soe|wfoe|mnc)(?![a-z0-9])|state[- ]owned|foreign[- ]owned|"
    r"foreign[- ]company|private[- ]company|public[- ]institution|government[- ]agency|"
    r"public[- ]sector|multinational)",
    re.IGNORECASE,
)
NON_HUMAN_AUTHORITY_RE = re.compile(
    r"(?:AI|人工智能|大模型|语言模型|自动代理|智能代理|机器人|自动化代理|"
    r"(?<![a-z0-9])(?:agent|bot|model)(?![a-z0-9]))",
    re.IGNORECASE,
)
INERT_ASSERTION_RE = re.compile(
    r"(?:未改变任何|没有改变任何|无任何改变|仅(?:仅)?引用|只是引用|没有执行验证|未执行验证|"
    r"无验证|不会观察任何|不观察任何|no changes?|citation only|not executed|no validation|"
    r"will not observe|not applicable)",
    re.IGNORECASE,
)
VAGUE_PLACEHOLDER_RE = re.compile(
    r"^(?:someone|somebody|something|someday|looks fine|result\.changed|artifact\.field|output\.field|later|"
    r"unknown|pending|placeholder|tbd|todo|to be determined|to be confirmed|fill later|not specified|"
    r"待定|待补充|待填写|待确认|稍后|以后再说|后续补充|未知|未指定|占位|某人|相关人员)$",
    re.IGNORECASE,
)
BRACKETED_PLACEHOLDER_RE = re.compile(
    r"(?:<[^>]+>|\[(?:placeholder|tbd|todo|待定|待补充|待填写|待确认|未知|未指定|占位)\]|"
    r"【(?:待定|待补充|待填写|待确认|未知|未指定|占位)】)",
    re.IGNORECASE,
)
UNIT_FIELDS = {
    "record_type", "schema_version", "id", "version", "status", "origin", "name",
    "job_family", "roles", "task_families", "lifecycle_stages", "signals",
    "professional_problem", "claims", "injection", "stage_adaptation", "source_refs",
    "decision_graph", "evidence_model", "permission_model", "risk_gates", "authority_scope", "supersedes",
    "refresh_triggers", "tests", "review",
}
CATALOG_FIELDS = {
    "record_type", "schema_version", "catalog_id", "catalog_version", "origin",
    "published_at", "governance_complete", "units",
}
BUILTIN_SOURCE_REGISTRY_FILE = "builtin-source-registry.json"
BUILTIN_SOURCE_LEDGER_COORDINATE = "xbskill/references/specialty-source-ledger.md"
RUNTIME_SCHEMA_FILE = "role-knowledge-runtime.schema.json"
_RUNTIME_SCHEMA_CACHE: dict[str, Any] | None = None
RELEASE_BINDING_FIELDS = {
    "candidate_catalog_version", "candidate_catalog_digest", "activated_catalog_version",
    "activated_at", "evidence_file", "evidence_sha256", "source_registry_sha256",
}
BLIND_REVIEW_RUBRIC = (
    "G/C/A/P/S/E/R/V each score 0-2: goal and single current specialist; correct conditional reasoning; "
    "user agency; authority ownership; safety and loud stops; falsifiable evidence; reality boundary and feedback; "
    "literal executability by a stranger. Release requires every score=2."
)


class RoleKnowledgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def fail(code: str, message: str) -> None:
    raise RoleKnowledgeError(code, message)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def project_scope_binding(unit: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_version": 1,
        "scope_kind": "project_rule",
        "project_scope_id": binding["project_scope_id"],
        "packet_file": binding["packet_file"],
        "packet_sha256": binding["packet_sha256"],
        "authority_decision_sha256": binding["authority_decision_sha256"],
        "claim_ids": binding["claim_ids"],
        "claims_sha256": canonical_digest(unit["claims"]),
        "job_family": unit["job_family"],
        "roles": unit["roles"],
        "task_families": unit["task_families"],
        "lifecycle_stages": unit["lifecycle_stages"],
    }


def project_rule_scope_digest(unit: dict[str, Any], binding: dict[str, Any]) -> str:
    return f"sha256:{canonical_digest(project_scope_binding(unit, binding))}"


def render_machine_policy(policy: dict[str, Any]) -> str:
    return "; ".join(
        f"{key}={str(value).lower() if type(value) is bool else value}"
        for key, value in policy.items()
    )


def artifact_field_marker(artifact_field: str) -> str:
    return f"[[field:{artifact_field}]]"


def trace_excerpt_placeholder(content: str, artifact_field: str | None = None) -> str:
    if artifact_field:
        return (
            f"<paste an exact delivered-artifact excerpt containing marker "
            f"{artifact_field_marker(artifact_field)} and exact content: {content}>"
        )
    return f"<paste an exact delivered-artifact excerpt containing exact content: {content}>"


def trace_material_placeholder(prefix: str, contents: list[str]) -> str:
    required = " | ".join(contents)
    return f"<{prefix}; include every required content exactly: {required}>"


def delivery_requirements(
    request: dict[str, Any], status: str, matched_units: list[dict[str, Any]],
    source_coordinates: list[dict[str, str]],
) -> dict[str, Any]:
    routing = {
        "current_specialist": request["current_specialist"],
        "task_family": request["task_family"],
        "problem": request["problem"],
        "lifecycle_stage": request["lifecycle_stage"],
        "selected_units": [
            {"unit_id": unit["id"], "match_reasons": unit["match_reasons"]}
            for unit in matched_units
        ],
    }
    if status == "no_match":
        return {
            "mode": "no_match",
            "routing": routing,
            "status_statement": "packet.status=no_match；当前没有岗位知识单元同时命中实际责任与任务/信号。",
            "responsibility_branches": [
                {
                    "hypothesis": "当前岗位责任可能正确，但缺少能区分专业单元的任务事实或权威来源。",
                    "discriminator": "核对实际责任、当前目标、任务信号和可用的一手来源。",
                    "next_action": "补足证据后重新匹配，不在本轮编造岗位事实。",
                },
                {
                    "hypothesis": "当前事项可能由另一具名责任人或专业单元承担。",
                    "discriminator": "确认谁提出、决定、授权、执行、复核并接受剩余风险。",
                    "next_action": "把已确认责任交给入口重新选择一个当前专科。",
                },
                {
                    "hypothesis": "当前事项可能只是通用协作，不需要岗位专科知识。",
                    "discriminator": "确认是否存在专业判断、受控动作或特定验收责任。",
                    "next_action": "若都不存在，保留当前专科做通用支持且不声称岗位知识已应用。",
                },
            ],
            "reality_feedback": {
                "observer": "用户或当前事项的具名责任人",
                "observable": "下一辨别动作是否确认了实际责任、形成新的合法匹配，或继续保持 no_match",
                "when": "取得下一条责任/任务/来源证据后",
            },
            "completion_boundary": "本轮只完成 no_match 与下一辨别点，不证明现实问题已经解决。",
        }
    coordinate_map = {coordinate["source_ref"]: coordinate for coordinate in source_coordinates}
    evidence_requirements: list[dict[str, Any]] = []
    for unit in matched_units:
        evidence_requirements.append({
            "unit_id": unit["id"],
            "claims": [
                {
                    "claim_id": claim["id"],
                    "statement": claim["statement"],
                    "source_bindings": [coordinate_map[source_ref] for source_ref in claim["source_refs"]],
                }
                for claim in unit["claims"]
            ],
            "limitations": unit["evidence_model"]["limitations"],
            "refresh_triggers": unit["refresh_triggers"],
        })
    return {
        "mode": "active",
        "routing": routing,
        "evidence": evidence_requirements,
        "artifact_locator": {
            "marker_syntax": "[[field:<artifact_field>]]",
            "rule": "专业 effect 的 artifact_excerpt 必须同时包含精确 field marker 与所选 effect content。",
        },
        "completion_boundary": "本轮证明岗位知识进入当前交付物，不证明现实问题已经解决。",
    }


def permission_effect(unit: dict[str, Any], permission: str) -> dict[str, Any]:
    policy = copy.deepcopy(PERMISSION_POLICIES[permission])
    context = unit["permission_model"][permission]
    return {
        "effect_id": f"{unit['id']}:{unit['version']}:permissions:{permission}",
        "unit_id": unit["id"],
        "slot": "permissions",
        "content": f"machine_permission_policy: {render_machine_policy(policy)}",
        "policy": policy,
        "responsibility_context": context,
        "context_role": "responsibility_only",
        "authority_effect": False,
    }


def risk_gate_effect(unit: dict[str, Any], gate: str, index: int, context: str) -> dict[str, Any]:
    policy = copy.deepcopy(RISK_GATE_POLICIES[gate])
    return {
        "effect_id": f"{unit['id']}:{unit['version']}:risk_gates:{gate}:{index}",
        "unit_id": unit["id"],
        "slot": "risk_gates",
        "content": f"machine_risk_policy: {render_machine_policy(policy)}",
        "policy": policy,
        "trigger_context": context,
        "context_role": "trigger_condition_only",
        "authority_effect": False,
    }


def reviewable_unit_payload(unit: dict[str, Any]) -> dict[str, Any]:
    """Return the professional/test content that frozen evidence must bind.

    Activation changes lifecycle and review bookkeeping, so those fields are
    deliberately neutralized. Professional content, source bindings, version,
    test prompts, permissions, risk gates, and stage behavior remain covered.
    """
    payload = copy.deepcopy(unit)
    payload.pop("status", None)
    payload.pop("review", None)
    tests = payload.get("tests")
    if isinstance(tests, dict):
        tests.pop("evidence_refs", None)
    return payload


def reviewable_unit_digest(unit: dict[str, Any]) -> str:
    return canonical_digest(reviewable_unit_payload(unit))


def reviewable_catalog_digest(catalog: dict[str, Any]) -> str:
    payload = {
        "record_type": catalog.get("record_type"),
        "schema_version": catalog.get("schema_version"),
        "catalog_id": catalog.get("catalog_id"),
        "origin": catalog.get("origin"),
        "units": [reviewable_unit_payload(unit) for unit in catalog.get("units", [])],
    }
    if "source_registry" in catalog:
        payload["source_registry"] = copy.deepcopy(catalog["source_registry"])
    return canonical_digest(payload)


def absolute_path(raw: str, flag: str, *, must_exist: bool = True, directory: bool = False) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        fail("E_USAGE", f"{flag} must be an absolute path: {raw}")
    path = path.resolve()
    if must_exist and not path.exists():
        fail("E_IO", f"{flag} does not exist: {path}")
    if must_exist and directory and not path.is_dir():
        fail("E_IO", f"{flag} is not a directory: {path}")
    if must_exist and not directory and not path.is_file():
        fail("E_IO", f"{flag} is not a file: {path}")
    return path


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail("E_IO", f"cannot read {path}: {exc}")
    except json.JSONDecodeError as exc:
        fail("E_JSON", f"invalid JSON {path}: {exc}")
    if not isinstance(value, dict):
        fail("E_SCHEMA", f"top-level JSON must be an object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any], *, exclusive: bool) -> None:
    if exclusive and path.exists():
        fail("E_OUTPUT", f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", delete=False, dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive and path.exists():
            fail("E_OUTPUT", f"refusing to overwrite existing file: {path}")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def exact_fields(value: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extras = sorted(actual - expected)
    if missing or extras:
        fail("E_SCHEMA", f"{context} fields mismatch; missing={missing} extras={extras}")


def runtime_schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / RUNTIME_SCHEMA_FILE


def runtime_schema() -> dict[str, Any]:
    """Load the shipped runtime contract without adding a third-party dependency."""

    global _RUNTIME_SCHEMA_CACHE
    if _RUNTIME_SCHEMA_CACHE is not None:
        return _RUNTIME_SCHEMA_CACHE
    path = runtime_schema_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail("E_RK_PACKET", f"runtime packet/trace JSON Schema is missing or unreadable: {path}: {exc}")
    except json.JSONDecodeError as exc:
        fail("E_RK_PACKET", f"runtime packet/trace JSON Schema is invalid JSON: {path}: {exc}")
    if not isinstance(value, dict) or not isinstance(value.get("$defs"), dict):
        fail("E_RK_PACKET", f"runtime packet/trace JSON Schema lacks $defs: {path}")
    for definition in ("RoleKnowledgePacket", "ApplicationTrace", "ApplicationTraceTemplate"):
        if not isinstance(value["$defs"].get(definition), dict):
            fail("E_RK_PACKET", f"runtime packet/trace JSON Schema lacks $defs.{definition}: {path}")
    _RUNTIME_SCHEMA_CACHE = value
    return value


def schema_pointer(root: dict[str, Any], reference: str) -> dict[str, Any] | None:
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return None
    current: Any = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current if isinstance(current, dict) else None


def schema_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": (type(value) is int or type(value) is float),
        "boolean": type(value) is bool,
        "null": value is None,
    }.get(expected, False)


def json_schema_errors(
    value: Any, schema: dict[str, Any], root: dict[str, Any], context: str,
) -> list[str]:
    """Validate the deliberately small Draft 2020-12 subset used by the shipped runtime schema."""

    errors: list[str] = []
    reference = schema.get("$ref")
    if reference is not None:
        target = schema_pointer(root, reference)
        if target is None:
            return [f"{context} schema has an unresolved $ref: {reference}"]
        errors.extend(json_schema_errors(value, target, root, context))

    alternatives = schema.get("oneOf")
    if alternatives is not None:
        if not isinstance(alternatives, list) or not alternatives:
            errors.append(f"{context} schema oneOf must be a non-empty array")
        else:
            matches = [
                not json_schema_errors(value, candidate, root, context)
                for candidate in alternatives
                if isinstance(candidate, dict)
            ]
            if sum(matches) != 1:
                errors.append(f"{context} must match exactly one permitted runtime structure")

    if "const" in schema and value != schema["const"]:
        errors.append(f"{context} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{context} is not one of the permitted values")

    expected_types = schema.get("type")
    if expected_types is not None:
        candidates = [expected_types] if isinstance(expected_types, str) else expected_types
        if not isinstance(candidates, list) or not all(isinstance(item, str) for item in candidates):
            errors.append(f"{context} schema type declaration is invalid")
            return errors
        if not any(schema_type_matches(value, item) for item in candidates):
            errors.append(f"{context} must have JSON type {'|'.join(candidates)}")
            return errors

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if type(minimum) is int and len(value) < minimum:
            errors.append(f"{context} must contain at least {minimum} character(s)")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                matched = re.search(pattern, value) is not None
            except re.error as exc:
                errors.append(f"{context} schema pattern is invalid: {exc}")
            else:
                if not matched:
                    errors.append(f"{context} does not match the required pattern")

    if type(value) is int:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{context} must be >= {minimum}")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{context} must be <= {maximum}")

    if isinstance(value, list):
        minimum = schema.get("minItems")
        if type(minimum) is int and len(value) < minimum:
            errors.append(f"{context} must contain at least {minimum} item(s)")
        if schema.get("uniqueItems") is True:
            digests = [canonical_digest(item) for item in value]
            if len(set(digests)) != len(digests):
                errors.append(f"{context} must not contain duplicate items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(json_schema_errors(item, item_schema, root, f"{context}[{index}]"))

    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for field in required:
                if isinstance(field, str) and field not in value:
                    errors.append(f"{context} is missing required field {field}")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for field, field_schema in properties.items():
                if field in value and isinstance(field_schema, dict):
                    errors.extend(json_schema_errors(value[field], field_schema, root, f"{context}.{field}"))
            if schema.get("additionalProperties") is False:
                extras = sorted(set(value) - set(properties))
                if extras:
                    errors.append(f"{context} contains unsupported field(s): {extras}")
    return errors


def validate_runtime_schema(value: Any, definition: str, error_code: str) -> None:
    schema = runtime_schema()
    definition_schema = schema["$defs"].get(definition)
    if not isinstance(definition_schema, dict):
        fail("E_RK_PACKET", f"runtime JSON Schema definition is missing: {definition}")
    errors = json_schema_errors(value, definition_schema, schema, definition)
    if errors:
        fail(error_code, f"{definition} JSON Schema violation: {errors[0]}")


def nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail("E_SCHEMA", f"{context} must be a non-empty string")
    return value.strip()


def utc_timestamp(value: Any, context: str) -> str:
    result = nonempty_string(value, context)
    if not UTC_TIMESTAMP_RE.fullmatch(result):
        fail("E_SCHEMA", f"{context} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        dt.datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        fail("E_SCHEMA", f"{context} is not a real UTC date/time")
    return result


def calendar_date(value: Any, context: str) -> str:
    result = nonempty_string(value, context)
    if not CALENDAR_DATE_RE.fullmatch(result):
        fail("E_SCHEMA", f"{context} must be a YYYY-MM-DD date")
    try:
        dt.datetime.strptime(result, "%Y-%m-%d")
    except ValueError:
        fail("E_SCHEMA", f"{context} is not a real date")
    return result


def string_list(value: Any, context: str, *, minimum: int = 1, ids: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        fail("E_SCHEMA", f"{context} must contain at least {minimum} string item(s)")
    result: list[str] = []
    for index, item in enumerate(value):
        item = nonempty_string(item, f"{context}[{index}]")
        if ids and not ID_RE.fullmatch(item):
            fail("E_SCHEMA", f"{context}[{index}] is not a valid id: {item}")
        result.append(item)
    if len(set(result)) != len(result):
        fail("E_SCHEMA", f"{context} contains duplicate items")
    return result


def evidence_ref_list(value: Any, context: str, *, minimum: int = 0) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) < minimum:
        fail("E_SCHEMA", f"{context} must contain at least {minimum} evidence reference(s)")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_context = f"{context}[{index}]"
        if not isinstance(item, dict):
            fail("E_SCHEMA", f"{item_context} must be an object")
        exact_fields(item, {"file", "sha256", "record_ids"}, item_context)
        file_name = nonempty_string(item["file"], f"{item_context}.file")
        if not re.fullmatch(r"(?:evidence/)?[a-z0-9][a-z0-9-]{2,63}\.json", file_name):
            fail("E_SCHEMA", f"{item_context}.file is outside the allowed evidence path")
        digest = nonempty_string(item["sha256"], f"{item_context}.sha256")
        if not SHA256_RE.fullmatch(digest):
            fail("E_SCHEMA", f"{item_context}.sha256 is invalid")
        record_ids = string_list(item["record_ids"], f"{item_context}.record_ids", ids=True)
        normalized_ref = canonical_digest({"file": file_name, "sha256": digest, "record_ids": record_ids})
        if normalized_ref in seen:
            fail("E_SCHEMA", f"{context} contains a duplicate evidence reference")
        seen.add(normalized_ref)
        result.append({"file": file_name, "sha256": digest, "record_ids": record_ids})
    return result


def validate_review(unit: dict[str, Any], context: str) -> None:
    review = unit.get("review")
    if not isinstance(review, dict):
        fail("E_SCHEMA", f"{context}.review must be an object")
    exact_fields(review, {"status", "answerer_isolated", "reviewer_independent", "scores", "evidence_refs", "reviewed_at", "reviewer_id"}, f"{context}.review")
    if review["status"] not in {"pending", "passed", "failed"}:
        fail("E_SCHEMA", f"{context}.review.status is invalid")
    if type(review["answerer_isolated"]) is not bool or type(review["reviewer_independent"]) is not bool:
        fail("E_SCHEMA", f"{context}.review isolation fields must be boolean")
    evidence_refs = evidence_ref_list(review["evidence_refs"], f"{context}.review.evidence_refs")
    if review["reviewed_at"] is not None:
        utc_timestamp(review["reviewed_at"], f"{context}.review.reviewed_at")
    if review["reviewer_id"] is not None and not isinstance(review["reviewer_id"], str):
        fail("E_SCHEMA", f"{context}.review.reviewer_id must be string or null")
    scores = review["scores"]
    if not isinstance(scores, dict) or set(scores) != set(SCORES):
        fail("E_SCHEMA", f"{context}.review.scores must contain exactly {list(SCORES)}")
    if any(type(scores[key]) is not int or scores[key] not in {0, 1, 2} for key in SCORES):
        fail("E_SCHEMA", f"{context}.review.scores must be integers from 0 to 2")
    if unit["status"] == "active":
        if review["status"] != "passed" or not review["answerer_isolated"] or not review["reviewer_independent"]:
            fail("E_TEST_GATE", f"{context} active unit lacks isolated answerer and independent passed review")
        if any(scores[key] != 2 for key in SCORES):
            fail("E_TEST_GATE", f"{context} active unit has an eight-gate score below 2")
        if not evidence_refs or not review["reviewed_at"] or not review["reviewer_id"]:
            fail("E_TEST_GATE", f"{context} active unit lacks frozen review evidence, date, or reviewer id")


def validate_source_packet_binding(
    unit: dict[str, Any], context: str, project_scope_id: str | None = None,
) -> dict[str, Any]:
    binding = unit.get("source_packet")
    if not isinstance(binding, dict):
        fail("E_SOURCE_PACKET", f"{context} project source_packet must be an object")
    exact_fields(
        binding,
        {
            "packet_file", "packet_sha256", "lock_id", "lock_digest",
            "authority_decided_at", "authority_decision_sha256", "claim_ids",
            "binding_version", "scope_kind", "project_scope_id", "rule_scope_digest",
        },
        f"{context}.source_packet",
    )
    if type(binding["binding_version"]) is not int or binding["binding_version"] != 1:
        fail("E_SOURCE_PACKET", f"{context}.source_packet.binding_version must be integer 1")
    if binding["scope_kind"] != "project_rule":
        fail("E_AUTHORITY", f"{context}.source_packet.scope_kind must be project_rule")
    bound_project_scope_id = nonempty_string(
        binding["project_scope_id"], f"{context}.source_packet.project_scope_id",
    )
    if not ID_RE.fullmatch(bound_project_scope_id):
        fail("E_SOURCE_PACKET", f"{context}.source_packet.project_scope_id is invalid")
    if project_scope_id is not None and bound_project_scope_id != project_scope_id:
        fail("E_AUTHORITY", f"{context}.source_packet belongs to a different project scope")
    packet_file = nonempty_string(binding["packet_file"], f"{context}.source_packet.packet_file")
    if not re.fullmatch(r"knowledge/packets/[a-z0-9][a-z0-9-]{2,63}\.json", packet_file):
        fail("E_SOURCE_PACKET", f"{context}.source_packet.packet_file is outside the allowed packet path")
    packet_sha256 = nonempty_string(binding["packet_sha256"], f"{context}.source_packet.packet_sha256")
    lock_id = nonempty_string(binding["lock_id"], f"{context}.source_packet.lock_id")
    lock_digest = nonempty_string(binding["lock_digest"], f"{context}.source_packet.lock_digest")
    authority_decided_at = utc_timestamp(
        binding["authority_decided_at"], f"{context}.source_packet.authority_decided_at",
    )
    decision_digest = nonempty_string(
        binding["authority_decision_sha256"], f"{context}.source_packet.authority_decision_sha256",
    )
    scope_digest = nonempty_string(binding["rule_scope_digest"], f"{context}.source_packet.rule_scope_digest")
    if authority_decided_at > now_utc():
        fail("E_AUTHORITY", f"{context}.source_packet.authority_decided_at cannot be in the future")
    if not SCOPE_DIGEST_RE.fullmatch(scope_digest):
        fail("E_SOURCE_PACKET", f"{context}.source_packet.rule_scope_digest is invalid")
    if (
        not SHA256_RE.fullmatch(packet_sha256)
        or not SHA256_RE.fullmatch(decision_digest)
        or not ID_RE.fullmatch(lock_id)
        or not SHA256_RE.fullmatch(lock_digest)
    ):
        fail("E_SOURCE_PACKET", f"{context} packet/lock binding digest or id is invalid")
    claim_ids = string_list(binding["claim_ids"], f"{context}.source_packet.claim_ids", ids=True)
    unit_claim_ids = {claim["id"] for claim in unit["claims"]}
    if set(claim_ids) != unit_claim_ids:
        fail("E_SOURCE_PACKET", f"{context} source_packet.claim_ids must exactly bind every unit claim")
    if scope_digest != project_rule_scope_digest(unit, binding):
        fail("E_AUTHORITY", f"{context}.source_packet.rule_scope_digest does not bind the exact project rule scope")
    return binding


def validate_source_packet(
    unit: dict[str, Any], project_root: Path, context: str, project_scope_id: str,
) -> None:
    binding = validate_source_packet_binding(unit, context, project_scope_id)
    packet_file = binding["packet_file"]
    resolved_project = project_root.resolve()
    base = (resolved_project / "memory" / "xbskill").resolve()
    knowledge_root = (base / "knowledge").resolve()
    packets_root = (base / "knowledge" / "packets").resolve()
    packet_path = (base / packet_file).resolve()
    for candidate, label in ((base, "xbskill memory root"), (knowledge_root, "knowledge root"), (packets_root, "packet root")):
        if not candidate.is_relative_to(resolved_project):
            fail("E_PATH_BOUNDARY", f"{context} {label} escapes project root through a link: {candidate}")
    for relative in (
        "registry", "registry/requirements", "sources", "locks", "evidence", "packets", "update-journal",
    ):
        lexical = knowledge_root / relative
        resolved = lexical.resolve()
        resolved_parent = (knowledge_root / Path(relative).parent).resolve()
        if not resolved.is_relative_to(resolved_project) or resolved.parent != resolved_parent:
            fail(
                "E_PATH_BOUNDARY",
                f"{context} governed knowledge directory escapes its exact project parent through a link: {lexical} -> {resolved}",
            )
    if not packet_path.is_relative_to(packets_root) or packet_path.parent != packets_root:
        fail("E_SOURCE_PACKET", f"{context} packet escapes project knowledge/packets: {packet_path}")
    if not packet_path.is_file():
        fail("E_SOURCE_PACKET", f"{context} packet is missing: {packet_path}")
    packet_sha256 = binding["packet_sha256"]
    try:
        actual_packet_sha256 = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    except OSError as exc:
        fail("E_IO", f"cannot read source packet {packet_path}: {exc}")
    if packet_sha256 != actual_packet_sha256:
        fail("E_SOURCE_PACKET", f"{context} packet file digest does not match source_packet binding")
    knowledge_manager = Path(__file__).resolve().parents[2] / "xbskill" / "scripts" / "knowledge_manager.py"
    if not knowledge_manager.is_file():
        fail("E_SOURCE_PACKET", f"knowledge manager dependency is missing: {knowledge_manager}")
    completed = subprocess.run(
        [sys.executable, str(knowledge_manager), "validate", "--root", str(knowledge_root)],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stdout + completed.stderr).strip()
        fail("E_SOURCE_PACKET", f"{context} project KnowledgePacket root failed full validation: {detail}")
    packet = read_json(packet_path)
    if packet.get("record_type") != "KnowledgePacket":
        fail("E_SOURCE_PACKET", f"{context} source is not a KnowledgePacket: {packet_path}")
    if packet.get("model_prior_fallback") is not False or packet.get("execution_authorized") is not False:
        fail("E_SOURCE_PACKET", f"{context} packet permits fallback or execution")
    lock_id = binding["lock_id"]
    lock_digest = binding["lock_digest"]
    if packet.get("lock_id") != lock_id or packet.get("lock_digest") != lock_digest:
        fail("E_SOURCE_PACKET", f"{context} lock id/digest does not match packet")
    claim_ids = binding["claim_ids"]
    packet_claims = {
        item.get("claim_id") for item in packet.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("claim_id"), str)
    }
    missing = sorted(set(claim_ids) - packet_claims)
    if missing:
        fail("E_SOURCE_PACKET", f"{context} packet omits bound claim ids: {missing}")
    packet_sources = {
        item.get("source_id") for item in packet.get("sources", [])
        if isinstance(item, dict) and isinstance(item.get("source_id"), str)
    }
    missing_sources = sorted(set(unit["source_refs"]) - packet_sources)
    if missing_sources:
        fail("E_SOURCE_PACKET", f"{context} unit source_refs are absent from packet sources: {missing_sources}")
    authority = packet.get("authority_decision")
    if not isinstance(authority, dict) or authority.get("status") != "confirmed":
        fail("E_AUTHORITY", f"{context} packet lacks confirmed authority decision")
    if authority.get("scope") != unit["authority_scope"]:
        fail("E_AUTHORITY", f"{context} authority scope does not exactly match unit authority_scope")
    if authority.get("decided_at") != binding["authority_decided_at"]:
        fail("E_AUTHORITY", f"{context} authority decision timestamp does not match source_packet binding")
    if binding["authority_decision_sha256"] != canonical_digest(authority):
        fail("E_AUTHORITY", f"{context} authority decision digest does not bind the exact KnowledgePacket decision")


def validate_unit(
    unit: dict[str, Any], catalog_origin: str, project_root: Path | None,
    project_scope_id: str, context: str,
) -> None:
    allowed = set(UNIT_FIELDS)
    if "source_packet" in unit:
        allowed.add("source_packet")
    exact_fields(unit, allowed, context)
    if unit["record_type"] != "RoleKnowledgeUnit" or type(unit["schema_version"]) is not int or unit["schema_version"] != SCHEMA_VERSION:
        fail("E_SCHEMA", f"{context} record type or schema version is invalid")
    unit_id = nonempty_string(unit["id"], f"{context}.id")
    if not ID_RE.fullmatch(unit_id):
        fail("E_SCHEMA", f"{context}.id is invalid: {unit_id}")
    if not isinstance(unit["version"], str) or not VERSION_RE.fullmatch(unit["version"]):
        fail("E_SCHEMA", f"{context}.version is not semantic x.y.z")
    if unit["status"] not in STATUSES or unit["origin"] not in {"builtin", "project"}:
        fail("E_SCHEMA", f"{context} status or origin is invalid")
    if unit["origin"] != catalog_origin:
        fail("E_CATALOG", f"{context} origin differs from its catalog")
    nonempty_string(unit["name"], f"{context}.name")
    if unit["job_family"] not in FAMILIES:
        fail("E_SCHEMA", f"{context}.job_family is invalid")
    roles = string_list(unit["roles"], f"{context}.roles")
    task_families = string_list(unit["task_families"], f"{context}.task_families")
    lifecycle_stages = string_list(unit["lifecycle_stages"], f"{context}.lifecycle_stages")
    signals = unit["signals"]
    if not isinstance(signals, dict):
        fail("E_SCHEMA", f"{context}.signals must be an object")
    exact_fields(signals, {"include", "exclude"}, f"{context}.signals")
    include_signals = string_list(signals["include"], f"{context}.signals.include")
    exclude_signals = string_list(signals["exclude"], f"{context}.signals.exclude")
    for matcher_term in roles + task_families + lifecycle_stages + include_signals + exclude_signals:
        if ORG_CATEGORY_RE.search(matcher_term):
            fail("E_ORG_STEREOTYPE", f"{context} professional matcher key contains an organization category: {matcher_term}")
    nonempty_string(unit["professional_problem"], f"{context}.professional_problem")
    claims = unit["claims"]
    if not isinstance(claims, list) or not claims:
        fail("E_SCHEMA", f"{context}.claims must be a non-empty array")
    claim_ids: list[str] = []
    unit_sources = set(string_list(unit["source_refs"], f"{context}.source_refs"))
    for index, claim in enumerate(claims):
        claim_context = f"{context}.claims[{index}]"
        if not isinstance(claim, dict):
            fail("E_SCHEMA", f"{claim_context} must be an object")
        exact_fields(claim, {"id", "statement", "conditions", "source_refs", "disconfirming_signals"}, claim_context)
        claim_id = nonempty_string(claim["id"], f"{claim_context}.id")
        if not ID_RE.fullmatch(claim_id):
            fail("E_SCHEMA", f"{claim_context}.id is invalid")
        claim_ids.append(claim_id)
        nonempty_string(claim["statement"], f"{claim_context}.statement")
        string_list(claim["conditions"], f"{claim_context}.conditions")
        claim_sources = set(string_list(claim["source_refs"], f"{claim_context}.source_refs"))
        if not claim_sources <= unit_sources:
            fail("E_SCHEMA", f"{claim_context} references sources absent from unit.source_refs")
        string_list(claim["disconfirming_signals"], f"{claim_context}.disconfirming_signals")
    if len(set(claim_ids)) != len(claim_ids):
        fail("E_DUPLICATE", f"{context} contains duplicate claim ids")
    if "source_packet" in unit:
        validate_source_packet_binding(unit, context, project_scope_id if catalog_origin == "project" else None)
    injection = unit["injection"]
    if not isinstance(injection, dict) or set(injection) != set(SLOTS):
        fail("E_SCHEMA", f"{context}.injection must contain exactly {list(SLOTS)}")
    for slot in SLOTS:
        minimum = 2 if slot == "competing_explanations" else 1
        string_list(injection[slot], f"{context}.injection.{slot}", minimum=minimum)
    decision_graph = unit["decision_graph"]
    if not isinstance(decision_graph, list) or not decision_graph:
        fail("E_SCHEMA", f"{context}.decision_graph must be a non-empty array")
    explanation_set = set(injection["competing_explanations"])
    covered_explanations: set[str] = set()
    permission_fields = set(PERMISSION_KEYS)
    for index, graph in enumerate(decision_graph):
        graph_context = f"{context}.decision_graph[{index}]"
        if not isinstance(graph, dict):
            fail("E_SCHEMA", f"{graph_context} must be an object")
        exact_fields(
            graph,
            {"hypotheses", "distinguishing_action", "evidence_output", "required_permission", "outcomes"},
            graph_context,
        )
        hypotheses = set(string_list(graph["hypotheses"], f"{graph_context}.hypotheses", minimum=2))
        unknown_hypotheses = sorted(hypotheses - explanation_set)
        if unknown_hypotheses:
            fail("E_SCHEMA", f"{graph_context} cites hypotheses absent from competing_explanations: {unknown_hypotheses}")
        covered_explanations.update(hypotheses)
        nonempty_string(graph["distinguishing_action"], f"{graph_context}.distinguishing_action")
        nonempty_string(graph["evidence_output"], f"{graph_context}.evidence_output")
        if graph["required_permission"] not in permission_fields:
            fail("E_SCHEMA", f"{graph_context}.required_permission is invalid")
        outcomes = graph["outcomes"]
        if not isinstance(outcomes, list) or len(outcomes) < 2:
            fail("E_SCHEMA", f"{graph_context}.outcomes must contain at least two outcomes")
        outcome_conditions: list[str] = []
        for outcome_index, outcome in enumerate(outcomes):
            outcome_context = f"{graph_context}.outcomes[{outcome_index}]"
            if not isinstance(outcome, dict):
                fail("E_SCHEMA", f"{outcome_context} must be an object")
            exact_fields(outcome, {"when", "interpretation", "next_action"}, outcome_context)
            outcome_conditions.append(nonempty_string(outcome["when"], f"{outcome_context}.when"))
            nonempty_string(outcome["interpretation"], f"{outcome_context}.interpretation")
            nonempty_string(outcome["next_action"], f"{outcome_context}.next_action")
        if len(set(outcome_conditions)) != len(outcome_conditions):
            fail("E_SCHEMA", f"{graph_context}.outcomes contains duplicate when conditions")
    uncovered = sorted(explanation_set - covered_explanations)
    if uncovered:
        fail("E_SCHEMA", f"{context}.decision_graph does not cover competing explanations: {uncovered}")
    stages = unit["stage_adaptation"]
    if not isinstance(stages, dict) or set(stages) != STAGES:
        fail("E_SCHEMA", f"{context}.stage_adaptation must contain exactly {sorted(STAGES)}")
    for stage in STAGES:
        string_list(stages[stage], f"{context}.stage_adaptation.{stage}")
    if canonical_digest(stages["S0_new"]) == canonical_digest(stages["S2_system"]):
        fail("E_TEST_GATE", f"{context} S0_new and S2_system cannot be identical")
    evidence_model = unit["evidence_model"]
    if not isinstance(evidence_model, dict):
        fail("E_SCHEMA", f"{context}.evidence_model must be an object")
    exact_fields(evidence_model, {"confidence", "observation_window", "limitations"}, f"{context}.evidence_model")
    if evidence_model["confidence"] not in {"low", "medium", "high"}:
        fail("E_SCHEMA", f"{context}.evidence_model.confidence is invalid")
    nonempty_string(evidence_model["observation_window"], f"{context}.evidence_model.observation_window")
    string_list(evidence_model["limitations"], f"{context}.evidence_model.limitations")
    permission_model = unit["permission_model"]
    if not isinstance(permission_model, dict):
        fail("E_SCHEMA", f"{context}.permission_model must be an object")
    exact_fields(permission_model, permission_fields, f"{context}.permission_model")
    permission_text = {
        field: nonempty_string(permission_model[field], f"{context}.permission_model.{field}")
        for field in permission_fields
    }
    if "AI" not in permission_text["propose"] or re.search(r"提出|起草|建议", permission_text["propose"]) is None:
        fail("E_PERMISSION", f"{context}.permission_model.propose must limit AI to proposing/drafting")
    waived_gate = re.compile(r"(?:无需|无须|不需|不必|没有).{0,8}(?:授权|批准|复核|停止)|无授权")
    ai_power = re.compile(r"AI.{0,8}(?:直接|自行|独立|无需授权).{0,8}(?:决定|授权|批准|执行|删除|发布|变更|接受.{0,6}风险)")
    for field, text in permission_text.items():
        if waived_gate.search(text) or (field != "propose" and ai_power.search(text)):
            fail("E_PERMISSION", f"{context}.permission_model.{field} grants or normalizes unowned authority")
        if field != "propose" and NON_HUMAN_AUTHORITY_RE.search(text):
            fail("E_PERMISSION", f"{context}.permission_model.{field} cannot assign authority or execution to a non-human agent")
    permission_markers = {
        "decide": r"决定|裁决",
        "authorize": r"授权|批准",
        "execute": r"执行|实施|实现|交付|流转|运行|准备|发布|回滚",
        "verify": r"验证|确认|核验|复核|验收",
        "accept_risk": r"接受.{0,8}风险|风险.{0,8}接受",
    }
    for field, marker in permission_markers.items():
        if re.search(marker, permission_text[field]) is None:
            fail("E_PERMISSION", f"{context}.permission_model.{field} does not name its distinct authority action")
    if re.search(r"获批|授权|既有权限|批准范围|确认范围", permission_text["execute"]) is None:
        fail("E_PERMISSION", f"{context}.permission_model.execute must stay inside an explicit approved scope")
    if re.search(r"owner|负责人|有权|主体|领导|sponsor", permission_text["accept_risk"], re.IGNORECASE) is None:
        fail("E_PERMISSION", f"{context}.permission_model.accept_risk must retain a human/organizational risk owner")
    risk_gates = unit["risk_gates"]
    if not isinstance(risk_gates, dict):
        fail("E_SCHEMA", f"{context}.risk_gates must be an object")
    exact_fields(risk_gates, set(RISK_GATE_KEYS), f"{context}.risk_gates")
    validated_risk_gates = {
        field: string_list(risk_gates[field], f"{context}.risk_gates.{field}")
        for field in ("stop", "escalate", "calibrate")
    }
    if any("停止" not in text or re.search(r"无需停止|无须停止|不需停止|不必停止", text) for text in validated_risk_gates["stop"]):
        fail("E_SAFETY", f"{context}.risk_gates.stop must state affirmative stop conditions")
    if any(re.search(r"交|升级|移交|报告|复核", text) is None for text in validated_risk_gates["escalate"]):
        fail("E_SAFETY", f"{context}.risk_gates.escalate must name an escalation or handoff")
    if any(re.search(r"无需|无须|不需|不必", text) for text in validated_risk_gates["calibrate"]):
        fail("E_SAFETY", f"{context}.risk_gates.calibrate cannot waive calibration")
    for gate, texts in validated_risk_gates.items():
        if any(NON_HUMAN_AUTHORITY_RE.search(text) for text in texts):
            fail("E_SAFETY", f"{context}.risk_gates.{gate} cannot delegate a risk gate to a non-human agent")
    nonempty_string(unit["authority_scope"], f"{context}.authority_scope")
    supersedes = string_list(unit["supersedes"], f"{context}.supersedes", minimum=0, ids=True)
    if unit_id in supersedes:
        fail("E_SCHEMA", f"{context} cannot supersede itself")
    string_list(unit["refresh_triggers"], f"{context}.refresh_triggers")
    tests = unit["tests"]
    if not isinstance(tests, dict):
        fail("E_SCHEMA", f"{context}.tests must be an object")
    exact_fields(tests, {"positive", "negative", "stage_pair", "overturn", "evidence_refs"}, f"{context}.tests")
    for field in ("positive", "negative", "stage_pair", "overturn"):
        string_list(tests[field], f"{context}.tests.{field}")
    test_evidence = evidence_ref_list(tests["evidence_refs"], f"{context}.tests.evidence_refs")
    if unit["status"] == "active" and not test_evidence:
        fail("E_TEST_GATE", f"{context} active unit lacks frozen test evidence refs")
    validate_review(unit, context)
    if catalog_origin == "builtin":
        if "source_packet" in unit:
            fail("E_CATALOG", f"{context} builtin unit must use the published source ledger, not a project packet")
    elif unit["status"] == "active":
        if project_root is None:
            fail("E_SOURCE_PACKET", f"{context} active project unit cannot be validated without project root")
        validate_source_packet(unit, project_root, context, project_scope_id)


def validate_evidence_registry(registry: dict[str, Any], path: Path) -> dict[str, dict[str, Any]]:
    context = f"evidence registry {path}"
    exact_fields(registry, {
        "record_type", "schema_version", "registry_id", "catalog_id", "candidate_catalog_version",
        "candidate_catalog_digest", "frozen_at", "records",
    }, context)
    if registry["record_type"] != "RoleKnowledgeEvidenceRegistry" or type(registry["schema_version"]) is not int or registry["schema_version"] != 1:
        fail("E_TEST_GATE", f"{context} type or schema version is invalid")
    registry_id = nonempty_string(registry["registry_id"], f"{context}.registry_id")
    catalog_id = nonempty_string(registry["catalog_id"], f"{context}.catalog_id")
    if not ID_RE.fullmatch(registry_id) or not ID_RE.fullmatch(catalog_id):
        fail("E_TEST_GATE", f"{context}.registry_id or catalog_id is invalid")
    if not isinstance(registry["candidate_catalog_version"], str) or not VERSION_RE.fullmatch(registry["candidate_catalog_version"]):
        fail("E_TEST_GATE", f"{context}.candidate_catalog_version is invalid")
    if not isinstance(registry["candidate_catalog_digest"], str) or not SHA256_RE.fullmatch(registry["candidate_catalog_digest"]):
        fail("E_TEST_GATE", f"{context}.candidate_catalog_digest is invalid")
    frozen_at = utc_timestamp(registry["frozen_at"], f"{context}.frozen_at")
    if frozen_at > now_utc():
        fail("E_TEST_GATE", f"{context}.frozen_at cannot be in the future")
    records = registry["records"]
    if not isinstance(records, list) or not records:
        fail("E_TEST_GATE", f"{context}.records must be a non-empty array")
    by_id: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        record_context = f"{context}.records[{index}]"
        if not isinstance(record, dict):
            fail("E_TEST_GATE", f"{record_context} must be an object")
        exact_fields(record, {
            "id", "unit_id", "unit_version", "unit_digest", "kind", "scenario_kind", "executed_at", "actor_id", "input_text", "input_sha256",
            "output_text", "output_sha256", "result", "answerer_id", "reviewer_id",
            "answer_record_ids", "isolation", "scores",
        }, record_context)
        record_id = nonempty_string(record["id"], f"{record_context}.id")
        unit_id = nonempty_string(record["unit_id"], f"{record_context}.unit_id")
        actor_id = nonempty_string(record["actor_id"], f"{record_context}.actor_id")
        if not ID_RE.fullmatch(record_id) or not ID_RE.fullmatch(unit_id) or not ID_RE.fullmatch(actor_id):
            fail("E_TEST_GATE", f"{record_context} id, unit_id, or actor_id is invalid")
        if not isinstance(record["unit_version"], str) or not VERSION_RE.fullmatch(record["unit_version"]):
            fail("E_TEST_GATE", f"{record_context}.unit_version is invalid")
        if not isinstance(record["unit_digest"], str) or not SHA256_RE.fullmatch(record["unit_digest"]):
            fail("E_TEST_GATE", f"{record_context}.unit_digest is invalid")
        if record_id in by_id:
            fail("E_TEST_GATE", f"duplicate evidence record id {record_id} in {path}")
        if record["kind"] not in EVIDENCE_KINDS:
            fail("E_TEST_GATE", f"{record_context}.kind is invalid")
        executed_at = utc_timestamp(record["executed_at"], f"{record_context}.executed_at")
        if executed_at > frozen_at:
            fail("E_TEST_GATE", f"{record_context}.executed_at occurs after registry.frozen_at")
        input_text = nonempty_string(record["input_text"], f"{record_context}.input_text")
        output_text = nonempty_string(record["output_text"], f"{record_context}.output_text")
        if record["input_sha256"] != hashlib.sha256(input_text.encode("utf-8")).hexdigest():
            fail("E_TEST_GATE", f"{record_context}.input_sha256 does not bind input_text")
        if record["output_sha256"] != hashlib.sha256(output_text.encode("utf-8")).hexdigest():
            fail("E_TEST_GATE", f"{record_context}.output_sha256 does not bind output_text")
        answerer_id = record["answerer_id"]
        reviewer_id = record["reviewer_id"]
        if answerer_id is not None and (not isinstance(answerer_id, str) or not ID_RE.fullmatch(answerer_id)):
            fail("E_TEST_GATE", f"{record_context}.answerer_id is invalid")
        if reviewer_id is not None and (not isinstance(reviewer_id, str) or not ID_RE.fullmatch(reviewer_id)):
            fail("E_TEST_GATE", f"{record_context}.reviewer_id is invalid")
        answer_record_ids = string_list(record["answer_record_ids"], f"{record_context}.answer_record_ids", minimum=0, ids=True)
        isolation = record["isolation"]
        if not isinstance(isolation, dict):
            fail("E_TEST_GATE", f"{record_context}.isolation must be an object")
        exact_fields(isolation, {"answerer_blind_to_acceptance", "reviewer_separate_from_answerer"}, f"{record_context}.isolation")
        if any(type(isolation[field]) is not bool for field in isolation):
            fail("E_TEST_GATE", f"{record_context}.isolation fields must be boolean")
        scores = record["scores"]
        if scores is not None:
            if not isinstance(scores, dict) or set(scores) != set(SCORES):
                fail("E_TEST_GATE", f"{record_context}.scores must be null or contain exactly {list(SCORES)}")
            if any(type(scores[key]) is not int or scores[key] not in {0, 1, 2} for key in SCORES):
                fail("E_TEST_GATE", f"{record_context}.scores must use integers from 0 to 2")
        kind = record["kind"]
        if record["scenario_kind"] is not None and not isinstance(record["scenario_kind"], str):
            fail("E_TEST_GATE", f"{record_context}.scenario_kind must be string or null")
        if kind.startswith("deterministic_"):
            if record["scenario_kind"] is not None or record["result"] not in {"passed", "failed"} or answerer_id is not None or reviewer_id is not None or answer_record_ids or scores is not None:
                fail("E_TEST_GATE", f"{record_context} deterministic record has invalid review fields")
        elif kind in {"blind_failure", "blind_answer"}:
            expected_result = "failed" if kind == "blind_failure" else "frozen"
            if record["scenario_kind"] not in BLIND_SCENARIO_KINDS:
                fail("E_TEST_GATE", f"{record_context}.scenario_kind is invalid for blind evidence")
            if record["result"] != expected_result or answerer_id != actor_id or reviewer_id is not None or answer_record_ids or scores is not None:
                fail("E_TEST_GATE", f"{record_context} blind answer/failure has invalid frozen identity fields")
            if isolation["answerer_blind_to_acceptance"] is not True:
                fail("E_TEST_GATE", f"{record_context} answerer was not isolated from acceptance criteria")
        elif kind == "independent_review":
            if record["scenario_kind"] not in BLIND_SCENARIO_KINDS:
                fail("E_TEST_GATE", f"{record_context}.scenario_kind is invalid for independent review")
            if record["result"] not in {"passed", "failed"} or reviewer_id != actor_id or answerer_id is None or answerer_id == reviewer_id:
                fail("E_TEST_GATE", f"{record_context} independent review identity fields are invalid")
            if not answer_record_ids or scores is None:
                fail("E_TEST_GATE", f"{record_context} independent review lacks answer bindings or scores")
            if isolation != {"answerer_blind_to_acceptance": True, "reviewer_separate_from_answerer": True}:
                fail("E_TEST_GATE", f"{record_context} independent review lacks both isolation guarantees")
        by_id[record_id] = record
    for record in by_id.values():
        if record["kind"] != "independent_review":
            continue
        for answer_record_id in record["answer_record_ids"]:
            answer = by_id.get(answer_record_id)
            if answer is None:
                fail("E_TEST_GATE", f"review {record['id']} references missing blind answer {answer_record_id}")
            if answer["kind"] != "blind_answer" or answer["unit_id"] != record["unit_id"]:
                fail("E_TEST_GATE", f"review {record['id']} references an answer for the wrong kind or unit")
            if answer["unit_version"] != record["unit_version"] or answer["unit_digest"] != record["unit_digest"]:
                fail("E_TEST_GATE", f"review {record['id']} does not bind the same frozen unit as {answer_record_id}")
            if answer["answerer_id"] != record["answerer_id"]:
                fail("E_TEST_GATE", f"review {record['id']} answerer_id does not match {answer_record_id}")
            if answer["scenario_kind"] != record["scenario_kind"]:
                fail("E_TEST_GATE", f"review {record['id']} scenario_kind does not match {answer_record_id}")
            if record["executed_at"] <= answer["executed_at"]:
                fail("E_TEST_GATE", f"review {record['id']} must occur strictly after {answer_record_id}")
    return by_id


def evidence_records_from_refs(
    refs: list[dict[str, Any]], catalog_path: Path, unit_id: str,
    cache: dict[Path, tuple[dict[str, Any], dict[str, dict[str, Any]]]],
    expected_catalog_id: str, expected_catalog_digest: str,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    evidence_root = catalog_path.parent.resolve()
    for ref in refs:
        path = (evidence_root / ref["file"]).resolve()
        if not path.is_relative_to(evidence_root) or not path.is_file():
            fail("E_TEST_GATE", f"evidence file is missing or escapes catalog directory: {path}")
        try:
            actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            fail("E_IO", f"cannot read evidence file {path}: {exc}")
        if actual_digest != ref["sha256"]:
            fail("E_TEST_GATE", f"evidence file digest mismatch: {path}")
        if path not in cache:
            registry_value = read_json(path)
            cache[path] = (registry_value, validate_evidence_registry(registry_value, path))
        registry_value, registry = cache[path]
        if (
            registry_value["catalog_id"] != expected_catalog_id
            or registry_value["candidate_catalog_digest"] != expected_catalog_digest
        ):
            fail(
                "E_TEST_GATE",
                f"evidence registry {path} targets a different catalog id or reviewable catalog digest",
            )
        for record_id in ref["record_ids"]:
            if record_id in selected_ids:
                fail("E_TEST_GATE", f"unit {unit_id} repeats evidence record {record_id}")
            record = registry.get(record_id)
            if record is None:
                fail("E_TEST_GATE", f"unit {unit_id} references missing evidence record {record_id} in {path}")
            if record["unit_id"] != unit_id:
                fail("E_TEST_GATE", f"unit {unit_id} references evidence for {record['unit_id']}: {record_id}")
            selected_ids.add(record_id)
            selected.append(record)
    return selected


def validate_active_evidence(
    unit: dict[str, Any], catalog: dict[str, Any], catalog_path: Path,
    cache: dict[Path, tuple[dict[str, Any], dict[str, dict[str, Any]]]],
) -> None:
    expected_digest = reviewable_unit_digest(unit)
    expected_catalog_digest = reviewable_catalog_digest(catalog)
    test_refs = evidence_ref_list(unit["tests"]["evidence_refs"], f"unit {unit['id']}.tests.evidence_refs", minimum=1)
    test_records = evidence_records_from_refs(
        test_refs, catalog_path, unit["id"], cache, catalog["catalog_id"], expected_catalog_digest,
    )
    if any(
        record["unit_version"] != unit["version"] or record["unit_digest"] != expected_digest
        for record in test_records
    ):
        fail("E_TEST_GATE", f"active unit {unit['id']} deterministic evidence targets a different unit version or digest")
    required_kinds = {
        "deterministic_positive", "deterministic_negative", "deterministic_stage_pair", "deterministic_overturn",
    }
    passed_kinds = {record["kind"] for record in test_records if record["result"] == "passed"}
    missing_kinds = sorted(required_kinds - passed_kinds)
    if missing_kinds:
        fail("E_TEST_GATE", f"active unit {unit['id']} lacks passed deterministic evidence: {missing_kinds}")
    review_refs = evidence_ref_list(unit["review"]["evidence_refs"], f"unit {unit['id']}.review.evidence_refs", minimum=1)
    review_records = evidence_records_from_refs(
        review_refs, catalog_path, unit["id"], cache, catalog["catalog_id"], expected_catalog_digest,
    )
    if any(
        record["unit_version"] != unit["version"] or record["unit_digest"] != expected_digest
        for record in review_records
    ):
        fail("E_TEST_GATE", f"active unit {unit['id']} review evidence targets a different unit version or digest")
    matching_reviews = [
        record for record in review_records
        if record["kind"] == "independent_review"
        and record["result"] == "passed"
        and record["reviewer_id"] == unit["review"]["reviewer_id"]
        and record["executed_at"] == unit["review"]["reviewed_at"]
        and record["scores"] == unit["review"]["scores"]
        and all(record["scores"][key] == 2 for key in SCORES)
    ]
    review_coverage = {record["scenario_kind"] for record in matching_reviews}
    if review_coverage != BLIND_SCENARIO_KINDS:
        fail(
            "E_TEST_GATE",
            f"active unit {unit['id']} review declaration lacks four blind scenario kinds: "
            f"missing={sorted(BLIND_SCENARIO_KINDS - review_coverage)}",
        )


def validate_catalog(
    catalog: dict[str, Any], path: Path, project_root: Path | None = None, *, enforce_release_gate: bool = True,
) -> list[dict[str, Any]]:
    origin_hint = catalog.get("origin")
    raw_units = catalog.get("units")
    release_binding_required = bool(
        enforce_release_gate
        and catalog.get("governance_complete") is True
        and isinstance(raw_units, list)
        and any(isinstance(unit, dict) and unit.get("status") == "active" for unit in raw_units)
    )
    expected_catalog_fields = (
        CATALOG_FIELDS
        | ({"source_registry"} if origin_hint == "builtin" else set())
        | ({"release_binding"} if release_binding_required else set())
    )
    exact_fields(catalog, expected_catalog_fields, f"catalog {path}")
    if catalog["record_type"] != "RoleKnowledgeCatalog" or type(catalog["schema_version"]) is not int or catalog["schema_version"] != SCHEMA_VERSION:
        fail("E_SCHEMA", f"catalog record type or schema version is invalid: {path}")
    catalog_id = nonempty_string(catalog["catalog_id"], f"catalog {path}.catalog_id")
    if not ID_RE.fullmatch(catalog_id):
        fail("E_SCHEMA", f"catalog id is invalid: {catalog_id}")
    if not isinstance(catalog["catalog_version"], str) or not VERSION_RE.fullmatch(catalog["catalog_version"]):
        fail("E_SCHEMA", f"catalog version is invalid: {path}")
    origin = catalog["origin"]
    if origin not in {"builtin", "project"}:
        fail("E_SCHEMA", f"catalog origin is invalid: {path}")
    if origin == "project" and project_root is None:
        fail("E_PROJECT_UNINITIALIZED", f"project catalog validation requires its exact project root: {path}")
    if origin == "project" and project_root is not None:
        expected_project_catalog = project_catalog_path(project_root)
        if path.resolve() != expected_project_catalog:
            fail("E_PATH_BOUNDARY", f"project catalog must use the exact governed path: {expected_project_catalog}")
        expected_scope_id = project_scope_id_for_root(project_root)
        if catalog_id != expected_scope_id:
            fail("E_AUTHORITY", f"project catalog id does not bind its exact project root: expected {expected_scope_id}")
    utc_timestamp(catalog["published_at"], f"catalog {path}.published_at")
    if type(catalog["governance_complete"]) is not bool:
        fail("E_SCHEMA", f"catalog governance_complete must be boolean: {path}")
    units = catalog["units"]
    if not isinstance(units, list):
        fail("E_SCHEMA", f"catalog units must be an array: {path}")
    release_records = validate_release_binding(catalog, path, project_root) if release_binding_required else None
    ids: set[str] = set()
    evidence_cache: dict[Path, tuple[dict[str, Any], dict[str, dict[str, Any]]]] = {}
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            fail("E_SCHEMA", f"catalog unit {index} must be an object: {path}")
        validate_unit(unit, origin, project_root, catalog_id, f"{path}.units[{index}]")
        if unit["id"] in ids:
            fail("E_DUPLICATE", f"duplicate unit id {unit['id']} in {path}")
        ids.add(unit["id"])
        if unit["status"] == "active" and enforce_release_gate:
            validate_active_evidence(unit, catalog, path, evidence_cache)
    if release_records is not None:
        validate_frozen_evidence_replay(catalog, units, release_records)
    if origin == "builtin":
        governed_sources = builtin_source_registry(catalog, path)
        for unit in units:
            missing_sources = sorted(set(unit["source_refs"]) - set(governed_sources))
            if missing_sources:
                fail(
                    "E_CATALOG",
                    f"builtin unit {unit['id']} references source ids absent from the governed source registry: {missing_sources}",
                )
            ineligible_sources = sorted(
                source_id for source_id in unit["source_refs"]
                if governed_sources[source_id]["active_for_role_knowledge"] is not True
            )
            if ineligible_sources:
                fail("E_CATALOG", f"builtin unit {unit['id']} uses sources not activated for role knowledge: {ineligible_sources}")
    active_count = sum(unit.get("status") == "active" for unit in units)
    if enforce_release_gate and origin == "builtin" and (not catalog["governance_complete"] or active_count == 0):
        fail("E_CATALOG", f"builtin catalog must be governed and contain active units: {path}")
    if enforce_release_gate and origin == "project" and active_count and not catalog["governance_complete"]:
        fail("E_TEST_GATE", f"project catalog with active units must set governance_complete=true: {path}")
    return units


def builtin_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "builtin-role-knowledge.json"


def project_catalog_path(project_root: Path) -> Path:
    resolved_project = project_root.resolve()
    role_root = (resolved_project / "memory" / "xbskill" / "role-knowledge").resolve()
    if not role_root.is_relative_to(resolved_project):
        fail("E_PATH_BOUNDARY", f"project role-knowledge root escapes project through a link: {role_root}")
    catalog = (role_root / "catalog.json").resolve()
    if not catalog.is_relative_to(resolved_project) or catalog.parent != role_root:
        fail("E_PATH_BOUNDARY", f"project catalog must be a direct child of the resolved role-knowledge root: {catalog}")
    return catalog


def project_scope_id_for_root(project_root: Path) -> str:
    canonical_root = str(project_root.resolve()).replace("\\", "/").casefold()
    return f"project-role-{canonical_digest({'resolved_project_root': canonical_root})[:16]}"


def source_ledger_path() -> Path:
    return Path(__file__).resolve().parents[2] / "xbskill" / "references" / "specialty-source-ledger.md"


def builtin_source_registry_path(catalog_path: Path) -> Path:
    return catalog_path.resolve().parent / BUILTIN_SOURCE_REGISTRY_FILE


def builtin_source_registry(catalog: dict[str, Any], catalog_path: Path) -> dict[str, dict[str, Any]]:
    binding = catalog.get("source_registry")
    if not isinstance(binding, dict):
        fail("E_SOURCE_COORDINATE", "builtin catalog must bind its structured source registry")
    exact_fields(binding, {"file", "sha256"}, "catalog.source_registry")
    if binding["file"] != BUILTIN_SOURCE_REGISTRY_FILE:
        fail("E_SOURCE_COORDINATE", f"builtin source registry must use {BUILTIN_SOURCE_REGISTRY_FILE}")
    expected_registry_digest = nonempty_string(binding["sha256"], "catalog.source_registry.sha256")
    if not SHA256_RE.fullmatch(expected_registry_digest):
        fail("E_SOURCE_COORDINATE", "catalog.source_registry.sha256 is invalid")
    registry_path = builtin_source_registry_path(catalog_path).resolve()
    if registry_path.parent != catalog_path.resolve().parent or not registry_path.is_file():
        fail("E_SOURCE_COORDINATE", f"builtin source registry is missing or outside the catalog directory: {registry_path}")
    try:
        actual_registry_digest = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    except OSError as exc:
        fail("E_IO", f"cannot read builtin source registry {registry_path}: {exc}")
    if actual_registry_digest != expected_registry_digest:
        fail("E_SOURCE_COORDINATE", f"builtin source registry digest drifted: {registry_path}")
    registry = read_json(registry_path)
    exact_fields(registry, {
        "record_type", "schema_version", "registry_id", "registry_version", "captured_at",
        "ledger_file", "ledger_sha256", "license_policies", "security_profiles", "sources",
    }, f"builtin source registry {registry_path}")
    if registry["record_type"] != "RoleKnowledgeBuiltinSourceRegistry" or type(registry["schema_version"]) is not int or registry["schema_version"] != 1:
        fail("E_SOURCE_COORDINATE", "builtin source registry type or schema version is invalid")
    if not ID_RE.fullmatch(nonempty_string(registry["registry_id"], "source registry.registry_id")):
        fail("E_SOURCE_COORDINATE", "builtin source registry id is invalid")
    if not isinstance(registry["registry_version"], str) or not VERSION_RE.fullmatch(registry["registry_version"]):
        fail("E_SOURCE_COORDINATE", "builtin source registry version is invalid")
    utc_timestamp(registry["captured_at"], "source registry.captured_at")
    if registry["ledger_file"] != BUILTIN_SOURCE_LEDGER_COORDINATE:
        fail("E_SOURCE_COORDINATE", "builtin source registry points to an unexpected source ledger")
    ledger = source_ledger_path().resolve()
    if not ledger.is_file():
        fail("E_CATALOG", f"builtin source ledger dependency is missing: {ledger}")
    try:
        ledger_bytes = ledger.read_bytes()
        content = ledger_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        fail("E_IO", f"cannot read builtin source ledger {ledger}: {exc}")
    actual_ledger_digest = hashlib.sha256(ledger_bytes).hexdigest()
    if registry["ledger_sha256"] != actual_ledger_digest:
        fail("E_SOURCE_COORDINATE", f"builtin source ledger digest drifted: {ledger}")
    license_policies = registry["license_policies"]
    security_profiles = registry["security_profiles"]
    if not isinstance(license_policies, dict) or not isinstance(security_profiles, dict):
        fail("E_SOURCE_COORDINATE", "source registry license/security policy maps must be objects")
    for policy_id, policy in license_policies.items():
        if not ID_RE.fullmatch(policy_id) or not isinstance(policy, dict):
            fail("E_SOURCE_COORDINATE", f"invalid license policy {policy_id}")
        exact_fields(policy, {"status", "scope", "basis"}, f"license policy {policy_id}")
        if policy["status"] != "approved" or policy["scope"] != "facts_and_functional_relationships_only_no_verbatim_assets":
            fail("E_LICENSE", f"license policy {policy_id} is not approved for bounded functional reimplementation")
        nonempty_string(policy["basis"], f"license policy {policy_id}.basis")
    for profile_id, profile in security_profiles.items():
        if not ID_RE.fullmatch(profile_id) or not isinstance(profile, dict):
            fail("E_SOURCE_COORDINATE", f"invalid security profile {profile_id}")
        exact_fields(profile, {"review_status", "content_policy", "execution_authorized"}, f"security profile {profile_id}")
        if profile != {
            "review_status": "reviewed",
            "content_policy": "untrusted_data_no_execute",
            "execution_authorized": False,
        }:
            fail("E_SECURITY", f"security profile {profile_id} does not preserve read-only untrusted-content gates")
    ledger_rows: dict[str, str] = {}
    for line in content.splitlines():
        match = re.match(r"^\|\s*((?:OFF|GH)-[A-Z0-9]+)\s", line)
        if match:
            if match.group(1) in ledger_rows:
                fail("E_SOURCE_COORDINATE", f"duplicate source row in ledger: {match.group(1)}")
            ledger_rows[match.group(1)] = hashlib.sha256(line.encode("utf-8")).hexdigest()
    sources = registry["sources"]
    if not isinstance(sources, list) or not sources:
        fail("E_SOURCE_COORDINATE", "builtin source registry contains no sources")
    by_id: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(sources):
        context = f"source registry.sources[{index}]"
        if not isinstance(source, dict):
            fail("E_SOURCE_COORDINATE", f"{context} must be an object")
        exact_fields(source, {
            "id", "status", "active_for_role_knowledge", "row_sha256", "pin",
            "license_policy_id", "security_profile_id",
        }, context)
        source_id = nonempty_string(source["id"], f"{context}.id")
        if not re.fullmatch(r"(?:OFF|GH)-[A-Z0-9]+", source_id) or source_id in by_id:
            fail("E_SOURCE_COORDINATE", f"{context}.id is invalid or duplicated")
        if source["status"] not in {"activated", "supporting", "discovery_only", "rejected"} or type(source["active_for_role_knowledge"]) is not bool:
            fail("E_SOURCE_COORDINATE", f"{context} status or active flag is invalid")
        row_digest = nonempty_string(source["row_sha256"], f"{context}.row_sha256")
        if not SHA256_RE.fullmatch(row_digest) or ledger_rows.get(source_id) != row_digest:
            fail("E_SOURCE_COORDINATE", f"{context} does not bind the exact ledger row for {source_id}")
        pin = source["pin"]
        if not isinstance(pin, dict):
            fail("E_SOURCE_COORDINATE", f"{context}.pin must be an object")
        exact_fields(pin, {"kind", "value"}, f"{context}.pin")
        if source_id.startswith("GH-"):
            if pin["kind"] != "git_commit" or not isinstance(pin["value"], str) or not re.fullmatch(r"[a-f0-9]{40}", pin["value"]):
                fail("E_PIN", f"{context} GitHub source lacks a 40-character commit pin")
        elif pin != {"kind": "retrieval_date", "value": "2026-08-11"}:
            fail("E_PIN", f"{context} official source lacks its frozen retrieval date")
        if source["license_policy_id"] not in license_policies:
            fail("E_LICENSE", f"{context} references an unknown license policy")
        if source["security_profile_id"] not in security_profiles:
            fail("E_SECURITY", f"{context} references an unknown security profile")
        by_id[source_id] = source
    if set(by_id) != set(ledger_rows):
        fail(
            "E_SOURCE_COORDINATE",
            f"structured source registry and ledger row ids differ: missing={sorted(set(ledger_rows)-set(by_id))} extra={sorted(set(by_id)-set(ledger_rows))}",
        )
    return by_id


def validate_release_binding(
    catalog: dict[str, Any], catalog_path: Path, project_root: Path | None,
) -> dict[str, dict[str, Any]]:
    binding = catalog.get("release_binding")
    if not isinstance(binding, dict):
        fail("E_TEST_GATE", f"active governed catalog lacks release binding: {catalog_path}")
    exact_fields(binding, RELEASE_BINDING_FIELDS, "catalog.release_binding")
    candidate_version = nonempty_string(binding["candidate_catalog_version"], "catalog.release_binding.candidate_catalog_version")
    activated_version = nonempty_string(binding["activated_catalog_version"], "catalog.release_binding.activated_catalog_version")
    if not VERSION_RE.fullmatch(candidate_version) or not VERSION_RE.fullmatch(activated_version):
        fail("E_TEST_GATE", "catalog release binding versions are invalid")
    if activated_version != catalog["catalog_version"]:
        fail("E_TEST_GATE", "active catalog_version differs from its frozen release binding")
    activated_at = utc_timestamp(binding["activated_at"], "catalog.release_binding.activated_at")
    if activated_at > now_utc():
        fail("E_TEST_GATE", "catalog release binding activated_at cannot be in the future")
    if activated_at != catalog["published_at"]:
        fail("E_TEST_GATE", "active published_at differs from its frozen release binding")
    candidate_digest = nonempty_string(binding["candidate_catalog_digest"], "catalog.release_binding.candidate_catalog_digest")
    evidence_digest = nonempty_string(binding["evidence_sha256"], "catalog.release_binding.evidence_sha256")
    if not SHA256_RE.fullmatch(candidate_digest) or not SHA256_RE.fullmatch(evidence_digest):
        fail("E_TEST_GATE", "catalog release binding digest is invalid")
    expected_candidate_digest = reviewable_catalog_digest(catalog)
    if candidate_digest != expected_candidate_digest:
        fail("E_TEST_GATE", "active catalog professional/source content differs from its reviewed candidate digest")
    evidence_file = nonempty_string(binding["evidence_file"], "catalog.release_binding.evidence_file")
    if catalog["origin"] == "builtin":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}\.json", evidence_file):
            fail("E_TEST_GATE", "builtin release evidence must be a direct JSON child of the catalog directory")
    elif not re.fullmatch(r"evidence/[a-z0-9][a-z0-9-]{2,63}\.json", evidence_file):
        fail("E_TEST_GATE", "project release evidence must be an evidence/<id>.json child")
    evidence_root = catalog_path.resolve().parent
    evidence_path = (evidence_root / evidence_file).resolve()
    if not evidence_path.is_relative_to(evidence_root) or not evidence_path.is_file():
        fail("E_PATH_BOUNDARY", f"release evidence is missing or escapes the governed catalog root: {evidence_path}")
    if catalog["origin"] == "project" and project_root is not None and not evidence_path.is_relative_to(project_root.resolve()):
        fail("E_PATH_BOUNDARY", f"project release evidence escapes the exact project root: {evidence_path}")
    try:
        actual_evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    except OSError as exc:
        fail("E_IO", f"cannot read release evidence {evidence_path}: {exc}")
    if actual_evidence_digest != evidence_digest:
        fail("E_TEST_GATE", f"release evidence digest drifted: {evidence_path}")
    registry = read_json(evidence_path)
    records = validate_evidence_registry(registry, evidence_path)
    if registry["frozen_at"] > activated_at:
        fail("E_TEST_GATE", "catalog activation must occur at or after evidence registry frozen_at")
    if (
        registry["catalog_id"] != catalog["catalog_id"]
        or registry["candidate_catalog_version"] != candidate_version
        or registry["candidate_catalog_digest"] != candidate_digest
    ):
        fail("E_TEST_GATE", "release evidence targets a different candidate catalog id, version, or digest")
    source_registry_digest = binding["source_registry_sha256"]
    if catalog["origin"] == "builtin":
        if source_registry_digest != catalog["source_registry"]["sha256"]:
            fail("E_SOURCE_COORDINATE", "release evidence does not bind the active builtin source registry")
    elif source_registry_digest is not None:
        fail("E_TEST_GATE", "project release binding must use its KnowledgePackets, not a builtin source registry")
    return records


def legacy_builtin_source_registry_ids() -> set[str]:
    """Discovery-only helper retained for diagnostics; runtime uses the bound JSON registry."""
    ledger = source_ledger_path()
    if not ledger.is_file():
        fail("E_CATALOG", f"builtin source ledger dependency is missing: {ledger}")
    try:
        content = ledger.read_text(encoding="utf-8")
    except OSError as exc:
        fail("E_IO", f"cannot read builtin source ledger {ledger}: {exc}")
    source_ids = set(re.findall(r"^\|\s*((?:OFF|GH)-[A-Z0-9]+)\s", content, flags=re.MULTILINE))
    if not source_ids:
        fail("E_CATALOG", f"builtin source ledger contains no stable source ids: {ledger}")
    return source_ids


def load_units(project_root: Path | None) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    builtins = validate_catalog(read_json(builtin_path()), builtin_path())
    all_units = list(builtins)
    notices: list[dict[str, str]] = []
    if project_root is None:
        return all_units, notices
    project_path = project_catalog_path(project_root)
    if not project_path.is_file():
        fail("E_PROJECT_UNINITIALIZED", f"project role knowledge is not initialized: {project_path}")
    project_units = validate_catalog(read_json(project_path), project_path, project_root)
    builtin_ids = {unit["id"] for unit in builtins}
    project_ids = {unit["id"] for unit in project_units}
    duplicates = sorted(builtin_ids & project_ids)
    if duplicates:
        fail("E_DUPLICATE", f"project unit ids collide with builtin ids: {duplicates}")
    known = builtin_ids | project_ids
    for unit in project_units:
        for old_id in unit["supersedes"]:
            if old_id not in known:
                fail("E_CATALOG", f"project unit {unit['id']} supersedes unknown unit {old_id}")
            notices.append({
                "unit_id": unit["id"],
                "supersedes": old_id,
                "scope_digest": unit["source_packet"]["rule_scope_digest"],
            })
    all_units.extend(project_units)
    return all_units, notices


def validate_request(value: dict[str, Any], path: Path) -> dict[str, Any]:
    fields = {
        "schema_version", "current_specialist", "job_family", "role", "task_family", "lifecycle_stage",
        "proficiency_mode", "problem", "signals", "knowledge_requirement",
        "actual_constraints", "required_unit_ids", "max_units",
    }
    exact_fields(value, fields, f"request {path}")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        fail("E_SCHEMA", f"request schema_version is invalid: {path}")
    if not isinstance(value["job_family"], str) or value["job_family"] not in FAMILIES:
        fail("E_SCHEMA", f"request job_family is invalid: {path}")
    current_specialist = nonempty_string(value["current_specialist"], "request.current_specialist")
    if not re.fullmatch(r"xb-[a-z0-9-]+", current_specialist) or current_specialist == "xb-role-knowledge":
        fail("E_ROUTE_CONFLICT", "request.current_specialist must remain one existing non-role-knowledge xb-* specialist")
    specialist_skill = Path(__file__).resolve().parents[2] / current_specialist / "SKILL.md"
    if not specialist_skill.is_file():
        fail("E_ROUTE_CONFLICT", f"request.current_specialist is not installed in this xbskill suite: {specialist_skill}")
    try:
        specialist_text = specialist_skill.read_text(encoding="utf-8")
    except OSError as exc:
        fail("E_IO", f"cannot read current specialist contract {specialist_skill}: {exc}")
    if re.search(rf"^name:\s*{re.escape(current_specialist)}\s*$", specialist_text, re.MULTILINE) is None:
        fail("E_ROUTE_CONFLICT", f"current specialist SKILL.md does not declare name={current_specialist}")
    for key in ("role", "task_family", "problem"):
        nonempty_string(value[key], f"request.{key}")
    if not isinstance(value["lifecycle_stage"], str):
        fail("E_SCHEMA", "request.lifecycle_stage must be a string, possibly empty")
    if not isinstance(value["proficiency_mode"], str) or value["proficiency_mode"] not in STAGES:
        fail("E_SCHEMA", "request.proficiency_mode is invalid")
    if not isinstance(value["signals"], list) or any(not isinstance(item, str) or not item.strip() for item in value["signals"]):
        fail("E_SCHEMA", "request.signals must be a string array")
    actual_constraints = value["actual_constraints"]
    if not isinstance(actual_constraints, list):
        fail("E_SCHEMA", "request.actual_constraints must be an array")
    seen_constraints: set[tuple[str, str]] = set()
    for index, constraint in enumerate(actual_constraints):
        context = f"request.actual_constraints[{index}]"
        if not isinstance(constraint, dict):
            fail("E_SCHEMA", f"{context} must be an evidence-bound object, not a free-form label")
        exact_fields(constraint, {"kind", "value", "evidence_date", "evidence_ref"}, context)
        if not isinstance(constraint["kind"], str) or constraint["kind"] not in ACTUAL_CONSTRAINT_KINDS:
            fail("E_SCHEMA", f"{context}.kind is invalid")
        constraint_value = nonempty_string(constraint["value"], f"{context}.value")
        if constraint["kind"] == "rule_scope" and not SCOPE_DIGEST_RE.fullmatch(constraint_value):
            fail("E_AUTHORITY", f"{context}.value must be the exact sha256 digest bound by a project KnowledgePacket")
        if ORG_CATEGORY_RE.search(constraint_value):
            fail("E_ORG_STEREOTYPE", f"organization category cannot become a professional match constraint: {constraint_value}")
        evidence_date = calendar_date(constraint["evidence_date"], f"{context}.evidence_date")
        if evidence_date > dt.date.today().isoformat():
            fail("E_AUTHORITY", f"{context}.evidence_date cannot be in the future")
        nonempty_string(constraint["evidence_ref"], f"{context}.evidence_ref")
        key = (constraint["kind"], normalized(constraint_value))
        if key in seen_constraints:
            fail("E_SCHEMA", f"request.actual_constraints repeats {constraint['kind']}={constraint_value}")
        seen_constraints.add(key)
    if not isinstance(value["knowledge_requirement"], str) or value["knowledge_requirement"] not in {"required", "optional"}:
        fail("E_SCHEMA", "request.knowledge_requirement must be required or optional")
    required_unit_ids = string_list(value["required_unit_ids"], "request.required_unit_ids", minimum=0, ids=True)
    if type(value["max_units"]) is not int or value["max_units"] not in {1, 2}:
        fail("E_SCHEMA", "request.max_units must be 1 or 2")
    if len(required_unit_ids) > value["max_units"]:
        fail("E_REQUIRED_UNIT", "request.max_units cannot silently truncate required_unit_ids")
    return value


def normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def text_hit(term: str, haystack: str) -> bool:
    needle = normalized(term)
    return bool(needle) and needle in haystack


def match_units(
    units: list[dict[str, Any]], request: dict[str, Any], notices: list[dict[str, str]],
) -> tuple[list[tuple[int, list[str], dict[str, Any]]], list[dict[str, str]]]:
    required_ids = set(request["required_unit_ids"])
    by_id = {unit["id"]: unit for unit in units}
    missing = sorted(required_ids - set(by_id))
    if missing:
        fail("E_REQUIRED_UNIT", f"required unit ids do not exist: {missing}")
    inactive = sorted(unit_id for unit_id in required_ids if by_id[unit_id]["status"] != "active")
    if inactive:
        fail("E_REQUIRED_UNIT", f"required unit ids are not active: {inactive}")

    haystack = normalized(" ".join([
        request["task_family"], request["lifecycle_stage"], request["problem"], *request["signals"],
    ]))
    matched_by_id: dict[str, tuple[int, list[str], dict[str, Any]]] = {}
    for unit in units:
        if unit["status"] != "active":
            continue
        if required_ids and unit["id"] not in required_ids:
            continue
        if unit["job_family"] != request["job_family"]:
            continue
        if normalized(request["role"]) not in {normalized(role) for role in unit["roles"]}:
            continue
        if unit["origin"] == "project":
            scope_constraints = [
                constraint for constraint in request["actual_constraints"]
                if constraint["kind"] == "rule_scope"
                and constraint["value"] == unit["source_packet"]["rule_scope_digest"]
                and constraint["evidence_ref"] == unit["source_packet"]["packet_file"]
                and constraint["evidence_date"] >= unit["source_packet"]["authority_decided_at"][:10]
            ]
            if not scope_constraints:
                if unit["id"] in required_ids:
                    fail(
                        "E_AUTHORITY",
                        f"required project unit {unit['id']} lacks an exact current rule_scope constraint bound to its KnowledgePacket",
                    )
                continue
        exclude_hits = [term for term in unit["signals"]["exclude"] if text_hit(term, haystack)]
        if exclude_hits:
            if unit["id"] in required_ids:
                fail("E_REQUIRED_UNIT", f"required unit {unit['id']} is blocked by exclude signals: {exclude_hits}")
            continue
        task_hits = [term for term in unit["task_families"] if text_hit(term, normalized(request["task_family"]))]
        signal_hits = [term for term in unit["signals"]["include"] if text_hit(term, haystack)]
        if not task_hits and not signal_hits:
            if unit["id"] in required_ids:
                fail("E_REQUIRED_UNIT", f"required unit {unit['id']} does not match the current task or signals")
            continue
        lifecycle_hits = [stage for stage in unit["lifecycle_stages"] if text_hit(stage, normalized(request["lifecycle_stage"]))]
        if request["lifecycle_stage"] and not lifecycle_hits:
            if unit["id"] in required_ids:
                fail("E_REQUIRED_UNIT", f"required unit {unit['id']} does not match lifecycle_stage={request['lifecycle_stage']}")
            continue
        score = 130 + min(len(task_hits), 2) * 20 + min(len(signal_hits), 3) * 10
        reasons = [f"job_family={unit['job_family']}", f"role={request['role']}"]
        if task_hits:
            reasons.append("task_hits=" + "|".join(task_hits))
        if signal_hits:
            reasons.append("signal_hits=" + "|".join(signal_hits))
        if lifecycle_hits:
            score += 5
            reasons.append("lifecycle_hits=" + "|".join(lifecycle_hits))
        if unit["origin"] == "project":
            score += 3
            reasons.append("authorized_project_scope")
        matched_by_id[unit["id"]] = (score, reasons, unit)

    replacements_by_old: dict[str, list[dict[str, str]]] = {}
    for notice in notices:
        old_id = notice["supersedes"]
        replacement_id = notice["unit_id"]
        if old_id in required_ids and replacement_id in required_ids:
            fail(
                "E_SUPERSESSION_CONFLICT",
                f"request explicitly requires both superseded unit {old_id} and replacement {replacement_id}",
            )
        if old_id in required_ids:
            continue
        if old_id in matched_by_id and replacement_id in matched_by_id:
            replacements_by_old.setdefault(old_id, []).append(notice)

    suppressed: set[str] = set()
    used_notices: list[dict[str, str]] = []
    for old_id, applicable in replacements_by_old.items():
        replacement_ids = sorted({item["unit_id"] for item in applicable})
        if len(replacement_ids) > 1:
            fail(
                "E_SUPERSESSION_CONFLICT",
                f"multiple fully matched project units supersede {old_id}: {replacement_ids}",
            )
        chosen = applicable[0]
        suppressed.add(old_id)
        used_notices.append({
            "unit_id": chosen["unit_id"],
            "supersedes": old_id,
            "scope_digest": chosen["scope_digest"],
        })

    results = [item for unit_id, item in matched_by_id.items() if unit_id not in suppressed]
    results.sort(key=lambda item: (-item[0], item[2]["id"]))
    selected = results[:request["max_units"]]
    selected_ids = {item[2]["id"] for item in selected}
    if required_ids and selected_ids != required_ids:
        fail("E_REQUIRED_UNIT", f"required units were not all selected: missing={sorted(required_ids - selected_ids)}")
    used_notices = [item for item in used_notices if item["unit_id"] in selected_ids]
    return selected, used_notices


def build_packet(
    request: dict[str, Any], matched: list[tuple[int, list[str], dict[str, Any]]],
    supersession_notices: list[dict[str, str]],
) -> dict[str, Any]:
    digest = canonical_digest(request)
    if not matched:
        return {
            "record_type": "RoleKnowledgePacket",
            "schema_version": SCHEMA_VERSION,
            "id": f"rkp-{digest[:16]}",
            "packet_version": "1.3.0",
            "generated_at": now_utc(),
            "context_digest": digest,
            "request": request,
            "status": "no_match",
            "used_unit_ids": [],
            "matched_units": [],
            "active_injection": {slot: [] for slot in PACKET_SLOTS},
            "claims": [],
            "source_refs": [],
            "source_coordinates": [],
            "supersession_notices": [],
            "unknowns": ["No active role knowledge unit matched both the actual role and current task/signals."],
            "omissions": ["No role knowledge was injected."],
            "generic_fallback_allowed": request["knowledge_requirement"] == "optional",
            "model_prior_fallback": False,
            "execution_authorized": False,
            "participation_contract": "no_match: do not claim role-specialized knowledge was applied",
            "delivery_requirements": delivery_requirements(request, "no_match", [], []),
            "completion_boundary": "No knowledge packet or generic answer proves the real-world problem is solved.",
        }

    active_injection: dict[str, list[dict[str, Any]]] = {slot: [] for slot in PACKET_SLOTS}
    packet_units: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    source_refs: list[str] = []
    source_coordinates: dict[str, dict[str, str]] = {}
    for score, reasons, unit in matched:
        unit_claims = []
        for claim in unit["claims"]:
            current = dict(claim)
            current["unit_id"] = unit["id"]
            unit_claims.append(current)
            claims.append(current)
        for slot in SLOTS:
            for index, content in enumerate(unit["injection"][slot], start=1):
                active_injection[slot].append({
                    "effect_id": f"{unit['id']}:{unit['version']}:{slot}:{index}",
                    "unit_id": unit["id"],
                    "slot": slot,
                    "content": content,
                    "authority_effect": False,
                })
        for graph_index, graph in enumerate(unit["decision_graph"], start=1):
            hypotheses = " | ".join(graph["hypotheses"])
            active_injection["distinguish"].append({
                "effect_id": f"{unit['id']}:{unit['version']}:decision_graph:{graph_index}:distinguish",
                "unit_id": unit["id"],
                "slot": "distinguish",
                "content": (
                    f"在权限 {graph['required_permission']} 下区分 [{hypotheses}]："
                    f"{graph['distinguishing_action']}；留下 {graph['evidence_output']}"
                ),
                "authority_effect": False,
            })
            for outcome_index, outcome in enumerate(graph["outcomes"], start=1):
                active_injection["branches"].append({
                    "effect_id": f"{unit['id']}:{unit['version']}:decision_graph:{graph_index}:branch:{outcome_index}",
                    "unit_id": unit["id"],
                    "slot": "branches",
                    "content": (
                        f"若 {outcome['when']}，解释为 {outcome['interpretation']}；"
                        f"下一步 {outcome['next_action']}"
                    ),
                    "authority_effect": False,
                })
        for field in PERMISSION_KEYS:
            active_injection["permissions"].append(permission_effect(unit, field))
        for field in RISK_GATE_KEYS:
            values = unit["risk_gates"][field]
            for index, content in enumerate(values, start=1):
                active_injection["risk_gates"].append(risk_gate_effect(unit, field, index, content))
        stage_effects = [
            {
                "effect_id": f"{unit['id']}:{unit['version']}:stage_adaptation:{index}",
                "unit_id": unit["id"],
                "slot": "stage_adaptation",
                "content": content,
                "authority_effect": False,
            }
            for index, content in enumerate(unit["stage_adaptation"][request["proficiency_mode"]], start=1)
        ]
        active_injection["stage_adaptation"].extend(stage_effects)
        packet_units.append({
            "id": unit["id"],
            "version": unit["version"],
            "origin": unit["origin"],
            "name": unit["name"],
            "score": score,
            "match_reasons": reasons,
            "professional_problem": unit["professional_problem"],
            "claims": unit_claims,
            "decision_graph": unit["decision_graph"],
            "evidence_model": unit["evidence_model"],
            "permission_model": unit["permission_model"],
            "risk_gates": unit["risk_gates"],
            "stage_adaptation": stage_effects,
            "authority_scope": unit["authority_scope"],
            "authority_binding": (
                None
                if unit["origin"] == "builtin"
                else {
                    "scope_binding": project_scope_binding(unit, unit["source_packet"]),
                    "rule_scope_digest": unit["source_packet"]["rule_scope_digest"],
                    "packet_file": unit["source_packet"]["packet_file"],
                    "packet_sha256": unit["source_packet"]["packet_sha256"],
                    "authority_decided_at": unit["source_packet"]["authority_decided_at"],
                }
            ),
            "refresh_triggers": unit["refresh_triggers"],
        })
        for source_ref in unit["source_refs"]:
            if source_ref not in source_refs:
                source_refs.append(source_ref)
            coordinate = {
                "source_ref": source_ref,
                "registry": (
                    "xbskill/references/specialty-source-ledger.md"
                    if unit["origin"] == "builtin"
                    else unit["source_packet"]["packet_file"]
                ),
                "coordinate_key": source_ref,
            }
            existing = source_coordinates.get(source_ref)
            if existing is not None and existing != coordinate:
                fail("E_SOURCE_COORDINATE", f"source ref {source_ref} resolves to conflicting registries")
            source_coordinates[source_ref] = coordinate
    trace_applications: list[dict[str, Any]] = []
    substantive_priority = (
        "actions", "artifacts", "validation", "distinguish", "branches",
        "observe", "competing_explanations", "boundaries", "reality_feedback",
    )
    for unit in packet_units:
        unit_id = unit["id"]
        substantive = next(
            effect
            for slot in substantive_priority
            for effect in active_injection[slot]
            if effect["unit_id"] == unit_id
        )
        validation_contents = [
            effect["content"] for effect in active_injection["validation"]
            if effect["unit_id"] == unit_id
        ]
        control_templates: dict[str, dict[str, list[str]]] = {}
        for control_key, slot in (
            ("permissions", "permissions"),
            ("risk_gates", "risk_gates"),
            ("stage_adaptation", "stage_adaptation"),
        ):
            selected_controls = [
                effect for effect in active_injection[slot]
                if effect["unit_id"] == unit_id
            ]
            unique_contents = list(dict.fromkeys(effect["content"] for effect in selected_controls))
            control_templates[control_key] = {
                "effect_ids": [effect["effect_id"] for effect in selected_controls],
                "artifact_excerpts": [trace_excerpt_placeholder(content) for content in unique_contents],
            }
        trace_applications.append({
            "unit_id": unit_id,
            "unit_version": unit["version"],
            "claim_ids": [claim["id"] for claim in unit["claims"]],
            "effects": [{
                "effect_id": substantive["effect_id"],
                "artifact_field": f"role_knowledge.{unit_id}.professional_effect_1",
                "artifact_excerpt": trace_excerpt_placeholder(
                    substantive["content"],
                    f"role_knowledge.{unit_id}.professional_effect_1",
                ),
                "validation_point": {
                    "checker": "<name the accountable human checker role>",
                    "observable": trace_material_placeholder(
                        "state an observable result",
                        validation_contents,
                    ),
                    "acceptance_condition": "<state a checkable acceptance condition>",
                },
            }],
            "controls": control_templates,
        })
    reality_contents = [effect["content"] for effect in active_injection["reality_feedback"]]
    return {
        "record_type": "RoleKnowledgePacket",
        "schema_version": SCHEMA_VERSION,
        "id": f"rkp-{digest[:16]}",
        "packet_version": "1.3.0",
        "generated_at": now_utc(),
        "context_digest": digest,
        "request": request,
        "status": "active",
        "used_unit_ids": [item[2]["id"] for item in matched],
        "matched_units": packet_units,
        "active_injection": active_injection,
        "claims": claims,
        "source_refs": source_refs,
        "source_coordinates": [source_coordinates[source_ref] for source_ref in source_refs],
        "supersession_notices": supersession_notices,
        "unknowns": [],
        "omissions": ["Non-matching roles and task units were not injected."],
        "generic_fallback_allowed": False,
        "model_prior_fallback": False,
        "execution_authorized": False,
        "participation_contract": (
            "The current specialist must materially apply at least one professional effect per unit, expose all "
            "six machine-validated permission policies, every machine-validated stop/escalate/calibrate gate, and the selected stage adaptation "
            "in the delivered answer or artifact. Complete the pre-bound ApplicationTrace with an affirmative "
            "artifact field whose exact [[field:...]] marker exists in the artifact, exact artifact excerpts for the professional effect and every control, the artifact "
            "SHA-256, a checkable validation object, and a named observer/observable/time feedback point. Machine "
            "policies are the only authority truth; responsibility/trigger contexts and all professional effects "
            "have authority_effect=false, and no packet authorizes execution. The delivery must also expose the "
            "unique current specialist, lifecycle/match reasons, claim-to-source bindings, limitations, and refresh triggers."
        ),
        "delivery_requirements": delivery_requirements(
            request,
            "active",
            packet_units,
            [source_coordinates[source_ref] for source_ref in source_refs],
        ),
        "application_trace_template": {
            "record_type": "RoleKnowledgeApplicationTrace",
            "schema_version": 1,
            "context_digest": digest,
            "current_specialist": request["current_specialist"],
            "artifact_sha256": "<sha256-of-delivered-artifact-utf8>",
            "applications": trace_applications,
            "reality_feedback_point": {
                "observer": "<name the accountable human observer role>",
                "observable": trace_material_placeholder(
                    "state an observable reality signal",
                    reality_contents,
                ),
                "when": "<state the observation event or time>",
            },
            "completion_claim": "packet_applied_not_reality_solved",
        },
        "completion_boundary": "The packet is formed and may guide the current specialist; the real-world problem is not thereby solved.",
    }


def governed_rule_scope_constraint(unit: dict[str, Any]) -> list[dict[str, str]]:
    if unit["origin"] != "project":
        return []
    return [{
        "kind": "rule_scope",
        "value": unit["source_packet"]["rule_scope_digest"],
        "evidence_date": unit["source_packet"]["authority_decided_at"][:10],
        "evidence_ref": unit["source_packet"]["packet_file"],
    }]


def frozen_json(text: Any, context: str) -> dict[str, Any]:
    source = nonempty_string(text, context)
    try:
        value = json.loads(source)
    except json.JSONDecodeError as exc:
        fail("E_TEST_GATE", f"{context} is not frozen JSON: {exc}")
    if not isinstance(value, dict):
        fail("E_TEST_GATE", f"{context} must freeze a JSON object")
    return value


def comparable_packet(packet: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(packet)
    result.pop("generated_at", None)
    return result


def validate_frozen_evidence_replay(
    catalog: dict[str, Any], units: list[dict[str, Any]], records: dict[str, dict[str, Any]],
) -> None:
    """Re-run routing and bind blind answers to current professional content."""
    import blind_fixture as blind
    import deterministic_test as deterministic

    runtime_units = copy.deepcopy([unit for unit in units if unit["status"] in {"candidate", "active"}])
    for unit in runtime_units:
        unit["status"] = "active"
    runtime_by_id = {unit["id"]: unit for unit in runtime_units}
    runtime_index = {unit["id"]: index for index, unit in enumerate(runtime_units, start=1)}
    for unit in runtime_units:
        expected_digest = reviewable_unit_digest(unit)
        constraints = governed_rule_scope_constraint(unit)
        for kind in deterministic.KIND_SUFFIX:
            matching = [
                record for record in records.values()
                if record["kind"] == kind
                and record["unit_id"] == unit["id"]
                and record["unit_version"] == unit["version"]
                and record["unit_digest"] == expected_digest
                and record["result"] == "passed"
            ]
            if len(matching) != 1:
                fail("E_TEST_GATE", f"unit {unit['id']} must have exactly one current passed {kind} record")
            expected_input, expected_output, expected_result = deterministic.run_case(
                kind, unit, runtime_units, constraints,
            )
            record = matching[0]
            if (
                record["input_text"] != expected_input
                or record["output_text"] != expected_output
                or record["result"] != expected_result
            ):
                fail("E_TEST_GATE", f"{record['id']} does not replay from the current candidate unit")

    current_answers: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
    for record in records.values():
        if record["kind"] != "blind_answer" or record["unit_id"] not in runtime_by_id:
            continue
        unit = runtime_by_id[record["unit_id"]]
        if record["unit_version"] != unit["version"] or record["unit_digest"] != reviewable_unit_digest(unit):
            continue
        wrapper = frozen_json(record["input_text"], f"evidence {record['id']}.input_text")
        case = wrapper.get("case")
        if not isinstance(case, dict):
            fail("E_TEST_GATE", f"blind answer {record['id']} lacks its frozen case")
        exact_fields(
            case,
            {"case_id", "case_kind", "unit_id", "unit_version", "unit_digest", "user_prompt", "packet"},
            f"blind answer {record['id']}.case",
        )
        if (
            case["unit_id"] != unit["id"]
            or case["unit_version"] != unit["version"]
            or case["unit_digest"] != reviewable_unit_digest(unit)
            or case["case_kind"] != record["scenario_kind"]
        ):
            fail("E_TEST_GATE", f"blind answer {record['id']} case does not bind its current unit/scenario")
        expected_case = blind.build_case(
            unit, runtime_units, runtime_index[unit["id"]], record["scenario_kind"],
        )
        actual_without_packet = {key: value for key, value in case.items() if key != "packet"}
        expected_without_packet = {key: value for key, value in expected_case.items() if key != "packet"}
        if actual_without_packet != expected_without_packet:
            fail("E_TEST_GATE", f"blind answer {record['id']} is not the canonical frozen {record['scenario_kind']} case")
        packet = case["packet"]
        if not isinstance(packet, dict):
            fail("E_TEST_GATE", f"blind answer {record['id']} case packet must be an object")
        validate_role_packet(packet)
        if canonical_digest(comparable_packet(packet)) != canonical_digest(comparable_packet(expected_case["packet"])):
            fail("E_TEST_GATE", f"blind answer {record['id']} packet does not reproduce from current candidate units")
        output = frozen_json(record["output_text"], f"evidence {record['id']}.output_text")
        exact_fields(output, {"answer_text", "trace"}, f"blind answer {record['id']}.output")
        answer_text = nonempty_string(output["answer_text"], f"blind answer {record['id']}.answer_text")
        if packet["status"] == "active":
            if not isinstance(output["trace"], dict):
                fail("E_TEST_GATE", f"active blind answer {record['id']} lacks an ApplicationTrace")
            validate_trace(packet, output["trace"], answer_text)
        else:
            if output["trace"] is not None:
                fail("E_TEST_GATE", f"no_match blind answer {record['id']} must not claim an ApplicationTrace")
            validate_no_match_delivery(packet, answer_text)
        current_answers[record["id"]] = (record, case, output)

    for record in records.values():
        if record["kind"] != "independent_review" or record["unit_id"] not in runtime_by_id:
            continue
        unit = runtime_by_id[record["unit_id"]]
        if record["unit_version"] != unit["version"] or record["unit_digest"] != reviewable_unit_digest(unit):
            continue
        if len(record["answer_record_ids"]) != 1 or record["answer_record_ids"][0] not in current_answers:
            fail("E_TEST_GATE", f"review {record['id']} must bind exactly one current blind answer")
        answer, answer_case, _ = current_answers[record["answer_record_ids"][0]]
        review_input = frozen_json(record["input_text"], f"review {record['id']}.input_text")
        exact_fields(
            review_input,
            {"answer_output_sha256", "answer_record_id", "rubric", "scenario_kind"},
            f"review {record['id']}.input",
        )
        if (
            review_input["answer_record_id"] != answer["id"]
            or review_input["answer_output_sha256"] != answer["output_sha256"]
            or review_input["scenario_kind"] != answer["scenario_kind"]
        ):
            fail("E_TEST_GATE", f"review {record['id']} input does not bind the exact answer output")
        if review_input["rubric"] != BLIND_REVIEW_RUBRIC:
            fail("E_TEST_GATE", f"review {record['id']} rubric differs from the frozen eight-gate release rubric")
        if record["executed_at"] <= answer["executed_at"]:
            fail("E_TEST_GATE", f"review {record['id']} must occur after its blind answer")
        review_output = frozen_json(record["output_text"], f"review {record['id']}.output_text")
        exact_fields(
            review_output,
            {"case_id", "normalized_result", "rationale", "raw_verdict", "scores"},
            f"review {record['id']}.output",
        )
        if (
            review_output["case_id"] != answer_case["case_id"]
            or review_output["normalized_result"] != record["result"]
            or review_output["scores"] != record["scores"]
        ):
            fail("E_TEST_GATE", f"review {record['id']} output does not bind its case, result, and scores")
        expected_raw = {"passed": {"pass", "passed"}, "failed": {"fail", "failed"}}[record["result"]]
        if review_output["raw_verdict"] not in expected_raw:
            fail("E_TEST_GATE", f"review {record['id']} raw verdict contradicts normalized_result")
        nonempty_string(review_output["rationale"], f"review {record['id']}.rationale")


def validate_role_packet(packet: dict[str, Any]) -> None:
    validate_runtime_schema(packet, "RoleKnowledgePacket", "E_RK_PACKET")
    base_fields = {
        "record_type", "schema_version", "id", "packet_version", "generated_at", "context_digest",
        "request", "status", "used_unit_ids", "matched_units", "active_injection", "claims",
        "source_refs", "source_coordinates", "supersession_notices", "unknowns", "omissions", "generic_fallback_allowed",
        "model_prior_fallback", "execution_authorized", "participation_contract", "delivery_requirements",
        "completion_boundary",
    }
    status = packet.get("status")
    expected = set(base_fields)
    if status == "active":
        expected.add("application_trace_template")
    exact_fields(packet, expected, "RoleKnowledgePacket")
    if packet["record_type"] != "RoleKnowledgePacket" or type(packet["schema_version"]) is not int or packet["schema_version"] != 1:
        fail("E_RK_PACKET", "RoleKnowledgePacket type or schema version is invalid")
    packet_id = nonempty_string(packet["id"], "RoleKnowledgePacket.id")
    if not re.fullmatch(r"rkp-[a-f0-9]{16}", packet_id):
        fail("E_RK_PACKET", "RoleKnowledgePacket.id is invalid")
    if packet["packet_version"] != "1.3.0":
        fail("E_RK_PACKET", "RoleKnowledgePacket.packet_version is unsupported")
    utc_timestamp(packet["generated_at"], "RoleKnowledgePacket.generated_at")
    if not isinstance(packet["context_digest"], str) or not SHA256_RE.fullmatch(packet["context_digest"]):
        fail("E_RK_PACKET", "RoleKnowledgePacket.context_digest is invalid")
    if not isinstance(packet["request"], dict):
        fail("E_RK_PACKET", "RoleKnowledgePacket.request must be an object")
    validate_request(packet["request"], Path("<RoleKnowledgePacket.request>"))
    if canonical_digest(packet["request"]) != packet["context_digest"]:
        fail("E_RK_PACKET", "RoleKnowledgePacket.request does not match context_digest")
    if packet["model_prior_fallback"] is not False or packet["execution_authorized"] is not False:
        fail("E_RK_PACKET", "RoleKnowledgePacket permits model fallback or execution")
    if type(packet["generic_fallback_allowed"]) is not bool:
        fail("E_RK_PACKET", "RoleKnowledgePacket.generic_fallback_allowed must be boolean")
    nonempty_string(packet["participation_contract"], "RoleKnowledgePacket.participation_contract")
    nonempty_string(packet["completion_boundary"], "RoleKnowledgePacket.completion_boundary")
    used_ids = string_list(packet["used_unit_ids"], "RoleKnowledgePacket.used_unit_ids", minimum=0, ids=True)
    if not isinstance(packet["matched_units"], list):
        fail("E_RK_PACKET", "RoleKnowledgePacket.matched_units must be an array")
    matched_ids: list[str] = []
    flattened_claims: list[dict[str, Any]] = []
    claim_source_refs: set[str] = set()
    for index, unit in enumerate(packet["matched_units"]):
        context = f"RoleKnowledgePacket.matched_units[{index}]"
        if not isinstance(unit, dict):
            fail("E_RK_PACKET", f"{context} must be an object")
        exact_fields(unit, {
            "id", "version", "origin", "name", "score", "match_reasons", "professional_problem",
            "claims", "decision_graph", "evidence_model", "permission_model", "risk_gates", "stage_adaptation",
            "authority_scope", "authority_binding", "refresh_triggers",
        }, context)
        unit_id = nonempty_string(unit["id"], f"{context}.id")
        if not ID_RE.fullmatch(unit_id) or not isinstance(unit["version"], str) or not VERSION_RE.fullmatch(unit["version"]):
            fail("E_RK_PACKET", f"{context} id/version is invalid")
        matched_ids.append(unit_id)
        if unit["origin"] not in {"builtin", "project"} or type(unit["score"]) is not int:
            fail("E_RK_PACKET", f"{context} origin/score is invalid")
        string_list(unit["match_reasons"], f"{context}.match_reasons")
        nonempty_string(unit["name"], f"{context}.name")
        nonempty_string(unit["professional_problem"], f"{context}.professional_problem")
        if not isinstance(unit["claims"], list) or not unit["claims"]:
            fail("E_RK_PACKET", f"{context}.claims must be non-empty")
        unit_claim_ids: list[str] = []
        for claim_index, claim in enumerate(unit["claims"]):
            claim_context = f"{context}.claims[{claim_index}]"
            if not isinstance(claim, dict):
                fail("E_RK_PACKET", f"{claim_context} must be an object")
            exact_fields(
                claim,
                {"id", "statement", "conditions", "source_refs", "disconfirming_signals", "unit_id"},
                claim_context,
            )
            claim_id = nonempty_string(claim["id"], f"{claim_context}.id")
            if not ID_RE.fullmatch(claim_id) or claim["unit_id"] != unit_id:
                fail("E_RK_PACKET", f"{claim_context} has an invalid unit/id binding")
            nonempty_string(claim["statement"], f"{claim_context}.statement")
            string_list(claim["conditions"], f"{claim_context}.conditions")
            claim_sources = string_list(claim["source_refs"], f"{claim_context}.source_refs")
            string_list(claim["disconfirming_signals"], f"{claim_context}.disconfirming_signals")
            unit_claim_ids.append(claim_id)
            claim_source_refs.update(claim_sources)
            flattened_claims.append(copy.deepcopy(claim))
        if len(set(unit_claim_ids)) != len(unit_claim_ids):
            fail("E_RK_PACKET", f"{context}.claims contains duplicate claim ids")
        if not isinstance(unit["decision_graph"], list) or not unit["decision_graph"]:
            fail("E_RK_PACKET", f"{context}.decision_graph must be non-empty")
        if not isinstance(unit["evidence_model"], dict) or not isinstance(unit["permission_model"], dict) or not isinstance(unit["risk_gates"], dict):
            fail("E_RK_PACKET", f"{context} misses evidence, permission, or risk model")
        exact_fields(
            unit["evidence_model"],
            {"confidence", "observation_window", "limitations"},
            f"{context}.evidence_model",
        )
        if unit["evidence_model"]["confidence"] not in {"low", "medium", "high"}:
            fail("E_RK_PACKET", f"{context}.evidence_model.confidence is invalid")
        nonempty_string(unit["evidence_model"]["observation_window"], f"{context}.evidence_model.observation_window")
        string_list(unit["evidence_model"]["limitations"], f"{context}.evidence_model.limitations")
        exact_fields(unit["permission_model"], set(PERMISSION_KEYS), f"{context}.permission_model")
        for permission in PERMISSION_KEYS:
            nonempty_string(unit["permission_model"][permission], f"{context}.permission_model.{permission}")
        exact_fields(unit["risk_gates"], set(RISK_GATE_KEYS), f"{context}.risk_gates")
        for gate in RISK_GATE_KEYS:
            string_list(unit["risk_gates"][gate], f"{context}.risk_gates.{gate}")
        if not isinstance(unit["stage_adaptation"], list) or not unit["stage_adaptation"]:
            fail("E_RK_PACKET", f"{context}.stage_adaptation must be non-empty")
        string_list(unit["refresh_triggers"], f"{context}.refresh_triggers")
        unit_scope = nonempty_string(unit["authority_scope"], f"{context}.authority_scope")
        authority_binding = unit["authority_binding"]
        if unit["origin"] == "builtin":
            if authority_binding is not None:
                fail("E_RK_PACKET", f"{context}.authority_binding must be null for builtin knowledge")
        else:
            if not isinstance(authority_binding, dict):
                fail("E_RK_PACKET", f"{context}.authority_binding must bind project authority")
            exact_fields(
                authority_binding,
                {"scope_binding", "rule_scope_digest", "packet_file", "packet_sha256", "authority_decided_at"},
                f"{context}.authority_binding",
            )
            scope_binding = authority_binding["scope_binding"]
            if not isinstance(scope_binding, dict):
                fail("E_RK_PACKET", f"{context}.authority_binding.scope_binding must be an object")
            exact_fields(scope_binding, {
                "binding_version", "scope_kind", "project_scope_id", "packet_file", "packet_sha256",
                "authority_decision_sha256", "claim_ids", "job_family", "roles", "task_families",
                "lifecycle_stages", "claims_sha256",
            }, f"{context}.authority_binding.scope_binding")
            if type(scope_binding["binding_version"]) is not int or scope_binding["binding_version"] != 1:
                fail("E_RK_PACKET", f"{context}.authority_binding.scope_binding version is invalid")
            if scope_binding["scope_kind"] != "project_rule":
                fail("E_RK_PACKET", f"{context}.authority_binding.scope_binding kind is invalid")
            if not ID_RE.fullmatch(nonempty_string(scope_binding["project_scope_id"], f"{context}.authority_binding.scope_binding.project_scope_id")):
                fail("E_RK_PACKET", f"{context}.authority_binding.scope_binding project id is invalid")
            if not isinstance(scope_binding["job_family"], str) or scope_binding["job_family"] not in FAMILIES:
                fail("E_RK_PACKET", f"{context}.authority_binding.scope_binding job family is invalid")
            string_list(scope_binding["roles"], f"{context}.authority_binding.scope_binding.roles")
            string_list(scope_binding["task_families"], f"{context}.authority_binding.scope_binding.task_families")
            string_list(scope_binding["lifecycle_stages"], f"{context}.authority_binding.scope_binding.lifecycle_stages")
            bound_claim_ids = string_list(
                scope_binding["claim_ids"], f"{context}.authority_binding.scope_binding.claim_ids", ids=True,
            )
            if set(bound_claim_ids) != {claim["id"] for claim in unit["claims"]}:
                fail("E_RK_PACKET", f"{context}.authority_binding.scope_binding claim ids drifted")
            packet_claims = [
                {key: value for key, value in claim.items() if key != "unit_id"}
                for claim in unit["claims"]
            ]
            if scope_binding["claims_sha256"] != canonical_digest(packet_claims):
                fail("E_RK_PACKET", f"{context}.authority_binding.scope_binding claim content drifted")
            if not SHA256_RE.fullmatch(nonempty_string(
                scope_binding["authority_decision_sha256"],
                f"{context}.authority_binding.scope_binding.authority_decision_sha256",
            )):
                fail("E_RK_PACKET", f"{context}.authority_binding.scope_binding decision digest is invalid")
            if authority_binding["rule_scope_digest"] != f"sha256:{canonical_digest(scope_binding)}":
                fail("E_RK_PACKET", f"{context}.authority_binding rule scope digest drifted")
            if (
                scope_binding["packet_file"] != authority_binding["packet_file"]
                or scope_binding["packet_sha256"] != authority_binding["packet_sha256"]
            ):
                fail("E_RK_PACKET", f"{context}.authority_binding scope/packet binding drifted")
            if not re.fullmatch(r"knowledge/packets/[a-z0-9][a-z0-9-]{2,63}\.json", authority_binding["packet_file"]):
                fail("E_RK_PACKET", f"{context}.authority_binding.packet_file is invalid")
            if not isinstance(authority_binding["packet_sha256"], str) or not SHA256_RE.fullmatch(authority_binding["packet_sha256"]):
                fail("E_RK_PACKET", f"{context}.authority_binding.packet_sha256 is invalid")
            decided_at = utc_timestamp(
                authority_binding["authority_decided_at"], f"{context}.authority_binding.authority_decided_at",
            )
            matching_scope_constraints = [
                constraint for constraint in packet["request"]["actual_constraints"]
                if constraint["kind"] == "rule_scope"
                and constraint["value"] == authority_binding["rule_scope_digest"]
                and constraint["evidence_ref"] == authority_binding["packet_file"]
                and constraint["evidence_date"] >= decided_at[:10]
            ]
            if len(matching_scope_constraints) != 1:
                fail("E_RK_PACKET", f"{context} lacks one exact current rule_scope authority binding")
    if matched_ids != used_ids:
        fail("E_RK_PACKET", "RoleKnowledgePacket used_unit_ids and matched_units differ")
    expected_control_effects: dict[str, dict[str, Any]] = {}
    expected_control_order: dict[str, list[str]] = {"permissions": [], "risk_gates": []}
    for unit in packet["matched_units"]:
        for permission in PERMISSION_KEYS:
            expected = permission_effect(unit, permission)
            expected_control_effects[expected["effect_id"]] = expected
            expected_control_order["permissions"].append(expected["effect_id"])
        for gate in RISK_GATE_KEYS:
            for gate_index, trigger_context in enumerate(unit["risk_gates"][gate], start=1):
                expected = risk_gate_effect(unit, gate, gate_index, trigger_context)
                expected_control_effects[expected["effect_id"]] = expected
                expected_control_order["risk_gates"].append(expected["effect_id"])
    if not isinstance(packet["active_injection"], dict) or set(packet["active_injection"]) != set(PACKET_SLOTS):
        fail("E_RK_PACKET", f"RoleKnowledgePacket.active_injection must contain exactly {list(PACKET_SLOTS)}")
    effect_ids: set[str] = set()
    effect_bindings: dict[str, tuple[str, str]] = {}
    units_with_effects: set[str] = set()
    actual_control_order: dict[str, list[str]] = {"permissions": [], "risk_gates": []}
    for slot, effects in packet["active_injection"].items():
        if not isinstance(effects, list):
            fail("E_RK_PACKET", f"RoleKnowledgePacket.active_injection.{slot} must be an array")
        for index, effect in enumerate(effects):
            context = f"RoleKnowledgePacket.active_injection.{slot}[{index}]"
            if not isinstance(effect, dict):
                fail("E_RK_PACKET", f"{context} must be an object")
            effect_fields = {"effect_id", "unit_id", "slot", "content", "authority_effect"}
            if slot == "permissions":
                effect_fields |= {"policy", "responsibility_context", "context_role", "authority_effect"}
            elif slot == "risk_gates":
                effect_fields |= {"policy", "trigger_context", "context_role", "authority_effect"}
            exact_fields(effect, effect_fields, context)
            effect_id = nonempty_string(effect["effect_id"], f"{context}.effect_id")
            unit_id = nonempty_string(effect["unit_id"], f"{context}.unit_id")
            if effect["slot"] != slot:
                fail("E_RK_PACKET", f"{context}.slot does not match its active_injection key")
            nonempty_string(effect["content"], f"{context}.content")
            if effect["authority_effect"] is not False:
                fail("E_RK_PACKET", f"{context} cannot authorize execution or expand authority")
            if effect_id in effect_ids or unit_id not in used_ids:
                fail("E_RK_PACKET", f"{context} has duplicate effect or unknown unit")
            if slot in {"permissions", "risk_gates"}:
                expected_control = expected_control_effects.get(effect_id)
                if expected_control is None or effect != expected_control:
                    fail("E_RK_PACKET", f"{context} differs from its fixed machine control policy")
                actual_control_order[slot].append(effect_id)
            effect_ids.add(effect_id)
            effect_bindings[effect_id] = (unit_id, slot)
            units_with_effects.add(unit_id)
    selected_control_ids = {
        effect_id for effect_id, (_, slot) in effect_bindings.items()
        if slot in {"permissions", "risk_gates"}
    }
    if selected_control_ids != set(expected_control_effects):
        fail("E_RK_PACKET", "RoleKnowledgePacket must contain every fixed permission and risk policy exactly once")
    if actual_control_order != expected_control_order:
        fail("E_RK_PACKET", "RoleKnowledgePacket permission and risk policies must retain deterministic order")
    if packet["claims"] != flattened_claims:
        fail(
            "E_RK_PACKET",
            "RoleKnowledgePacket.claims must exactly equal the ordered claims flattened from matched_units",
        )
    source_refs = string_list(packet["source_refs"], "RoleKnowledgePacket.source_refs", minimum=0)
    if not isinstance(packet["source_coordinates"], list):
        fail("E_RK_PACKET", "RoleKnowledgePacket.source_coordinates must be an array")
    coordinate_refs: list[str] = []
    for index, coordinate in enumerate(packet["source_coordinates"]):
        context = f"RoleKnowledgePacket.source_coordinates[{index}]"
        if not isinstance(coordinate, dict):
            fail("E_RK_PACKET", f"{context} must be an object")
        exact_fields(coordinate, {"source_ref", "registry", "coordinate_key"}, context)
        source_ref = nonempty_string(coordinate["source_ref"], f"{context}.source_ref")
        nonempty_string(coordinate["registry"], f"{context}.registry")
        if nonempty_string(coordinate["coordinate_key"], f"{context}.coordinate_key") != source_ref:
            fail("E_RK_PACKET", f"{context}.coordinate_key must equal source_ref")
        coordinate_refs.append(source_ref)
    if coordinate_refs != source_refs:
        fail("E_RK_PACKET", "RoleKnowledgePacket source coordinates do not exactly track source_refs")
    missing_claim_sources = sorted(claim_source_refs - set(source_refs))
    if missing_claim_sources:
        fail(
            "E_RK_PACKET",
            f"RoleKnowledgePacket claims reference sources absent from source_refs/source_coordinates: {missing_claim_sources}",
        )
    if not isinstance(packet["supersession_notices"], list):
        fail("E_RK_PACKET", "RoleKnowledgePacket.supersession_notices must be an array")
    for index, notice in enumerate(packet["supersession_notices"]):
        context = f"RoleKnowledgePacket.supersession_notices[{index}]"
        if not isinstance(notice, dict):
            fail("E_RK_PACKET", f"{context} must be an object")
        exact_fields(notice, {"unit_id", "supersedes", "scope_digest"}, context)
        if notice["unit_id"] not in used_ids:
            fail("E_RK_PACKET", f"{context} refers to an unselected replacement")
        if not ID_RE.fullmatch(nonempty_string(notice["supersedes"], f"{context}.supersedes")):
            fail("E_RK_PACKET", f"{context}.supersedes is invalid")
        if not SCOPE_DIGEST_RE.fullmatch(nonempty_string(notice["scope_digest"], f"{context}.scope_digest")):
            fail("E_RK_PACKET", f"{context}.scope_digest is invalid")
    expected_delivery = delivery_requirements(
        packet["request"], status, packet["matched_units"], packet["source_coordinates"],
    )
    if packet["delivery_requirements"] != expected_delivery:
        fail("E_RK_PACKET", "RoleKnowledgePacket.delivery_requirements do not reproduce from routing/evidence")
    string_list(packet["unknowns"], "RoleKnowledgePacket.unknowns", minimum=0)
    string_list(packet["omissions"], "RoleKnowledgePacket.omissions", minimum=0)
    if status == "active":
        if not used_ids or units_with_effects != set(used_ids) or packet["generic_fallback_allowed"] is not False:
            fail("E_RK_PACKET", "active RoleKnowledgePacket lacks selected effects or enables generic fallback")
        if not isinstance(packet["application_trace_template"], dict):
            fail("E_RK_PACKET", "active RoleKnowledgePacket lacks an application trace template")
        validate_trace_template(packet, effect_bindings)
    elif status == "no_match":
        if used_ids or matched_ids or effect_ids or packet["claims"] or packet["source_refs"] or packet["source_coordinates"]:
            fail("E_RK_PACKET", "no_match RoleKnowledgePacket contains selected knowledge")
    else:
        fail("E_RK_PACKET", f"unsupported RoleKnowledgePacket.status: {status}")


def validate_trace_template(packet: dict[str, Any], effect_bindings: dict[str, tuple[str, str]]) -> None:
    template = packet["application_trace_template"]
    validate_runtime_schema(template, "ApplicationTraceTemplate", "E_RK_PACKET")
    context = "RoleKnowledgePacket.application_trace_template"
    exact_fields(template, {
        "record_type", "schema_version", "context_digest", "current_specialist", "artifact_sha256",
        "applications", "reality_feedback_point", "completion_claim",
    }, context)
    if template["record_type"] != "RoleKnowledgeApplicationTrace" or type(template["schema_version"]) is not int or template["schema_version"] != 1:
        fail("E_RK_PACKET", f"{context} type or schema version is invalid")
    if template["context_digest"] != packet["context_digest"] or template["current_specialist"] != packet["request"]["current_specialist"]:
        fail("E_RK_PACKET", f"{context} does not bind packet context/current specialist")
    if template["artifact_sha256"] != "<sha256-of-delivered-artifact-utf8>" or template["completion_claim"] != "packet_applied_not_reality_solved":
        fail("E_RK_PACKET", f"{context} artifact/completion placeholders are invalid")
    feedback = template["reality_feedback_point"]
    if not isinstance(feedback, dict):
        fail("E_RK_PACKET", f"{context}.reality_feedback_point must be an object")
    exact_fields(feedback, {"observer", "observable", "when"}, f"{context}.reality_feedback_point")
    expected_feedback = {
        "observer": "<name the accountable human observer role>",
        "observable": trace_material_placeholder(
            "state an observable reality signal",
            [effect["content"] for effect in packet["active_injection"]["reality_feedback"]],
        ),
        "when": "<state the observation event or time>",
    }
    if feedback != expected_feedback:
        fail("E_RK_PACKET", f"{context}.reality_feedback_point does not expose exact feedback requirements")
    unit_map = {unit["id"]: unit for unit in packet["matched_units"]}
    effect_map = {
        effect["effect_id"]: effect
        for effects in packet["active_injection"].values()
        for effect in effects
    }
    applications = template["applications"]
    if not isinstance(applications, list) or len(applications) != len(unit_map):
        fail("E_RK_PACKET", f"{context}.applications must contain one template per selected unit")
    seen: set[str] = set()
    control_slots = {"permissions": "permissions", "risk_gates": "risk_gates", "stage_adaptation": "stage_adaptation"}
    for index, application in enumerate(applications):
        app_context = f"{context}.applications[{index}]"
        if not isinstance(application, dict):
            fail("E_RK_PACKET", f"{app_context} must be an object")
        exact_fields(application, {"unit_id", "unit_version", "claim_ids", "effects", "controls"}, app_context)
        unit_id = application["unit_id"]
        if unit_id not in unit_map or unit_id in seen or application["unit_version"] != unit_map[unit_id]["version"]:
            fail("E_RK_PACKET", f"{app_context} unit binding is invalid")
        seen.add(unit_id)
        expected_claims = [claim["id"] for claim in unit_map[unit_id]["claims"]]
        if application["claim_ids"] != expected_claims:
            fail("E_RK_PACKET", f"{app_context}.claim_ids must bind every selected claim")
        effects = application["effects"]
        if not isinstance(effects, list) or len(effects) != 1:
            fail("E_RK_PACKET", f"{app_context}.effects must contain exactly one professional effect template")
        for effect_index, effect in enumerate(effects):
            effect_context = f"{app_context}.effects[{effect_index}]"
            if not isinstance(effect, dict):
                fail("E_RK_PACKET", f"{effect_context} must be an object")
            exact_fields(effect, {"effect_id", "artifact_field", "artifact_excerpt", "validation_point"}, effect_context)
            binding = effect_bindings.get(effect["effect_id"])
            if binding is None or binding[0] != unit_id or binding[1] not in SLOTS:
                fail("E_RK_PACKET", f"{effect_context}.effect_id is not a professional effect for this unit")
            expected_artifact_field = f"role_knowledge.{unit_id}.professional_effect_1"
            if effect["artifact_field"] != expected_artifact_field:
                fail("E_RK_PACKET", f"{effect_context}.artifact_field is not the concrete prefilled path")
            if effect["artifact_excerpt"] != trace_excerpt_placeholder(
                effect_map[effect["effect_id"]]["content"], expected_artifact_field,
            ):
                fail("E_RK_PACKET", f"{effect_context}.artifact_excerpt does not expose the selected content")
            validation = effect["validation_point"]
            if not isinstance(validation, dict):
                fail("E_RK_PACKET", f"{effect_context}.validation_point must be an object")
            exact_fields(validation, {"checker", "observable", "acceptance_condition"}, f"{effect_context}.validation_point")
            expected_validation = {
                "checker": "<name the accountable human checker role>",
                "observable": trace_material_placeholder(
                    "state an observable result",
                    [
                        selected["content"] for selected in packet["active_injection"]["validation"]
                        if selected["unit_id"] == unit_id
                    ],
                ),
                "acceptance_condition": "<state a checkable acceptance condition>",
            }
            if validation != expected_validation:
                fail("E_RK_PACKET", f"{effect_context}.validation_point does not expose exact validation requirements")
        controls = application["controls"]
        if not isinstance(controls, dict):
            fail("E_RK_PACKET", f"{app_context}.controls must be an object")
        exact_fields(controls, set(control_slots), f"{app_context}.controls")
        for control_key, slot in control_slots.items():
            binding = controls[control_key]
            binding_context = f"{app_context}.controls.{control_key}"
            if not isinstance(binding, dict):
                fail("E_RK_PACKET", f"{binding_context} must be an object")
            exact_fields(binding, {"effect_ids", "artifact_excerpts"}, binding_context)
            selected_controls = [
                effect for effect in packet["active_injection"][slot]
                if effect["unit_id"] == unit_id
            ]
            expected_ids = [effect["effect_id"] for effect in selected_controls]
            if binding["effect_ids"] != expected_ids:
                fail("E_RK_PACKET", f"{binding_context}.effect_ids does not bind every selected control")
            expected_excerpts = [
                trace_excerpt_placeholder(content)
                for content in dict.fromkeys(effect["content"] for effect in selected_controls)
            ]
            if binding["artifact_excerpts"] != expected_excerpts:
                fail("E_RK_PACKET", f"{binding_context}.artifact_excerpts do not expose every exact control content")
    if seen != set(unit_map):
        fail("E_RK_PACKET", f"{context} omits selected units")


def non_placeholder_string(value: Any, context: str) -> str:
    result = nonempty_string(value, context)
    if BRACKETED_PLACEHOLDER_RE.search(result) or VAGUE_PLACEHOLDER_RE.fullmatch(result.strip()):
        fail("E_RK_INERT", f"{context} contains an unresolved placeholder")
    return result


def material_string(value: Any, context: str) -> str:
    result = non_placeholder_string(value, context)
    if INERT_ASSERTION_RE.search(result) or VAGUE_PLACEHOLDER_RE.fullmatch(result.strip()):
        fail("E_RK_INERT", f"{context} explicitly declares inert or absent work")
    return result


def validate_validation_point(value: Any, context: str) -> None:
    if not isinstance(value, dict):
        fail("E_RK_INERT", f"{context} must be an object")
    exact_fields(value, {"checker", "observable", "acceptance_condition"}, context)
    material_string(value["checker"], f"{context}.checker")
    material_string(value["observable"], f"{context}.observable")
    material_string(value["acceptance_condition"], f"{context}.acceptance_condition")


def validate_reality_feedback_point(value: Any, context: str) -> None:
    if not isinstance(value, dict):
        fail("E_RK_INERT", f"{context} must be an object")
    exact_fields(value, {"observer", "observable", "when"}, context)
    material_string(value["observer"], f"{context}.observer")
    material_string(value["observable"], f"{context}.observable")
    material_string(value["when"], f"{context}.when")


def require_delivery_text(artifact_text: str, required: str, context: str) -> None:
    value = nonempty_string(required, context)
    if value not in artifact_text:
        fail("E_RK_INERT", f"delivered artifact omits {context}: {value}")


def validate_active_delivery(packet: dict[str, Any], artifact_text: str) -> None:
    requirements = packet["delivery_requirements"]
    routing = requirements["routing"]
    require_delivery_text(artifact_text, routing["current_specialist"], "delivery routing.current_specialist")
    require_delivery_text(artifact_text, routing["task_family"], "delivery routing.task_family")
    require_delivery_text(artifact_text, routing["problem"], "delivery routing.problem")
    require_delivery_text(artifact_text, routing["lifecycle_stage"], "delivery routing.lifecycle_stage")
    for unit in routing["selected_units"]:
        require_delivery_text(artifact_text, unit["unit_id"], "delivery routing.unit_id")
        for reason in unit["match_reasons"]:
            require_delivery_text(artifact_text, reason, "delivery routing.match_reason")
    for unit in requirements["evidence"]:
        require_delivery_text(artifact_text, unit["unit_id"], "delivery evidence.unit_id")
        for claim in unit["claims"]:
            require_delivery_text(artifact_text, claim["claim_id"], "delivery evidence.claim_id")
            require_delivery_text(artifact_text, claim["statement"], "delivery evidence.claim.statement")
            for source in claim["source_bindings"]:
                require_delivery_text(artifact_text, source["source_ref"], "delivery evidence.source_ref")
                require_delivery_text(artifact_text, source["registry"], "delivery evidence.source.registry")
                require_delivery_text(artifact_text, source["coordinate_key"], "delivery evidence.source.coordinate_key")
        for limitation in unit["limitations"]:
            require_delivery_text(artifact_text, limitation, "delivery evidence.limitation")
        for trigger in unit["refresh_triggers"]:
            require_delivery_text(artifact_text, trigger, "delivery evidence.refresh_trigger")
    require_delivery_text(
        artifact_text, requirements["completion_boundary"], "delivery completion_boundary",
    )


def validate_no_match_delivery(packet: dict[str, Any], answer_text: str) -> None:
    validate_role_packet(packet)
    if packet["status"] != "no_match":
        fail("E_RK_INERT", "no-match delivery validation requires a no_match RoleKnowledgePacket")
    text = material_string(answer_text, "no_match answer_text")
    requirements = packet["delivery_requirements"]
    routing = requirements["routing"]
    require_delivery_text(text, routing["current_specialist"], "no_match routing.current_specialist")
    require_delivery_text(text, routing["task_family"], "no_match routing.task_family")
    require_delivery_text(text, routing["problem"], "no_match routing.problem")
    require_delivery_text(text, routing["lifecycle_stage"], "no_match routing.lifecycle_stage")
    require_delivery_text(text, requirements["status_statement"], "no_match status_statement")
    for branch in requirements["responsibility_branches"]:
        for field in ("hypothesis", "discriminator", "next_action"):
            require_delivery_text(text, branch[field], f"no_match branch.{field}")
    for field in ("observer", "observable", "when"):
        require_delivery_text(text, requirements["reality_feedback"][field], f"no_match reality_feedback.{field}")
    require_delivery_text(text, requirements["completion_boundary"], "no_match completion_boundary")


def validate_trace(packet: dict[str, Any], trace: dict[str, Any], artifact_text: str | None = None) -> None:
    validate_role_packet(packet)
    if packet["status"] != "active":
        fail("E_RK_INERT", "trace requires an active RoleKnowledgePacket")
    validate_runtime_schema(trace, "ApplicationTrace", "E_RK_INERT")
    expected = {
        "record_type", "schema_version", "context_digest", "current_specialist",
        "artifact_sha256", "applications", "reality_feedback_point", "completion_claim",
    }
    exact_fields(trace, expected, "ApplicationTrace")
    if trace["record_type"] != "RoleKnowledgeApplicationTrace" or type(trace["schema_version"]) is not int or trace["schema_version"] != 1:
        fail("E_RK_INERT", "ApplicationTrace type or schema version is invalid")
    if trace["context_digest"] != packet["context_digest"]:
        fail("E_RK_INERT", "ApplicationTrace context_digest does not match packet")
    specialist = non_placeholder_string(trace["current_specialist"], "ApplicationTrace.current_specialist")
    if not re.fullmatch(r"xb-[a-z0-9-]+", specialist) or specialist == "xb-role-knowledge" or specialist != packet["request"]["current_specialist"]:
        fail("E_RK_INERT", "support trace must retain a different current xb-* specialist")
    if artifact_text is None or not isinstance(artifact_text, str) or not artifact_text.strip():
        fail("E_RK_INERT", "ApplicationTrace verification requires the actual delivered artifact text")
    artifact_sha256 = non_placeholder_string(trace["artifact_sha256"], "ApplicationTrace.artifact_sha256")
    actual_artifact_sha256 = hashlib.sha256(artifact_text.encode("utf-8")).hexdigest()
    if not SHA256_RE.fullmatch(artifact_sha256) or artifact_sha256 != actual_artifact_sha256:
        fail("E_RK_INERT", "ApplicationTrace artifact_sha256 does not bind the delivered artifact")
    validate_active_delivery(packet, artifact_text)
    validate_reality_feedback_point(trace["reality_feedback_point"], "ApplicationTrace.reality_feedback_point")
    if trace["completion_claim"] != "packet_applied_not_reality_solved":
        fail("E_RK_INERT", "ApplicationTrace must preserve the reality completion boundary")
    valid_effects: dict[str, tuple[str, str, str]] = {}
    required_controls: dict[str, dict[str, list[str]]] = {
        unit_id: {
            "permissions": [],
            "risk_gates": [],
            "stage_adaptation": [],
        }
        for unit_id in packet["used_unit_ids"]
    }
    required_validation_content: dict[str, list[str]] = {unit_id: [] for unit_id in packet["used_unit_ids"]}
    required_reality_content: dict[str, list[str]] = {unit_id: [] for unit_id in packet["used_unit_ids"]}
    control_key_by_slot = {
        "permissions": "permissions",
        "risk_gates": "risk_gates",
        "stage_adaptation": "stage_adaptation",
    }
    for slot, effects in packet["active_injection"].items():
        for effect in effects:
            valid_effects[effect["effect_id"]] = (effect["unit_id"], slot, effect["content"])
            control_key = control_key_by_slot.get(slot)
            if control_key is not None:
                required_controls[effect["unit_id"]][control_key].append(effect["effect_id"])
            if slot == "validation":
                required_validation_content[effect["unit_id"]].append(effect["content"])
            elif slot == "reality_feedback":
                required_reality_content[effect["unit_id"]].append(effect["content"])
    unit_map = {unit["id"]: unit for unit in packet["matched_units"]}
    applications = trace["applications"]
    if not isinstance(applications, list) or not applications:
        fail("E_RK_INERT", "ApplicationTrace needs at least one application")
    seen_units: set[str] = set()
    for index, application in enumerate(applications):
        context = f"ApplicationTrace.applications[{index}]"
        if not isinstance(application, dict):
            fail("E_RK_INERT", f"{context} must be an object")
        exact_fields(application, {"unit_id", "unit_version", "claim_ids", "effects", "controls"}, context)
        unit_id = non_placeholder_string(application["unit_id"], f"{context}.unit_id")
        if unit_id not in unit_map or application["unit_version"] != unit_map[unit_id]["version"]:
            fail("E_RK_INERT", f"{context} unit id/version was not selected by packet")
        if unit_id in seen_units:
            fail("E_RK_INERT", f"{context} repeats unit {unit_id}; controls must be complete in one application")
        valid_claims = {claim["id"] for claim in unit_map[unit_id]["claims"]}
        used_claims = set(string_list(application["claim_ids"], f"{context}.claim_ids", ids=True))
        if not used_claims <= valid_claims:
            fail("E_RK_INERT", f"{context} cites claim ids absent from selected unit")
        effects = application["effects"]
        if not isinstance(effects, list) or not effects:
            fail("E_RK_INERT", f"{context} must apply at least one professional effect")
        applied_effect_ids: set[str] = set()
        validation_material: list[str] = []
        for effect_index, effect in enumerate(effects):
            effect_context = f"{context}.effects[{effect_index}]"
            if not isinstance(effect, dict):
                fail("E_RK_INERT", f"{effect_context} must be an object")
            exact_fields(effect, {"effect_id", "artifact_field", "artifact_excerpt", "validation_point"}, effect_context)
            effect_id = non_placeholder_string(effect["effect_id"], f"{effect_context}.effect_id")
            if effect_id not in valid_effects or valid_effects[effect_id][0] != unit_id:
                fail("E_RK_INERT", f"{effect_context} effect_id is not available to this unit")
            if valid_effects[effect_id][1] not in SLOTS:
                fail("E_RK_INERT", f"{effect_context} must cite a professional effect; controls belong in controls")
            if effect_id in applied_effect_ids:
                fail("E_RK_INERT", f"{effect_context} repeats effect_id={effect_id}")
            applied_effect_ids.add(effect_id)
            artifact_field = material_string(effect["artifact_field"], f"{effect_context}.artifact_field")
            if not ARTIFACT_FIELD_RE.fullmatch(artifact_field):
                fail("E_RK_INERT", f"{effect_context}.artifact_field must be a concrete dotted field path")
            artifact_excerpt = material_string(effect["artifact_excerpt"], f"{effect_context}.artifact_excerpt")
            if artifact_excerpt not in artifact_text:
                fail("E_RK_INERT", f"{effect_context}.artifact_excerpt is absent from the delivered artifact")
            marker = artifact_field_marker(artifact_field)
            if marker not in artifact_excerpt:
                fail("E_RK_INERT", f"{effect_context}.artifact_excerpt omits its exact field marker")
            if valid_effects[effect_id][2] not in artifact_excerpt:
                fail(
                    "E_RK_INERT",
                    f"{effect_context}.artifact_excerpt does not contain the selected professional effect content",
                )
            validate_validation_point(effect["validation_point"], f"{effect_context}.validation_point")
            validation_material.extend(
                str(effect["validation_point"][field])
                for field in ("checker", "observable", "acceptance_condition")
            )
        combined_validation_material = "\n".join(validation_material)
        missing_validation_content = [
            content for content in required_validation_content[unit_id]
            if content not in combined_validation_material
        ]
        if missing_validation_content:
            fail(
                "E_RK_INERT",
                f"{context}.effects validation points omit selected professional validation content",
            )
        controls = application["controls"]
        if not isinstance(controls, dict):
            fail("E_RK_INERT", f"{context}.controls must be an object")
        exact_fields(controls, set(control_key_by_slot.values()), f"{context}.controls")
        for control_key, expected_ids in required_controls[unit_id].items():
            binding = controls[control_key]
            binding_context = f"{context}.controls.{control_key}"
            if not isinstance(binding, dict):
                fail("E_RK_INERT", f"{binding_context} must be an object")
            exact_fields(binding, {"effect_ids", "artifact_excerpts"}, binding_context)
            actual_ids = string_list(binding["effect_ids"], f"{binding_context}.effect_ids")
            excerpts = string_list(binding["artifact_excerpts"], f"{binding_context}.artifact_excerpts")
            for excerpt_index, raw_excerpt in enumerate(excerpts):
                excerpt = material_string(raw_excerpt, f"{binding_context}.artifact_excerpts[{excerpt_index}]")
                if excerpt not in artifact_text:
                    fail("E_RK_INERT", f"{binding_context}.artifact_excerpts[{excerpt_index}] is absent from the delivered artifact")
            if actual_ids != expected_ids:
                fail("E_RK_INERT", f"{context}.controls.{control_key} must exactly bind every selected control effect")
            combined_excerpts = "\n".join(excerpts)
            missing_control_content = [
                effect_id for effect_id in expected_ids
                if valid_effects[effect_id][2] not in combined_excerpts
            ]
            if missing_control_content:
                fail(
                    "E_RK_INERT",
                    f"{binding_context}.artifact_excerpts omit selected control content: {missing_control_content}",
                )
        seen_units.add(unit_id)
    missing_units = sorted(set(packet["used_unit_ids"]) - seen_units)
    if missing_units:
        fail("E_RK_INERT", f"ApplicationTrace did not apply selected unit(s): {missing_units}")
    feedback_material = "\n".join(
        str(trace["reality_feedback_point"][field]) for field in ("observer", "observable", "when")
    )
    missing_reality_content = [
        content
        for unit_id in packet["used_unit_ids"]
        for content in required_reality_content[unit_id]
        if content not in feedback_material
    ]
    if missing_reality_content:
        fail("E_RK_INERT", "ApplicationTrace reality feedback omits selected professional feedback content")


def cmd_validate(args: argparse.Namespace) -> int:
    if args.catalog:
        path = absolute_path(args.catalog, "--catalog")
        catalog = read_json(path)
        project_root = absolute_path(args.project_root, "--project-root", directory=True) if args.project_root else None
        units = validate_catalog(catalog, path, project_root)
        print(f"VALID catalog={path} units={len(units)} active={sum(u['status'] == 'active' for u in units)}")
        return 0
    if args.project_root:
        root = absolute_path(args.project_root, "--project-root", directory=True)
        units, _ = load_units(root)
        print(f"VALID builtin={builtin_path()} project={project_catalog_path(root)} units={len(units)}")
        return 0
    units, _ = load_units(None)
    print(f"VALID catalog={builtin_path()} units={len(units)} active={sum(u['status'] == 'active' for u in units)}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    context_path = absolute_path(args.context, "--context")
    request = validate_request(read_json(context_path), context_path)
    project_root = absolute_path(args.project_root, "--project-root", directory=True) if args.project_root else None
    units, notices = load_units(project_root)
    matched, used_notices = match_units(units, request, notices)
    if not matched and request["knowledge_requirement"] == "required":
        fail(
            "E_NO_MATCH",
            f"no active unit matched job_family={request['job_family']} role={request['role']} "
            f"task={request['task_family']}; affected role-specialized conclusion is stopped",
        )
    packet = build_packet(request, matched, used_notices)
    validate_role_packet(packet)
    if args.output:
        output = absolute_path(args.output, "--output", must_exist=False)
        if output.suffix.lower() != ".json":
            fail("E_OUTPUT", f"--output must end with .json: {output}")
        atomic_json(output, packet, exclusive=True)
        print(
            f"PACKET_CREATED path={output} status={packet['status']} "
            f"units={','.join(packet['used_unit_ids']) or 'none'} model_prior_fallback=false execution_authorized=false"
        )
    else:
        print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


def cmd_init_project(args: argparse.Namespace) -> int:
    if not args.yes:
        fail("E_CONFIRMATION", "init-project requires --yes for the exact project root")
    project_root = absolute_path(args.project_root, "--project-root", directory=True)
    path = project_catalog_path(project_root)
    if path.exists():
        fail("E_OUTPUT", f"project role knowledge already exists: {path}")
    catalog = {
        "record_type": "RoleKnowledgeCatalog",
        "schema_version": 1,
        "catalog_id": project_scope_id_for_root(project_root),
        "catalog_version": "0.1.0",
        "origin": "project",
        "published_at": now_utc(),
        "governance_complete": False,
        "units": [],
    }
    atomic_json(path, catalog, exclusive=True)
    print(f"INITIALIZED path={path} units=0 governance_complete=false")
    return 0


def cmd_verify_trace(args: argparse.Namespace) -> int:
    packet_path = absolute_path(args.packet, "--packet")
    trace_path = absolute_path(args.trace, "--trace")
    artifact_path = absolute_path(args.artifact, "--artifact")
    try:
        artifact_text = artifact_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail("E_IO", f"cannot read delivered artifact {artifact_path}: {exc}")
    packet = read_json(packet_path)
    validate_role_packet(packet)
    project_root = absolute_path(args.project_root, "--project-root", directory=True) if args.project_root else None
    if any(unit.get("origin") == "project" for unit in packet.get("matched_units", [])) and project_root is None:
        fail("E_PROJECT_UNINITIALIZED", "verifying a project-derived packet requires its exact --project-root")
    units, notices = load_units(project_root)
    matched, used_notices = match_units(units, packet["request"], notices)
    expected_packet = build_packet(packet["request"], matched, used_notices)
    comparable_actual = dict(packet)
    comparable_expected = dict(expected_packet)
    comparable_actual.pop("generated_at", None)
    comparable_expected.pop("generated_at", None)
    if canonical_digest(comparable_actual) != canonical_digest(comparable_expected):
        fail("E_RK_PACKET", "packet does not reproduce from the current governed catalogs and request")
    validate_trace(packet, read_json(trace_path), artifact_text)
    print(
        f"TRACE_VALID packet={packet_path} trace={trace_path} artifact={artifact_path} "
        f"artifact_sha256={hashlib.sha256(artifact_text.encode('utf-8')).hexdigest()} inert=false"
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate builtin or explicit catalog")
    validate.add_argument("--catalog")
    validate.add_argument("--project-root")
    resolve = commands.add_parser("resolve", help="resolve a minimal role knowledge packet")
    resolve.add_argument("--context", required=True)
    resolve.add_argument("--project-root")
    resolve.add_argument("--output")
    init = commands.add_parser("init-project", help="initialize an explicit project overlay")
    init.add_argument("--project-root", required=True)
    init.add_argument("--yes", action="store_true")
    trace = commands.add_parser("verify-trace", help="prove that a selected unit changed the current specialist")
    trace.add_argument("--packet", required=True)
    trace.add_argument("--trace", required=True)
    trace.add_argument("--artifact", required=True)
    trace.add_argument("--project-root")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            return cmd_validate(args)
        if args.command == "resolve":
            return cmd_resolve(args)
        if args.command == "init-project":
            return cmd_init_project(args)
        if args.command == "verify-trace":
            return cmd_verify_trace(args)
        fail("E_USAGE", f"unsupported command: {args.command}")
    except RoleKnowledgeError as exc:
        print(f"ERROR {exc.code}: {exc.message}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
