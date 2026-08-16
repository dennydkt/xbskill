#!/usr/bin/env python3
"""Merge fully replayable unchanged-unit evidence with current partial evidence."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import role_knowledge as rk


DETERMINISTIC_KINDS = {
    "deterministic_positive",
    "deterministic_negative",
    "deterministic_stage_pair",
    "deterministic_overturn",
}
CURRENT_SUCCESS_KINDS = DETERMINISTIC_KINDS | {"blind_answer", "independent_review"}


def file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        rk.fail("E_IO", f"cannot read {path}: {exc}")


def validate_bound_source_registry(
    catalog: dict[str, Any], supplied_path: Path, context: str, *, verify_current_ledger: bool,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if catalog.get("origin") != "builtin":
        rk.fail("E_USAGE", f"{context} only supports builtin catalogs with structured source registries")
    binding = catalog.get("source_registry")
    if not isinstance(binding, dict) or set(binding) != {"file", "sha256"}:
        rk.fail("E_SOURCE_COORDINATE", f"{context} catalog lacks an exact source_registry binding")
    if binding["file"] != rk.BUILTIN_SOURCE_REGISTRY_FILE:
        rk.fail("E_SOURCE_COORDINATE", f"{context} catalog source_registry.file is invalid")
    if file_sha256(supplied_path) != binding["sha256"]:
        rk.fail("E_SOURCE_COORDINATE", f"{context} source registry digest differs from its catalog binding")
    registry = rk.read_json(supplied_path)
    schema_path = Path(__file__).resolve().parents[1] / "references" / "builtin-source-registry.schema.json"
    schema = rk.read_json(schema_path)
    schema_errors = rk.json_schema_errors(registry, schema, schema, f"{context} source registry")
    if schema_errors:
        rk.fail("E_SOURCE_COORDINATE", f"{context} source registry schema violation: {schema_errors[0]}")
    rk.utc_timestamp(registry["captured_at"], f"{context} source registry.captured_at")
    if registry["ledger_file"] != rk.BUILTIN_SOURCE_LEDGER_COORDINATE:
        rk.fail("E_SOURCE_COORDINATE", f"{context} source registry ledger coordinate is invalid")
    license_policies = registry["license_policies"]
    security_profiles = registry["security_profiles"]
    for policy_id in license_policies:
        if not rk.ID_RE.fullmatch(policy_id):
            rk.fail("E_SOURCE_COORDINATE", f"{context} source registry license policy id is invalid: {policy_id}")
    for profile_id in security_profiles:
        if not rk.ID_RE.fullmatch(profile_id):
            rk.fail("E_SOURCE_COORDINATE", f"{context} source registry security profile id is invalid: {profile_id}")
    sources: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(registry["sources"]):
        source_id = source["id"]
        if source_id in sources:
            rk.fail("E_SOURCE_COORDINATE", f"{context} source registry repeats source id {source_id}")
        pin = source["pin"]
        if source_id.startswith("GH-"):
            if pin["kind"] != "git_commit" or re.fullmatch(r"[a-f0-9]{40}", pin["value"]) is None:
                rk.fail("E_PIN", f"{context} source registry.sources[{index}] lacks an exact commit pin")
        elif pin["kind"] != "retrieval_date":
            rk.fail("E_PIN", f"{context} source registry.sources[{index}] lacks a retrieval-date pin")
        else:
            rk.calendar_date(pin["value"], f"{context} source registry.sources[{index}].pin.value")
        if source["license_policy_id"] not in license_policies:
            rk.fail("E_LICENSE", f"{context} source {source_id} references an unknown license policy")
        if source["security_profile_id"] not in security_profiles:
            rk.fail("E_SECURITY", f"{context} source {source_id} references an unknown security profile")
        sources[source_id] = source
    if verify_current_ledger:
        ledger_path = rk.source_ledger_path().resolve()
        try:
            ledger_bytes = ledger_path.read_bytes()
            ledger_text = ledger_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            rk.fail("E_IO", f"cannot read current source ledger {ledger_path}: {exc}")
        if hashlib.sha256(ledger_bytes).hexdigest() != registry["ledger_sha256"]:
            rk.fail("E_SOURCE_COORDINATE", f"{context} source registry does not bind the current source ledger")
        ledger_rows: dict[str, str] = {}
        for line in ledger_text.splitlines():
            match = re.match(r"^\|\s*((?:OFF|GH)-[A-Z0-9]+)\s", line)
            if match:
                if match.group(1) in ledger_rows:
                    rk.fail("E_SOURCE_COORDINATE", f"current source ledger repeats {match.group(1)}")
                ledger_rows[match.group(1)] = hashlib.sha256(line.encode("utf-8")).hexdigest()
        if set(ledger_rows) != set(sources):
            rk.fail("E_SOURCE_COORDINATE", f"{context} source registry ids differ from the current source ledger")
        for source_id, source in sources.items():
            if source["row_sha256"] != ledger_rows[source_id]:
                rk.fail("E_SOURCE_COORDINATE", f"{context} source record does not bind ledger row {source_id}")
    return registry, sources


def validate_catalog_with_supplied_files(
    catalog: dict[str, Any], catalog_path: Path, source_path: Path,
    sources: dict[str, dict[str, Any]], evidence_path: Path | None, *, enforce_release_gate: bool,
) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="rk-incremental-validate-") as raw_root:
        root = Path(raw_root).resolve()
        staged_catalog_path = root / "__catalog_input__.json"
        shutil.copyfile(catalog_path, staged_catalog_path)
        source_file = catalog["source_registry"]["file"]
        shutil.copyfile(source_path, root / source_file)
        if evidence_path is not None:
            evidence_file = catalog["release_binding"]["evidence_file"]
            if re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}\.json", evidence_file) is None:
                rk.fail("E_TEST_GATE", "previous release evidence_file is not a direct builtin JSON child")
            if evidence_file == source_file:
                rk.fail("E_TEST_GATE", "previous evidence_file cannot alias the builtin source registry")
            shutil.copyfile(evidence_path, root / evidence_file)
        original_source_validator = rk.builtin_source_registry
        rk.builtin_source_registry = lambda _catalog, _path: sources
        try:
            return rk.validate_catalog(
                catalog, staged_catalog_path, enforce_release_gate=enforce_release_gate,
            )
        finally:
            rk.builtin_source_registry = original_source_validator


def require_exact_source_record(
    unit: dict[str, Any], previous_registry: dict[str, Any], current_registry: dict[str, Any],
    previous_sources: dict[str, dict[str, Any]], current_sources: dict[str, dict[str, Any]],
) -> None:
    for source_ref in unit["source_refs"]:
        previous = previous_sources.get(source_ref)
        current = current_sources.get(source_ref)
        if previous is None or current is None:
            rk.fail("E_SOURCE_COORDINATE", f"unit {unit['id']} source {source_ref} is absent from an old/new registry")
        if previous != current:
            rk.fail(
                "E_SOURCE_COORDINATE",
                f"unit {unit['id']} source record drifted for {source_ref}; frozen evidence cannot be reused",
            )
        license_id = previous["license_policy_id"]
        security_id = previous["security_profile_id"]
        if (
            previous_registry["license_policies"].get(license_id)
            != current_registry["license_policies"].get(license_id)
        ):
            rk.fail(
                "E_SOURCE_COORDINATE",
                f"unit {unit['id']} resolved license policy drifted for {source_ref}",
            )
        if (
            previous_registry["security_profiles"].get(security_id)
            != current_registry["security_profiles"].get(security_id)
        ):
            rk.fail(
                "E_SOURCE_COORDINATE",
                f"unit {unit['id']} resolved security profile drifted for {source_ref}",
            )


def current_unit_records(
    unit: dict[str, Any], records: dict[str, dict[str, Any]], context: str,
) -> list[dict[str, Any]]:
    expected_digest = rk.reviewable_unit_digest(unit)
    unit_records = [record for record in records.values() if record["unit_id"] == unit["id"]]
    stale_success = [
        record["id"]
        for record in unit_records
        if record["kind"] != "blind_failure"
        and (record["unit_version"] != unit["version"] or record["unit_digest"] != expected_digest)
    ]
    if stale_success:
        rk.fail(
            "E_TEST_GATE",
            f"{context} contains non-current success records for {unit['id']}: {sorted(stale_success)}",
        )
    current = [
        record for record in unit_records
        if record["kind"] != "blind_failure"
        and record["unit_version"] == unit["version"]
        and record["unit_digest"] == expected_digest
    ]
    unexpected = sorted(record["id"] for record in current if record["kind"] not in CURRENT_SUCCESS_KINDS)
    if unexpected:
        rk.fail("E_TEST_GATE", f"{context} has unsupported current records for {unit['id']}: {unexpected}")

    deterministic = [record for record in current if record["kind"] in DETERMINISTIC_KINDS]
    if (
        len(deterministic) != len(DETERMINISTIC_KINDS)
        or {record["kind"] for record in deterministic} != DETERMINISTIC_KINDS
        or any(record["result"] != "passed" for record in deterministic)
    ):
        rk.fail(
            "E_TEST_GATE",
            f"{context} unit {unit['id']} must have exactly four current passed deterministic records",
        )

    answers = [record for record in current if record["kind"] == "blind_answer"]
    if len(answers) != len(rk.BLIND_SCENARIO_KINDS) or {
        record["scenario_kind"] for record in answers
    } != rk.BLIND_SCENARIO_KINDS:
        rk.fail(
            "E_TEST_GATE",
            f"{context} unit {unit['id']} must have exactly four current canonical blind answers",
        )

    reviews = [record for record in current if record["kind"] == "independent_review"]
    if (
        len(reviews) != len(rk.BLIND_SCENARIO_KINDS)
        or {record["scenario_kind"] for record in reviews} != rk.BLIND_SCENARIO_KINDS
        or any(
            record["result"] != "passed"
            or record["scores"] is None
            or any(record["scores"][score] != 2 for score in rk.SCORES)
            for record in reviews
        )
    ):
        rk.fail(
            "E_TEST_GATE",
            f"{context} unit {unit['id']} must have exactly four independent all-two current reviews",
        )
    answer_ids = {record["id"] for record in answers}
    if any(
        len(record["answer_record_ids"]) != 1
        or record["answer_record_ids"][0] not in answer_ids
        for record in reviews
    ):
        rk.fail("E_TEST_GATE", f"{context} reviews for {unit['id']} do not bind its four current answers")
    return current


def require_registry_binding(
    registry: dict[str, Any], catalog: dict[str, Any], catalog_digest: str, context: str,
) -> None:
    expected = {
        "catalog_id": catalog["catalog_id"],
        "candidate_catalog_version": catalog["catalog_version"],
        "candidate_catalog_digest": catalog_digest,
    }
    actual = {key: registry[key] for key in expected}
    if actual != expected:
        rk.fail(
            "E_TEST_GATE",
            f"{context} targets a different candidate catalog id, version, or reviewable digest",
        )


def add_record(
    merged: list[dict[str, Any]], by_id: dict[str, dict[str, Any]], record: dict[str, Any], provenance: str,
) -> bool:
    existing = by_id.get(record["id"])
    if existing is None:
        by_id[record["id"]] = record
        merged.append(record)
        return True
    if existing == record and record["kind"] == "blind_failure":
        return False
    rk.fail(
        "E_TEST_GATE",
        f"duplicate evidence record id {record['id']} while adding {provenance}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--previous-catalog", required=True)
    parser.add_argument("--previous-evidence", required=True)
    parser.add_argument("--previous-source-registry", required=True)
    parser.add_argument("--current-source-registry", required=True)
    parser.add_argument("--current-evidence", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        rk.fail("E_CONFIRMATION", "incremental evidence merge requires --yes after reviewing the exact inputs")
    candidate_path = rk.absolute_path(args.candidate, "--candidate")
    previous_catalog_path = rk.absolute_path(args.previous_catalog, "--previous-catalog")
    previous_evidence_path = rk.absolute_path(args.previous_evidence, "--previous-evidence")
    previous_source_path = rk.absolute_path(args.previous_source_registry, "--previous-source-registry")
    current_source_path = rk.absolute_path(args.current_source_registry, "--current-source-registry")
    current_evidence_path = rk.absolute_path(args.current_evidence, "--current-evidence")
    output_path = rk.absolute_path(args.output, "--output", must_exist=False)
    if output_path.suffix.lower() != ".json":
        rk.fail("E_OUTPUT", f"--output must end with .json: {output_path}")
    if output_path.exists():
        rk.fail("E_OUTPUT", f"refusing to overwrite existing file: {output_path}")

    previous_catalog = rk.read_json(previous_catalog_path)
    candidate = rk.read_json(candidate_path)
    if previous_catalog.get("origin") != "builtin" or candidate.get("origin") != "builtin":
        rk.fail("E_USAGE", "incremental source-registry reuse currently requires builtin catalogs")
    if previous_catalog.get("catalog_id") != candidate.get("catalog_id"):
        rk.fail("E_TEST_GATE", "previous and candidate catalogs must retain the same catalog_id")

    release_binding = previous_catalog.get("release_binding")
    if not isinstance(release_binding, dict):
        rk.fail("E_TEST_GATE", "--previous-catalog must be an active catalog with a release_binding")
    rk.exact_fields(release_binding, rk.RELEASE_BINDING_FIELDS, "previous catalog.release_binding")
    evidence_file = release_binding.get("evidence_file")
    if not isinstance(evidence_file, str) or not evidence_file:
        rk.fail("E_TEST_GATE", "--previous-catalog release_binding.evidence_file is invalid")

    previous_registry, previous_sources = validate_bound_source_registry(
        previous_catalog, previous_source_path, "previous", verify_current_ledger=False,
    )
    current_registry, current_sources = validate_bound_source_registry(
        candidate, current_source_path, "current", verify_current_ledger=True,
    )

    previous_evidence = rk.read_json(previous_evidence_path)
    previous_records = rk.validate_evidence_registry(previous_evidence, previous_evidence_path)
    if file_sha256(previous_evidence_path) != release_binding["evidence_sha256"]:
        rk.fail("E_TEST_GATE", "--previous-evidence digest differs from the active catalog release binding")
    expected_previous_binding = {
        "catalog_id": previous_catalog["catalog_id"],
        "candidate_catalog_version": release_binding["candidate_catalog_version"],
        "candidate_catalog_digest": release_binding["candidate_catalog_digest"],
    }
    if {key: previous_evidence[key] for key in expected_previous_binding} != expected_previous_binding:
        rk.fail("E_TEST_GATE", "--previous-evidence does not bind the active catalog's reviewed candidate")
    previous_units = validate_catalog_with_supplied_files(
        previous_catalog, previous_catalog_path, previous_source_path,
        previous_sources, previous_evidence_path, enforce_release_gate=True,
    )
    if not previous_units or any(unit["status"] != "active" for unit in previous_units):
        rk.fail("E_TEST_GATE", "--previous-catalog must contain only fully active units")
    candidate_units = validate_catalog_with_supplied_files(
        candidate, candidate_path, current_source_path,
        current_sources, None, enforce_release_gate=False,
    )
    if not candidate_units or any(unit["status"] != "candidate" for unit in candidate_units):
        rk.fail("E_TEST_GATE", "--candidate must contain only candidate units")
    rk.validate_frozen_evidence_replay(previous_catalog, previous_units, previous_records)

    current_evidence = rk.read_json(current_evidence_path)
    current_records = rk.validate_evidence_registry(current_evidence, current_evidence_path)
    candidate_digest = rk.reviewable_catalog_digest(candidate)
    require_registry_binding(current_evidence, candidate, candidate_digest, "--current-evidence")

    previous_by_id = {unit["id"]: unit for unit in previous_units}
    candidate_by_id = {unit["id"]: unit for unit in candidate_units}
    carried_unit_ids: list[str] = []
    changed_unit_ids: list[str] = []
    carried_success_ids: set[str] = set()
    current_success_ids: set[str] = set()
    for unit in candidate_units:
        previous_unit = previous_by_id.get(unit["id"])
        unchanged = bool(
            previous_unit is not None
            and previous_unit["version"] == unit["version"]
            and rk.reviewable_unit_digest(previous_unit) == rk.reviewable_unit_digest(unit)
        )
        if unchanged:
            require_exact_source_record(
                unit, previous_registry, current_registry, previous_sources, current_sources,
            )
            reusable_records = current_unit_records(
                unit, previous_records, "--previous-evidence",
            )
            carried_unit_ids.append(unit["id"])
            carried_success_ids.update(record["id"] for record in reusable_records)
        else:
            changed_unit_ids.append(unit["id"])

    carried_set = set(carried_unit_ids)
    for record in current_records.values():
        if record["kind"] == "blind_failure":
            continue
        unit = candidate_by_id.get(record["unit_id"])
        if unit is None:
            rk.fail("E_TEST_GATE", f"--current-evidence contains success for unknown candidate unit {record['unit_id']}")
        if record["unit_id"] in carried_set:
            rk.fail(
                "E_TEST_GATE",
                f"--current-evidence must not replace reusable frozen records for {record['unit_id']}",
            )
        expected_digest = rk.reviewable_unit_digest(unit)
        if record["unit_version"] != unit["version"] or record["unit_digest"] != expected_digest:
            rk.fail("E_TEST_GATE", f"--current-evidence record {record['id']} does not bind the current unit digest")
    for unit_id in changed_unit_ids:
        fresh_records = current_unit_records(
            candidate_by_id[unit_id], current_records, "--current-evidence",
        )
        current_success_ids.update(record["id"] for record in fresh_records)

    merged_records: list[dict[str, Any]] = []
    merged_by_id: dict[str, dict[str, Any]] = {}
    carried_count = 0
    current_count = 0
    historical_failure_count = 0
    for record in previous_evidence["records"]:
        if record["kind"] == "blind_failure":
            if add_record(merged_records, merged_by_id, record, "previous blind_failure history"):
                historical_failure_count += 1
        elif record["id"] in carried_success_ids:
            if add_record(merged_records, merged_by_id, record, "reusable current record"):
                carried_count += 1
    for record in current_evidence["records"]:
        if record["kind"] == "blind_failure":
            if add_record(merged_records, merged_by_id, record, "current blind_failure history"):
                historical_failure_count += 1
        elif record["id"] in current_success_ids:
            if add_record(merged_records, merged_by_id, record, "current changed/new record"):
                current_count += 1

    if not merged_records:
        rk.fail("E_TEST_GATE", "incremental merge produced no evidence records")
    merged = {
        "record_type": "RoleKnowledgeEvidenceRegistry",
        "schema_version": 1,
        "registry_id": current_evidence["registry_id"],
        "catalog_id": candidate["catalog_id"],
        "candidate_catalog_version": candidate["catalog_version"],
        "candidate_catalog_digest": candidate_digest,
        "frozen_at": max(record["executed_at"] for record in merged_records),
        "records": merged_records,
    }
    validated_merged = rk.validate_evidence_registry(merged, output_path)
    rk.validate_frozen_evidence_replay(candidate, candidate_units, validated_merged)
    rk.atomic_json(output_path, merged, exclusive=True)
    print(
        f"INCREMENTAL_EVIDENCE_MERGED path={output_path} "
        f"carried_units={len(carried_unit_ids)} carried_unit_ids={','.join(carried_unit_ids) or 'none'} "
        f"changed_or_new_units={len(changed_unit_ids)} changed_or_new_unit_ids={','.join(changed_unit_ids) or 'none'} "
        f"carried_records={carried_count} current_records={current_count} "
        f"historical_blind_failures={historical_failure_count} records={len(merged_records)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except rk.RoleKnowledgeError as exc:
        print(f"ERROR {exc.code}: {exc.message}")
        raise SystemExit(2)
