#!/usr/bin/env python3
"""Create an activated catalog only from fully bound deterministic and independent evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import re
from pathlib import Path

import role_knowledge as rk


REQUIRED_TEST_KINDS = {
    "deterministic_positive", "deterministic_negative", "deterministic_stage_pair", "deterministic_overturn",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--catalog-version", required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if not args.yes:
        rk.fail("E_CONFIRMATION", "catalog activation requires --yes after independent review")
    if not rk.VERSION_RE.fullmatch(args.catalog_version):
        rk.fail("E_USAGE", "--catalog-version must be semantic x.y.z")
    catalog_path = rk.absolute_path(args.catalog, "--catalog")
    evidence_path = rk.absolute_path(args.evidence, "--evidence")
    output_path = rk.absolute_path(args.output, "--output", must_exist=False)
    if output_path.suffix.lower() != ".json":
        rk.fail("E_OUTPUT", f"--output must end with .json: {output_path}")
    catalog = rk.read_json(catalog_path)
    project_root = rk.absolute_path(args.project_root, "--project-root", directory=True) if args.project_root else None
    if catalog.get("origin") == "project" and project_root is None:
        rk.fail("E_PROJECT_UNINITIALIZED", "activating a project catalog requires its exact --project-root")
    if catalog.get("origin") != "project" and project_root is not None:
        rk.fail("E_USAGE", "--project-root is only valid for a project catalog")
    catalog_role_root = catalog_path.parent.resolve()
    if catalog.get("origin") == "project":
        expected_evidence_root = (catalog_role_root / "evidence").resolve()
        if not expected_evidence_root.is_relative_to(project_root.resolve()) or evidence_path.parent.resolve() != expected_evidence_root:
            rk.fail("E_PATH_BOUNDARY", f"project evidence must stay in the resolved role-knowledge/evidence directory: {expected_evidence_root}")
        evidence_ref_file = f"evidence/{evidence_path.name}"
    else:
        if evidence_path.parent.resolve() != catalog_role_root:
            rk.fail("E_TEST_GATE", "builtin evidence registry must sit beside the catalog it activates")
        evidence_ref_file = evidence_path.name
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}\.json", evidence_path.name):
        rk.fail("E_TEST_GATE", "evidence registry filename is invalid")

    units = rk.validate_catalog(catalog, catalog_path, project_root, enforce_release_gate=False)
    if project_root is not None:
        for index, unit in enumerate(units):
            rk.validate_source_packet(
                unit, project_root, f"activation candidate units[{index}]", catalog["catalog_id"],
            )
    registry = rk.read_json(evidence_path)
    records = rk.validate_evidence_registry(registry, evidence_path)
    rk.validate_frozen_evidence_replay(catalog, units, records)
    expected_catalog_digest = rk.reviewable_catalog_digest(catalog)
    expected_catalog_binding = {
        "catalog_id": catalog["catalog_id"],
        "candidate_catalog_version": catalog["catalog_version"],
        "candidate_catalog_digest": expected_catalog_digest,
    }
    actual_catalog_binding = {key: registry[key] for key in expected_catalog_binding}
    if actual_catalog_binding != expected_catalog_binding:
        rk.fail("E_TEST_GATE", "evidence registry targets a different candidate catalog id, version, or digest")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    activated = copy.deepcopy(catalog)
    activated_at = rk.now_utc()
    activated["release_binding"] = {
        "candidate_catalog_version": catalog["catalog_version"],
        "candidate_catalog_digest": expected_catalog_digest,
        "activated_catalog_version": args.catalog_version,
        "activated_at": activated_at,
        "evidence_file": evidence_ref_file,
        "evidence_sha256": evidence_digest,
        "source_registry_sha256": (
            catalog["source_registry"]["sha256"] if catalog.get("origin") == "builtin" else None
        ),
    }
    for unit in activated["units"]:
        if unit["status"] != "candidate":
            rk.fail("E_TEST_GATE", f"activation input must keep {unit['id']} candidate, found {unit['status']}")
        unit_records = [record for record in records.values() if record["unit_id"] == unit["id"]]
        expected_unit_digest = rk.reviewable_unit_digest(unit)
        if any(
            record["kind"] != "blind_failure"
            and (record["unit_version"] != unit["version"] or record["unit_digest"] != expected_unit_digest)
            for record in unit_records
        ):
            rk.fail("E_TEST_GATE", f"evidence for {unit['id']} targets a different unit version or digest")
        current_records = [
            record for record in unit_records
            if record["unit_version"] == unit["version"] and record["unit_digest"] == expected_unit_digest
        ]
        test_records = [
            record for record in current_records
            if record["kind"] in REQUIRED_TEST_KINDS and record["result"] == "passed"
        ]
        if {record["kind"] for record in test_records} != REQUIRED_TEST_KINDS:
            rk.fail("E_TEST_GATE", f"unit {unit['id']} lacks four passed deterministic record kinds")
        reviews = [
            record for record in current_records
            if record["kind"] == "independent_review"
            and record["result"] == "passed"
            and all(record["scores"][key] == 2 for key in rk.SCORES)
        ]
        review_coverage = {record["scenario_kind"] for record in reviews}
        if review_coverage != rk.BLIND_SCENARIO_KINDS:
            rk.fail(
                "E_TEST_GATE",
                f"unit {unit['id']} needs all-two blind review coverage for {sorted(rk.BLIND_SCENARIO_KINDS)}; "
                f"found={sorted(review_coverage)}",
            )
        review = sorted(reviews, key=lambda item: (item["executed_at"], item["id"]))[-1]
        unit["tests"]["evidence_refs"] = [{
            "file": evidence_ref_file,
            "sha256": evidence_digest,
            "record_ids": sorted(record["id"] for record in test_records),
        }]
        unit["review"] = {
            "status": "passed",
            "answerer_isolated": True,
            "reviewer_independent": True,
            "scores": review["scores"],
            "evidence_refs": [{
                "file": evidence_ref_file,
                "sha256": evidence_digest,
                "record_ids": sorted(record["id"] for record in reviews),
            }],
            "reviewed_at": review["executed_at"],
            "reviewer_id": review["reviewer_id"],
        }
        unit["status"] = "active"
    if len(units) != len(activated["units"]):
        rk.fail("E_CATALOG", "catalog changed during activation")
    activated["catalog_version"] = args.catalog_version
    activated["published_at"] = activated_at
    activated["governance_complete"] = True
    rk.validate_catalog(activated, catalog_path, project_root)
    rk.atomic_json(output_path, activated, exclusive=True)
    print(
        f"CATALOG_ACTIVATED path={output_path} version={args.catalog_version} "
        f"units={len(activated['units'])} evidence_sha256={evidence_digest}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except rk.RoleKnowledgeError as exc:
        print(f"ERROR {exc.code}: {exc.message}")
        raise SystemExit(2)
