#!/usr/bin/env python3
"""Validate and refresh pinned upstream role-knowledge candidates.

Only the Python standard library is used. GitHub repository content is always
treated as untrusted text: this program never imports, installs, evaluates, or
executes anything obtained from an upstream repository. Candidate text is only
written below an explicit new directory outside this skill.
"""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"
SCRIPT_PATH = Path(__file__).resolve()
SKILL_ROOT = SCRIPT_PATH.parent.parent.resolve()
DEFAULT_REGISTRY = SKILL_ROOT / "references" / "upstream-role-sources.json"
SCHEMA_PATH = SKILL_ROOT / "references" / "upstream-role-sources.schema.json"
ACTIVE_CATALOG = SKILL_ROOT / "references" / "builtin-role-knowledge.json"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")
SOURCE_ID_RE = re.compile(r"^upstream-[a-z0-9][a-z0-9-]{2,63}$")
UNIT_ID_RE = re.compile(r"^rk-[a-z0-9][a-z0-9-]{2,95}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA1_RE = re.compile(r"^[a-f0-9]{40}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_RELATIVE_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

TOP_FIELDS = {
    "record_type", "schema_version", "registry_id", "registry_version", "captured_at",
    "active_registry_protection", "policies", "sources",
}
PROTECTION_FIELDS = {
    "protected_relative_paths", "candidate_output_policy", "overwrite_allowed",
    "active_registry_mutation_allowed",
}
POLICY_FIELDS = {
    "api_base", "api_version", "external_content_policy", "execute_source_content",
    "stars_usage", "stars_evidence_weight", "network_failure", "unexpected_404",
    "max_text_bytes", "accepted_text_extensions", "candidate_manifest_filename",
    "candidate_text_root",
}
SOURCE_FIELDS = {
    "id", "repository", "availability", "expected_http_status", "intended_use",
    "affected_scope", "affected_units", "required_gates", "license", "allowlist", "notes",
}
REPOSITORY_FIELDS = {
    "owner", "name", "full_name", "api_url", "pinned_commit", "expected_default_branch",
    "expected_archived",
}
LICENSE_FIELDS = {
    "declared_id", "github_api_spdx_id", "file_path", "baseline_git_blob_sha",
    "baseline_sha256", "use_policy",
}
ALLOWLIST_FIELDS = {"path", "content_use", "baseline_git_blob_sha", "coordinates"}
COORDINATE_FIELDS = {"id", "start_line", "end_line", "disposition", "coordinate", "note"}

GATES = {
    "availability_recheck", "immutable_pin_review", "license_review", "security_review",
    "allowlist_review", "untrusted_text_review", "evidence_coordinate_review",
    "claim_conflict_review", "candidate_unit_rewrite", "deterministic_test", "blind_answer",
    "independent_review", "activation_diff_review", "discovery_scope_review", "reality_feedback",
}
ACTIVATION_GATES = {
    "immutable_pin_review", "license_review", "security_review", "untrusted_text_review",
    "evidence_coordinate_review", "claim_conflict_review", "candidate_unit_rewrite",
    "deterministic_test", "blind_answer", "independent_review", "activation_diff_review",
    "reality_feedback",
}
REQUIRED_SOURCE_IDS = {
    "upstream-ui-ux-pro-max",
    "upstream-financial-services",
    "upstream-marketing-skills",
    "upstream-pm-claude-skills",
    "upstream-product-manager-skills-dean",
    "upstream-awesome-agent-skills",
    "upstream-k-dense-admin-skills",
}

ERROR_CODES = {
    "E_USAGE": 2,
    "E_CONFIRMATION": 3,
    "E_IO": 13,
    "E_JSON": 20,
    "E_SCHEMA": 21,
    "E_SOURCE_COORDINATE": 22,
    "E_LICENSE": 32,
    "E_SECURITY": 33,
    "E_PIN": 34,
    "E_NETWORK": 40,
    "E_GITHUB_METADATA": 41,
    "E_OUTPUT": 50,
    "E_VALIDATION": 60,
    "E_STATE": 52,
}


class UpstreamError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = ERROR_CODES.get(code, 1)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UpstreamError("E_USAGE", message)


class DuplicateKeyError(ValueError):
    pass


@dataclass(frozen=True)
class ApiResult:
    status: int
    data: Any | None


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha(value: bytes) -> str:
    header = f"blob {len(value)}\0".encode("ascii")
    return hashlib.sha1(header + value).hexdigest()  # noqa: S324 - Git's object format requires SHA-1.


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UpstreamError("E_IO", f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
    except (json.JSONDecodeError, DuplicateKeyError) as exc:
        raise UpstreamError("E_JSON", f"cannot parse {path}: {exc}") from exc


def is_exact_int(value: Any) -> bool:
    return type(value) is int


def is_safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not SAFE_RELATIVE_RE.fullmatch(value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def exact_fields(value: Any, fields: set[str], context: str, issues: list[str]) -> bool:
    if not isinstance(value, dict):
        issues.append(f"{context} must be an object")
        return False
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        issues.append(f"{context} fields mismatch; missing={missing} extra={extra}")
        return False
    return True


def valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        return False
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def expected_coordinate(source: dict[str, Any], entry: dict[str, Any], coordinate: dict[str, Any]) -> str:
    repo = source["repository"]
    return (
        f"{repo['full_name']}@{repo['pinned_commit']}:{entry['path']}"
        f"#L{coordinate['start_line']}-L{coordinate['end_line']}"
    )


def validate_schema_document(schema: Any) -> list[str]:
    issues: list[str] = []
    if not isinstance(schema, dict):
        return ["schema document must be an object"]
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        issues.append("schema must declare JSON Schema draft 2020-12")
    if schema.get("$id") != "https://xbskill.local/schemas/role-knowledge-upstream-sources-v1.json":
        issues.append("schema $id is unexpected")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        issues.append("schema root must be a closed object")
    record_type = ((schema.get("properties") or {}).get("record_type") or {}).get("const")
    if record_type != "RoleKnowledgeUpstreamSourceRegistry":
        issues.append("schema record_type constant is unexpected")
    if not isinstance(schema.get("$defs"), dict):
        issues.append("schema must contain $defs")
    return issues


def validate_registry(registry: Any, known_unit_ids: set[str] | None = None) -> list[str]:
    issues: list[str] = []
    if not exact_fields(registry, TOP_FIELDS, "registry", issues):
        return issues
    if registry["record_type"] != "RoleKnowledgeUpstreamSourceRegistry":
        issues.append("registry.record_type is invalid")
    if not is_exact_int(registry["schema_version"]) or registry["schema_version"] != SCHEMA_VERSION:
        issues.append("registry.schema_version must be JSON integer 1")
    if not isinstance(registry["registry_id"], str) or not ID_RE.fullmatch(registry["registry_id"]):
        issues.append("registry.registry_id is invalid")
    if not isinstance(registry["registry_version"], str) or not VERSION_RE.fullmatch(registry["registry_version"]):
        issues.append("registry.registry_version is invalid")
    if not valid_timestamp(registry["captured_at"]):
        issues.append("registry.captured_at must be a valid UTC second timestamp")

    protection = registry["active_registry_protection"]
    if exact_fields(protection, PROTECTION_FIELDS, "active_registry_protection", issues):
        paths = protection["protected_relative_paths"]
        if not isinstance(paths, list) or not paths or len(set(map(str, paths))) != len(paths):
            issues.append("active_registry_protection.protected_relative_paths must be a non-empty unique array")
        elif any(not is_safe_relative_path(path) for path in paths):
            issues.append("active registry protected paths must be safe relative paths")
        elif "references/builtin-source-registry.json" not in paths:
            issues.append("builtin-source-registry.json must be explicitly protected")
        if protection["candidate_output_policy"] != "absolute_nonexistent_directory_outside_skill":
            issues.append("candidate output policy is unsafe")
        if protection["overwrite_allowed"] is not False:
            issues.append("candidate overwrite must remain false")
        if protection["active_registry_mutation_allowed"] is not False:
            issues.append("active registry mutation must remain false")

    policies = registry["policies"]
    accepted_extensions: set[str] = set()
    if exact_fields(policies, POLICY_FIELDS, "policies", issues):
        constants = {
            "api_base": API_BASE,
            "api_version": API_VERSION,
            "external_content_policy": "untrusted_data_no_execute",
            "execute_source_content": False,
            "stars_usage": "discovery_only",
            "stars_evidence_weight": "none",
            "network_failure": "fail_closed",
            "unexpected_404": "fail_closed",
            "candidate_manifest_filename": "candidate-manifest.json",
            "candidate_text_root": "texts",
        }
        for key, expected in constants.items():
            if policies[key] != expected or (isinstance(expected, bool) and policies[key] is not expected):
                issues.append(f"policies.{key} must equal {expected!r}")
        max_bytes = policies["max_text_bytes"]
        if not is_exact_int(max_bytes) or not 1 <= max_bytes <= 1048576:
            issues.append("policies.max_text_bytes must be integer 1..1048576")
        extensions = policies["accepted_text_extensions"]
        if (
            not isinstance(extensions, list) or not extensions
            or any(ext not in {".md", ".csv", ".txt"} for ext in extensions)
            or len(set(extensions)) != len(extensions)
        ):
            issues.append("policies.accepted_text_extensions is invalid")
        else:
            accepted_extensions = set(extensions)

    sources = registry["sources"]
    if not isinstance(sources, list) or not sources:
        issues.append("registry.sources must be a non-empty array")
        return issues
    seen_source_ids: set[str] = set()
    seen_repositories: set[str] = set()
    seen_coordinate_ids: set[str] = set()
    for source_index, source in enumerate(sources):
        context = f"sources[{source_index}]"
        if not exact_fields(source, SOURCE_FIELDS, context, issues):
            continue
        source_id = source["id"]
        if not isinstance(source_id, str) or not SOURCE_ID_RE.fullmatch(source_id):
            issues.append(f"{context}.id is invalid")
        elif source_id in seen_source_ids:
            issues.append(f"duplicate source id: {source_id}")
        else:
            seen_source_ids.add(source_id)

        repo = source["repository"]
        repo_valid = exact_fields(repo, REPOSITORY_FIELDS, f"{context}.repository", issues)
        if repo_valid:
            owner, name = repo["owner"], repo["name"]
            full_name = f"{owner}/{name}"
            if repo["full_name"] != full_name:
                issues.append(f"{context}.repository.full_name must equal owner/name")
            if repo["api_url"] != f"{API_BASE}/repos/{full_name}":
                issues.append(f"{context}.repository.api_url is not the official GitHub API URL")
            if full_name.lower() in seen_repositories:
                issues.append(f"duplicate repository: {full_name}")
            seen_repositories.add(full_name.lower())

        availability = source["availability"]
        intended_use = source["intended_use"]
        if availability not in {"available", "expected_unavailable"}:
            issues.append(f"{context}.availability is invalid")
        if intended_use not in {"internalization_candidate", "discovery_only", "unavailable"}:
            issues.append(f"{context}.intended_use is invalid")
        affected_scope = source["affected_scope"]
        if affected_scope not in {"role_units", "discovery_index_only", "unavailable_gap"}:
            issues.append(f"{context}.affected_scope is invalid")
        affected_units = source["affected_units"]
        if (
            not isinstance(affected_units, list)
            or any(not isinstance(unit, str) or not UNIT_ID_RE.fullmatch(unit) for unit in affected_units)
            or len(set(affected_units)) != len(affected_units)
        ):
            issues.append(f"{context}.affected_units must be unique rk-* ids")
        elif known_unit_ids is not None:
            unknown_units = sorted(set(affected_units) - known_unit_ids)
            if unknown_units:
                issues.append(
                    f"{context}.affected_units reference unknown active role units: {unknown_units}"
                )

        required_gates = source["required_gates"]
        if (
            not isinstance(required_gates, list) or not required_gates
            or any(gate not in GATES for gate in required_gates)
            or len(set(required_gates)) != len(required_gates)
        ):
            issues.append(f"{context}.required_gates is invalid")
            gates_set: set[str] = set()
        else:
            gates_set = set(required_gates)

        license_record = source["license"]
        allowlist = source["allowlist"]
        if availability == "expected_unavailable":
            if source["expected_http_status"] != 404:
                issues.append(f"{context}.expected_http_status must be 404")
            if intended_use != "unavailable" or affected_scope != "unavailable_gap":
                issues.append(f"{context} unavailable source has inconsistent use/scope")
            if repo_valid and any(repo[key] is not None for key in ("pinned_commit", "expected_default_branch", "expected_archived")):
                issues.append(f"{context} unavailable repository must not invent pin/branch/archive facts")
            if license_record is not None or allowlist != []:
                issues.append(f"{context} unavailable source must have null license and empty allowlist")
            if "availability_recheck" not in gates_set:
                issues.append(f"{context} unavailable source must require availability_recheck")
        else:
            if source["expected_http_status"] != 200:
                issues.append(f"{context}.expected_http_status must be 200")
            if intended_use == "unavailable" or affected_scope == "unavailable_gap":
                issues.append(f"{context} available source has inconsistent use/scope")
            if repo_valid:
                if not isinstance(repo["pinned_commit"], str) or not SHA1_RE.fullmatch(repo["pinned_commit"]):
                    issues.append(f"{context}.repository.pinned_commit must be a 40-character SHA")
                if not isinstance(repo["expected_default_branch"], str) or not repo["expected_default_branch"]:
                    issues.append(f"{context}.repository.expected_default_branch is invalid")
                if type(repo["expected_archived"]) is not bool:
                    issues.append(f"{context}.repository.expected_archived must be boolean")
            if not isinstance(allowlist, list) or not allowlist:
                issues.append(f"{context}.allowlist must be non-empty")

        if license_record is not None:
            if exact_fields(license_record, LICENSE_FIELDS, f"{context}.license", issues):
                if license_record["declared_id"] not in {"MIT", "Apache-2.0", "CC-BY-NC-SA-4.0"}:
                    issues.append(f"{context}.license.declared_id is invalid")
                if license_record["github_api_spdx_id"] not in {"MIT", "Apache-2.0", "CC-BY-NC-SA-4.0", "NOASSERTION"}:
                    issues.append(f"{context}.license.github_api_spdx_id is invalid")
                if not is_safe_relative_path(license_record["file_path"]):
                    issues.append(f"{context}.license.file_path is unsafe")
                if not isinstance(license_record["baseline_git_blob_sha"], str) or not SHA1_RE.fullmatch(license_record["baseline_git_blob_sha"]):
                    issues.append(f"{context}.license.baseline_git_blob_sha is invalid")
                if not isinstance(license_record["baseline_sha256"], str) or not SHA256_RE.fullmatch(license_record["baseline_sha256"]):
                    issues.append(f"{context}.license.baseline_sha256 is invalid")
                if license_record["use_policy"] != intended_use:
                    issues.append(f"{context}.license.use_policy must match intended_use")

        if isinstance(allowlist, list):
            seen_paths: set[str] = set()
            for entry_index, entry in enumerate(allowlist):
                entry_context = f"{context}.allowlist[{entry_index}]"
                if not exact_fields(entry, ALLOWLIST_FIELDS, entry_context, issues):
                    continue
                path = entry["path"]
                if not is_safe_relative_path(path):
                    issues.append(f"{entry_context}.path is unsafe")
                elif PurePosixPath(path).suffix.lower() not in accepted_extensions:
                    issues.append(f"{entry_context}.path is not an accepted text extension")
                if path in seen_paths:
                    issues.append(f"{context} duplicate allowlisted path: {path}")
                seen_paths.add(path)
                if not isinstance(entry["baseline_git_blob_sha"], str) or not SHA1_RE.fullmatch(entry["baseline_git_blob_sha"]):
                    issues.append(f"{entry_context}.baseline_git_blob_sha is invalid")
                content_use = entry["content_use"]
                if content_use not in {"candidate_evidence", "discovery_only"}:
                    issues.append(f"{entry_context}.content_use is invalid")
                if intended_use == "discovery_only" and content_use != "discovery_only":
                    issues.append(f"{entry_context} cannot exceed discovery-only source use")
                coordinates = entry["coordinates"]
                if not isinstance(coordinates, list):
                    issues.append(f"{entry_context}.coordinates must be an array")
                    continue
                candidate_coordinates = 0
                for coordinate_index, coordinate in enumerate(coordinates):
                    coordinate_context = f"{entry_context}.coordinates[{coordinate_index}]"
                    if not exact_fields(coordinate, COORDINATE_FIELDS, coordinate_context, issues):
                        continue
                    coordinate_id = coordinate["id"]
                    if not isinstance(coordinate_id, str) or not ID_RE.fullmatch(coordinate_id):
                        issues.append(f"{coordinate_context}.id is invalid")
                    elif coordinate_id in seen_coordinate_ids:
                        issues.append(f"duplicate coordinate id: {coordinate_id}")
                    else:
                        seen_coordinate_ids.add(coordinate_id)
                    start, end = coordinate["start_line"], coordinate["end_line"]
                    if not is_exact_int(start) or not is_exact_int(end) or start < 1 or end < start:
                        issues.append(f"{coordinate_context} line range is invalid")
                    disposition = coordinate["disposition"]
                    if disposition not in {"candidate_evidence", "discovery_only", "excluded"}:
                        issues.append(f"{coordinate_context}.disposition is invalid")
                    if disposition == "candidate_evidence":
                        candidate_coordinates += 1
                    if content_use == "discovery_only" and disposition == "candidate_evidence":
                        issues.append(f"{coordinate_context} cannot promote discovery-only text")
                    if repo_valid and availability == "available" and coordinate.get("coordinate") != expected_coordinate(source, entry, coordinate):
                        issues.append(f"{coordinate_context}.coordinate does not bind exact repo/commit/path/lines")
                    if not isinstance(coordinate["note"], str) or not coordinate["note"].strip():
                        issues.append(f"{coordinate_context}.note is empty")
                if content_use == "candidate_evidence" and candidate_coordinates == 0:
                    issues.append(f"{entry_context} candidate evidence file has no candidate coordinate")

        notes = source["notes"]
        if not isinstance(notes, list) or not notes or any(not isinstance(note, str) or not note.strip() for note in notes):
            issues.append(f"{context}.notes must be a non-empty string array")
        if intended_use == "internalization_candidate" and not ACTIVATION_GATES.issubset(gates_set):
            issues.append(f"{context} internalization candidate is missing activation gates")
        if intended_use == "discovery_only" and "discovery_scope_review" not in gates_set:
            issues.append(f"{context} discovery-only source must require discovery_scope_review")

    if seen_source_ids != REQUIRED_SOURCE_IDS:
        issues.append(
            "registry must contain the exact v1 source set; "
            f"missing={sorted(REQUIRED_SOURCE_IDS - seen_source_ids)} extra={sorted(seen_source_ids - REQUIRED_SOURCE_IDS)}"
        )
    source_by_id = {source.get("id"): source for source in sources if isinstance(source, dict)}
    dean = source_by_id.get("upstream-product-manager-skills-dean", {})
    if dean.get("intended_use") != "discovery_only" or (dean.get("license") or {}).get("declared_id") != "CC-BY-NC-SA-4.0":
        issues.append("Dean source must remain CC-BY-NC-SA-4.0 discovery-only")
    volt = source_by_id.get("upstream-awesome-agent-skills", {})
    if volt.get("intended_use") != "discovery_only":
        issues.append("VoltAgent source must remain discovery-only")
    kdense = source_by_id.get("upstream-k-dense-admin-skills", {})
    if kdense.get("availability") != "expected_unavailable" or kdense.get("expected_http_status") != 404:
        issues.append("K-Dense source must remain explicitly expected-unavailable/404 until reviewed")
    return issues


def resolve_registry_path(value: str | None) -> Path:
    if value is None:
        return DEFAULT_REGISTRY
    path = Path(value)
    if not path.is_absolute():
        raise UpstreamError("E_USAGE", "--registry must be an absolute path")
    return path.resolve(strict=False)


def bundled_active_unit_ids() -> set[str]:
    catalog = load_json(ACTIVE_CATALOG)
    if not isinstance(catalog, dict) or catalog.get("record_type") != "RoleKnowledgeCatalog":
        raise UpstreamError("E_VALIDATION", f"active role catalog type is invalid: {ACTIVE_CATALOG}")
    units = catalog.get("units")
    if not isinstance(units, list) or not units:
        raise UpstreamError("E_VALIDATION", f"active role catalog contains no units: {ACTIVE_CATALOG}")
    unit_ids: list[str] = []
    for index, unit in enumerate(units):
        if not isinstance(unit, dict) or unit.get("status") != "active":
            raise UpstreamError("E_VALIDATION", f"active role catalog unit[{index}] is not active")
        unit_id = unit.get("id")
        if not isinstance(unit_id, str) or not UNIT_ID_RE.fullmatch(unit_id):
            raise UpstreamError("E_VALIDATION", f"active role catalog unit[{index}].id is invalid")
        unit_ids.append(unit_id)
    if len(set(unit_ids)) != len(unit_ids):
        raise UpstreamError("E_VALIDATION", f"active role catalog contains duplicate unit ids: {ACTIVE_CATALOG}")
    return set(unit_ids)


def load_validated_registry(path: Path) -> tuple[dict[str, Any], str]:
    schema = load_json(SCHEMA_PATH)
    schema_issues = validate_schema_document(schema)
    if schema_issues:
        for issue in schema_issues:
            print(f"ERROR E_SCHEMA: {issue}", file=sys.stderr)
        raise UpstreamError("E_VALIDATION", f"schema has {len(schema_issues)} validation error(s): {SCHEMA_PATH}")
    registry = load_json(path)
    known_unit_ids = bundled_active_unit_ids() if path.resolve() == DEFAULT_REGISTRY.resolve() else None
    issues = validate_registry(registry, known_unit_ids)
    if issues:
        for issue in issues:
            print(f"ERROR E_SCHEMA: {issue}", file=sys.stderr)
        raise UpstreamError("E_VALIDATION", f"registry has {len(issues)} validation error(s): {path}")
    return registry, file_sha256(path)


def quote_segment(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def repo_path(source: dict[str, Any]) -> str:
    repo = source["repository"]
    return f"/repos/{quote_segment(repo['owner'])}/{quote_segment(repo['name'])}"


class GitHubApiClient:
    def __init__(self, timeout: int = 30):
        if not is_exact_int(timeout) or not 1 <= timeout <= 120:
            raise UpstreamError("E_USAGE", "--timeout must be an integer from 1 to 120 seconds")
        self.timeout = timeout
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "xb-role-knowledge-upstream-sync/1",
            "X-GitHub-Api-Version": API_VERSION,
        }
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def request_json(self, path: str, *, allow_404: bool = False, max_bytes: int = 20 * 1024 * 1024) -> ApiResult:
        if not path.startswith("/"):
            raise UpstreamError("E_STATE", f"internal API path must start with '/': {path}")
        url = f"{API_BASE}{path}"
        request = urllib.request.Request(url, headers=self.headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                final = urllib.parse.urlsplit(response.geturl())
                if final.scheme != "https" or final.netloc.lower() != "api.github.com":
                    raise UpstreamError("E_SECURITY", f"GitHub API redirected outside api.github.com: {response.geturl()}")
                status = int(response.status)
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise UpstreamError("E_GITHUB_METADATA", f"GitHub API response exceeds {max_bytes} bytes: {path}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and allow_404:
                return ApiResult(404, None)
            if exc.code == 404:
                raise UpstreamError("E_NETWORK", f"unexpected GitHub 404 for {path}") from exc
            raise UpstreamError("E_NETWORK", f"GitHub API HTTP {exc.code} for {path}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpstreamError("E_NETWORK", f"GitHub API request failed for {path}: {exc}") from exc
        if status != 200:
            raise UpstreamError("E_NETWORK", f"unexpected GitHub HTTP {status} for {path}")
        try:
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_without_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
            raise UpstreamError("E_GITHUB_METADATA", f"invalid GitHub JSON for {path}: {exc}") from exc
        return ApiResult(status, data)


def require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UpstreamError("E_GITHUB_METADATA", f"{context} must be an object")
    return value


def require_string(value: Any, context: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value or (pattern is not None and not pattern.fullmatch(value)):
        raise UpstreamError("E_GITHUB_METADATA", f"{context} is missing or invalid")
    return value


def decode_api_content(value: Any, context: str, max_bytes: int) -> bytes:
    obj = require_object(value, context)
    if obj.get("encoding") != "base64" or not isinstance(obj.get("content"), str):
        raise UpstreamError("E_GITHUB_METADATA", f"{context} must contain base64 content")
    try:
        compact = "".join(obj["content"].split())
        raw = base64.b64decode(compact, validate=True)
    except (ValueError, TypeError) as exc:
        raise UpstreamError("E_GITHUB_METADATA", f"{context} contains invalid base64") from exc
    if len(raw) > max_bytes:
        raise UpstreamError("E_GITHUB_METADATA", f"{context} exceeds {max_bytes} bytes")
    size = obj.get("size")
    if is_exact_int(size) and size != len(raw):
        raise UpstreamError("E_GITHUB_METADATA", f"{context} size does not match decoded content")
    return raw


def make_change(source: dict[str, Any], kind: str, code: str, baseline: Any, current: Any, *, path: str | None = None) -> dict[str, Any]:
    change = {
        "source_id": source["id"],
        "repository": source["repository"]["full_name"],
        "kind": kind,
        "code": code,
        "baseline": baseline,
        "current": current,
        "affected_scope": source["affected_scope"],
        "affected_units": source["affected_units"],
        "required_gates": source["required_gates"],
    }
    if path is not None:
        change["path"] = path
    return change


def inspect_source(source: dict[str, Any], client: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = repo_path(source)
    response = client.request_json(base, allow_404=True)
    if source["availability"] == "expected_unavailable":
        if response.status == 404:
            return ({
                "source_id": source["id"],
                "repository": source["repository"]["full_name"],
                "availability": "expected_unavailable",
                "http_status": 404,
                "stars": None,
                "stars_usage": "discovery_only",
            }, [])
        return ({
            "source_id": source["id"],
            "repository": source["repository"]["full_name"],
            "availability": "unexpectedly_available",
            "http_status": response.status,
            "stars": None,
            "stars_usage": "discovery_only",
        }, [make_change(source, "availability_recovered", "E_GITHUB_METADATA", 404, response.status)])
    if response.status == 404:
        raise UpstreamError("E_NETWORK", f"required upstream repository returned 404: {source['repository']['full_name']}")
    metadata = require_object(response.data, f"{source['id']} repository metadata")
    full_name = require_string(metadata.get("full_name"), f"{source['id']}.full_name")
    default_branch = require_string(metadata.get("default_branch"), f"{source['id']}.default_branch")
    archived = metadata.get("archived")
    stars = metadata.get("stargazers_count")
    if type(archived) is not bool or not is_exact_int(stars) or stars < 0:
        raise UpstreamError("E_GITHUB_METADATA", f"{source['id']} archive/stars metadata is invalid")
    metadata_license = metadata.get("license")
    metadata_spdx = None
    if metadata_license is not None:
        metadata_spdx = require_string(require_object(metadata_license, f"{source['id']}.metadata.license").get("spdx_id"), f"{source['id']}.metadata.license.spdx_id")

    ref_path = f"{base}/git/ref/heads/{quote_segment(default_branch)}"
    ref = require_object(client.request_json(ref_path).data, f"{source['id']} default branch ref")
    ref_object = require_object(ref.get("object"), f"{source['id']} default branch ref.object")
    head = require_string(ref_object.get("sha"), f"{source['id']}.head", SHA1_RE)

    license_path = f"{base}/license?ref={quote_segment(head)}"
    license_response = client.request_json(license_path, allow_404=True)
    if license_response.status == 404:
        raise UpstreamError("E_LICENSE", f"license endpoint returned 404 for {source['repository']['full_name']}@{head}")
    license_obj = require_object(license_response.data, f"{source['id']} license")
    license_api = require_object(license_obj.get("license"), f"{source['id']} license.license")
    license_spdx = require_string(license_api.get("spdx_id"), f"{source['id']} license.spdx_id")
    license_file_path = require_string(license_obj.get("path"), f"{source['id']} license.path")
    license_blob = require_string(license_obj.get("sha"), f"{source['id']} license.sha", SHA1_RE)
    license_raw = decode_api_content(license_obj, f"{source['id']} license", 1024 * 1024)
    license_digest = sha256_bytes(license_raw)

    snapshot = {
        "source_id": source["id"],
        "repository": full_name,
        "availability": "available",
        "http_status": 200,
        "default_branch": default_branch,
        "head_commit": head,
        "archived": archived,
        "metadata_spdx_id": metadata_spdx,
        "license_spdx_id": license_spdx,
        "license_path": license_file_path,
        "license_git_blob_sha": license_blob,
        "license_sha256": license_digest,
        "stars": stars,
        "stars_usage": "discovery_only",
    }
    repo = source["repository"]
    expected_license = source["license"]
    changes: list[dict[str, Any]] = []
    checks = [
        ("repository_identity_drift", "E_GITHUB_METADATA", repo["full_name"], full_name),
        ("default_branch_drift", "E_GITHUB_METADATA", repo["expected_default_branch"], default_branch),
        ("head_drift", "E_PIN", repo["pinned_commit"], head),
        ("archive_drift", "E_SECURITY", repo["expected_archived"], archived),
        ("metadata_license_drift", "E_LICENSE", expected_license["github_api_spdx_id"], metadata_spdx),
        ("license_spdx_drift", "E_LICENSE", expected_license["github_api_spdx_id"], license_spdx),
        ("license_path_drift", "E_LICENSE", expected_license["file_path"], license_file_path),
        ("license_blob_drift", "E_LICENSE", expected_license["baseline_git_blob_sha"], license_blob),
        ("license_content_drift", "E_LICENSE", expected_license["baseline_sha256"], license_digest),
    ]
    for kind, code, baseline, current in checks:
        if baseline != current:
            changes.append(make_change(source, kind, code, baseline, current))
    return snapshot, changes


def inspect_all(registry: dict[str, Any], client: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    snapshots: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    for source in registry["sources"]:
        snapshot, source_changes = inspect_source(source, client)
        snapshots.append(snapshot)
        changes.extend(source_changes)
    return snapshots, changes


def format_list(values: list[str]) -> str:
    return "[" + ",".join(values) + "]"


def print_change(change: dict[str, Any], *, error: bool) -> None:
    prefix = f"ERROR {change['code']}:" if error else "CHANGE"
    path = f" path={change['path']}" if "path" in change else ""
    print(
        f"{prefix} source={change['source_id']} kind={change['kind']}{path} "
        f"baseline={change['baseline']} current={change['current']} "
        f"affected_units={format_list(change['affected_units'])} "
        f"required_gates={format_list(change['required_gates'])}",
        file=sys.stderr if error else sys.stdout,
    )


def blocking_refresh_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [change for change in changes if change["kind"] != "head_drift"]


def protected_file_snapshot(registry: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in registry["active_registry_protection"]["protected_relative_paths"]:
        path = (SKILL_ROOT / PurePosixPath(relative)).resolve(strict=False)
        if not path.is_file():
            raise UpstreamError("E_STATE", f"protected active file is missing: {path}")
        result[relative] = file_sha256(path)
    return result


def normcase_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath([normcase_path(path), normcase_path(parent)]) == normcase_path(parent)
    except ValueError:
        return False


def validate_output_directory(output_value: str) -> Path:
    output = Path(output_value)
    if not output.is_absolute():
        raise UpstreamError("E_OUTPUT", "--output must be an absolute path")
    if output.exists() or output.is_symlink():
        raise UpstreamError("E_OUTPUT", f"candidate output already exists; overwrite is forbidden: {output}")
    try:
        parent = output.parent.resolve(strict=True)
    except OSError as exc:
        raise UpstreamError("E_OUTPUT", f"candidate output parent must already exist: {output.parent}") from exc
    if not parent.is_dir():
        raise UpstreamError("E_OUTPUT", f"candidate output parent is not a directory: {parent}")
    resolved_output = parent / output.name
    if not output.name or output.name in {".", ".."}:
        raise UpstreamError("E_OUTPUT", "candidate output directory name is invalid")
    if path_is_within(resolved_output, SKILL_ROOT):
        raise UpstreamError("E_OUTPUT", f"candidate text must not be written inside xb-role-knowledge: {resolved_output}")
    return resolved_output


def tree_for_source(source: dict[str, Any], snapshot: dict[str, Any], client: Any) -> dict[str, dict[str, Any]]:
    base = repo_path(source)
    head = snapshot["head_commit"]
    response = client.request_json(f"{base}/git/trees/{quote_segment(head)}?recursive=1", max_bytes=32 * 1024 * 1024)
    tree_obj = require_object(response.data, f"{source['id']} tree")
    if tree_obj.get("truncated") is not False or not isinstance(tree_obj.get("tree"), list):
        raise UpstreamError("E_GITHUB_METADATA", f"{source['id']} recursive tree is truncated or invalid")
    paths: dict[str, dict[str, Any]] = {}
    for item in tree_obj["tree"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        paths[item["path"]] = item
    return paths


def fetch_allowlisted_blob(source: dict[str, Any], path: str, blob_sha: str, client: Any, max_bytes: int) -> tuple[bytes, str]:
    base = repo_path(source)
    response = client.request_json(f"{base}/git/blobs/{quote_segment(blob_sha)}", max_bytes=max_bytes * 2 + 1024 * 1024)
    raw = decode_api_content(response.data, f"{source['id']} allowlisted blob {path}", max_bytes)
    actual_blob = git_blob_sha(raw)
    if actual_blob != blob_sha:
        raise UpstreamError("E_PIN", f"Git blob digest mismatch for {source['repository']['full_name']}:{path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UpstreamError("E_SECURITY", f"allowlisted path is not UTF-8 text: {source['repository']['full_name']}:{path}") from exc
    if "\x00" in text:
        raise UpstreamError("E_SECURITY", f"allowlisted path contains NUL bytes: {source['repository']['full_name']}:{path}")
    return raw, text


def candidate_coordinate(source: dict[str, Any], path: str, head: str, start: int, end: int) -> str:
    return f"{source['repository']['full_name']}@{head}:{path}#L{start}-L{end}"


def build_candidate(
    registry: dict[str, Any],
    registry_path: Path,
    registry_digest: str,
    output: Path,
    client: Any,
    snapshots: list[dict[str, Any]],
    remote_changes: list[dict[str, Any]],
) -> dict[str, Any]:
    source_by_id = {source["id"]: source for source in registry["sources"]}
    snapshot_by_id = {snapshot["source_id"]: snapshot for snapshot in snapshots}
    max_bytes = registry["policies"]["max_text_bytes"]
    protected_before = protected_file_snapshot(registry)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=str(output.parent)))
    committed = False
    try:
        file_records: list[dict[str, Any]] = []
        source_records: list[dict[str, Any]] = []
        changes = copy.deepcopy(remote_changes)
        for source_id in [source["id"] for source in registry["sources"]]:
            source = source_by_id[source_id]
            snapshot = snapshot_by_id[source_id]
            if source["availability"] == "expected_unavailable":
                source_records.append({
                    "source_id": source_id,
                    "repository": source["repository"]["full_name"],
                    "status": "expected_unavailable",
                    "http_status": 404,
                    "affected_scope": source["affected_scope"],
                    "affected_units": source["affected_units"],
                    "required_gates": source["required_gates"],
                    "files": [],
                })
                continue
            tree = tree_for_source(source, snapshot, client)
            current_file_records: list[dict[str, Any]] = []
            for entry in source["allowlist"]:
                path = entry["path"]
                item = tree.get(path)
                if not isinstance(item, dict) or item.get("type") != "blob":
                    raise UpstreamError("E_NETWORK", f"allowlisted text path returned 404/missing blob: {source['repository']['full_name']}@{snapshot['head_commit']}:{path}")
                blob_sha = require_string(item.get("sha"), f"{source_id}:{path} blob sha", SHA1_RE)
                raw, text = fetch_allowlisted_blob(source, path, blob_sha, client, max_bytes)
                relative_text_path = PurePosixPath(registry["policies"]["candidate_text_root"]) / source_id / PurePosixPath(path)
                target = stage.joinpath(*relative_text_path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                line_count = len(text.splitlines())
                coordinate_records: list[dict[str, Any]] = []
                for coordinate in entry["coordinates"]:
                    in_range = coordinate["end_line"] <= line_count
                    coordinate_record = {
                        "id": coordinate["id"],
                        "disposition": coordinate["disposition"],
                        "baseline_coordinate": coordinate["coordinate"],
                        "candidate_coordinate": candidate_coordinate(
                            source, path, snapshot["head_commit"], coordinate["start_line"], coordinate["end_line"]
                        ),
                        "start_line": coordinate["start_line"],
                        "end_line": coordinate["end_line"],
                        "status": "within_file" if in_range else "out_of_range",
                        "note": coordinate["note"],
                    }
                    coordinate_records.append(coordinate_record)
                    if not in_range:
                        changes.append(make_change(
                            source,
                            "evidence_coordinate_out_of_range",
                            "E_SOURCE_COORDINATE",
                            coordinate["coordinate"],
                            f"line_count={line_count}",
                            path=path,
                        ))
                changed = blob_sha != entry["baseline_git_blob_sha"]
                if changed:
                    changes.append(make_change(
                        source,
                        "allowlisted_file_changed",
                        "E_PIN",
                        entry["baseline_git_blob_sha"],
                        blob_sha,
                        path=path,
                    ))
                record = {
                    "source_id": source_id,
                    "repository": source["repository"]["full_name"],
                    "commit": snapshot["head_commit"],
                    "path": path,
                    "content_use": entry["content_use"],
                    "baseline_git_blob_sha": entry["baseline_git_blob_sha"],
                    "candidate_git_blob_sha": blob_sha,
                    "changed": changed,
                    "sha256": sha256_bytes(raw),
                    "byte_count": len(raw),
                    "line_count": line_count,
                    "local_relative_path": relative_text_path.as_posix(),
                    "coordinates": coordinate_records,
                }
                file_records.append(record)
                current_file_records.append(record)
            source_records.append({
                "source_id": source_id,
                "repository": source["repository"]["full_name"],
                "status": "candidate_snapshot",
                "intended_use": source["intended_use"],
                "baseline_commit": source["repository"]["pinned_commit"],
                "candidate_commit": snapshot["head_commit"],
                "head_changed": source["repository"]["pinned_commit"] != snapshot["head_commit"],
                "archived": snapshot["archived"],
                "license": {
                    "declared_id": source["license"]["declared_id"],
                    "github_api_spdx_id": snapshot["license_spdx_id"],
                    "path": snapshot["license_path"],
                    "git_blob_sha": snapshot["license_git_blob_sha"],
                    "sha256": snapshot["license_sha256"],
                    "use_policy": source["license"]["use_policy"],
                },
                "stars": {
                    "observed": snapshot["stars"],
                    "captured_at": now_utc(),
                    "usage": "discovery_only",
                    "evidence_weight": "none",
                },
                "affected_scope": source["affected_scope"],
                "affected_units": source["affected_units"],
                "required_gates": source["required_gates"],
                "files": [record["path"] for record in current_file_records],
            })

        changed_source_ids = sorted({change["source_id"] for change in changes})
        required_gates = sorted({
            gate
            for change in changes
            for gate in change["required_gates"]
        })
        protected_after = protected_file_snapshot(registry)
        if protected_before != protected_after:
            raise UpstreamError("E_STATE", "protected active registry/catalog changed during candidate refresh")
        manifest = {
            "record_type": "RoleKnowledgeUpstreamCandidate",
            "schema_version": 1,
            "candidate_id": f"upstream-role-candidate-{now_utc().replace('-', '').replace(':', '')}",
            "created_at": now_utc(),
            "status": "candidate_only",
            "activation_allowed": False,
            "activation_reason": "Refresh output is unreviewed evidence material; it never updates or activates the builtin registry/catalog.",
            "external_content_policy": "untrusted_data_no_execute",
            "execution_authorized": False,
            "model_prior_fallback": False,
            "stars_usage": "discovery_only",
            "stars_evidence_weight": "none",
            "source_registry": {
                "id": registry["registry_id"],
                "version": registry["registry_version"],
                "sha256": registry_digest,
                "schema_sha256": file_sha256(SCHEMA_PATH),
                "input_file_name": registry_path.name,
            },
            "active_registry_protection": {
                "verified_unchanged": True,
                "files": protected_after,
            },
            "sources": source_records,
            "files": file_records,
            "changes": changes,
            "change_summary": {
                "changed_source_ids": changed_source_ids,
                "affected_units": sorted({unit for change in changes for unit in change["affected_units"]}),
                "required_gates": required_gates,
            },
            "next_step": "Review changed allowlisted text and rerun every listed gate before preparing any separate RoleKnowledgeUnit candidate.",
        }
        manifest_path = stage / registry["policies"]["candidate_manifest_filename"]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        if output.exists() or output.is_symlink():
            raise UpstreamError("E_OUTPUT", f"candidate output appeared during refresh; refusing overwrite: {output}")
        os.rename(stage, output)
        committed = True
        return manifest
    finally:
        if not committed and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def refresh_candidate(
    registry: dict[str, Any],
    registry_path: Path,
    registry_digest: str,
    output_value: str,
    yes: bool,
    client: Any,
) -> tuple[Path, dict[str, Any]]:
    if not yes:
        raise UpstreamError("E_CONFIRMATION", "refresh-candidate requires explicit --yes")
    output = validate_output_directory(output_value)
    snapshots, remote_changes = inspect_all(registry, client)
    blockers = blocking_refresh_changes(remote_changes)
    if blockers:
        for change in blockers:
            print_change(change, error=True)
        raise UpstreamError("E_VALIDATION", f"candidate refresh blocked by {len(blockers)} metadata/license/archive/availability change(s)")
    manifest = build_candidate(registry, registry_path, registry_digest, output, client, snapshots, remote_changes)
    return output, manifest


def cmd_validate(args: argparse.Namespace) -> int:
    registry_path = resolve_registry_path(args.registry)
    registry, digest = load_validated_registry(registry_path)
    file_count = sum(len(source["allowlist"]) for source in registry["sources"])
    coordinate_count = sum(
        len(entry["coordinates"])
        for source in registry["sources"]
        for entry in source["allowlist"]
    )
    print(
        f"VALID registry={registry_path} sha256={digest} sources={len(registry['sources'])} "
        f"allowlisted_files={file_count} evidence_coordinates={coordinate_count} "
        "external_content_policy=untrusted_data_no_execute execute=false"
    )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    registry_path = resolve_registry_path(args.registry)
    registry, _ = load_validated_registry(registry_path)
    snapshots, changes = inspect_all(registry, GitHubApiClient(args.timeout))
    for snapshot in snapshots:
        if snapshot["availability"] == "expected_unavailable":
            print(
                f"CHECK source={snapshot['source_id']} repository={snapshot['repository']} "
                "status=stable_unavailable http=404 stars=unavailable stars_usage=discovery_only"
            )
        else:
            print(
                f"CHECK source={snapshot['source_id']} repository={snapshot['repository']} "
                f"status=observed head={snapshot['head_commit']} archived={str(snapshot['archived']).lower()} "
                f"license={snapshot['license_spdx_id']} stars={snapshot['stars']} stars_usage=discovery_only"
            )
    if changes:
        for change in changes:
            print_change(change, error=True)
        raise UpstreamError("E_VALIDATION", f"remote check found {len(changes)} blocking drift(s)")
    print(f"CHECK_OK sources={len(snapshots)} drift=0 stars_usage=discovery_only")
    return 0


def cmd_refresh_candidate(args: argparse.Namespace) -> int:
    registry_path = resolve_registry_path(args.registry)
    registry, digest = load_validated_registry(registry_path)
    output, manifest = refresh_candidate(
        registry,
        registry_path,
        digest,
        args.output,
        args.yes,
        GitHubApiClient(args.timeout),
    )
    for change in manifest["changes"]:
        print_change(change, error=False)
    summary = manifest["change_summary"]
    print(
        f"CANDIDATE_WRITTEN output={output} files={len(manifest['files'])} "
        f"changed_sources={format_list(summary['changed_source_ids'])} "
        f"affected_units={format_list(summary['affected_units'])} "
        f"required_gates={format_list(summary['required_gates'])} "
        "activation_allowed=false active_registry_unchanged=true"
    )
    return 0


class FakeApiClient:
    def __init__(self, routes: dict[str, ApiResult]):
        self.routes = routes

    def request_json(self, path: str, *, allow_404: bool = False, max_bytes: int = 20 * 1024 * 1024) -> ApiResult:
        del max_bytes
        result = self.routes.get(path)
        if result is None:
            raise UpstreamError("E_STATE", f"self-test route missing: {path}")
        if result.status == 404 and not allow_404:
            raise UpstreamError("E_NETWORK", f"self-test unexpected 404: {path}")
        return copy.deepcopy(result)


def fake_registry_and_routes(
    registry: dict[str, Any],
    *,
    drift_source_id: str | None = None,
    license_drift_source_id: str | None = None,
    recover_kdense: bool = False,
) -> tuple[dict[str, Any], dict[str, ApiResult]]:
    fake = copy.deepcopy(registry)
    routes: dict[str, ApiResult] = {}
    for source in fake["sources"]:
        base = repo_path(source)
        if source["availability"] == "expected_unavailable":
            if recover_kdense:
                routes[base] = ApiResult(200, {"full_name": source["repository"]["full_name"]})
            else:
                routes[base] = ApiResult(404, None)
            continue
        repo = source["repository"]
        baseline_head = repo["pinned_commit"]
        head = baseline_head
        if source["id"] == drift_source_id:
            head = hashlib.sha1(f"drift:{source['id']}".encode("utf-8")).hexdigest()
        license_raw = f"SELF_TEST_LICENSE:{source['license']['declared_id']}\n".encode("utf-8")
        baseline_license_raw = license_raw
        license_blob = git_blob_sha(baseline_license_raw)
        source["license"]["baseline_git_blob_sha"] = license_blob
        source["license"]["baseline_sha256"] = sha256_bytes(baseline_license_raw)
        if source["id"] == license_drift_source_id:
            license_raw += b"CHANGED\n"
            license_blob = git_blob_sha(license_raw)
        metadata = {
            "full_name": repo["full_name"],
            "default_branch": repo["expected_default_branch"],
            "archived": repo["expected_archived"],
            "stargazers_count": 123,
            "license": {"spdx_id": source["license"]["github_api_spdx_id"]},
        }
        routes[base] = ApiResult(200, metadata)
        ref_path = f"{base}/git/ref/heads/{quote_segment(repo['expected_default_branch'])}"
        routes[ref_path] = ApiResult(200, {"object": {"sha": head}})
        license_path = f"{base}/license?ref={quote_segment(head)}"
        routes[license_path] = ApiResult(200, {
            "path": source["license"]["file_path"],
            "sha": license_blob,
            "size": len(license_raw),
            "encoding": "base64",
            "content": base64.b64encode(license_raw).decode("ascii"),
            "license": {"spdx_id": source["license"]["github_api_spdx_id"]},
        })
        tree_items: list[dict[str, Any]] = []
        for entry_index, entry in enumerate(source["allowlist"]):
            max_line = max((coordinate["end_line"] for coordinate in entry["coordinates"]), default=3)
            body = "".join(
                f"UNTRUSTED_TEXT_BODY_{source['id']}_{entry_index}_{line}\n"
                for line in range(1, max_line + 2)
            ).encode("utf-8")
            baseline_blob = git_blob_sha(body)
            entry["baseline_git_blob_sha"] = baseline_blob
            candidate_body = body
            if source["id"] == drift_source_id and entry_index == 0:
                candidate_body += b"UNTRUSTED_TEXT_BODY_CHANGED\n"
            candidate_blob = git_blob_sha(candidate_body)
            tree_items.append({"path": entry["path"], "type": "blob", "sha": candidate_blob, "size": len(candidate_body)})
            routes[f"{base}/git/blobs/{quote_segment(candidate_blob)}"] = ApiResult(200, {
                "sha": candidate_blob,
                "size": len(candidate_body),
                "encoding": "base64",
                "content": base64.b64encode(candidate_body).decode("ascii"),
            })
        routes[f"{base}/git/trees/{quote_segment(head)}?recursive=1"] = ApiResult(200, {
            "truncated": False,
            "tree": tree_items,
        })
    return fake, routes


def expect_error(code: str, action: Any) -> None:
    try:
        action()
    except UpstreamError as exc:
        if exc.code != code:
            raise AssertionError(f"expected {code}, got {exc.code}: {exc.message}") from exc
    else:
        raise AssertionError(f"expected {code}, action succeeded")


def cmd_self_test(args: argparse.Namespace) -> int:
    del args
    registry, digest = load_validated_registry(DEFAULT_REGISTRY)
    protected_before = protected_file_snapshot(registry)
    cases = 0

    stable_registry, stable_routes = fake_registry_and_routes(registry)
    known_unit_ids = bundled_active_unit_ids()
    stable_issues = validate_registry(stable_registry, known_unit_ids)
    if stable_issues:
        raise AssertionError(f"self-test fake registry invalid: {stable_issues}")
    stable_snapshots, stable_changes = inspect_all(stable_registry, FakeApiClient(stable_routes))
    assert not stable_changes
    cases += 1

    unknown_unit_registry = copy.deepcopy(stable_registry)
    next(
        source for source in unknown_unit_registry["sources"]
        if source["id"] == "upstream-financial-services"
    )["affected_units"] = ["rk-does-not-exist"]
    unknown_unit_issues = validate_registry(unknown_unit_registry, known_unit_ids)
    assert any("unknown active role units" in issue for issue in unknown_unit_issues)
    cases += 1

    expect_error(
        "E_CONFIRMATION",
        lambda: refresh_candidate(
            stable_registry, DEFAULT_REGISTRY, digest, str(Path(tempfile.gettempdir()) / "missing-confirmation"), False,
            FakeApiClient(stable_routes),
        ),
    )
    cases += 1

    with tempfile.TemporaryDirectory(prefix="xb-upstream-self-test-") as temp_name:
        temp_root = Path(temp_name).resolve()
        existing = temp_root / "existing"
        existing.mkdir()
        expect_error("E_OUTPUT", lambda: validate_output_directory(str(existing)))
        cases += 1

        inside_skill = SKILL_ROOT / f"self-test-output-{os.getpid()}"
        if inside_skill.exists():
            raise AssertionError(f"unexpected pre-existing self-test path: {inside_skill}")
        expect_error("E_OUTPUT", lambda: validate_output_directory(str(inside_skill)))
        cases += 1

        output = temp_root / "stable-candidate"
        written, manifest = refresh_candidate(
            stable_registry, DEFAULT_REGISTRY, digest, str(output), True, FakeApiClient(stable_routes)
        )
        assert written == output and output.is_dir()
        assert len(manifest["files"]) == sum(len(source["allowlist"]) for source in stable_registry["sources"])
        manifest_text = (output / stable_registry["policies"]["candidate_manifest_filename"]).read_text(encoding="utf-8")
        assert "UNTRUSTED_TEXT_BODY_" not in manifest_text
        assert manifest["activation_allowed"] is False and manifest["execution_authorized"] is False
        assert manifest["active_registry_protection"]["verified_unchanged"] is True
        cases += 1

        drift_id = "upstream-ui-ux-pro-max"
        drift_registry, drift_routes = fake_registry_and_routes(registry, drift_source_id=drift_id)
        drift_snapshots, drift_changes = inspect_all(drift_registry, FakeApiClient(drift_routes))
        assert any(change["kind"] == "head_drift" and change["affected_units"] for change in drift_changes)
        drift_output = temp_root / "drift-candidate"
        _, drift_manifest = refresh_candidate(
            drift_registry, DEFAULT_REGISTRY, digest, str(drift_output), True, FakeApiClient(drift_routes)
        )
        assert any(change["kind"] == "allowlisted_file_changed" for change in drift_manifest["changes"])
        assert drift_manifest["change_summary"]["affected_units"]
        assert drift_manifest["change_summary"]["required_gates"]
        cases += 1

        license_registry, license_routes = fake_registry_and_routes(
            registry, license_drift_source_id="upstream-ui-ux-pro-max"
        )
        license_snapshots, license_changes = inspect_all(license_registry, FakeApiClient(license_routes))
        del license_snapshots
        assert any(change["code"] == "E_LICENSE" for change in license_changes)
        assert blocking_refresh_changes(license_changes)
        cases += 1

        recovered_registry, recovered_routes = fake_registry_and_routes(registry, recover_kdense=True)
        recovered_snapshots, recovered_changes = inspect_all(recovered_registry, FakeApiClient(recovered_routes))
        del recovered_snapshots
        assert any(change["kind"] == "availability_recovered" for change in recovered_changes)
        cases += 1

        assert len(stable_snapshots) == len(registry["sources"])
        assert any(snapshot["availability"] == "expected_unavailable" for snapshot in stable_snapshots)
        cases += 1

    protected_after = protected_file_snapshot(registry)
    assert protected_before == protected_after
    cases += 1
    print(
        f"SELF_TEST_OK cases={cases} network=mocked standard_library=true "
        "untrusted_text_executed=false active_registry_unchanged=true"
    )
    return 0


def parser() -> Parser:
    root = Parser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate the bundled schema and upstream registry")
    validate.add_argument("--registry", help="optional absolute registry path; defaults to the bundled registry")
    check = commands.add_parser("check", help="check official GitHub metadata, HEAD, license, archive and availability drift")
    check.add_argument("--registry", help="optional absolute registry path; defaults to the bundled registry")
    check.add_argument("--timeout", type=int, default=30, help="per-request timeout in seconds (1..120)")
    refresh = commands.add_parser(
        "refresh-candidate",
        help="write a new external candidate directory containing only allowlisted untrusted text",
    )
    refresh.add_argument("--registry", help="optional absolute registry path; defaults to the bundled registry")
    refresh.add_argument("--output", required=True, help="absolute, nonexistent candidate directory outside this skill")
    refresh.add_argument("--yes", action="store_true", help="confirm creation of the candidate directory")
    refresh.add_argument("--timeout", type=int, default=30, help="per-request timeout in seconds (1..120)")
    commands.add_parser("self-test", help="run deterministic TEMP regression with a mocked GitHub API")
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command == "validate":
            return cmd_validate(args)
        if args.command == "check":
            return cmd_check(args)
        if args.command == "refresh-candidate":
            return cmd_refresh_candidate(args)
        if args.command == "self-test":
            return cmd_self_test(args)
        raise UpstreamError("E_USAGE", f"unsupported command: {args.command}")
    except UpstreamError as exc:
        print(f"ERROR {exc.code}: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except AssertionError as exc:
        print(f"ERROR E_STATE: self-test assertion failed: {exc}", file=sys.stderr)
        return ERROR_CODES["E_STATE"]
    except KeyboardInterrupt:
        print("ERROR E_STATE: interrupted", file=sys.stderr)
        return ERROR_CODES["E_STATE"]
    except OSError as exc:
        print(f"ERROR E_IO: {exc}", file=sys.stderr)
        return ERROR_CODES["E_IO"]


if __name__ == "__main__":
    raise SystemExit(main())
