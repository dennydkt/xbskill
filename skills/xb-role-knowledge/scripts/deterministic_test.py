#!/usr/bin/env python3
"""Freeze deterministic candidate-unit tests without making candidates runtime-active."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import role_knowledge as rk


KIND_SUFFIX = {
    "deterministic_positive": "positive",
    "deterministic_negative": "negative",
    "deterministic_stage_pair": "stage-pair",
    "deterministic_overturn": "overturn",
}


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def request_for(
    unit: dict[str, Any], proficiency: str = "S1_working",
    actual_constraints: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    current_specialist = {
        "data": "xb-data",
        "product_rd": "xb-it",
        "function": "xb-plan",
        "finance": "xb-analysis",
        "marketing": "xb-analysis",
    }[unit["job_family"]]
    return {
        "schema_version": 1,
        "current_specialist": current_specialist,
        "job_family": unit["job_family"],
        "role": unit["roles"][0],
        "task_family": unit["task_families"][0],
        "lifecycle_stage": unit["lifecycle_stages"][0],
        "proficiency_mode": proficiency,
        "problem": unit["tests"]["positive"][0],
        "signals": [unit["signals"]["include"][0]],
        "actual_constraints": copy.deepcopy(actual_constraints or []),
        "knowledge_requirement": "optional",
        "required_unit_ids": [],
        "max_units": 2,
    }


def selected_ids(units: list[dict[str, Any]], request: dict[str, Any]) -> list[str]:
    matched, _ = rk.match_units(units, request, [])
    return [item[2]["id"] for item in matched]


def run_case(
    kind: str, unit: dict[str, Any], runtime_units: list[dict[str, Any]],
    actual_constraints: list[dict[str, str]],
) -> tuple[str, str, str]:
    expected = unit["id"]
    if kind == "deterministic_positive":
        request = request_for(unit, actual_constraints=actual_constraints)
        actual = selected_ids(runtime_units, request)
        passed = actual == [expected]
        input_value = {"request": request, "expected_unit_ids": [expected]}
        output_value = {"actual_unit_ids": actual, "single_expected_match": passed}
    elif kind == "deterministic_negative":
        request = request_for(unit, actual_constraints=actual_constraints)
        request["role"] = f"{unit['roles'][0]}（非本轮实际责任）"
        request["problem"] = unit["tests"]["negative"][0]
        request["signals"] = []
        actual = selected_ids(runtime_units, request)
        passed = expected not in actual
        input_value = {"request": request, "unit_that_must_not_match": expected}
        output_value = {"actual_unit_ids": actual, "target_isolated": passed}
    elif kind == "deterministic_overturn":
        request = request_for(unit, actual_constraints=actual_constraints)
        request["problem"] = unit["tests"]["overturn"][0]
        request["signals"].append(unit["signals"]["exclude"][0])
        actual = selected_ids(runtime_units, request)
        passed = expected not in actual
        input_value = {
            "request": request,
            "unit_that_must_be_overturned": expected,
            "exclude_signal": unit["signals"]["exclude"][0],
        }
        output_value = {"actual_unit_ids": actual, "target_overturned": passed}
    elif kind == "deterministic_stage_pair":
        s0_request = request_for(unit, "S0_new", actual_constraints)
        s2_request = request_for(unit, "S2_system", actual_constraints)
        s0_match, _ = rk.match_units(runtime_units, s0_request, [])
        s2_match, _ = rk.match_units(runtime_units, s2_request, [])
        s0_packet = rk.build_packet(s0_request, s0_match, [])
        s2_packet = rk.build_packet(s2_request, s2_match, [])
        rk.validate_role_packet(s0_packet)
        rk.validate_role_packet(s2_packet)
        s0_core = {key: value for key, value in s0_packet["active_injection"].items() if key != "stage_adaptation"}
        s2_core = {key: value for key, value in s2_packet["active_injection"].items() if key != "stage_adaptation"}
        assertions = {
            "same_selected_unit": s0_packet["used_unit_ids"] == s2_packet["used_unit_ids"] == [expected],
            "same_claims": s0_packet["claims"] == s2_packet["claims"],
            "same_permissions_risks_and_professional_effects": s0_core == s2_core,
            "different_stage_help": (
                s0_packet["active_injection"]["stage_adaptation"]
                != s2_packet["active_injection"]["stage_adaptation"]
            ),
        }
        passed = all(assertions.values())
        input_value = {
            "S0_request": s0_request,
            "S2_request": s2_request,
            "catalog_test_intent": unit["tests"]["stage_pair"][0],
        }
        output_value = {
            "assertions": assertions,
            "S0_stage_digest": rk.canonical_digest(s0_packet["active_injection"]["stage_adaptation"]),
            "S2_stage_digest": rk.canonical_digest(s2_packet["active_injection"]["stage_adaptation"]),
        }
    else:
        raise AssertionError(f"unsupported deterministic kind: {kind}")
    output_value["result"] = "passed" if passed else "failed"
    return json_text(input_value), json_text(output_value), "passed" if passed else "failed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--actor-id", default="rk-deterministic-runner")
    parser.add_argument("--project-root")
    parser.add_argument("--unit-id", action="append", default=[])
    args = parser.parse_args()

    catalog_path = rk.absolute_path(args.catalog, "--catalog")
    output_path = rk.absolute_path(args.output, "--output", must_exist=False)
    if output_path.suffix.lower() != ".json":
        rk.fail("E_OUTPUT", f"--output must end with .json: {output_path}")
    if not rk.ID_RE.fullmatch(args.actor_id):
        rk.fail("E_USAGE", "--actor-id must be a stable lowercase id")
    catalog = rk.read_json(catalog_path)
    project_root = rk.absolute_path(args.project_root, "--project-root", directory=True) if args.project_root else None
    if catalog.get("origin") == "project" and project_root is None:
        rk.fail("E_PROJECT_UNINITIALIZED", "testing a project catalog requires its exact --project-root")
    if catalog.get("origin") != "project" and project_root is not None:
        rk.fail("E_USAGE", "--project-root is only valid for a project catalog")
    units = rk.validate_catalog(catalog, catalog_path, project_root, enforce_release_gate=False)
    if project_root is not None:
        for index, unit in enumerate(units):
            rk.validate_source_packet(
                unit, project_root, f"deterministic candidate units[{index}]", catalog["catalog_id"],
            )
    runtime_units = copy.deepcopy(units)
    for unit in runtime_units:
        if unit["status"] not in {"candidate", "active"}:
            rk.fail("E_TEST_GATE", f"deterministic test cannot promote {unit['status']} unit {unit['id']}")
        unit["status"] = "active"

    requested_unit_ids = args.unit_id
    invalid_unit_ids = sorted({unit_id for unit_id in requested_unit_ids if not rk.ID_RE.fullmatch(unit_id)})
    if invalid_unit_ids:
        rk.fail("E_USAGE", f"--unit-id contains invalid id(s): {invalid_unit_ids}")
    duplicate_unit_ids = sorted({unit_id for unit_id in requested_unit_ids if requested_unit_ids.count(unit_id) > 1})
    if duplicate_unit_ids:
        rk.fail("E_USAGE", f"--unit-id contains duplicate id(s): {duplicate_unit_ids}")
    runtime_unit_ids = {unit["id"] for unit in runtime_units}
    unknown_unit_ids = sorted(set(requested_unit_ids) - runtime_unit_ids)
    if unknown_unit_ids:
        rk.fail("E_USAGE", f"--unit-id contains unknown candidate unit id(s): {unknown_unit_ids}")
    selected_unit_ids = set(requested_unit_ids) if requested_unit_ids else runtime_unit_ids

    constraint_by_unit = {unit["id"]: rk.governed_rule_scope_constraint(unit) for unit in runtime_units}

    executed_at = rk.now_utc()
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for unit in runtime_units:
        if unit["id"] not in selected_unit_ids:
            continue
        for kind in KIND_SUFFIX:
            input_text, output_text, result = run_case(kind, unit, runtime_units, constraint_by_unit[unit["id"]])
            record_id = f"det-{unit['id'][3:]}-{KIND_SUFFIX[kind]}"
            records.append({
                "id": record_id,
                "unit_id": unit["id"],
                "unit_version": unit["version"],
                "unit_digest": rk.reviewable_unit_digest(unit),
                "kind": kind,
                "scenario_kind": None,
                "executed_at": executed_at,
                "actor_id": args.actor_id,
                "input_text": input_text,
                "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
                "output_text": output_text,
                "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
                "result": result,
                "answerer_id": None,
                "reviewer_id": None,
                "answer_record_ids": [],
                "isolation": {
                    "answerer_blind_to_acceptance": False,
                    "reviewer_separate_from_answerer": False,
                },
                "scores": None,
            })
            if result != "passed":
                failures.append(record_id)
    registry = {
        "record_type": "RoleKnowledgeEvidenceRegistry",
        "schema_version": 1,
        "registry_id": (
            "rk-builtin-role-evidence" if catalog["origin"] == "builtin"
            else f"{catalog['catalog_id'][:54]}-evidence"
        ),
        "catalog_id": catalog["catalog_id"],
        "candidate_catalog_version": catalog["catalog_version"],
        "candidate_catalog_digest": rk.reviewable_catalog_digest(catalog),
        "frozen_at": executed_at,
        "records": records,
    }
    rk.validate_evidence_registry(registry, output_path)
    rk.atomic_json(output_path, registry, exclusive=True)
    print(f"DETERMINISTIC_EVIDENCE path={output_path} records={len(records)} failed={len(failures)}")
    if failures:
        print("FAILED_RECORDS " + ",".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except rk.RoleKnowledgeError as exc:
        print(f"ERROR {exc.code}: {exc.message}")
        raise SystemExit(2)
