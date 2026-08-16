#!/usr/bin/env python3
"""Manage governed knowledge sources without downloading or executing them.

The manager uses only the Python standard library.  It creates and validates the
registry/sources/locks/evidence/packets/update-journal layout described in
references/knowledge-source-protocol.md.  Every failure is printed as
``ERROR <CODE>: <message>``; aggregate validation exits with E_VALIDATION (60)
after printing the individual issue codes.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
REQUIRED_DIRS = (
    "registry",
    "registry/requirements",
    "sources",
    "locks",
    "evidence",
    "packets",
    "update-journal",
)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
COMMIT_RE = re.compile(r"^[a-f0-9]{40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SOURCE_TYPES = {"local", "official", "paper", "github"}
EXTERNAL_TYPES = {"official", "paper", "github"}

ERROR_CODES = {
    "E_USAGE": 2,
    "E_CONFIRMATION": 3,
    "E_ROOT": 10,
    "E_NOT_INITIALIZED": 11,
    "E_ALREADY_INITIALIZED": 12,
    "E_IO": 13,
    "E_PATH_BOUNDARY": 14,
    "E_JSON": 20,
    "E_SCHEMA": 21,
    "E_REFERENCE": 22,
    "E_REQUIRED_SOURCE_MISSING": 30,
    "E_PERMISSION": 31,
    "E_LICENSE": 32,
    "E_SECURITY": 33,
    "E_PIN": 34,
    "E_CONFLICT": 35,
    "E_EVIDENCE": 36,
    "E_AUTHORITY": 37,
    "E_NETWORK": 40,
    "E_GITHUB_METADATA": 41,
    "E_OUTPUT": 50,
    "E_NO_ROLLBACK": 51,
    "E_STATE": 52,
    "E_VALIDATION": 60,
}


class KnowledgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = ERROR_CODES[code]


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise KnowledgeError("E_USAGE", message)


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def explicit_absolute_path(raw: str, label: str) -> Path:
    if not raw or raw.strip() != raw:
        raise KnowledgeError("E_ROOT", f"{label} must be a non-empty explicit path")
    path = Path(raw)
    if not path.is_absolute():
        raise KnowledgeError("E_ROOT", f"{label} must be absolute; received: {raw}")
    exact = Path(os.path.abspath(os.fspath(path)))
    if exact.parent == exact:
        raise KnowledgeError("E_ROOT", f"{label} must not be a filesystem root: {exact}")
    return exact


def resolve_for_boundary(path: Path, context: str) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise KnowledgeError(
            "E_PATH_BOUNDARY", f"cannot resolve {context} without crossing an unsafe link: {path}: {exc}"
        ) from exc


def exact_knowledge_root(root: Path) -> Path:
    exact = Path(os.path.abspath(os.fspath(root)))
    resolved = resolve_for_boundary(exact, "knowledge root")
    if resolved != exact:
        raise KnowledgeError(
            "E_PATH_BOUNDARY",
            f"knowledge root must be the exact path and must not resolve through a link: {exact} -> {resolved}",
        )
    return resolved


def governed_directory(root: Path, directory: Path, context: str) -> Path:
    exact_root = exact_knowledge_root(root)
    exact_directory = Path(os.path.abspath(os.fspath(directory)))
    try:
        relative = exact_directory.relative_to(exact_root).as_posix()
    except ValueError as exc:
        raise KnowledgeError(
            "E_PATH_BOUNDARY", f"{context} is outside the exact knowledge root {exact_root}: {exact_directory}"
        ) from exc
    if relative not in REQUIRED_DIRS:
        raise KnowledgeError(
            "E_PATH_BOUNDARY", f"{context} is not an exact governed directory under {exact_root}: {exact_directory}"
        )
    resolved = resolve_for_boundary(exact_directory, context)
    if resolved != exact_directory:
        raise KnowledgeError(
            "E_PATH_BOUNDARY",
            f"{context} must use its exact governed path and must not be a link: {exact_directory} -> {resolved}",
        )
    return resolved


def governed_file_path(root: Path, path: Path, parent: Path, context: str) -> Path:
    exact_root = exact_knowledge_root(root)
    exact_path = Path(os.path.abspath(os.fspath(path)))
    exact_parent = Path(os.path.abspath(os.fspath(parent)))
    if exact_path.parent != exact_parent:
        raise KnowledgeError(
            "E_PATH_BOUNDARY", f"{context} must be a direct child of {exact_parent}: {exact_path}"
        )
    resolved_parent = governed_directory(exact_root, exact_parent, f"{context} parent")
    resolved = resolve_for_boundary(exact_path, context)
    if resolved != exact_path or resolved.parent != resolved_parent:
        raise KnowledgeError(
            "E_PATH_BOUNDARY",
            f"{context} must use its exact governed path and must not be a link: {exact_path} -> {resolved}",
        )
    return resolved


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path, *, root: Path, parent: Path, context: str) -> str:
    path = governed_file_path(root, path, parent, context)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise KnowledgeError("E_IO", f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def atomic_write_json(
    root: Path, path: Path, value: dict[str, Any], *, exclusive: bool = False
) -> None:
    safe_path = governed_file_path(root, path, path.parent, f"write target {path}")
    if exclusive and safe_path.exists():
        raise KnowledgeError("E_OUTPUT", f"refusing to overwrite existing file: {path}")
    try:
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{safe_path.name}.", suffix=".tmp", dir=safe_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            current_safe_path = governed_file_path(root, path, path.parent, f"write target {path}")
            if current_safe_path != safe_path:
                raise KnowledgeError(
                    "E_PATH_BOUNDARY", f"write target changed after validation: {path} -> {current_safe_path}"
                )
            if exclusive and safe_path.exists():
                raise KnowledgeError("E_OUTPUT", f"refusing to overwrite existing file: {path}")
            os.replace(temporary, safe_path)
        finally:
            if temporary.exists():
                temporary.unlink()
    except KnowledgeError:
        raise
    except OSError as exc:
        raise KnowledgeError("E_IO", f"atomic write failed for {path}: {exc}") from exc


def read_json(path: Path, *, root: Path, parent: Path, context: str) -> dict[str, Any]:
    path = governed_file_path(root, path, parent, context)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KnowledgeError("E_REFERENCE", f"missing JSON document: {path}") from exc
    except json.JSONDecodeError as exc:
        raise KnowledgeError("E_JSON", f"invalid JSON {path}: {exc}") from exc
    except OSError as exc:
        raise KnowledgeError("E_IO", f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise KnowledgeError("E_SCHEMA", f"JSON document must be an object: {path}")
    return value


def journal_id(operation: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dt%H%M%S%fz")
    return f"j-{stamp}-{operation}-{uuid.uuid4().hex[:8]}"


def transactional_write(
    root: Path,
    operation: str,
    target: Path,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    *,
    exclusive: bool = False,
) -> None:
    jid = journal_id(operation)
    journal_path = root / "update-journal" / f"{jid}.json"
    governed_file_path(root, target, target.parent, f"{operation} target")
    governed_file_path(root, journal_path, root / "update-journal", f"{operation} journal")
    created = now_utc()
    try:
        relative_target = target.relative_to(root).as_posix()
    except ValueError:
        relative_target = str(target)
    journal = {
        "record_type": "JournalRecord",
        "schema_version": SCHEMA_VERSION,
        "id": jid,
        "operation": operation,
        "status": "prepared",
        "created_at": created,
        "committed_at": None,
        "before": before,
        "after": after,
        "target": relative_target,
    }
    atomic_write_json(root, journal_path, journal, exclusive=True)
    try:
        atomic_write_json(root, target, after, exclusive=exclusive)
    except Exception:
        journal["status"] = "aborted"
        journal["committed_at"] = now_utc()
        atomic_write_json(root, journal_path, journal)
        raise
    journal["status"] = "committed"
    journal["committed_at"] = now_utc()
    atomic_write_json(root, journal_path, journal)


def issue(issues: list[Issue], code: str, message: str) -> None:
    issues.append(Issue(code, message))


def exact_fields(
    value: Any,
    required: Iterable[str],
    optional: Iterable[str],
    context: str,
    issues: list[Issue],
) -> bool:
    if not isinstance(value, dict):
        issue(issues, "E_SCHEMA", f"{context} must be an object")
        return False
    required_set = set(required)
    allowed = required_set | set(optional)
    for name in sorted(required_set - value.keys()):
        issue(issues, "E_SCHEMA", f"{context} missing field: {name}")
    for name in sorted(value.keys() - allowed):
        issue(issues, "E_SCHEMA", f"{context} has unsupported field: {name}")
    return required_set <= value.keys()


def check_string(value: Any, context: str, issues: list[Issue], *, nullable: bool = False) -> bool:
    if nullable and value is None:
        return True
    if not isinstance(value, str) or not value:
        issue(issues, "E_SCHEMA", f"{context} must be a non-empty string")
        return False
    return True


def check_id(value: Any, context: str, issues: list[Issue], *, nullable: bool = False) -> bool:
    if nullable and value is None:
        return True
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        issue(issues, "E_SCHEMA", f"{context} is not a valid id: {value!r}")
        return False
    return True


def check_timestamp(value: Any, context: str, issues: list[Issue], *, nullable: bool = False) -> bool:
    if nullable and value is None:
        return True
    if not isinstance(value, str):
        issue(issues, "E_SCHEMA", f"{context} must be an ISO-8601 timestamp")
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
    except ValueError:
        issue(issues, "E_SCHEMA", f"{context} must include a valid timezone: {value!r}")
        return False
    return True


def check_id_list(value: Any, context: str, issues: list[Issue], *, minimum: int = 0) -> bool:
    if not isinstance(value, list):
        issue(issues, "E_SCHEMA", f"{context} must be an array")
        return False
    if len(value) < minimum:
        issue(issues, "E_SCHEMA", f"{context} requires at least {minimum} item(s)")
    seen: set[str] = set()
    for index, item in enumerate(value):
        if check_id(item, f"{context}[{index}]", issues):
            if item in seen:
                issue(issues, "E_SCHEMA", f"{context} contains duplicate id: {item}")
            seen.add(item)
    return True


def check_permissions(value: Any, context: str, issues: list[Issue]) -> bool:
    if not exact_fields(value, ("discover", "read", "execute"), (), context, issues):
        return False
    valid = True
    for name in ("discover", "read", "execute"):
        if type(value.get(name)) is not bool:
            issue(issues, "E_SCHEMA", f"{context}.{name} must be boolean")
            valid = False
    return valid


def check_pin(value: Any, context: str, issues: list[Issue], *, nullable: bool = False) -> bool:
    if nullable and value is None:
        return True
    if not exact_fields(value, ("kind", "value", "captured_at", "verification_method"), (), context, issues):
        return False
    kind = value.get("kind")
    raw = value.get("value")
    valid = True
    if kind not in {"sha256", "git_commit"}:
        issue(issues, "E_PIN", f"{context}.kind must be sha256 or git_commit")
        valid = False
    elif kind == "sha256" and (not isinstance(raw, str) or not SHA256_RE.fullmatch(raw)):
        issue(issues, "E_PIN", f"{context}.value must be 64 lowercase hex characters")
        valid = False
    elif kind == "git_commit" and (not isinstance(raw, str) or not COMMIT_RE.fullmatch(raw)):
        issue(issues, "E_PIN", f"{context}.value must be a 40-character commit SHA")
        valid = False
    valid = check_timestamp(value.get("captured_at"), f"{context}.captured_at", issues) and valid
    valid = check_string(value.get("verification_method"), f"{context}.verification_method", issues) and valid
    return valid


def check_license(value: Any, context: str, issues: list[Issue]) -> bool:
    if not exact_fields(value, ("status", "identifier", "usage_notes"), (), context, issues):
        return False
    valid = True
    status = value.get("status")
    if status not in {"approved", "internal_authorized", "unknown", "denied"}:
        issue(issues, "E_SCHEMA", f"{context}.status is invalid")
        valid = False
    identifier = value.get("identifier")
    if identifier is not None and not isinstance(identifier, str):
        issue(issues, "E_SCHEMA", f"{context}.identifier must be string or null")
        valid = False
    if status in {"approved", "internal_authorized"} and not identifier:
        issue(issues, "E_LICENSE", f"{context}.identifier is required when license is usable")
        valid = False
    if not isinstance(value.get("usage_notes"), str):
        issue(issues, "E_SCHEMA", f"{context}.usage_notes must be a string")
        valid = False
    return valid


def check_security(value: Any, context: str, issues: list[Issue]) -> bool:
    if not exact_fields(value, ("status", "reviewed_at", "reviewed_by", "notes"), (), context, issues):
        return False
    valid = True
    status = value.get("status")
    if status not in {"reviewed", "unreviewed", "blocked"}:
        issue(issues, "E_SCHEMA", f"{context}.status is invalid")
        valid = False
    valid = check_timestamp(value.get("reviewed_at"), f"{context}.reviewed_at", issues, nullable=True) and valid
    if value.get("reviewed_by") is not None and not isinstance(value.get("reviewed_by"), str):
        issue(issues, "E_SCHEMA", f"{context}.reviewed_by must be string or null")
        valid = False
    if status == "reviewed" and not value.get("reviewed_by"):
        issue(issues, "E_SECURITY", f"{context}.reviewed_by is required for reviewed content")
        valid = False
    if status == "reviewed" and value.get("reviewed_at") is None:
        issue(issues, "E_SECURITY", f"{context}.reviewed_at is required for reviewed content")
        valid = False
    if not isinstance(value.get("notes"), str):
        issue(issues, "E_SCHEMA", f"{context}.notes must be a string")
        valid = False
    return valid


def check_context_budget(value: Any, context: str, issues: list[Issue]) -> bool:
    required = (
        "max_sources",
        "max_evidence_records",
        "max_excerpt_chars",
        "minimum_evidence_per_required_source",
    )
    if not exact_fields(value, required, (), context, issues):
        return False
    ranges = {
        "max_sources": (1, 100),
        "max_evidence_records": (1, 1000),
        "max_excerpt_chars": (0, 1_000_000),
        "minimum_evidence_per_required_source": (1, 100),
    }
    valid = True
    for name, (low, high) in ranges.items():
        current = value.get(name)
        if type(current) is not int or not low <= current <= high:
            issue(issues, "E_SCHEMA", f"{context}.{name} must be an integer from {low} to {high}")
            valid = False
    return valid


def check_schema_version(value: Any, context: str, issues: list[Issue]) -> bool:
    if type(value) is not int or value != SCHEMA_VERSION:
        issue(issues, "E_SCHEMA", f"{context}.schema_version must be integer {SCHEMA_VERSION}")
        return False
    return True


def check_common(value: dict[str, Any], record_type: str, context: str, issues: list[Issue]) -> None:
    if value.get("record_type") != record_type:
        issue(issues, "E_SCHEMA", f"{context}.record_type must be {record_type}")
    check_schema_version(value.get("schema_version"), context, issues)
    if record_type not in {"RegistryState"}:
        check_id(value.get("id"), f"{context}.id", issues)


def validate_requirement(value: dict[str, Any], context: str, issues: list[Issue]) -> None:
    required = (
        "record_type", "schema_version", "id", "purpose", "question",
        "required_source_ids", "optional_source_ids", "critical_claims",
        "permissions", "context_budget", "conflict_policy", "created_at",
    )
    if not exact_fields(value, required, (), context, issues):
        return
    check_common(value, "KnowledgeRequirement", context, issues)
    check_string(value.get("purpose"), f"{context}.purpose", issues)
    check_string(value.get("question"), f"{context}.question", issues)
    check_id_list(value.get("required_source_ids"), f"{context}.required_source_ids", issues, minimum=1)
    check_id_list(value.get("optional_source_ids"), f"{context}.optional_source_ids", issues)
    check_id_list(value.get("critical_claims"), f"{context}.critical_claims", issues, minimum=1)
    if isinstance(value.get("required_source_ids"), list) and isinstance(value.get("optional_source_ids"), list):
        overlap = set(value["required_source_ids"]) & set(value["optional_source_ids"])
        if overlap:
            issue(issues, "E_SCHEMA", f"{context} source ids cannot be both required and optional: {sorted(overlap)}")
    check_permissions(value.get("permissions"), f"{context}.permissions", issues)
    check_context_budget(value.get("context_budget"), f"{context}.context_budget", issues)
    if value.get("conflict_policy") != "fail_on_critical":
        issue(issues, "E_SCHEMA", f"{context}.conflict_policy must be fail_on_critical")
    check_timestamp(value.get("created_at"), f"{context}.created_at", issues)


def validate_source(value: dict[str, Any], context: str, issues: list[Issue]) -> None:
    required = (
        "record_type", "schema_version", "id", "source_type", "title", "locator",
        "discovered_at", "permissions", "license", "security", "pin",
        "content_trust", "status", "notes",
    )
    if not exact_fields(value, required, ("discovery_metadata",), context, issues):
        return
    check_common(value, "SourceRecord", context, issues)
    source_type = value.get("source_type")
    if source_type not in SOURCE_TYPES:
        issue(issues, "E_SCHEMA", f"{context}.source_type is invalid")
    check_string(value.get("title"), f"{context}.title", issues)
    check_string(value.get("locator"), f"{context}.locator", issues)
    check_timestamp(value.get("discovered_at"), f"{context}.discovered_at", issues)
    check_permissions(value.get("permissions"), f"{context}.permissions", issues)
    check_license(value.get("license"), f"{context}.license", issues)
    check_security(value.get("security"), f"{context}.security", issues)
    check_pin(value.get("pin"), f"{context}.pin", issues, nullable=True)
    if value.get("content_trust") not in {"local_controlled", "untrusted_data"}:
        issue(issues, "E_SCHEMA", f"{context}.content_trust is invalid")
    if source_type in EXTERNAL_TYPES and value.get("content_trust") != "untrusted_data":
        issue(issues, "E_SECURITY", f"{context} external content must be marked untrusted_data")
    if value.get("status") not in {"candidate", "approved", "rejected"}:
        issue(issues, "E_SCHEMA", f"{context}.status is invalid")
    if not isinstance(value.get("notes"), str):
        issue(issues, "E_SCHEMA", f"{context}.notes must be a string")
    metadata = value.get("discovery_metadata")
    if source_type == "github":
        if not isinstance(metadata, dict):
            issue(issues, "E_SCHEMA", f"{context}.discovery_metadata is required for github")
        else:
            fields = ("kind", "stars", "captured_at", "stars_use", "license_spdx", "archived", "default_branch", "head_commit")
            if exact_fields(metadata, fields, (), f"{context}.discovery_metadata", issues):
                if metadata.get("kind") != "github":
                    issue(issues, "E_SCHEMA", f"{context}.discovery_metadata.kind must be github")
                if type(metadata.get("stars")) is not int or metadata.get("stars", -1) < 0:
                    issue(issues, "E_SCHEMA", f"{context}.discovery_metadata.stars must be a non-negative integer")
                check_timestamp(metadata.get("captured_at"), f"{context}.discovery_metadata.captured_at", issues)
                if metadata.get("stars_use") != "discovery_only":
                    issue(issues, "E_SCHEMA", f"{context}.discovery_metadata.stars_use must be discovery_only")
                if metadata.get("license_spdx") is not None and not isinstance(metadata.get("license_spdx"), str):
                    issue(issues, "E_SCHEMA", f"{context}.discovery_metadata.license_spdx must be string or null")
                if type(metadata.get("archived")) is not bool:
                    issue(issues, "E_SCHEMA", f"{context}.discovery_metadata.archived must be boolean")
                check_string(metadata.get("default_branch"), f"{context}.discovery_metadata.default_branch", issues)
                if not isinstance(metadata.get("head_commit"), str) or not COMMIT_RE.fullmatch(metadata["head_commit"]):
                    issue(issues, "E_PIN", f"{context}.discovery_metadata.head_commit is invalid")
        pin = value.get("pin")
        if not isinstance(pin, dict) or pin.get("kind") != "git_commit":
            issue(issues, "E_PIN", f"{context} github source must use a git_commit pin")


def validate_locator(value: Any, context: str, issues: list[Issue]) -> None:
    if not isinstance(value, dict):
        issue(issues, "E_EVIDENCE", f"{context} must be an evidence locator object")
        return
    kind = value.get("kind")
    if kind == "local":
        required, optional = ("kind", "path", "content_sha256"), ("line_start", "line_end", "page", "section")
        exact_fields(value, required, optional, context, issues)
        check_string(value.get("path"), f"{context}.path", issues)
        if not isinstance(value.get("content_sha256"), str) or not SHA256_RE.fullmatch(value["content_sha256"]):
            issue(issues, "E_PIN", f"{context}.content_sha256 is invalid")
        if not any(value.get(name) not in (None, "") for name in ("line_start", "page", "section")):
            issue(issues, "E_EVIDENCE", f"{context} needs line, page or section coordinates")
        if "line_start" in value or "line_end" in value:
            start, end = value.get("line_start"), value.get("line_end")
            if type(start) is not int or type(end) is not int or start < 1 or end < start:
                issue(issues, "E_EVIDENCE", f"{context} line range is invalid")
    elif kind == "official":
        required, optional = ("kind", "url", "content_sha256", "published_version"), ("page", "section", "fragment")
        exact_fields(value, required, optional, context, issues)
        check_string(value.get("url"), f"{context}.url", issues)
        check_string(value.get("published_version"), f"{context}.published_version", issues)
        if not isinstance(value.get("content_sha256"), str) or not SHA256_RE.fullmatch(value["content_sha256"]):
            issue(issues, "E_PIN", f"{context}.content_sha256 is invalid")
        if not any(value.get(name) for name in ("page", "section", "fragment")):
            issue(issues, "E_EVIDENCE", f"{context} needs page, section or fragment coordinates")
    elif kind == "paper":
        required, optional = ("kind", "identifier", "content_sha256"), ("page", "section", "figure", "table")
        exact_fields(value, required, optional, context, issues)
        check_string(value.get("identifier"), f"{context}.identifier", issues)
        if not isinstance(value.get("content_sha256"), str) or not SHA256_RE.fullmatch(value["content_sha256"]):
            issue(issues, "E_PIN", f"{context}.content_sha256 is invalid")
        if not any(value.get(name) for name in ("page", "section", "figure", "table")):
            issue(issues, "E_EVIDENCE", f"{context} needs page, section, figure or table coordinates")
    elif kind == "github":
        fields = ("kind", "repository", "commit", "path", "line_start", "line_end")
        exact_fields(value, fields, (), context, issues)
        if not isinstance(value.get("repository"), str) or not REPO_RE.fullmatch(value["repository"]):
            issue(issues, "E_EVIDENCE", f"{context}.repository must be owner/repo")
        if not isinstance(value.get("commit"), str) or not COMMIT_RE.fullmatch(value["commit"]):
            issue(issues, "E_PIN", f"{context}.commit is invalid")
        check_string(value.get("path"), f"{context}.path", issues)
        start, end = value.get("line_start"), value.get("line_end")
        if type(start) is not int or type(end) is not int or start < 1 or end < start:
            issue(issues, "E_EVIDENCE", f"{context} line range is invalid")
    else:
        issue(issues, "E_EVIDENCE", f"{context}.kind must be one of {sorted(SOURCE_TYPES)}")


def validate_evidence(value: dict[str, Any], context: str, issues: list[Issue]) -> None:
    required = (
        "record_type", "schema_version", "id", "requirement_id", "source_id",
        "claim_id", "claim", "stance", "captured_at", "source_pin", "locator",
        "excerpt_sha256", "notes",
    )
    if not exact_fields(value, required, ("excerpt",), context, issues):
        return
    check_common(value, "EvidenceRecord", context, issues)
    check_id(value.get("requirement_id"), f"{context}.requirement_id", issues)
    check_id(value.get("source_id"), f"{context}.source_id", issues)
    check_id(value.get("claim_id"), f"{context}.claim_id", issues)
    check_string(value.get("claim"), f"{context}.claim", issues)
    if value.get("stance") not in {"supports", "contradicts", "context"}:
        issue(issues, "E_SCHEMA", f"{context}.stance is invalid")
    check_timestamp(value.get("captured_at"), f"{context}.captured_at", issues)
    check_pin(value.get("source_pin"), f"{context}.source_pin", issues)
    validate_locator(value.get("locator"), f"{context}.locator", issues)
    excerpt_hash = value.get("excerpt_sha256")
    if not isinstance(excerpt_hash, str) or not SHA256_RE.fullmatch(excerpt_hash):
        issue(issues, "E_EVIDENCE", f"{context}.excerpt_sha256 is invalid")
    excerpt = value.get("excerpt")
    if excerpt is not None:
        if not isinstance(excerpt, str):
            issue(issues, "E_SCHEMA", f"{context}.excerpt must be a string")
        elif sha256_bytes(excerpt.encode("utf-8")) != excerpt_hash:
            issue(issues, "E_EVIDENCE", f"{context}.excerpt_sha256 does not match excerpt")
    if not isinstance(value.get("notes"), str):
        issue(issues, "E_SCHEMA", f"{context}.notes must be a string")


def validate_authority(value: Any, context: str, issues: list[Issue]) -> None:
    fields = ("status", "decided_by", "authority_role", "scope", "decided_at", "supersedes", "basis")
    if not exact_fields(value, fields, (), context, issues):
        return
    if value.get("status") not in {"confirmed", "candidate_only"}:
        issue(issues, "E_SCHEMA", f"{context}.status is invalid")
    check_string(value.get("scope"), f"{context}.scope", issues)
    check_string(value.get("basis"), f"{context}.basis", issues)
    check_id_list(value.get("supersedes"), f"{context}.supersedes", issues)
    if value.get("decided_by") is not None and not isinstance(value.get("decided_by"), str):
        issue(issues, "E_SCHEMA", f"{context}.decided_by must be string or null")
    if value.get("authority_role") is not None and not isinstance(value.get("authority_role"), str):
        issue(issues, "E_SCHEMA", f"{context}.authority_role must be string or null")
    check_timestamp(value.get("decided_at"), f"{context}.decided_at", issues, nullable=True)
    if value.get("status") == "confirmed":
        if not value.get("decided_by") or not value.get("authority_role") or not value.get("decided_at"):
            issue(issues, "E_AUTHORITY", f"{context} confirmed decision needs decider, role and date")


def validate_conflict(value: Any, context: str, issues: list[Issue]) -> None:
    fields = ("id", "claim", "source_ids", "evidence_ids", "severity", "status", "resolution")
    if not exact_fields(value, fields, (), context, issues):
        return
    check_id(value.get("id"), f"{context}.id", issues)
    check_string(value.get("claim"), f"{context}.claim", issues)
    check_id_list(value.get("source_ids"), f"{context}.source_ids", issues, minimum=2)
    check_id_list(value.get("evidence_ids"), f"{context}.evidence_ids", issues, minimum=2)
    if value.get("severity") not in {"critical", "noncritical"}:
        issue(issues, "E_SCHEMA", f"{context}.severity is invalid")
    if value.get("status") not in {"resolved", "unresolved"}:
        issue(issues, "E_SCHEMA", f"{context}.status is invalid")
    resolution = value.get("resolution")
    if resolution is not None and not isinstance(resolution, str):
        issue(issues, "E_SCHEMA", f"{context}.resolution must be string or null")
    if value.get("status") == "resolved" and not resolution:
        issue(issues, "E_CONFLICT", f"{context} resolved conflict needs a resolution")


def validate_lock(value: dict[str, Any], context: str, issues: list[Issue]) -> None:
    required = (
        "record_type", "schema_version", "id", "requirement_id", "created_at",
        "source_pins", "evidence_ids", "conflicts", "conflict_review",
        "authority_decision", "notes",
    )
    if not exact_fields(value, required, (), context, issues):
        return
    check_common(value, "SourceLock", context, issues)
    check_id(value.get("requirement_id"), f"{context}.requirement_id", issues)
    check_timestamp(value.get("created_at"), f"{context}.created_at", issues)
    bindings = value.get("source_pins")
    if not isinstance(bindings, list) or not bindings:
        issue(issues, "E_SCHEMA", f"{context}.source_pins must be a non-empty array")
    else:
        seen: set[str] = set()
        for index, binding in enumerate(bindings):
            bctx = f"{context}.source_pins[{index}]"
            if exact_fields(binding, ("source_id", "source_type", "pin"), (), bctx, issues):
                check_id(binding.get("source_id"), f"{bctx}.source_id", issues)
                if binding.get("source_id") in seen:
                    issue(issues, "E_SCHEMA", f"{context}.source_pins duplicates {binding.get('source_id')}")
                seen.add(binding.get("source_id"))
                if binding.get("source_type") not in SOURCE_TYPES:
                    issue(issues, "E_SCHEMA", f"{bctx}.source_type is invalid")
                check_pin(binding.get("pin"), f"{bctx}.pin", issues)
    check_id_list(value.get("evidence_ids"), f"{context}.evidence_ids", issues, minimum=1)
    conflicts = value.get("conflicts")
    if not isinstance(conflicts, list):
        issue(issues, "E_SCHEMA", f"{context}.conflicts must be an array")
    else:
        for index, conflict in enumerate(conflicts):
            validate_conflict(conflict, f"{context}.conflicts[{index}]", issues)
    review = value.get("conflict_review")
    fields = ("status", "reviewed_at", "reviewed_by", "notes")
    if exact_fields(review, fields, (), f"{context}.conflict_review", issues):
        if review.get("status") not in {"complete", "incomplete"}:
            issue(issues, "E_SCHEMA", f"{context}.conflict_review.status is invalid")
        check_timestamp(review.get("reviewed_at"), f"{context}.conflict_review.reviewed_at", issues, nullable=True)
        if review.get("reviewed_by") is not None and not isinstance(review.get("reviewed_by"), str):
            issue(issues, "E_SCHEMA", f"{context}.conflict_review.reviewed_by must be string or null")
        if review.get("status") == "complete" and (not review.get("reviewed_at") or not review.get("reviewed_by")):
            issue(issues, "E_CONFLICT", f"{context}.conflict_review complete needs reviewer and date")
        if not isinstance(review.get("notes"), str):
            issue(issues, "E_SCHEMA", f"{context}.conflict_review.notes must be a string")
    validate_authority(value.get("authority_decision"), f"{context}.authority_decision", issues)
    if not isinstance(value.get("notes"), str):
        issue(issues, "E_SCHEMA", f"{context}.notes must be a string")


def validate_packet(value: dict[str, Any], context: str, issues: list[Issue]) -> None:
    required = (
        "record_type", "schema_version", "id", "requirement_id", "lock_id",
        "lock_digest", "generated_at", "purpose", "question", "authority_decision",
        "sources", "evidence", "conflicts", "selection", "model_prior_fallback",
        "external_content_policy", "execution_authorized",
    )
    if not exact_fields(value, required, (), context, issues):
        return
    check_common(value, "KnowledgePacket", context, issues)
    check_id(value.get("requirement_id"), f"{context}.requirement_id", issues)
    check_id(value.get("lock_id"), f"{context}.lock_id", issues)
    if not isinstance(value.get("lock_digest"), str) or not SHA256_RE.fullmatch(value["lock_digest"]):
        issue(issues, "E_PIN", f"{context}.lock_digest is invalid")
    check_timestamp(value.get("generated_at"), f"{context}.generated_at", issues)
    check_string(value.get("purpose"), f"{context}.purpose", issues)
    check_string(value.get("question"), f"{context}.question", issues)
    validate_authority(value.get("authority_decision"), f"{context}.authority_decision", issues)
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        issue(issues, "E_SCHEMA", f"{context}.sources must be a non-empty array")
    else:
        fields = ("source_id", "source_type", "title", "locator", "pin", "license", "content_trust")
        for index, source in enumerate(sources):
            sctx = f"{context}.sources[{index}]"
            if exact_fields(source, fields, (), sctx, issues):
                check_id(source.get("source_id"), f"{sctx}.source_id", issues)
                if source.get("source_type") not in SOURCE_TYPES:
                    issue(issues, "E_SCHEMA", f"{sctx}.source_type is invalid")
                check_string(source.get("title"), f"{sctx}.title", issues)
                check_string(source.get("locator"), f"{sctx}.locator", issues)
                check_pin(source.get("pin"), f"{sctx}.pin", issues)
                check_license(source.get("license"), f"{sctx}.license", issues)
                if source.get("content_trust") not in {"local_controlled", "untrusted_data"}:
                    issue(issues, "E_SCHEMA", f"{sctx}.content_trust is invalid")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        issue(issues, "E_SCHEMA", f"{context}.evidence must be a non-empty array")
    else:
        for index, item in enumerate(evidence):
            if isinstance(item, dict):
                validate_evidence(item, f"{context}.evidence[{index}]", issues)
            else:
                issue(issues, "E_SCHEMA", f"{context}.evidence[{index}] must be an object")
    conflicts = value.get("conflicts")
    if not isinstance(conflicts, list):
        issue(issues, "E_SCHEMA", f"{context}.conflicts must be an array")
    else:
        for index, conflict in enumerate(conflicts):
            validate_conflict(conflict, f"{context}.conflicts[{index}]", issues)
    selection = value.get("selection")
    selection_fields = (
        "context_budget", "included_source_ids", "omitted_source_ids",
        "included_evidence_ids", "omitted_evidence_ids", "omitted_excerpt_ids", "rationale",
    )
    if exact_fields(selection, selection_fields, (), f"{context}.selection", issues):
        check_context_budget(selection.get("context_budget"), f"{context}.selection.context_budget", issues)
        for name in ("included_source_ids", "omitted_source_ids", "included_evidence_ids", "omitted_evidence_ids", "omitted_excerpt_ids"):
            check_id_list(selection.get(name), f"{context}.selection.{name}", issues)
        check_string(selection.get("rationale"), f"{context}.selection.rationale", issues)
    if value.get("model_prior_fallback") is not False:
        issue(issues, "E_REQUIRED_SOURCE_MISSING", f"{context}.model_prior_fallback must be false")
    if value.get("external_content_policy") != "untrusted_data_no_execute":
        issue(issues, "E_SECURITY", f"{context}.external_content_policy is invalid")
    if value.get("execution_authorized") is not False:
        issue(issues, "E_PERMISSION", f"{context}.execution_authorized must be false")


def validate_state(value: dict[str, Any], context: str, issues: list[Issue]) -> None:
    required = (
        "record_type", "schema_version", "registry_id", "created_at", "updated_at",
        "active_lock_id", "active_lock_digest", "previous_lock_id", "previous_lock_digest",
    )
    if not exact_fields(value, required, (), context, issues):
        return
    if value.get("record_type") != "RegistryState":
        issue(issues, "E_SCHEMA", f"{context}.record_type must be RegistryState")
    check_schema_version(value.get("schema_version"), context, issues)
    check_id(value.get("registry_id"), f"{context}.registry_id", issues)
    check_timestamp(value.get("created_at"), f"{context}.created_at", issues)
    check_timestamp(value.get("updated_at"), f"{context}.updated_at", issues)
    for prefix in ("active", "previous"):
        lock_id = value.get(f"{prefix}_lock_id")
        digest = value.get(f"{prefix}_lock_digest")
        check_id(lock_id, f"{context}.{prefix}_lock_id", issues, nullable=True)
        if digest is not None and (not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)):
            issue(issues, "E_PIN", f"{context}.{prefix}_lock_digest is invalid")
        if (lock_id is None) != (digest is None):
            issue(issues, "E_STATE", f"{context}.{prefix} lock id and digest must both be null or both be set")


def validate_journal(value: dict[str, Any], context: str, issues: list[Issue]) -> None:
    required = (
        "record_type", "schema_version", "id", "operation", "status", "created_at",
        "committed_at", "before", "after", "target",
    )
    if not exact_fields(value, required, (), context, issues):
        return
    check_common(value, "JournalRecord", context, issues)
    if value.get("operation") not in {"init", "packet", "activate", "rollback"}:
        issue(issues, "E_SCHEMA", f"{context}.operation is invalid")
    if value.get("status") not in {"prepared", "committed", "aborted"}:
        issue(issues, "E_SCHEMA", f"{context}.status is invalid")
    check_timestamp(value.get("created_at"), f"{context}.created_at", issues)
    check_timestamp(value.get("committed_at"), f"{context}.committed_at", issues, nullable=True)
    if value.get("status") == "prepared":
        issue(issues, "E_STATE", f"{context} is still prepared; inspect transaction before continuing")
    if value.get("status") == "committed" and value.get("committed_at") is None:
        issue(issues, "E_STATE", f"{context} committed journal needs committed_at")
    if value.get("before") is not None and not isinstance(value.get("before"), dict):
        issue(issues, "E_SCHEMA", f"{context}.before must be object or null")
    if value.get("after") is not None and not isinstance(value.get("after"), dict):
        issue(issues, "E_SCHEMA", f"{context}.after must be object or null")
    check_string(value.get("target"), f"{context}.target", issues)


VALIDATORS = {
    "KnowledgeRequirement": validate_requirement,
    "SourceRecord": validate_source,
    "EvidenceRecord": validate_evidence,
    "SourceLock": validate_lock,
    "KnowledgePacket": validate_packet,
    "RegistryState": validate_state,
    "JournalRecord": validate_journal,
}


def load_documents(
    directory: Path, expected_type: str, issues: list[Issue], *, root: Path
) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    try:
        safe_directory = governed_directory(root, directory, f"{expected_type} directory")
    except KnowledgeError as exc:
        issue(issues, exc.code, exc.message)
        return documents
    if not safe_directory.is_dir():
        return documents
    try:
        paths = sorted(safe_directory.iterdir())
    except OSError as exc:
        issue(issues, "E_IO", f"cannot enumerate {directory}: {exc}")
        return documents
    for path in paths:
        try:
            safe_path = governed_file_path(root, path, directory, f"{expected_type} document {path.name}")
        except KnowledgeError as exc:
            issue(issues, exc.code, exc.message)
            continue
        if safe_path.is_dir() or path.suffix.lower() != ".json":
            issue(issues, "E_SCHEMA", f"unexpected item in {directory}: {path.name}")
            continue
        try:
            value = json.loads(safe_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issue(issues, "E_JSON", f"invalid JSON {path}: {exc}")
            continue
        except OSError as exc:
            issue(issues, "E_IO", f"cannot read {path}: {exc}")
            continue
        if not isinstance(value, dict):
            issue(issues, "E_SCHEMA", f"{path} must contain a JSON object")
            continue
        validator = VALIDATORS[expected_type]
        validator(value, str(path), issues)
        record_id = value.get("id")
        if isinstance(record_id, str):
            if path.stem != record_id:
                issue(issues, "E_REFERENCE", f"filename/id mismatch: {path.name} != {record_id}.json")
            if record_id in documents:
                issue(issues, "E_REFERENCE", f"duplicate {expected_type} id: {record_id}")
            documents[record_id] = value
    return documents


def pin_matches_source_type(source_type: str, pin: dict[str, Any]) -> bool:
    if source_type == "github":
        return pin.get("kind") == "git_commit" and isinstance(pin.get("value"), str) and bool(COMMIT_RE.fullmatch(pin["value"]))
    return pin.get("kind") == "sha256" and isinstance(pin.get("value"), str) and bool(SHA256_RE.fullmatch(pin["value"]))


def semantic_lock_issues(
    lock: dict[str, Any],
    requirements: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
) -> list[Issue]:
    issues: list[Issue] = []
    lock_id = lock.get("id", "<unknown>")
    requirement_id = lock.get("requirement_id")
    requirement = requirements.get(requirement_id)
    if requirement is None:
        issue(issues, "E_REFERENCE", f"lock {lock_id} references missing requirement {requirement_id}")
        return issues
    permissions = requirement.get("permissions", {})
    if not permissions.get("discover") or not permissions.get("read"):
        issue(issues, "E_PERMISSION", f"requirement {requirement_id} needs discover=true and read=true for lock use")

    raw_bindings = lock.get("source_pins")
    bindings = {
        item.get("source_id"): item
        for item in raw_bindings
        if isinstance(raw_bindings, list) and isinstance(item, dict) and isinstance(item.get("source_id"), str)
    } if isinstance(raw_bindings, list) else {}
    required_ids = requirement.get("required_source_ids", []) if isinstance(requirement.get("required_source_ids"), list) else []
    optional_ids = requirement.get("optional_source_ids", []) if isinstance(requirement.get("optional_source_ids"), list) else []
    missing = [source_id for source_id in required_ids if source_id not in bindings]
    if missing:
        issue(issues, "E_REQUIRED_SOURCE_MISSING", f"lock {lock_id} omits required sources: {missing}")
    allowed_ids = set(required_ids) | set(optional_ids)
    extras = sorted(set(bindings) - allowed_ids)
    if extras:
        issue(issues, "E_REFERENCE", f"lock {lock_id} includes sources not declared by requirement: {extras}")

    authority = lock.get("authority_decision", {})
    if not isinstance(authority, dict) or authority.get("status") != "confirmed":
        issue(issues, "E_AUTHORITY", f"lock {lock_id} lacks a confirmed in-scope authority decision")
    review = lock.get("conflict_review", {})
    if not isinstance(review, dict) or review.get("status") != "complete":
        issue(issues, "E_CONFLICT", f"lock {lock_id} conflict review is incomplete")

    for source_id, binding in bindings.items():
        source = sources.get(source_id)
        if source is None:
            issue(issues, "E_REFERENCE", f"lock {lock_id} references missing source {source_id}")
            continue
        if source.get("status") != "approved":
            issue(issues, "E_SECURITY", f"source {source_id} is not approved")
        source_permissions = source.get("permissions", {})
        if not source_permissions.get("discover") or not source_permissions.get("read"):
            issue(issues, "E_PERMISSION", f"source {source_id} needs discover=true and read=true")
        license_record = source.get("license", {})
        license_status = license_record.get("status") if isinstance(license_record, dict) else None
        if license_status not in {"approved", "internal_authorized"}:
            issue(issues, "E_LICENSE", f"source {source_id} license is {license_status or 'missing'}")
        security = source.get("security", {})
        security_status = security.get("status") if isinstance(security, dict) else None
        if security_status != "reviewed":
            issue(issues, "E_SECURITY", f"source {source_id} security is {security_status or 'missing'}")
        pin = source.get("pin")
        binding_pin = binding.get("pin")
        if not isinstance(pin, dict):
            issue(issues, "E_PIN", f"source {source_id} has no immutable pin")
        elif not pin_matches_source_type(source.get("source_type"), pin):
            issue(issues, "E_PIN", f"source {source_id} pin kind/value does not match {source.get('source_type')}")
        if binding.get("source_type") != source.get("source_type"):
            issue(issues, "E_REFERENCE", f"lock {lock_id} source type snapshot differs for {source_id}")
        if pin != binding_pin:
            issue(issues, "E_PIN", f"lock {lock_id} pin snapshot differs for {source_id}")
        if source.get("source_type") in EXTERNAL_TYPES and source.get("content_trust") != "untrusted_data":
            issue(issues, "E_SECURITY", f"source {source_id} external content is not marked untrusted_data")

    evidence_ids = lock.get("evidence_ids", []) if isinstance(lock.get("evidence_ids"), list) else []
    locked_evidence: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        item = evidence.get(evidence_id)
        if item is None:
            issue(issues, "E_REFERENCE", f"lock {lock_id} references missing evidence {evidence_id}")
            continue
        locked_evidence.append(item)
        source_id = item.get("source_id")
        if item.get("requirement_id") != requirement_id:
            issue(issues, "E_REFERENCE", f"evidence {evidence_id} belongs to another requirement")
        if source_id not in bindings:
            issue(issues, "E_REFERENCE", f"evidence {evidence_id} uses source not in lock: {source_id}")
            continue
        binding_pin = bindings[source_id].get("pin")
        if item.get("source_pin") != binding_pin:
            issue(issues, "E_PIN", f"evidence {evidence_id} pin differs from lock for {source_id}")
        source = sources.get(source_id, {})
        locator = item.get("locator", {})
        if isinstance(locator, dict) and locator.get("kind") != source.get("source_type"):
            issue(issues, "E_EVIDENCE", f"evidence {evidence_id} locator kind differs from source type")
        if isinstance(binding_pin, dict) and isinstance(locator, dict):
            if binding_pin.get("kind") == "git_commit" and locator.get("commit") != binding_pin.get("value"):
                issue(issues, "E_PIN", f"evidence {evidence_id} commit differs from source pin")
            if binding_pin.get("kind") == "sha256" and locator.get("content_sha256") != binding_pin.get("value"):
                issue(issues, "E_PIN", f"evidence {evidence_id} content hash differs from source pin")

    minimum = requirement.get("context_budget", {}).get("minimum_evidence_per_required_source")
    if type(minimum) is int:
        for source_id in required_ids:
            count = sum(1 for item in locked_evidence if item.get("source_id") == source_id)
            if count < minimum:
                issue(issues, "E_EVIDENCE", f"required source {source_id} has {count} evidence record(s), needs {minimum}")
    for claim_id in requirement.get("critical_claims", []) if isinstance(requirement.get("critical_claims"), list) else []:
        if not any(item.get("claim_id") == claim_id for item in locked_evidence):
            issue(issues, "E_EVIDENCE", f"critical claim {claim_id} has no evidence in lock {lock_id}")

    conflicts = lock.get("conflicts", []) if isinstance(lock.get("conflicts"), list) else []
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            continue
        conflict_id = conflict.get("id", "<unknown>")
        if conflict.get("severity") == "critical" and conflict.get("status") != "resolved":
            issue(issues, "E_CONFLICT", f"critical conflict {conflict_id} is unresolved")
        for source_id in conflict.get("source_ids", []) if isinstance(conflict.get("source_ids"), list) else []:
            if source_id not in bindings:
                issue(issues, "E_REFERENCE", f"conflict {conflict_id} references unlocked source {source_id}")
        for evidence_id in conflict.get("evidence_ids", []) if isinstance(conflict.get("evidence_ids"), list) else []:
            if evidence_id not in evidence_ids:
                issue(issues, "E_REFERENCE", f"conflict {conflict_id} references evidence outside lock: {evidence_id}")

    budget = requirement.get("context_budget", {})
    if isinstance(budget, dict):
        if type(budget.get("max_sources")) is int and len(required_ids) > budget["max_sources"]:
            issue(issues, "E_REQUIRED_SOURCE_MISSING", f"context budget cannot include every required source for {requirement_id}")
        if type(budget.get("max_evidence_records")) is int and type(minimum) is int:
            if len(required_ids) * minimum > budget["max_evidence_records"]:
                issue(issues, "E_EVIDENCE", f"context budget cannot include minimum evidence for {requirement_id}")
    return issues


def collect_root(root: Path) -> tuple[dict[str, Any], list[Issue]]:
    issues: list[Issue] = []
    root = Path(os.path.abspath(os.fspath(root)))
    try:
        root = exact_knowledge_root(root)
    except KnowledgeError as exc:
        return {}, [Issue(exc.code, exc.message)]
    if not root.is_dir():
        return {}, [Issue("E_NOT_INITIALIZED", f"knowledge root does not exist: {root}")]
    for relative in REQUIRED_DIRS:
        directory = root / relative
        try:
            safe_directory = governed_directory(root, directory, f"required directory {relative}")
        except KnowledgeError as exc:
            issue(issues, exc.code, exc.message)
            continue
        if not safe_directory.is_dir():
            issue(issues, "E_NOT_INITIALIZED", f"missing required directory: {directory}")
    state_path = root / "registry" / "root.json"
    state: dict[str, Any] = {}
    try:
        safe_state_path = governed_file_path(root, state_path, root / "registry", "registry state")
    except KnowledgeError as exc:
        issue(issues, exc.code, exc.message)
        safe_state_path = None
    if safe_state_path is not None and not safe_state_path.is_file():
        issue(issues, "E_NOT_INITIALIZED", f"missing registry state: {state_path}")
    elif safe_state_path is not None:
        try:
            loaded = json.loads(safe_state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
                validate_state(state, str(state_path), issues)
            else:
                issue(issues, "E_SCHEMA", f"{state_path} must contain a JSON object")
        except json.JSONDecodeError as exc:
            issue(issues, "E_JSON", f"invalid JSON {state_path}: {exc}")
        except OSError as exc:
            issue(issues, "E_IO", f"cannot read {state_path}: {exc}")

    requirements = load_documents(root / "registry" / "requirements", "KnowledgeRequirement", issues, root=root)
    sources = load_documents(root / "sources", "SourceRecord", issues, root=root)
    evidence = load_documents(root / "evidence", "EvidenceRecord", issues, root=root)
    locks = load_documents(root / "locks", "SourceLock", issues, root=root)
    packets = load_documents(root / "packets", "KnowledgePacket", issues, root=root)
    journals = load_documents(root / "update-journal", "JournalRecord", issues, root=root)

    for evidence_id, item in evidence.items():
        if item.get("requirement_id") not in requirements:
            issue(issues, "E_REFERENCE", f"evidence {evidence_id} references missing requirement {item.get('requirement_id')}")
        if item.get("source_id") not in sources:
            issue(issues, "E_REFERENCE", f"evidence {evidence_id} references missing source {item.get('source_id')}")
    for lock in locks.values():
        issues.extend(semantic_lock_issues(lock, requirements, sources, evidence))
    for packet_id, packet in packets.items():
        lock_id = packet.get("lock_id")
        lock_path = root / "locks" / f"{lock_id}.json"
        if lock_id not in locks:
            issue(issues, "E_REFERENCE", f"packet {packet_id} references missing lock {lock_id}")
            continue
        try:
            safe_lock_path = governed_file_path(
                root, lock_path, root / "locks", f"packet {packet_id} lock"
            )
        except KnowledgeError as exc:
            issue(issues, exc.code, exc.message)
            continue
        if not safe_lock_path.is_file():
            issue(issues, "E_REFERENCE", f"packet {packet_id} lock file is missing: {lock_path}")
            continue

        lock_digest = file_digest(
            lock_path, root=root, parent=root / "locks", context=f"packet {packet_id} lock"
        )
        if packet.get("lock_digest") != lock_digest:
            issue(issues, "E_PIN", f"packet {packet_id} lock digest no longer matches {lock_id}")

        lock = locks[lock_id]
        requirement_id = lock.get("requirement_id")
        requirement = requirements.get(requirement_id)
        if requirement is None:
            issue(issues, "E_REFERENCE", f"packet {packet_id} cannot rebuild from missing requirement {requirement_id}")
            continue
        try:
            rebuilt = build_packet(
                packet_id,
                lock,
                lock_digest,
                requirement,
                sources,
                evidence,
                generated_at=packet.get("generated_at"),
            )
        except KnowledgeError as exc:
            issue(issues, exc.code, f"packet {packet_id} cannot be deterministically rebuilt: {exc.message}")
            continue
        except (KeyError, TypeError) as exc:
            # Schema/reference validation above reports the malformed upstream
            # object; this issue makes the packet-integrity consequence explicit.
            issue(issues, "E_REFERENCE", f"packet {packet_id} cannot be deterministically rebuilt: {exc}")
            continue
        if packet != rebuilt:
            missing = object()
            changed_fields = sorted(
                key
                for key in set(packet) | set(rebuilt)
                if packet.get(key, missing) != rebuilt.get(key, missing)
            )
            issue(
                issues,
                "E_PIN",
                f"packet {packet_id} differs from deterministic rebuild; changed fields: {changed_fields}",
            )

    for prefix in ("active", "previous"):
        lock_id = state.get(f"{prefix}_lock_id")
        digest = state.get(f"{prefix}_lock_digest")
        if lock_id is None:
            continue
        lock_path = root / "locks" / f"{lock_id}.json"
        try:
            safe_lock_path = governed_file_path(
                root, lock_path, root / "locks", f"registry {prefix} lock"
            )
        except KnowledgeError as exc:
            issue(issues, exc.code, exc.message)
            continue
        if lock_id not in locks or not safe_lock_path.is_file():
            issue(issues, "E_STATE", f"registry {prefix} lock is missing: {lock_id}")
        elif digest != file_digest(
            lock_path, root=root, parent=root / "locks", context=f"registry {prefix} lock"
        ):
            issue(issues, "E_PIN", f"registry {prefix} lock digest does not match immutable lock {lock_id}")

    return {
        "state": state,
        "requirements": requirements,
        "sources": sources,
        "evidence": evidence,
        "locks": locks,
        "packets": packets,
        "journals": journals,
    }, issues


def require_valid(root: Path) -> dict[str, Any]:
    data, issues = collect_root(root)
    if issues:
        for current in issues:
            print(f"ERROR {current.code}: {current.message}", file=sys.stderr)
        raise KnowledgeError("E_VALIDATION", f"root has {len(issues)} validation error(s): {root}")
    return data


def resolve_lock(root: Path, raw: str) -> Path:
    if ID_RE.fullmatch(raw):
        path = root / "locks" / f"{raw}.json"
    else:
        candidate = Path(raw)
        if not candidate.is_absolute():
            raise KnowledgeError("E_REFERENCE", f"--lock must be a lock id or absolute path: {raw}")
        path = Path(os.path.abspath(os.fspath(candidate)))
    locks_root = root / "locks"
    if path.parent != locks_root or path.suffix.lower() != ".json":
        raise KnowledgeError("E_REFERENCE", f"lock must be a direct JSON child of {locks_root}: {path}")
    safe_path = governed_file_path(root, path, locks_root, "lock document")
    if not safe_path.is_file():
        raise KnowledgeError("E_REFERENCE", f"lock does not exist: {path}")
    return path


def cmd_init(args: argparse.Namespace) -> int:
    if not args.yes:
        raise KnowledgeError("E_CONFIRMATION", "init requires --yes for the exact --root path")
    root = exact_knowledge_root(explicit_absolute_path(args.root, "--root"))
    if root.exists():
        if not root.is_dir():
            raise KnowledgeError("E_ROOT", f"root exists and is not a directory: {root}")
        if (root / "registry" / "root.json").exists():
            raise KnowledgeError("E_ALREADY_INITIALIZED", f"knowledge root is already initialized: {root}")
        try:
            if any(root.iterdir()):
                raise KnowledgeError("E_ROOT", f"refusing to initialize non-empty unrecognized directory: {root}")
        except OSError as exc:
            raise KnowledgeError("E_IO", f"cannot inspect root {root}: {exc}") from exc
    try:
        root.mkdir(parents=True, exist_ok=True)
        for relative in REQUIRED_DIRS:
            (root / relative).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise KnowledgeError("E_IO", f"cannot create knowledge root {root}: {exc}") from exc
    for relative in REQUIRED_DIRS:
        governed_directory(root, root / relative, f"initialized directory {relative}")
    timestamp = now_utc()
    registry_id = re.sub(r"[^a-z0-9._-]+", "-", root.name.lower()).strip("-.") or "knowledge-registry"
    state = {
        "record_type": "RegistryState",
        "schema_version": SCHEMA_VERSION,
        "registry_id": registry_id[:128],
        "created_at": timestamp,
        "updated_at": timestamp,
        "active_lock_id": None,
        "active_lock_digest": None,
        "previous_lock_id": None,
        "previous_lock_digest": None,
    }
    transactional_write(root, "init", root / "registry" / "root.json", None, state, exclusive=True)
    print(f"INITIALIZED root={root} active_lock_id=null governance_complete=false")
    return 0


def github_get(url: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "xbskill-knowledge-manager/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise KnowledgeError("E_NETWORK", f"GitHub metadata request failed for {url}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeError("E_GITHUB_METADATA", f"GitHub returned invalid JSON for {url}: {exc}") from exc
    if not isinstance(value, dict):
        raise KnowledgeError("E_GITHUB_METADATA", f"GitHub response is not an object for {url}")
    return value


def cmd_probe_github(args: argparse.Namespace) -> int:
    repository = args.repository
    if not REPO_RE.fullmatch(repository):
        raise KnowledgeError("E_USAGE", f"repository must be owner/repo: {repository}")
    owner, repo = repository.split("/", 1)
    base = f"https://api.github.com/repos/{owner}/{repo}"
    metadata = github_get(base)
    required = ("full_name", "html_url", "stargazers_count", "archived", "default_branch")
    missing = [name for name in required if name not in metadata]
    if missing:
        raise KnowledgeError("E_GITHUB_METADATA", f"GitHub repository metadata missing fields: {missing}")
    default_branch = metadata["default_branch"]
    if not isinstance(default_branch, str) or not default_branch:
        raise KnowledgeError("E_GITHUB_METADATA", "GitHub default_branch is empty")
    commit = github_get(f"{base}/commits/{default_branch}")
    head = commit.get("sha")
    if not isinstance(head, str) or not COMMIT_RE.fullmatch(head):
        raise KnowledgeError("E_GITHUB_METADATA", "GitHub HEAD commit is missing or invalid")
    stars = metadata["stargazers_count"]
    archived = metadata["archived"]
    if type(stars) is not int or stars < 0 or type(archived) is not bool:
        raise KnowledgeError("E_GITHUB_METADATA", "GitHub stars or archived field has an invalid type")
    license_value = metadata.get("license")
    spdx = license_value.get("spdx_id") if isinstance(license_value, dict) else None
    if spdx in {"NOASSERTION", "OTHER", ""}:
        spdx = None
    captured = now_utc()
    source_id = re.sub(r"[^a-z0-9._-]+", "-", f"github-{owner}-{repo}".lower()).strip("-.")[:128]
    record = {
        "record_type": "SourceRecord",
        "schema_version": SCHEMA_VERSION,
        "id": source_id,
        "source_type": "github",
        "title": str(metadata["full_name"]),
        "locator": str(metadata["html_url"]),
        "discovered_at": captured,
        "permissions": {"discover": True, "read": False, "execute": False},
        "license": {
            "status": "unknown",
            "identifier": spdx,
            "usage_notes": "GitHub metadata only; compatibility and intended use have not been reviewed.",
        },
        "security": {
            "status": "unreviewed",
            "reviewed_at": None,
            "reviewed_by": None,
            "notes": "Metadata probe did not download or execute repository content.",
        },
        "pin": {
            "kind": "git_commit",
            "value": head,
            "captured_at": captured,
            "verification_method": "github_rest_api_head_metadata",
        },
        "content_trust": "untrusted_data",
        "status": "candidate",
        "discovery_metadata": {
            "kind": "github",
            "stars": stars,
            "captured_at": captured,
            "stars_use": "discovery_only",
            "license_spdx": spdx,
            "archived": archived,
            "default_branch": default_branch,
            "head_commit": head,
        },
        "notes": "Candidate metadata only. Read, license, security and authority gates remain closed.",
    }
    probe_issues: list[Issue] = []
    validate_source(record, "probe-github output", probe_issues)
    if probe_issues:
        raise KnowledgeError("E_GITHUB_METADATA", "; ".join(item.message for item in probe_issues))
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = explicit_absolute_path(args.root, "--root")
    data, issues = collect_root(root)
    if issues:
        for current in issues:
            print(f"ERROR {current.code}: {current.message}", file=sys.stderr)
        print(f"ERROR E_VALIDATION: root has {len(issues)} validation error(s): {root}", file=sys.stderr)
        return ERROR_CODES["E_VALIDATION"]
    state = data["state"]
    candidate_count = sum(1 for value in data["sources"].values() if value.get("status") == "candidate")
    print(
        "VALID "
        f"root={root} requirements={len(data['requirements'])} sources={len(data['sources'])} "
        f"locks={len(data['locks'])} evidence={len(data['evidence'])} packets={len(data['packets'])} "
        f"candidate_sources={candidate_count} active_lock_id={state.get('active_lock_id')} "
        f"governance_complete=false"
    )
    return 0


def build_packet(
    packet_id: str,
    lock: dict[str, Any],
    lock_digest: str,
    requirement: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    budget = requirement["context_budget"]
    bindings = {item["source_id"]: item for item in lock["source_pins"]}
    evidence_order = [evidence[evidence_id] for evidence_id in lock["evidence_ids"]]
    selected_ids: list[str] = []

    def select(evidence_id: str) -> None:
        if evidence_id not in selected_ids:
            selected_ids.append(evidence_id)

    minimum = budget["minimum_evidence_per_required_source"]
    for source_id in requirement["required_source_ids"]:
        matching = [item["id"] for item in evidence_order if item["source_id"] == source_id]
        for evidence_id in matching[:minimum]:
            select(evidence_id)
    for claim_id in requirement["critical_claims"]:
        matching = [item["id"] for item in evidence_order if item["claim_id"] == claim_id]
        if not matching:
            raise KnowledgeError("E_EVIDENCE", f"critical claim lacks evidence: {claim_id}")
        select(matching[0])
    if len(selected_ids) > budget["max_evidence_records"]:
        raise KnowledgeError("E_EVIDENCE", "minimum evidence and critical claims exceed context budget")

    required_source_set = set(requirement["required_source_ids"])
    mandatory_source_set = required_source_set | {evidence[item_id]["source_id"] for item_id in selected_ids}
    if len(mandatory_source_set) > budget["max_sources"]:
        raise KnowledgeError("E_REQUIRED_SOURCE_MISSING", "required evidence sources exceed context source budget")
    selected_source_ids = [item["source_id"] for item in lock["source_pins"] if item["source_id"] in mandatory_source_set]

    for item in evidence_order:
        if len(selected_ids) >= budget["max_evidence_records"]:
            break
        source_id = item["source_id"]
        if source_id not in selected_source_ids:
            if len(selected_source_ids) >= budget["max_sources"]:
                continue
            selected_source_ids.append(source_id)
        select(item["id"])

    omitted_evidence = [item["id"] for item in evidence_order if item["id"] not in selected_ids]
    omitted_sources = [item["source_id"] for item in lock["source_pins"] if item["source_id"] not in selected_source_ids]
    selected_evidence: list[dict[str, Any]] = []
    omitted_excerpts: list[str] = []
    excerpt_chars = 0
    for evidence_id in selected_ids:
        item = copy.deepcopy(evidence[evidence_id])
        excerpt = item.get("excerpt")
        if isinstance(excerpt, str):
            if excerpt_chars + len(excerpt) <= budget["max_excerpt_chars"]:
                excerpt_chars += len(excerpt)
            else:
                item.pop("excerpt", None)
                omitted_excerpts.append(evidence_id)
        selected_evidence.append(item)

    packet_sources = []
    for source_id in selected_source_ids:
        source = sources[source_id]
        packet_sources.append({
            "source_id": source_id,
            "source_type": source["source_type"],
            "title": source["title"],
            "locator": source["locator"],
            "pin": copy.deepcopy(bindings[source_id]["pin"]),
            "license": copy.deepcopy(source["license"]),
            "content_trust": source["content_trust"],
        })
    packet = {
        "record_type": "KnowledgePacket",
        "schema_version": SCHEMA_VERSION,
        "id": packet_id,
        "requirement_id": requirement["id"],
        "lock_id": lock["id"],
        "lock_digest": lock_digest,
        "generated_at": now_utc() if generated_at is None else generated_at,
        "purpose": requirement["purpose"],
        "question": requirement["question"],
        "authority_decision": copy.deepcopy(lock["authority_decision"]),
        "sources": packet_sources,
        "evidence": selected_evidence,
        "conflicts": copy.deepcopy(lock["conflicts"]),
        "selection": {
            "context_budget": copy.deepcopy(budget),
            "included_source_ids": selected_source_ids,
            "omitted_source_ids": omitted_sources,
            "included_evidence_ids": selected_ids,
            "omitted_evidence_ids": omitted_evidence,
            "omitted_excerpt_ids": omitted_excerpts,
            "rationale": "Required-source coverage and critical claims first; remaining evidence follows lock order within the explicit context budget.",
        },
        "model_prior_fallback": False,
        "external_content_policy": "untrusted_data_no_execute",
        "execution_authorized": False,
    }
    packet_issues: list[Issue] = []
    validate_packet(packet, f"generated packet {packet_id}", packet_issues)
    if packet_issues:
        raise KnowledgeError("E_SCHEMA", "; ".join(item.message for item in packet_issues))
    return packet


def cmd_packet(args: argparse.Namespace) -> int:
    root = explicit_absolute_path(args.root, "--root")
    output = explicit_absolute_path(args.output, "--output")
    packets_root = root / "packets"
    if output.parent != packets_root or output.suffix.lower() != ".json" or not ID_RE.fullmatch(output.stem):
        raise KnowledgeError("E_OUTPUT", f"output must be a direct <id>.json child of {packets_root}: {output}")
    safe_output = governed_file_path(root, output, packets_root, "packet output")
    if safe_output.exists():
        raise KnowledgeError("E_OUTPUT", f"refusing to overwrite existing packet: {output}")
    data = require_valid(root)
    lock_path = resolve_lock(root, args.lock)
    lock = read_json(
        lock_path, root=root, parent=root / "locks", context=f"lock document {lock_path.name}"
    )
    lock_id = lock.get("id")
    if lock_id not in data["locks"]:
        raise KnowledgeError("E_REFERENCE", f"lock is not registered under its id: {lock_path}")
    semantic = semantic_lock_issues(lock, data["requirements"], data["sources"], data["evidence"])
    if semantic:
        for current in semantic:
            print(f"ERROR {current.code}: {current.message}", file=sys.stderr)
        raise KnowledgeError("E_VALIDATION", f"lock {lock_id} is not packet-eligible")
    requirement = data["requirements"][lock["requirement_id"]]
    packet = build_packet(
        output.stem,
        lock,
        file_digest(lock_path, root=root, parent=root / "locks", context=f"lock {lock_id}"),
        requirement,
        data["sources"],
        data["evidence"],
    )
    transactional_write(root, "packet", output, None, packet, exclusive=True)
    print(f"PACKET_CREATED path={output} lock={lock_id} model_prior_fallback=false execution_authorized=false")
    return 0


def cmd_activate(args: argparse.Namespace) -> int:
    if not args.yes:
        raise KnowledgeError("E_CONFIRMATION", "activate requires --yes for the exact root and lock")
    root = explicit_absolute_path(args.root, "--root")
    data = require_valid(root)
    lock_path = resolve_lock(root, args.lock)
    lock = read_json(
        lock_path, root=root, parent=root / "locks", context=f"lock document {lock_path.name}"
    )
    lock_id = lock.get("id")
    if lock_id not in data["locks"]:
        raise KnowledgeError("E_REFERENCE", f"lock is not registered under its id: {lock_path}")
    semantic = semantic_lock_issues(lock, data["requirements"], data["sources"], data["evidence"])
    if semantic:
        for current in semantic:
            print(f"ERROR {current.code}: {current.message}", file=sys.stderr)
        raise KnowledgeError("E_VALIDATION", f"lock {lock_id} is not activation-eligible")
    state = data["state"]
    digest = file_digest(lock_path, root=root, parent=root / "locks", context=f"lock {lock_id}")
    if state.get("active_lock_id") == lock_id and state.get("active_lock_digest") == digest:
        print(f"ACTIVE_UNCHANGED root={root} lock={lock_id}")
        return 0
    updated = copy.deepcopy(state)
    updated["previous_lock_id"] = state.get("active_lock_id")
    updated["previous_lock_digest"] = state.get("active_lock_digest")
    updated["active_lock_id"] = lock_id
    updated["active_lock_digest"] = digest
    updated["updated_at"] = now_utc()
    transactional_write(root, "activate", root / "registry" / "root.json", state, updated)
    print(f"ACTIVATED root={root} lock={lock_id} previous={updated['previous_lock_id']}")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    if not args.yes:
        raise KnowledgeError("E_CONFIRMATION", "rollback requires --yes for the exact root")
    root = explicit_absolute_path(args.root, "--root")
    data = require_valid(root)
    state = data["state"]
    previous_id = state.get("previous_lock_id")
    previous_digest = state.get("previous_lock_digest")
    if previous_id is None or previous_digest is None:
        raise KnowledgeError("E_NO_ROLLBACK", f"registry has no previous lock: {root}")
    previous_path = root / "locks" / f"{previous_id}.json"
    safe_previous_path = governed_file_path(
        root, previous_path, root / "locks", f"previous lock {previous_id}"
    )
    if not safe_previous_path.is_file() or file_digest(
        previous_path, root=root, parent=root / "locks", context=f"previous lock {previous_id}"
    ) != previous_digest:
        raise KnowledgeError("E_PIN", f"previous lock is missing or changed: {previous_id}")
    previous_lock = data["locks"].get(previous_id)
    if previous_lock is None:
        raise KnowledgeError("E_REFERENCE", f"previous lock is not registered: {previous_id}")
    semantic = semantic_lock_issues(previous_lock, data["requirements"], data["sources"], data["evidence"])
    if semantic:
        for current in semantic:
            print(f"ERROR {current.code}: {current.message}", file=sys.stderr)
        raise KnowledgeError("E_VALIDATION", f"previous lock {previous_id} is no longer rollback-eligible")
    updated = copy.deepcopy(state)
    updated["active_lock_id"] = previous_id
    updated["active_lock_digest"] = previous_digest
    updated["previous_lock_id"] = state.get("active_lock_id")
    updated["previous_lock_digest"] = state.get("active_lock_digest")
    updated["updated_at"] = now_utc()
    transactional_write(root, "rollback", root / "registry" / "root.json", state, updated)
    print(f"ROLLED_BACK root={root} active={previous_id} previous={updated['previous_lock_id']}")
    return 0


def build_parser() -> Parser:
    parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=Parser)

    init_parser = subparsers.add_parser("init", help="initialize an explicit empty knowledge root")
    init_parser.add_argument("--root", required=True, help="absolute knowledge root path")
    init_parser.add_argument("--yes", action="store_true", help="confirm the exact root path")
    init_parser.set_defaults(func=cmd_init)

    probe_parser = subparsers.add_parser("probe-github", help="read GitHub repository metadata only")
    probe_parser.add_argument("repository", help="owner/repo")
    probe_parser.set_defaults(func=cmd_probe_github)

    validate_parser = subparsers.add_parser("validate", help="validate structure, references and every lock")
    validate_parser.add_argument("--root", required=True, help="absolute knowledge root path")
    validate_parser.set_defaults(func=cmd_validate)

    packet_parser = subparsers.add_parser("packet", help="create a minimal packet from an eligible lock")
    packet_parser.add_argument("--root", required=True, help="absolute knowledge root path")
    packet_parser.add_argument("--lock", required=True, help="lock id or absolute lock JSON path")
    packet_parser.add_argument("--output", required=True, help="absolute output path directly under <root>/packets")
    packet_parser.set_defaults(func=cmd_packet)

    activate_parser = subparsers.add_parser("activate", help="strictly validate and activate a lock")
    activate_parser.add_argument("--root", required=True, help="absolute knowledge root path")
    activate_parser.add_argument("--lock", required=True, help="lock id or absolute lock JSON path")
    activate_parser.add_argument("--yes", action="store_true", help="confirm the exact root and lock")
    activate_parser.set_defaults(func=cmd_activate)

    rollback_parser = subparsers.add_parser("rollback", help="restore the previous eligible lock")
    rollback_parser.add_argument("--root", required=True, help="absolute knowledge root path")
    rollback_parser.add_argument("--yes", action="store_true", help="confirm the exact root")
    rollback_parser.set_defaults(func=cmd_rollback)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except KnowledgeError as exc:
        print(f"ERROR {exc.code}: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("ERROR E_STATE: interrupted; inspect update-journal for a prepared transaction", file=sys.stderr)
        return ERROR_CODES["E_STATE"]
    except OSError as exc:
        print(f"ERROR E_IO: unexpected filesystem error: {exc}", file=sys.stderr)
        return ERROR_CODES["E_IO"]


if __name__ == "__main__":
    raise SystemExit(main())
