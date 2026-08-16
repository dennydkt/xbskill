#!/usr/bin/env python3
"""Derive a reviewable role-knowledge candidate without copying old release claims."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

import role_knowledge as rk


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--catalog-version", required=True)
    args = parser.parse_args()

    catalog_path = rk.absolute_path(args.catalog, "--catalog")
    output_path = rk.absolute_path(args.output, "--output", must_exist=False)
    if output_path.suffix.lower() != ".json":
        rk.fail("E_OUTPUT", f"--output must end with .json: {output_path}")
    if output_path.parent.resolve() != catalog_path.parent.resolve():
        rk.fail(
            "E_PATH_BOUNDARY",
            "builtin candidate must remain beside its bound source registry during review",
        )
    if not rk.VERSION_RE.fullmatch(args.catalog_version):
        rk.fail("E_USAGE", "--catalog-version must be semantic x.y.z")

    source = rk.read_json(catalog_path)
    if source.get("record_type") != "RoleKnowledgeCatalog" or source.get("origin") != "builtin":
        rk.fail("E_CATALOG", "prepare_candidate currently accepts only the governed builtin role catalog")
    units = source.get("units")
    if not isinstance(units, list) or not units:
        rk.fail("E_CATALOG", "source catalog has no role-knowledge units")

    candidate = copy.deepcopy(source)
    candidate.pop("release_binding", None)
    candidate["catalog_version"] = args.catalog_version
    candidate["published_at"] = rk.now_utc()
    candidate["governance_complete"] = False
    for index, unit in enumerate(candidate["units"]):
        if not isinstance(unit, dict) or unit.get("status") not in {"active", "candidate"}:
            rk.fail("E_TEST_GATE", f"unit {index} cannot enter a new candidate review cycle")
        unit["status"] = "candidate"
        unit["tests"]["evidence_refs"] = []
        unit["review"] = {
            "status": "pending",
            "answerer_isolated": False,
            "reviewer_independent": False,
            "scores": {gate: 0 for gate in rk.SCORES},
            "evidence_refs": [],
            "reviewed_at": None,
            "reviewer_id": None,
        }

    rk.validate_catalog(candidate, output_path, enforce_release_gate=False)
    rk.atomic_json(output_path, candidate, exclusive=True)
    print(
        f"CANDIDATE_CREATED path={output_path} units={len(candidate['units'])} "
        f"reviewable_digest={rk.reviewable_catalog_digest(candidate)} old_evidence_reused=false"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except rk.RoleKnowledgeError as exc:
        print(f"ERROR {exc.code}: {exc.message}")
        raise SystemExit(2)
