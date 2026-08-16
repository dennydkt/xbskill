#!/usr/bin/env python3
"""Bind deterministic tests, blind answers, and independent reviews into one frozen registry."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import role_knowledge as rk


RUBRIC = rk.BLIND_REVIEW_RUBRIC


def exact(value: dict[str, Any], fields: set[str], context: str) -> None:
    rk.exact_fields(value, fields, context)


def text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def read(path: str, flag: str) -> tuple[Path, dict[str, Any]]:
    resolved = rk.absolute_path(path, flag)
    return resolved, rk.read_json(resolved)


def normalize_external_utc(value: Any, context: str) -> str:
    """Normalize a frozen reviewer timestamp without rewriting its source file."""

    if isinstance(value, str) and rk.UTC_TIMESTAMP_RE.fullmatch(value):
        return rk.utc_timestamp(value, context)
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,9}Z", value,
    ):
        rk.fail("E_SCHEMA", f"{context} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        rk.fail("E_SCHEMA", f"{context} is not a real UTC timestamp")
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deterministic", required=True)
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--answers", required=True)
    parser.add_argument("--reviews", required=True)
    parser.add_argument("--prior-failure-fixtures", action="append", default=[])
    parser.add_argument("--prior-failure-answers", action="append", default=[])
    parser.add_argument("--prior-failure-reviews", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    deterministic_path, deterministic = read(args.deterministic, "--deterministic")
    fixtures_path, fixtures = read(args.fixtures, "--fixtures")
    answers_path, answers = read(args.answers, "--answers")
    reviews_path, reviews = read(args.reviews, "--reviews")
    if len(args.prior_failure_fixtures) != len(args.prior_failure_answers):
        rk.fail("E_USAGE", "each prior failure fixtures file needs a paired answers file")
    output_path = rk.absolute_path(args.output, "--output", must_exist=False)
    if output_path.suffix.lower() != ".json":
        rk.fail("E_OUTPUT", f"--output must end with .json: {output_path}")

    deterministic_records = rk.validate_evidence_registry(deterministic, deterministic_path)
    if any(not record["kind"].startswith("deterministic_") for record in deterministic_records.values()):
        rk.fail("E_TEST_GATE", "--deterministic contains non-deterministic records")

    exact(fixtures, {
        "record_type", "schema_version", "catalog_id", "candidate_catalog_version",
        "candidate_catalog_digest", "cases",
    }, "blind fixtures")
    if fixtures["record_type"] != "RoleKnowledgeBlindFixture" or type(fixtures["schema_version"]) is not int or fixtures["schema_version"] != 1:
        rk.fail("E_TEST_GATE", "blind fixture type or schema version is invalid")
    for field in ("catalog_id", "candidate_catalog_version", "candidate_catalog_digest"):
        if fixtures[field] != deterministic[field]:
            rk.fail("E_TEST_GATE", f"blind fixtures.{field} differs from deterministic evidence")
    exact(answers, {"record_type", "schema_version", "answerer_id", "frozen_at", "cases"}, "blind answers")
    if answers["record_type"] != "RoleKnowledgeBlindAnswers" or type(answers["schema_version"]) is not int or answers["schema_version"] != 1:
        rk.fail("E_TEST_GATE", "blind answers type or schema version is invalid")
    answerer_id = rk.nonempty_string(answers["answerer_id"], "blind answers.answerer_id")
    if not rk.ID_RE.fullmatch(answerer_id):
        rk.fail("E_TEST_GATE", "blind answerer_id is invalid")
    answer_time = normalize_external_utc(answers["frozen_at"], "blind answers.frozen_at")
    exact(reviews, {"record_type", "schema_version", "reviewer_id", "reviewed_at", "cases"}, "blind reviews")
    if reviews["record_type"] != "RoleKnowledgeBlindReviews" or type(reviews["schema_version"]) is not int or reviews["schema_version"] != 1:
        rk.fail("E_TEST_GATE", "blind reviews type or schema version is invalid")
    reviewer_id = rk.nonempty_string(reviews["reviewer_id"], "blind reviews.reviewer_id")
    if not rk.ID_RE.fullmatch(reviewer_id) or reviewer_id == answerer_id:
        rk.fail("E_TEST_GATE", "reviewer must be a distinct stable id")
    reviewed_at = normalize_external_utc(reviews["reviewed_at"], "blind reviews.reviewed_at")

    fixture_map: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(fixtures["cases"]):
        context = f"blind fixtures.cases[{index}]"
        if not isinstance(case, dict):
            rk.fail("E_TEST_GATE", f"{context} must be an object")
        exact(case, {"case_id", "case_kind", "unit_id", "unit_version", "unit_digest", "user_prompt", "packet"}, context)
        case_id = rk.nonempty_string(case["case_id"], f"{context}.case_id")
        if case["case_kind"] not in rk.BLIND_SCENARIO_KINDS:
            rk.fail("E_TEST_GATE", f"{context}.case_kind is invalid")
        if case_id in fixture_map:
            rk.fail("E_TEST_GATE", f"duplicate blind fixture case {case_id}")
        rk.nonempty_string(case["user_prompt"], f"{context}.user_prompt")
        if not isinstance(case["packet"], dict):
            rk.fail("E_TEST_GATE", f"{context}.packet must be an object")
        rk.validate_role_packet(case["packet"])
        if case["case_kind"] in {"positive_s0", "positive_s2"}:
            if case["packet"]["used_unit_ids"] != [case["unit_id"]] or len(case["packet"]["matched_units"]) != 1:
                rk.fail("E_TEST_GATE", f"{context} positive case must select exactly its target unit")
            selected = case["packet"]["matched_units"][0]
            if case["unit_version"] != selected["version"]:
                rk.fail("E_TEST_GATE", f"{context} unit version differs from packet")
        elif case["packet"]["status"] != "no_match" or case["packet"]["used_unit_ids"]:
            rk.fail("E_TEST_GATE", f"{context} negative/overturn case must freeze an explicit no_match packet")
        if not isinstance(case["unit_digest"], str) or not rk.SHA256_RE.fullmatch(case["unit_digest"]):
            rk.fail("E_TEST_GATE", f"{context}.unit_digest is invalid")
        fixture_map[case_id] = case

    deterministic_bindings: dict[str, tuple[str, str]] = {}
    for record in deterministic_records.values():
        binding = (record["unit_version"], record["unit_digest"])
        existing = deterministic_bindings.setdefault(record["unit_id"], binding)
        if existing != binding:
            rk.fail("E_TEST_GATE", f"deterministic evidence has conflicting unit bindings for {record['unit_id']}")
    for case_id, case in fixture_map.items():
        if deterministic_bindings.get(case["unit_id"]) != (case["unit_version"], case["unit_digest"]):
            rk.fail("E_TEST_GATE", f"blind fixture {case_id} targets a different frozen unit than deterministic evidence")

    answer_map: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(answers["cases"]):
        context = f"blind answers.cases[{index}]"
        if not isinstance(case, dict):
            rk.fail("E_TEST_GATE", f"{context} must be an object")
        exact(case, {"case_id", "case_kind", "unit_id", "answer_text", "trace"}, context)
        case_id = rk.nonempty_string(case["case_id"], f"{context}.case_id")
        fixture = fixture_map.get(case_id)
        if fixture is None or case_id in answer_map:
            rk.fail("E_TEST_GATE", f"{context} is missing from fixtures or duplicated")
        expected_unit = fixture["unit_id"]
        if case["unit_id"] != expected_unit or case["case_kind"] != fixture["case_kind"]:
            rk.fail("E_TEST_GATE", f"{context}.unit_id differs from packet")
        rk.nonempty_string(case["answer_text"], f"{context}.answer_text")
        if fixture["case_kind"] in {"positive_s0", "positive_s2"}:
            if not isinstance(case["trace"], dict):
                rk.fail("E_TEST_GATE", f"{context}.trace must be an object for an active packet")
            rk.validate_trace(fixture["packet"], case["trace"], case["answer_text"])
        else:
            if case["trace"] is not None:
                rk.fail("E_TEST_GATE", f"{context}.trace must be null when no role knowledge matched")
            rk.validate_no_match_delivery(fixture["packet"], case["answer_text"])
        answer_map[case_id] = case

    review_map: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(reviews["cases"]):
        context = f"blind reviews.cases[{index}]"
        if not isinstance(case, dict):
            rk.fail("E_TEST_GATE", f"{context} must be an object")
        exact(case, {"case_id", "case_kind", "unit_id", "answerer_id", "scores", "rationale", "verdict"}, context)
        case_id = rk.nonempty_string(case["case_id"], f"{context}.case_id")
        if case_id in review_map or case_id not in fixture_map or case_id not in answer_map:
            rk.fail("E_TEST_GATE", f"{context} is missing from source cases or duplicated")
        if case["unit_id"] != fixture_map[case_id]["unit_id"] or case["case_kind"] != fixture_map[case_id]["case_kind"] or case["answerer_id"] != answerer_id:
            rk.fail("E_TEST_GATE", f"{context} unit or answerer binding is invalid")
        scores = case["scores"]
        if not isinstance(scores, dict) or set(scores) != set(rk.SCORES):
            rk.fail("E_TEST_GATE", f"{context}.scores must contain exactly {list(rk.SCORES)}")
        if any(type(scores[key]) is not int or scores[key] not in {0, 1, 2} for key in rk.SCORES):
            rk.fail("E_TEST_GATE", f"{context}.scores must contain integers 0-2")
        rk.nonempty_string(case["rationale"], f"{context}.rationale")
        if case["verdict"] not in {"pass", "fail", "passed", "failed"}:
            rk.fail("E_TEST_GATE", f"{context}.verdict is invalid")
        normalized_verdict = "passed" if case["verdict"] in {"pass", "passed"} else "failed"
        if (normalized_verdict == "passed") != all(scores[key] == 2 for key in rk.SCORES):
            rk.fail("E_TEST_GATE", f"{context}.verdict contradicts all-two scores")
        review_map[case_id] = {
            **case,
            "raw_verdict": case["verdict"],
            "verdict": normalized_verdict,
        }

    expected_cases = set(fixture_map)
    if set(answer_map) != expected_cases or set(review_map) != expected_cases:
        rk.fail("E_TEST_GATE", "fixtures, answers, and reviews do not cover the same case ids")
    blind_coverage: dict[str, set[str]] = {}
    blind_case_counts: dict[str, int] = {}
    for case in fixture_map.values():
        blind_coverage.setdefault(case["unit_id"], set()).add(case["case_kind"])
        blind_case_counts[case["unit_id"]] = blind_case_counts.get(case["unit_id"], 0) + 1
    missing_coverage = {
        unit_id: sorted(rk.BLIND_SCENARIO_KINDS - kinds)
        for unit_id, kinds in blind_coverage.items()
        if kinds != rk.BLIND_SCENARIO_KINDS or blind_case_counts[unit_id] != len(rk.BLIND_SCENARIO_KINDS)
    }
    if missing_coverage or set(blind_coverage) != set(deterministic_bindings):
        rk.fail("E_TEST_GATE", f"blind fixtures lack four-case coverage for every unit: missing={missing_coverage}")

    records = list(deterministic["records"])
    prior_review_map: dict[tuple[str, str], dict[str, Any]] = {}
    prior_review_files: dict[tuple[str, str], tuple[Path, str, str]] = {}
    for review_arg in args.prior_failure_reviews:
        prior_review_path, prior_reviews = read(review_arg, "--prior-failure-reviews")
        exact(prior_reviews, {"record_type", "schema_version", "reviewer_id", "reviewed_at", "cases"}, "prior blind reviews")
        reviewer = rk.nonempty_string(prior_reviews["reviewer_id"], "prior blind reviews.reviewer_id")
        reviewed = normalize_external_utc(prior_reviews["reviewed_at"], "prior blind reviews.reviewed_at")
        review_digest = hashlib.sha256(prior_review_path.read_bytes()).hexdigest()
        for review_case in prior_reviews["cases"]:
            key = (review_case["answerer_id"], review_case["case_id"])
            if key in prior_review_map:
                rk.fail("E_TEST_GATE", f"duplicate prior review binding for {key}")
            prior_review_map[key] = review_case
            prior_review_files[key] = (prior_review_path, review_digest, reviewed)

    for round_index, (fixture_arg, answer_arg) in enumerate(
        zip(args.prior_failure_fixtures, args.prior_failure_answers), start=1,
    ):
        prior_fixture_path, prior_fixtures = read(fixture_arg, "--prior-failure-fixtures")
        prior_answers_path, prior_answers = read(answer_arg, "--prior-failure-answers")
        if prior_fixtures.get("record_type") != "RoleKnowledgeBlindFixture" or type(prior_fixtures.get("schema_version")) is not int or prior_fixtures.get("schema_version") != 1:
            rk.fail("E_TEST_GATE", f"prior round {round_index} fixture type/schema is invalid")
        exact(prior_answers, {"record_type", "schema_version", "answerer_id", "frozen_at", "cases"}, "prior blind answers")
        prior_answerer = rk.nonempty_string(prior_answers["answerer_id"], "prior blind answers.answerer_id")
        prior_time = normalize_external_utc(prior_answers["frozen_at"], "prior blind answers.frozen_at")
        prior_fixture_map = {case["case_id"]: case for case in prior_fixtures["cases"]}
        prior_answer_map = {case["case_id"]: case for case in prior_answers["cases"]}
        if len(prior_fixture_map) != len(prior_fixtures["cases"]) or set(prior_fixture_map) != set(prior_answer_map):
            rk.fail("E_TEST_GATE", f"prior blind failure round {round_index} cases are duplicated or misaligned")
        prior_fixture_digest = hashlib.sha256(prior_fixture_path.read_bytes()).hexdigest()
        prior_answers_digest = hashlib.sha256(prior_answers_path.read_bytes()).hexdigest()
        for case_id in sorted(prior_fixture_map):
            fixture = prior_fixture_map[case_id]
            answer = prior_answer_map[case_id]
            unit_id = answer["unit_id"]
            scenario_kind = fixture.get("case_kind") or (
                "positive_s0" if fixture["packet"]["request"]["proficiency_mode"] == "S0_new" else "positive_s2"
            )
            if scenario_kind in {"positive_s0", "positive_s2"}:
                if fixture.get("packet", {}).get("used_unit_ids") != [unit_id]:
                    rk.fail("E_TEST_GATE", f"prior failure {case_id} positive unit binding is invalid")
                selected_unit = fixture["packet"]["matched_units"][0]
                unit_version = selected_unit["version"]
            else:
                if fixture.get("packet", {}).get("status") != "no_match" or fixture["packet"].get("used_unit_ids"):
                    rk.fail("E_TEST_GATE", f"prior failure {case_id} negative/overturn packet is not no_match")
                unit_version = fixture.get("unit_version") or deterministic_bindings.get(unit_id, (None, None))[0]
                selected_unit = {"id": unit_id, "version": unit_version, "no_match": True}
            unit_digest = fixture.get("unit_digest") or deterministic_bindings.get(unit_id, (None, None))[1]
            if not isinstance(unit_digest, str) or not rk.SHA256_RE.fullmatch(unit_digest):
                unit_digest = rk.canonical_digest(selected_unit)
            review = prior_review_map.get((prior_answerer, case_id))
            review_binding = prior_review_files.get((prior_answerer, case_id))
            input_text = text({
                "fixture_file": str(prior_fixture_path),
                "fixture_file_sha256": prior_fixture_digest,
                "case": fixture,
            })
            output_value: dict[str, Any] = {
                "answers_file": str(prior_answers_path),
                "answers_file_sha256": prior_answers_digest,
                "raw_answer": answer,
                "frozen_validation_result": "failed",
            }
            if review is None:
                output_value["frozen_validation_error"] = (
                    "ApplicationTrace failed the then-current mechanical contract before review; "
                    "the frozen answer was not patched."
                )
            else:
                output_value["independent_review"] = review
                output_value["review_file"] = str(review_binding[0])
                output_value["review_file_sha256"] = review_binding[1]
            output_text = text(output_value)
            record_hash = rk.canonical_digest({"round": round_index, "case": case_id, "unit": unit_id})[:12]
            records.append({
                "id": f"blind-failure-{record_hash}",
                "unit_id": unit_id,
                "unit_version": unit_version,
                "unit_digest": unit_digest,
                "kind": "blind_failure",
                "scenario_kind": scenario_kind,
                "executed_at": prior_time,
                "actor_id": prior_answerer,
                "input_text": input_text,
                "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
                "output_text": output_text,
                "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
                "result": "failed",
                "answerer_id": prior_answerer,
                "reviewer_id": None,
                "answer_record_ids": [],
                "isolation": {"answerer_blind_to_acceptance": True, "reviewer_separate_from_answerer": False},
                "scores": None,
            })
    failed_reviews: list[str] = []
    for case_id in sorted(expected_cases):
        fixture = fixture_map[case_id]
        answer = answer_map[case_id]
        review = review_map[case_id]
        unit_id = answer["unit_id"]
        unit_version = fixture["unit_version"]
        unit_digest = fixture["unit_digest"]
        scenario_kind = fixture["case_kind"]
        record_hash = rk.canonical_digest({"case": case_id, "unit": unit_id, "answerer": answerer_id})[:16]
        answer_record_id = f"blind-answer-{record_hash}"
        review_record_id = f"blind-review-{record_hash}"
        answer_input = text({
            "fixture_file": str(fixtures_path),
            "fixture_file_sha256": hashlib.sha256(fixtures_path.read_bytes()).hexdigest(),
            "case": fixture,
        })
        answer_output = text({"answer_text": answer["answer_text"], "trace": answer["trace"]})
        records.append({
            "id": answer_record_id,
            "unit_id": unit_id,
            "unit_version": unit_version,
            "unit_digest": unit_digest,
            "kind": "blind_answer",
            "scenario_kind": scenario_kind,
            "executed_at": answer_time,
            "actor_id": answerer_id,
            "input_text": answer_input,
            "input_sha256": hashlib.sha256(answer_input.encode("utf-8")).hexdigest(),
            "output_text": answer_output,
            "output_sha256": hashlib.sha256(answer_output.encode("utf-8")).hexdigest(),
            "result": "frozen",
            "answerer_id": answerer_id,
            "reviewer_id": None,
            "answer_record_ids": [],
            "isolation": {"answerer_blind_to_acceptance": True, "reviewer_separate_from_answerer": False},
            "scores": None,
        })
        review_input = text({
            "rubric": RUBRIC,
            "scenario_kind": scenario_kind,
            "answer_record_id": answer_record_id,
            "answer_output_sha256": hashlib.sha256(answer_output.encode("utf-8")).hexdigest(),
        })
        review_output = text({
            "case_id": case_id,
            "rationale": review["rationale"],
            "scores": review["scores"],
            "raw_verdict": review["raw_verdict"],
            "normalized_result": review["verdict"],
        })
        records.append({
            "id": review_record_id,
            "unit_id": unit_id,
            "unit_version": unit_version,
            "unit_digest": unit_digest,
            "kind": "independent_review",
            "scenario_kind": scenario_kind,
            "executed_at": reviewed_at,
            "actor_id": reviewer_id,
            "input_text": review_input,
            "input_sha256": hashlib.sha256(review_input.encode("utf-8")).hexdigest(),
            "output_text": review_output,
            "output_sha256": hashlib.sha256(review_output.encode("utf-8")).hexdigest(),
            "result": review["verdict"],
            "answerer_id": answerer_id,
            "reviewer_id": reviewer_id,
            "answer_record_ids": [answer_record_id],
            "isolation": {"answerer_blind_to_acceptance": True, "reviewer_separate_from_answerer": True},
            "scores": review["scores"],
        })
        if review["verdict"] != "passed":
            failed_reviews.append(case_id)

    registry = {
        "record_type": "RoleKnowledgeEvidenceRegistry",
        "schema_version": 1,
        "registry_id": deterministic["registry_id"],
        "catalog_id": deterministic["catalog_id"],
        "candidate_catalog_version": deterministic["candidate_catalog_version"],
        "candidate_catalog_digest": deterministic["candidate_catalog_digest"],
        "frozen_at": reviewed_at,
        "records": records,
    }
    rk.validate_evidence_registry(registry, output_path)
    rk.atomic_json(output_path, registry, exclusive=True)
    print(
        f"EVIDENCE_ASSEMBLED path={output_path} records={len(records)} "
        f"failed_reviews={len(failed_reviews)} answers_sha256={hashlib.sha256(answers_path.read_bytes()).hexdigest()} "
        f"reviews_sha256={hashlib.sha256(reviews_path.read_bytes()).hexdigest()}"
    )
    if failed_reviews:
        print("FAILED_BLIND_CASES " + ",".join(failed_reviews))
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except rk.RoleKnowledgeError as exc:
        print(f"ERROR {exc.code}: {exc.message}")
        raise SystemExit(2)
