#!/usr/bin/env python3
"""Build sanitized candidate packets for a blind answerer without exposing review criteria."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

import role_knowledge as rk


SPECIALISTS = {
    "data": "xb-data",
    "product_rd": "xb-it",
    "function": "xb-plan",
    "finance": "xb-analysis",
    "marketing": "xb-analysis",
}


def build_case(
    unit: dict[str, Any], runtime_units: list[dict[str, Any]], index: int, case_kind: str,
) -> dict[str, Any]:
    definitions = {
        "positive_s0": ("S0_new", unit["roles"][0], unit["tests"]["positive"][0], [unit["signals"]["include"][0]], "required",
                        "这是我第一次独立处理，请给我当前一步、完整权限链、停止/升级门和亲验点。"),
        "positive_s2": ("S2_system", unit["roles"][0], unit["tests"]["positive"][0], [unit["signals"]["include"][0]], "required",
                        "我已能独立处理常规情况，请给系统化判断、完整权限链、取舍、停止/升级门和回滚/治理点。"),
        "negative": ("S1_working", f"非{unit['roles'][0]}实际责任", unit["tests"]["negative"][0], [], "optional",
                     "职位名称可能相近，但这不是该岗位在本轮的实际责任；请判断是否应加载该岗位知识，不要硬套。"),
        "overturn": ("S1_working", unit["roles"][0], unit["tests"]["overturn"][0], [unit["signals"]["exclude"][0]], "optional",
                     "出现了会翻转原方法的新事实；请判断是否仍应使用该岗位知识，并保留未知与下一辨别点。"),
    }
    if case_kind not in definitions:
        rk.fail("E_TEST_GATE", f"unsupported blind case kind: {case_kind}")
    stage, role, problem, signals, requirement, help_request = definitions[case_kind]
    request = {
        "schema_version": 1,
        "current_specialist": SPECIALISTS[unit["job_family"]],
        "job_family": unit["job_family"],
        "role": role,
        "task_family": unit["task_families"][0],
        "lifecycle_stage": unit["lifecycle_stages"][0],
        "proficiency_mode": stage,
        "problem": problem,
        "signals": signals,
        "actual_constraints": copy.deepcopy(rk.governed_rule_scope_constraint(unit)),
        "knowledge_requirement": requirement,
        "required_unit_ids": [],
        "max_units": 1,
    }
    matched, notices = rk.match_units(runtime_units, request, [])
    packet = rk.build_packet(request, matched, notices)
    rk.validate_role_packet(packet)
    if case_kind in {"positive_s0", "positive_s2"} and packet["used_unit_ids"] != [unit["id"]]:
        rk.fail("E_TEST_GATE", f"{unit['id']} {case_kind} did not select exactly its target unit")
    if case_kind in {"negative", "overturn"} and (packet["status"] != "no_match" or packet["used_unit_ids"]):
        rk.fail("E_TEST_GATE", f"{unit['id']} {case_kind} did not freeze an explicit no_match result")
    prompt_role = unit["roles"][0] if case_kind != "negative" else f"职位名称接近{unit['roles'][0]}"
    return {
        "case_id": f"blind-{index:02d}-{case_kind.replace('_', '-')}",
        "case_kind": case_kind,
        "unit_id": unit["id"],
        "unit_version": unit["version"],
        "unit_digest": rk.reviewable_unit_digest(unit),
        "user_prompt": f"我是{prompt_role}，{problem}。{help_request}",
        "packet": packet,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--unit-id", action="append", default=[])
    args = parser.parse_args()
    catalog_path = rk.absolute_path(args.catalog, "--catalog")
    output_path = rk.absolute_path(args.output, "--output", must_exist=False)
    if output_path.suffix.lower() != ".json":
        rk.fail("E_OUTPUT", f"--output must end with .json: {output_path}")
    catalog = rk.read_json(catalog_path)
    project_root = rk.absolute_path(args.project_root, "--project-root", directory=True) if args.project_root else None
    if catalog.get("origin") == "project" and project_root is None:
        rk.fail("E_PROJECT_UNINITIALIZED", "building project blind fixtures requires its exact --project-root")
    if catalog.get("origin") != "project" and project_root is not None:
        rk.fail("E_USAGE", "--project-root is only valid for a project catalog")
    units = rk.validate_catalog(catalog, catalog_path, project_root, enforce_release_gate=False)
    if project_root is not None:
        for index, unit in enumerate(units):
            rk.validate_source_packet(
                unit, project_root, f"blind candidate units[{index}]", catalog["catalog_id"],
            )
    runtime_units = copy.deepcopy(units)
    for unit in runtime_units:
        if unit["status"] not in {"candidate", "active"}:
            rk.fail("E_TEST_GATE", f"blind fixture cannot use {unit['status']} unit {unit['id']}")
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
    cases: list[dict[str, Any]] = []
    for index, unit in enumerate(runtime_units, start=1):
        if unit["id"] not in selected_unit_ids:
            continue
        for case_kind in ("positive_s0", "positive_s2", "negative", "overturn"):
            cases.append(build_case(unit, runtime_units, index, case_kind))
    rk.atomic_json(output_path, {
        "record_type": "RoleKnowledgeBlindFixture",
        "schema_version": 1,
        "catalog_id": catalog["catalog_id"],
        "candidate_catalog_version": catalog["catalog_version"],
        "candidate_catalog_digest": rk.reviewable_catalog_digest(catalog),
        "cases": cases,
    }, exclusive=True)
    print(f"BLIND_FIXTURE path={output_path} cases={len(cases)} acceptance_criteria_included=false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except rk.RoleKnowledgeError as exc:
        print(f"ERROR {exc.code}: {exc.message}")
        raise SystemExit(2)
