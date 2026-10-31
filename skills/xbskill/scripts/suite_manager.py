#!/usr/bin/env python3
"""Validate, compare, update, and restore the xbskill suite.

The suite root is the directory containing xbskill/ and xb-*/ directories.
Only those directories are managed. LOCAL-* files are always preserved.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath


MANIFEST = "xbskill/manifest.json"
MANAGED_RE = re.compile(r"^xb(?:skill|-[a-z0-9-]+)$")
NAME_RE = re.compile(r"^name:\s*([a-z0-9-]+)\s*$", re.MULTILINE)
ROUTE_RE = re.compile(r"`(xb-[a-z0-9-]+)`")
UI_STRING_RE = re.compile(r'^\s{2}([a-z_]+):\s*"([^"\n]+)"\s*$', re.MULTILINE)
DEPENDENCY_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:\.\./xbskill/(?:references|scripts)|(?:references|scripts))/[A-Za-z0-9._/-]+\.(?:md|json|py))"
)
CORE_REFERENCES = (
    "interaction-settings.md",
    "community-support.md",
    "work-model.md",
    "agency-model.md",
    "goal-help-model.md",
    "capability-model.md",
    "routing.md",
    "contracts.md",
    "context-protocol.md",
    "common-scenarios.md",
    "system-design.md",
    "resolution-standard.md",
    "intellectual-capabilities.md",
    "knowledge-source-protocol.md",
    "runtime-compatibility.md",
    "knowledge-source.schema.json",
    "workplace-regression.md",
    "specialist-rewrite-method.md",
    "dbs-reuse-case.md",
    "task-domain-patterns.md",
    "people-domain-patterns.md",
    "specialist-regression.md",
    "v0.5-forward-test-record.md",
    "role-context-model.md",
    "data-work-specialties.md",
    "product-rd-specialties.md",
    "function-work-specialties.md",
    "finance-marketing-specialties.md",
    "organization-strategy-genome.md",
    "specialty-source-ledger.md",
    "role-specialty-regression.md",
    "v0.7-role-forward-test-record.md",
    "v0.8-role-knowledge-forward-test-record.md",
    "v0.9-role-source-update-record.md",
    "v1.0-output-collab-blind-answers.md",
    "v1.0-output-collab-independent-review.md",
    "v1.0-output-collab-release-record.md",
)

OUTPUT_COLLAB_CASE_IDS = tuple(f"X{i:02d}" for i in range(13, 20))
OUTPUT_COLLAB_EVIDENCE_FILES = (
    "v1.0-output-collab-blind-answers.md",
    "v1.0-output-collab-independent-review.md",
    "v1.0-output-collab-release-record.md",
)
COPY_FORBIDDEN_RE = re.compile(
    r"不是.*而是|不在于|不需要.*需要|不会.*会|真正的|与其说"
)
UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
CASE_HEADING_RE = re.compile(r"^##\s+(X\d{2})\s*$", re.MULTILINE)
TWO_NO_RESPONSE_RE = re.compile(r"(?:两次|2\s*次).{0,18}(?:无回应|未回应|未回复|没回复|不回|没回)")

CRITICAL_MANIFEST_FILES = frozenset(
    {
        "xb-config/SKILL.md",
        "xb-config/references/config-contract.md",
        "xb-config/references/configuration-guide.md",
        "xb-config/references/spirit-sync.md",
        "xb-config/references/spirit-mindset.md",
        "xb-config/references/spirit-communication.md",
        "xb-config/references/spirit-context.md",
        "xb-config/references/spirit-sources.md",
        "xbskill/references/community-support.md",
        "xb-config/scripts/config_manager.py",
        "xb-config/scripts/test_config.py",
        "xbskill/references/specialty-source-ledger.md",
        "xb-role-knowledge/references/builtin-source-registry.json",
        "xb-role-knowledge/references/builtin-source-registry.schema.json",
        "xb-role-knowledge/references/upstream-role-sources.json",
        "xb-role-knowledge/references/upstream-role-sources.schema.json",
        "xb-role-knowledge/references/builtin-role-knowledge.json",
        "xb-role-knowledge/references/candidate-role-knowledge-round9.json",
        "xb-role-knowledge/references/role-knowledge-regression.json",
        "xb-role-knowledge/references/role-knowledge.schema.json",
        "xb-role-knowledge/references/role-knowledge-runtime.schema.json",
        "xb-role-knowledge/references/role-knowledge-evidence.schema.json",
        "xb-role-knowledge/references/round9-failed-evidence/rk-deterministic-evidence-20260811-round9-diff.json",
        "xb-role-knowledge/references/round9-failed-evidence/rk-blind-fixtures-20260811-round9-diff.json",
        "xb-role-knowledge/references/round9-failed-evidence/rk-blind-answers-20260811-round9-diff.json",
        "xb-role-knowledge/references/round9-failed-evidence/rk-blind-reviews-20260811-round9-diff.json",
        "xb-role-knowledge/scripts/role_knowledge.py",
        "xb-role-knowledge/scripts/deterministic_test.py",
        "xb-role-knowledge/scripts/blind_fixture.py",
        "xb-role-knowledge/scripts/assemble_evidence.py",
        "xb-role-knowledge/scripts/prepare_candidate.py",
        "xb-role-knowledge/scripts/activate_catalog.py",
        "xb-role-knowledge/scripts/merge_incremental_evidence.py",
        "xb-role-knowledge/scripts/upstream_sync.py",
    }
)

DEPTH_ANCHORS: dict[str, tuple[str, ...]] = {
    "xb-config": ("目标与边界", "初始化与修改", "调用门与用户选择", "样本与反馈"),
    "xb-sync": ("核心模型", "观察字段与竞争解释", "分支闸门", "正例、反例与边界例", "验证、失败与翻转"),
    "xb-triage": ("症状—候选解释词典", "分支与阈值", "归因记录卡", "边界例", "完成与回流"),
    "xb-goal": ("目标信号与竞争解释", "分支规则", "微型边界例", "现实验证"),
    "xb-plan": ("计划失效信号", "工作包与依赖规则", "决策分支", "微型边界例", "现实回流"),
    "xb-action": ("阻力信号词典", "六类主分支", "最小实验合同", "微型边界例", "复发控制"),
    "xb-capability": ("能力证据模型", "常见误判与辨别", "判级规则", "分支与案例", "微型边界例"),
    "xb-analysis": ("因果公理", "最小观察信号", "分支规则", "正例、反例与边界例", "现实验证与回流"),
    "xb-learning": ("能力因果模型", "材料与权限门", "分支规则", "正例、反例与边界例", "现实验证与回流"),
    "xb-decision": ("决策公理与因果模型", "四类信息分账", "分支规则", "正例、反例与边界例", "现实验证、翻转与回流"),
    "xb-it": ("核心判断模型", "信号词典", "模式与条件分支", "案例校准", "结果回流"),
    "xb-data": ("核心判断模型", "信号词典", "模式与条件分支", "案例校准", "结果回流"),
    "xb-automation": ("核心判断模型", "信号词典", "模式与条件分支", "案例校准", "结果回流"),
    "xb-writing": ("核心质量模型", "信号词典", "模式判断", "案例校准", "结果回流"),
    "xb-presentation": ("核心质量模型", "信号词典", "模式与叙事分支", "案例校准", "结果回流"),
    "xb-report": ("核心判断模型", "信号词典", "报告模式", "案例校准", "结果回流"),
    "xb-review": ("核心判断模型", "信号词典", "模式与条件分支", "案例校准", "结果回流"),
    "xb-meeting": ("触发与核心模型", "可观察信号词典", "模式与条件分支", "微型例", "验证、失败与翻转"),
    "xb-talk": ("触发与核心模型", "可观察信号词典", "模式与条件分支", "微型例", "验证、失败与翻转"),
    "xb-upward": ("触发与权力模型", "可观察信号词典", "模式与条件分支", "微型例", "验证、失败与翻转"),
    "xb-anti-blame": ("核心模型：归责主张协议", "观察字段与竞争解释", "模式与条件分支", "正例、反例与边界例", "验证、失败与翻转"),
    "xb-stakeholder": ("触发与权力模型", "可观察信号词典", "模式与条件分支", "微型分支", "验证、失败与翻转"),
    "xb-conflict": ("触发与核心因果模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-boundary": ("触发与核心因果模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-people": ("触发与核心因果模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-company": ("触发与核心系统模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-wellbeing": ("触发与核心因果模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-career": ("触发与核心职业模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-role-knowledge": ("触发与核心模型", "可观察信号词典", "岗位知识参与闭环", "匹配与条件分支", "验证、失败与翻转"),
    "xb-memory": ("触发与核心模型", "可观察信号词典", "模式与条件分支", "正例、反例与边界例", "验证、失败与翻转"),
    "xb-lucky": ("调起授权卡", "心理安全四条硬约束", "功能分层与路由边界", "信息、权限与竞争解释", "正例、反例与边界例"),
}

TASK_DEPTH_SKILLS = {
    "xb-it", "xb-data", "xb-automation", "xb-writing", "xb-presentation", "xb-report", "xb-review"
}
PEOPLE_DEPTH_SKILLS = {
    "xb-meeting", "xb-talk", "xb-upward", "xb-stakeholder", "xb-conflict", "xb-anti-blame",
    "xb-boundary", "xb-people", "xb-company", "xb-wellbeing", "xb-career",
}


def fail(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def root_path(raw: str, must_exist: bool = True) -> Path:
    path = Path(raw).expanduser().resolve()
    if must_exist and not path.is_dir():
        fail(f"skills root does not exist: {path}")
    if path.name in {"xbskill"} or path.name.startswith("xb-"):
        fail(f"expected the parent skills root, not a skill directory: {path}")
    return path


def skill_dirs(root: Path) -> list[Path]:
    managed = []
    for path in root.iterdir():
        if not MANAGED_RE.fullmatch(path.name):
            continue
        if is_link_or_reparse(path):
            fail(f"managed skill root is a link or reparse point: {path}")
        if not path.is_dir():
            fail(f"managed skill root is not a directory: {path}")
        managed.append(path)
    return sorted(managed, key=lambda p: p.name)


def is_local(rel: str) -> bool:
    return any(part.upper().startswith("LOCAL-") for part in Path(rel).parts)


def is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def assert_no_managed_symlinks(root: Path) -> None:
    """Reject symlinks, junctions, and reparse points anywhere in managed skill trees."""
    for entry in root.iterdir():
        if not MANAGED_RE.fullmatch(entry.name):
            continue
        if is_link_or_reparse(entry):
            fail(f"managed skill root is a link or reparse point: {entry}")
        if not entry.is_dir():
            fail(f"managed skill root is not a directory: {entry}")
        pending = [entry]
        while pending:
            directory = pending.pop()
            try:
                children = list(directory.iterdir())
            except OSError as exc:
                fail(f"cannot inspect managed skill path {directory}: {exc}")
            for child in children:
                if is_link_or_reparse(child):
                    fail(f"managed skill tree contains a link or reparse point: {child}")
                if child.is_dir():
                    pending.append(child)


def validate_manifest_relpath(root: Path, rel: str) -> Path:
    """Validate a manifest path and prove its resolved destination stays under root."""
    if not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel:
        fail(f"invalid manifest path: {rel!r}")
    parts = rel.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        fail(f"invalid manifest path: {rel!r}")
    parsed = PurePosixPath(rel)
    if parsed.is_absolute() or len(parts) < 2 or not MANAGED_RE.fullmatch(parts[0]):
        fail(f"manifest path is outside managed skill roots: {rel!r}")
    if rel == MANIFEST:
        fail(f"manifest must not list itself: {rel!r}")
    candidate = root.joinpath(*parts)
    root_resolved = root.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        fail(f"manifest path escapes skills root: {rel!r}")
    return candidate


def managed_path(root: Path, rel: str) -> Path:
    """Resolve a validated managed path while refusing root escapes and link parents."""
    candidate = validate_manifest_relpath(root, rel)
    if is_link_or_reparse(candidate):
        fail(f"managed destination is a link or reparse point: {candidate}")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        fail(f"managed path escapes skills root: {rel!r}")
    return candidate


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def current_manifest(root: Path) -> dict:
    assert_no_managed_symlinks(root)
    version_file = root / "xbskill" / "VERSION"
    if not version_file.is_file():
        fail(f"missing version file: {version_file}")
    files: dict[str, str] = {}
    for directory in skill_dirs(root):
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel == MANIFEST or is_local(rel) or "__pycache__" in path.parts:
                continue
            files[rel] = digest(path)
    return {
        "schema": 1,
        "version": version_file.read_text(encoding="utf-8").strip(),
        "files": files,
    }


def load_manifest(root: Path) -> dict:
    assert_no_managed_symlinks(root)
    path = root / MANIFEST
    if is_link_or_reparse(path):
        fail(f"suite manifest must be a regular file, not a link or reparse point: {path}")
    if not path.is_file():
        fail(f"required suite manifest is missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid manifest {path}: {exc}")
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("files"), dict):
        fail(f"unsupported manifest schema: {path}")
    for rel, file_digest in data["files"].items():
        validate_manifest_relpath(root, rel)
        if not isinstance(file_digest, str) or not SHA256_RE.fullmatch(file_digest):
            fail(f"invalid manifest digest for {rel!r}: {file_digest!r}")
    return data


def write_manifest(root: Path) -> None:
    data = current_manifest(root)
    path = root / MANIFEST
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"WROTE {path} ({len(data['files'])} managed files)")


def _field(text: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}:\s*(\S.*)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _case_sections(text: str) -> tuple[dict[str, str], list[str]]:
    matches = list(CASE_HEADING_RE.finditer(text))
    sections: dict[str, str] = {}
    duplicates: list[str] = []
    for index, match in enumerate(matches):
        case_id = match.group(1)
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if case_id in sections:
            duplicates.append(case_id)
        else:
            sections[case_id] = text[match.end():body_end]
    return sections, duplicates


def _validate_output_collab_evidence(references: Path, errors: list[str]) -> None:
    answers_path, review_path, record_path = (
        references / filename for filename in OUTPUT_COLLAB_EVIDENCE_FILES
    )
    if not all(path.is_file() for path in (answers_path, review_path, record_path)):
        return

    try:
        answers = answers_path.read_text(encoding="utf-8")
        review = review_path.read_text(encoding="utf-8")
        record = record_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read output/collaboration release evidence: {exc}")
        return

    answerer = _field(answers, "Answerer")
    frozen_at = _field(answers, "Frozen-At")
    reviewer = _field(review, "Reviewer")
    reviewed_answerer = _field(review, "Answerer")
    reviewed_at = _field(review, "Reviewed-At")
    designer = _field(record, "Designer")
    record_answerer = _field(record, "Answerer")
    record_reviewer = _field(record, "Reviewer")
    designer_patched = _field(record, "Designer-Patched-Frozen-Answers")

    identities = (answerer, reviewer, designer)
    if any(not identity for identity in identities):
        errors.append("output/collaboration evidence misses Answerer, Reviewer, or Designer identity")
    elif len(set(identities)) != 3:
        errors.append("output/collaboration answerer, reviewer, and designer must be three different identities")
    if designer != "root":
        errors.append("output/collaboration release record Designer must be root")
    if reviewed_answerer != answerer or record_answerer != answerer or record_reviewer != reviewer:
        errors.append("output/collaboration evidence identity chain is inconsistent")
    if designer_patched != "false":
        errors.append("designer must not patch frozen output/collaboration answers")
    for label, value in (("Frozen-At", frozen_at), ("Reviewed-At", reviewed_at)):
        if not value or not UTC_TIMESTAMP_RE.fullmatch(value):
            errors.append(f"output/collaboration {label} must be an explicit UTC timestamp ending in Z")

    expected = set(OUTPUT_COLLAB_CASE_IDS)
    answer_sections, answer_duplicates = _case_sections(answers)
    review_sections, review_duplicates = _case_sections(review)
    for label, sections, duplicates in (
        ("answers", answer_sections, answer_duplicates),
        ("review", review_sections, review_duplicates),
    ):
        actual = set(sections)
        if actual != expected:
            errors.append(
                f"output/collaboration {label} case coverage must be exactly X13-X19; "
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )
        if duplicates:
            errors.append(f"output/collaboration {label} repeats case ids: {sorted(set(duplicates))}")
    for case_id in OUTPUT_COLLAB_CASE_IDS:
        if not answer_sections.get(case_id, "").strip():
            errors.append(f"output/collaboration {case_id} frozen answer is empty")
        section = review_sections.get(case_id, "")
        if "G/C/A/P/S/E/R/V: 2/2/2/2/2/2/2/2" not in section:
            errors.append(f"output/collaboration {case_id} does not pass every G/C/A/P/S/E/R/V gate")
        if not re.search(r"^Verdict:\s*pass\s*$", section, re.MULTILINE):
            errors.append(f"output/collaboration {case_id} review verdict is not pass")
        if not re.search(r"^Release:\s*allow\s*$", section, re.MULTILINE):
            errors.append(f"output/collaboration {case_id} is not explicitly allowed for release")

    answers_sha = _field(record, "Answers-SHA256")
    review_sha = _field(record, "Review-SHA256")
    actual_answers_sha = digest(answers_path)
    actual_review_sha = digest(review_path)
    if not answers_sha or not SHA256_RE.fullmatch(answers_sha) or answers_sha.lower() != actual_answers_sha:
        errors.append(
            f"output/collaboration Answers-SHA256 mismatch: recorded={answers_sha!r} actual={actual_answers_sha}"
        )
    if not review_sha or not SHA256_RE.fullmatch(review_sha) or review_sha.lower() != actual_review_sha:
        errors.append(
            f"output/collaboration Review-SHA256 mismatch: recorded={review_sha!r} actual={actual_review_sha}"
        )

    required_record_fields = {
        "Initial-Structure-Audit": "xb-presentation V=1; xb-report V=1; xb-talk E=1,V=1",
        "Case-Map": (
            "X13=xb-presentation; X14=xb-presentation; X15=xb-report; "
            "X16=xb-report; X17=xb-talk; X18=xb-talk; X19=xb-talk"
        ),
        "Failure-Writeback": "complete",
        "Final-Gates": "G=2,C=2,A=2,P=2,S=2,E=2,R=2,V=2",
        "High-Total-Override": "forbidden",
    }
    for name, expected_value in required_record_fields.items():
        if _field(record, name) != expected_value:
            errors.append(
                f"output/collaboration release record must preserve {name}: {expected_value}"
            )


def _validate_output_collab_behavior(root: Path, errors: list[str]) -> None:
    for skill_name in ("xb-writing", "xb-presentation"):
        skill = root / skill_name / "SKILL.md"
        if skill.is_file():
            match = COPY_FORBIDDEN_RE.search(skill.read_text(encoding="utf-8"))
            if match:
                errors.append(
                    f"forbidden copy pattern {match.group(0)!r} remains in output specialist: {skill}"
                )

    talk_path = root / "xb-talk" / "SKILL.md"
    if not talk_path.is_file():
        return
    talk = talk_path.read_text(encoding="utf-8")
    for sentence in re.split(r"[。！？\n]", talk):
        if not (TWO_NO_RESPONSE_RE.search(sentence) and "升级" in sentence):
            continue
        safeguards = (
            "不能单独触发升级", "不得单独触发升级", "不可单独触发升级",
            "只作轨迹证据", "只记录沟通轨迹", "只作证据",
        )
        if not any(term in sentence for term in safeguards):
            errors.append(
                f"xb-talk still treats two non-responses as an independent escalation gate: {talk_path}"
            )
            break
    semantic_groups = {
        "explicit reply point or deadline": ("回复点", "截止"),
        "waiting window": ("等待窗口",),
        "reachable channel": ("接收渠道已确认可用", "渠道是否可接收", "送达证据"),
        "counterparty authority": ("对方有权", "回应权限"),
        "count cannot independently trigger escalation": (
            "次数只作轨迹证据", "次数只记录沟通轨迹", "次数只作证据", "次数不能单独触发升级"
        ),
        "low-risk confirmation when no reply point exists": (
            "未约定回复点时，先给低风险确认", "尚未约定回复点时，先建立低风险确认点",
            "缺少回复点时，先发低风险确认"
        ),
    }
    for label, alternatives in semantic_groups.items():
        if not any(term in talk for term in alternatives):
            errors.append(f"xb-talk misses {label}: {talk_path}")


def validate_display_name(name: str, display_name: str, ui: Path,
                          seen: dict[str, Path], errors: list[str]) -> None:
    if not display_name:
        return
    if name == "xbskill":
        if display_name != "xbskill 主入口｜从这里开始":
            errors.append(f"root display_name must identify the unique main entry: {ui}")
    else:
        prefix = f"{name} 设置｜" if name == "xb-config" else f"{name} 子技能｜"
        if not display_name.startswith(prefix) or not display_name[len(prefix):].strip():
            errors.append(f"specialist display_name must start with canonical name and role {prefix!r}: {ui}")
        if "主入口" in display_name or display_name.startswith("xbskill"):
            errors.append(f"specialist display_name cannot impersonate main entry: {ui}")
    if display_name in seen:
        errors.append(f"duplicate display_name {display_name!r}: {seen[display_name]} and {ui}")
    else:
        seen[display_name] = ui


def validate_configuration_guide(root: Path, errors: list[str]) -> None:
    path = root / "xb-config" / "references" / "configuration-guide.md"
    if not path.is_file():
        errors.append(f"missing required configuration guide: {path}")
        return
    text = path.read_text(encoding="utf-8")
    start, end = "<!-- concise-start -->", "<!-- concise-end -->"
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) >= text.index(end):
        errors.append(f"configuration guide misses concise default block: {path}")
    else:
        short = text.split(start, 1)[1].split(end, 1)[0].strip()
        if len(short) > 520 or sum(line.startswith("- **") for line in short.splitlines()) != 5:
            errors.append(f"configuration default exceeds concise five-option budget: {path}")
        if not all(term in short for term in ("直接使用 XB", "先征求你同意", "明确说用 XB", "要求保存后才写入", "平时不提醒", "省去确认", "多一次确认", "容易错过", "保存很重要", "减少重述", "换聊天丢失", "敏感内容", "读取记录")):
            errors.append(f"configuration concise default loses behavioral explanation: {path}")
    groups = {
        "explain before choice": ("说明与选项一并出现", "无默认值", "无推荐预选"),
        "same task three outcomes": ("帮我把这些内容写成一份周报", "直接进入 XB 的周报处理流程", "你明确同意后才进入", "普通请求继续由原来的 AI 处理"),
        "coexistence and activation": ("/code-review", "才开启当前任务", "换任务后重新按档位判断"),
        "reminder versus actual write": ("每次 XB 最终回复", "你没有提出保存要求时不写入对话", "平时不出现保存提醒", "两档实际保存都需要本次明确指令", "保存成功或失败都会告知结果"),
        "configuration scope": (".xbskill/config.json", "与保存对话分开处理", "只回答一项时", "$xb-config"),
    }
    for label, phrases in groups.items():
        if not all(phrase in text for phrase in phrases):
            errors.append(f"configuration guide loses {label}: {path}")

    interaction = root / "xbskill/references/interaction-settings.md"
    portability = root / "xbskill/references/memory-portability.md"
    if not interaction.is_file() or not portability.is_file():
        errors.append(f"missing memory onboarding dependency: {interaction} / {portability}")
        return
    intro_text = interaction.read_text(encoding="utf-8")
    intro_start, intro_end = "<!-- intro-start -->", "<!-- intro-end -->"
    if intro_text.count(intro_start) != 1 or intro_text.count(intro_end) != 1 or intro_text.index(intro_start) >= intro_text.index(intro_end):
        errors.append(f"missing memory introduction block: {interaction}")
    elif start in text and end in text:
        intro = intro_text.split(intro_start, 1)[1].split(intro_end, 1)[0].strip()
        options = text.split(start, 1)[1].split(end, 1)[0].strip()
        # Reserve scope, receipt and paragraph separators; file paths are excluded.
        if len(intro) + len(options) + 40 > 750:
            errors.append(f"complete initialization exceeds 750-character budget: {interaction}")
        if not all(term in intro for term in ("xb-save", "保存对话", "本体记忆", "换对话", "Kimi", "DeepSeek", "可读记忆文件")):
            errors.append(f"memory introduction loses value or handoff conditions: {interaction}")


def validate(root: Path) -> int:
    assert_no_managed_symlinks(root)
    errors: list[str] = []
    warnings: list[str] = []
    dirs = skill_dirs(root)
    names = {p.name for p in dirs}
    display_names: dict[str, Path] = {}
    validate_configuration_guide(root, errors)
    if "xbskill" not in names:
        errors.append(f"missing root skill: {root / 'xbskill'}")
    for rel in (
        "xb-config/SKILL.md", "xb-config/references/config-contract.md",
        "xb-config/scripts/config_manager.py", "xb-config/scripts/test_config.py",
        "xbskill/references/coexistence-protocol.md", "xbskill/references/work-state-intake.md",
    ):
        if not (root / rel).is_file():
            errors.append(f"missing required configuration dependency: {root / rel}")
    if len(dirs) < 2:
        errors.append("suite has no specialist skills")

    for directory in dirs:
        skill = directory / "SKILL.md"
        if not skill.is_file():
            errors.append(f"missing SKILL.md: {skill}")
            continue
        text = skill.read_text(encoding="utf-8")
        match = NAME_RE.search(text)
        if not match:
            errors.append(f"missing valid name frontmatter: {skill}")
        elif match.group(1) != directory.name:
            errors.append(f"name/folder mismatch: {skill} has {match.group(1)}")
        if "description:" not in text.split("---", 2)[1] if text.startswith("---") else True:
            errors.append(f"missing description frontmatter: {skill}")
        if "TODO" in text:
            errors.append(f"unresolved TODO: {skill}")
        if len(text.splitlines()) > 500:
            errors.append(f"SKILL.md exceeds 500 lines: {skill}")
        if "## " not in text:
            warnings.append(f"no level-2 workflow sections: {skill}")
        if directory.name != "xbskill":
            for required in ("../xbskill/references/contracts.md", "../xbskill/references/resolution-standard.md"):
                if required not in text:
                    errors.append(f"specialist missing direct-call contract {required}: {skill}")
        for rel in sorted(set(DEPENDENCY_RE.findall(text))):
            dependency = (directory / rel).resolve()
            if not dependency.is_file():
                errors.append(f"referenced dependency missing: {dependency} from {skill}")
        for anchor in DEPTH_ANCHORS.get(directory.name, ()):
            if anchor not in text:
                errors.append(f"specialist depth anchor missing {anchor!r}: {skill}")
        if directory.name in TASK_DEPTH_SKILLS and "../xbskill/references/task-domain-patterns.md" not in text:
            errors.append(f"task specialist missing shared domain patterns: {skill}")
        if directory.name in PEOPLE_DEPTH_SKILLS and "../xbskill/references/people-domain-patterns.md" not in text:
            errors.append(f"people specialist missing shared domain patterns: {skill}")
        ui = directory / "agents" / "openai.yaml"
        if not ui.is_file():
            errors.append(f"missing UI metadata: {ui}")
        else:
            ui_text = ui.read_text(encoding="utf-8")
            ui_fields = dict(UI_STRING_RE.findall(ui_text))
            for key in ("display_name", "short_description", "default_prompt"):
                if key not in ui_fields:
                    errors.append(f"missing quoted {key} in UI metadata: {ui}")
            display_name = ui_fields.get("display_name", "")
            validate_display_name(directory.name, display_name, ui, display_names, errors)
            short_description = ui_fields.get("short_description", "")
            if short_description and not 25 <= len(short_description) <= 64:
                errors.append(
                    f"short_description must be 25-64 characters, got {len(short_description)}: {ui}"
                )
            default_prompt = ui_fields.get("default_prompt", "")
            if default_prompt and f"${directory.name}" not in default_prompt:
                errors.append(f"default prompt does not name ${directory.name}: {ui}")

    routing = root / "xbskill" / "references" / "routing.md"
    if routing.is_file():
        routed = set(ROUTE_RE.findall(routing.read_text(encoding="utf-8")))
        for target in sorted(routed):
            if target not in names:
                errors.append(f"routing target missing: {target} referenced by {routing}")
        for target in sorted((names - {"xbskill"}) - routed):
            errors.append(f"specialist is not reachable from routing: {target}")
    else:
        errors.append(f"missing routing reference: {routing}")

    references = root / "xbskill" / "references"
    for filename in CORE_REFERENCES:
        path = references / filename
        if not path.is_file():
            errors.append(f"missing core reference: {path}")
    _validate_output_collab_evidence(references, errors)
    _validate_output_collab_behavior(root, errors)

    schema = references / "knowledge-source.schema.json"
    if schema.is_file():
        try:
            json.loads(schema.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid knowledge source schema {schema}: {exc}")

    knowledge_manager = root / "xbskill" / "scripts" / "knowledge_manager.py"
    if not knowledge_manager.is_file():
        errors.append(f"missing knowledge manager: {knowledge_manager}")
    else:
        try:
            compile(knowledge_manager.read_text(encoding="utf-8"), str(knowledge_manager), "exec")
        except (OSError, SyntaxError) as exc:
            errors.append(f"invalid knowledge manager {knowledge_manager}: {exc}")

    role_root = root / "xb-role-knowledge"
    role_schema = role_root / "references" / "role-knowledge.schema.json"
    role_runtime_schema = role_root / "references" / "role-knowledge-runtime.schema.json"
    role_evidence_schema = role_root / "references" / "role-knowledge-evidence.schema.json"
    role_catalog = role_root / "references" / "builtin-role-knowledge.json"
    role_evidence = role_root / "references" / "role-knowledge-regression.json"
    role_source_registry = role_root / "references" / "builtin-source-registry.json"
    role_source_registry_schema = role_root / "references" / "builtin-source-registry.schema.json"
    role_protocol = role_root / "references" / "role-knowledge-protocol.md"
    for role_json in (
        role_schema,
        role_runtime_schema,
        role_evidence_schema,
        role_catalog,
        role_evidence,
        role_source_registry,
        role_source_registry_schema,
    ):
        if not role_json.is_file():
            errors.append(f"missing role knowledge dependency: {role_json}")
        else:
            try:
                json.loads(role_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"invalid role knowledge JSON {role_json}: {exc}")
    if not role_protocol.is_file():
        errors.append(f"missing role knowledge protocol: {role_protocol}")
    role_scripts = tuple(
        role_root / "scripts" / filename
        for filename in (
            "role_knowledge.py", "deterministic_test.py", "blind_fixture.py",
            "assemble_evidence.py", "prepare_candidate.py", "activate_catalog.py",
        )
    )
    for role_script in role_scripts:
        if not role_script.is_file():
            errors.append(f"missing role knowledge script: {role_script}")
            continue
        try:
            compile(role_script.read_text(encoding="utf-8"), str(role_script), "exec")
        except (OSError, SyntaxError) as exc:
            errors.append(f"invalid role knowledge script {role_script}: {exc}")
    role_manager = role_scripts[0]
    if role_manager.is_file():
        try:
            child_env = os.environ.copy()
            child_env["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run(
                [sys.executable, str(role_manager), "validate"],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                env=child_env,
            )
            if completed.returncode:
                detail = (completed.stdout + completed.stderr).strip()
                errors.append(f"role knowledge semantic validation failed: {detail}")
        except OSError as exc:
            errors.append(f"cannot run role knowledge manager {role_manager}: {exc}")

    root_skill = root / "xbskill" / "SKILL.md"
    if root_skill.is_file():
        for rel in re.findall(r"\]\((references/[^)]+)\)", root_skill.read_text(encoding="utf-8")):
            if not (root / "xbskill" / rel).is_file():
                errors.append(f"root reference missing: {root / 'xbskill' / rel}")

    try:
        declared = load_manifest(root)
        actual = current_manifest(root)
        declared_version = declared.get("version")
        actual_version = actual["version"]
        if declared_version != actual_version:
            errors.append(
                "manifest version mismatch: "
                f"manifest={declared_version!r} VERSION={actual_version!r}"
            )
        declared_files = declared.get("files", {})
        actual_files = actual.get("files", {})
        drifted = {
            rel
            for rel in declared_files.keys() | actual_files.keys()
            if declared_files.get(rel) != actual_files.get(rel)
        }
        critical_drift = sorted(drifted & CRITICAL_MANIFEST_FILES)
        for rel in critical_drift:
            if rel not in declared_files:
                detail = "not declared in manifest"
            elif rel not in actual_files:
                detail = "declared file is missing"
            else:
                detail = "digest differs"
            errors.append(f"critical manifest drift ({detail}): {rel}")
        noncritical_drift = drifted - CRITICAL_MANIFEST_FILES
        for rel in sorted(noncritical_drift):
            if rel not in declared_files:
                detail = "not declared in manifest"
            elif rel not in actual_files:
                detail = "declared file is missing"
            else:
                detail = "digest differs"
            errors.append(f"manifest drift ({detail}): {rel}")
    except SystemExit:
        errors.append("manifest could not be read")

    for item in errors:
        print(f"ERROR: {item}")
    for item in warnings:
        print(f"WARN: {item}")
    print(f"SUMMARY skills={len(dirs)} errors={len(errors)} warnings={len(warnings)}")
    return 1 if errors else 0


def worktree_drift(root: Path) -> dict[str, str]:
    """Return managed files whose target contents differ from the target manifest."""
    declared = load_manifest(root).get("files", {})
    actual = current_manifest(root)["files"]
    drift: dict[str, str] = {}
    for rel in sorted(declared.keys() | actual.keys()):
        expected = declared.get(rel)
        observed = actual.get(rel)
        if expected == observed:
            continue
        if expected is None:
            drift[rel] = "unregistered"
        elif observed is None:
            drift[rel] = "missing"
        else:
            drift[rel] = "modified"
    return drift


def verified_reference(root: Path) -> dict:
    declared = load_manifest(root)
    actual = current_manifest(root)
    if declared != actual:
        fail(f"reference files or version differ from their manifest: {root}")
    return declared


def recover_manifest(source: Path, target: Path, backup: Path) -> None:
    """Restore only a missing manifest from a matching, pinned official reference.

    The caller verifies official provenance; this local primitive verifies bytes.
    It never invents a baseline for modified or incompletely installed files.
    """
    source, target, backup = source.resolve(), target.resolve(), backup.resolve()
    if source == target or source in target.parents or target in source.parents:
        fail("reference and target must be separate skills roots")
    if any(backup == root or root in backup.parents or backup in root.parents
           for root in (source, target)) or backup.exists():
        fail("backup must be new and outside reference and target trees")
    reference = verified_reference(source)
    actual = current_manifest(target)
    manifest = target / MANIFEST
    if manifest.exists() or is_link_or_reparse(manifest):
        fail(f"recovery only accepts a missing regular manifest: {manifest}")
    if reference != actual:
        fail("manifest recovery requires identical version and every managed file; "
             "use compare to review differences; target was not changed")
    backup.mkdir(parents=True)
    for directory in skill_dirs(target):
        shutil.copytree(directory, backup / directory.name)
    # Detect changes while backup was being made before creating the only new file.
    if current_manifest(target) != actual or current_manifest(backup) != actual:
        fail(f"installation changed during backup; recovery stopped: {backup}")
    if verified_reference(source) != reference:
        fail("reference changed during backup; recovery stopped")
    try:
        with manifest.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(reference, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        fail(f"cannot restore manifest; backup retained at {backup}: {exc}")
    print(f"RECOVERED_MANIFEST {manifest} BACKUP {backup}")


def diff(source: Path, target: Path) -> dict:
    src = load_manifest(source)["files"]
    target_manifest = target / MANIFEST
    baseline_missing = not target_manifest.exists() and not is_link_or_reparse(target_manifest)
    dst = current_manifest(target)["files"] if baseline_missing else load_manifest(target)["files"]
    return {
        "added": sorted(src.keys() - dst.keys()),
        "modified": sorted(k for k in src.keys() & dst.keys() if src[k] != dst[k]),
        "removed": sorted(dst.keys() - src.keys()),
        "local_drift": ([] if baseline_missing else
                        [f"{status}\t{rel}" for rel, status in sorted(worktree_drift(target).items())]),
        "baseline_missing": baseline_missing,
    }


def print_diff(source: Path, target: Path) -> dict[str, list[str]]:
    changes = diff(source, target)
    print(f"SOURCE version={load_manifest(source).get('version')} path={source}")
    version = (current_manifest(target) if changes["baseline_missing"] else load_manifest(target)).get("version")
    print(f"TARGET version={version} path={target}")
    if changes["baseline_missing"]:
        print("BASELINE_MISSING: comparing actual files with reference; local modification history is unknown; apply blocked")
    for group in ("added", "modified", "removed"):
        print(f"{group.upper()} {len(changes[group])}")
        for rel in changes[group]:
            print(f"  {rel}")
    print("LOCAL_DRIFT UNKNOWN" if changes["baseline_missing"] else f"LOCAL_DRIFT {len(changes['local_drift'])}")
    for item in changes["local_drift"]:
        status, rel = item.split("\t", 1)
        print(f"  {status}: {rel}")
    local = []
    for directory in skill_dirs(target):
        local.extend(p.relative_to(target).as_posix() for p in directory.rglob("LOCAL-*") if p.is_file())
    print(f"PRESERVED_LOCAL {len(local)}")
    for rel in sorted(local):
        print(f"  {rel}")
    return changes


def copy_suite(
    source: Path,
    target: Path,
    backup: Path,
    overwrite_drift: set[str] | None = None,
) -> None:
    source = source.resolve()
    target = target.resolve()
    backup = backup.resolve(strict=False)
    if not source.is_dir() or not target.is_dir():
        fail("source and target must be existing skills roots")
    if source == target:
        fail("source and target are the same directory")
    if source in backup.parents or backup == source:
        fail("backup must not be inside the source skills root")
    if backup == target or target in backup.parents:
        fail("backup must not be inside the target skills root")
    if backup.exists():
        fail(f"backup path already exists: {backup}")

    assert_no_managed_symlinks(source)
    assert_no_managed_symlinks(target)

    drift = worktree_drift(target)
    unregistered = sorted(rel for rel, status in drift.items() if status == "unregistered")
    if unregistered:
        fail("unregistered target files must be reviewed before update: " + ", ".join(unregistered))
    overwrite_drift = overwrite_drift or set()
    eligible = {rel for rel, status in drift.items() if status in {"modified", "missing"}}
    unknown = sorted(overwrite_drift - eligible)
    if unknown:
        fail("--overwrite-drift does not match a modified or missing managed target file: " + ", ".join(unknown))
    blocked = sorted(eligible - overwrite_drift)
    if blocked:
        fail("target files differ from their manifest; review and explicitly select each path with --overwrite-drift: " + ", ".join(blocked))

    backup.mkdir(parents=True)
    for directory in skill_dirs(target):
        shutil.copytree(directory, backup / directory.name)
    print(f"BACKUP {backup}")

    old = load_manifest(target)["files"]
    new = load_manifest(source)["files"]
    for rel in sorted(old.keys() - new.keys()):
        path = managed_path(target, rel)
        if path.exists() and not path.is_file():
            fail(f"managed target is not a regular file: {path}")
        if path.is_file() and not is_local(rel):
            path.unlink()
    for rel in sorted(new):
        src = managed_path(source, rel)
        dst = managed_path(target, rel)
        if not src.is_file():
            fail(f"source manifest file is missing or not a regular file: {src}")
        if dst.exists() and not dst.is_file():
            fail(f"managed target is not a regular file: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        managed_path(target, rel)
        shutil.copy2(src, dst)
    source_manifest = source / MANIFEST
    target_manifest = target / MANIFEST
    if is_link_or_reparse(source_manifest) or is_link_or_reparse(target_manifest):
        fail("suite manifest must be a regular file, not a link or reparse point")
    shutil.copy2(source_manifest, target_manifest)
    if validate(target):
        restore_suite(backup, target)
        fail(f"validation failed; restored backup from {backup}", 1)
    print(f"UPDATED {target}")


def restore_suite(backup: Path, target: Path) -> None:
    backup = backup.resolve()
    target = target.resolve()
    if not backup.is_dir():
        fail(f"backup does not exist: {backup}")
    if not target.is_dir():
        fail(f"target skills root does not exist: {target}")
    assert_no_managed_symlinks(backup)
    assert_no_managed_symlinks(target)
    candidates = skill_dirs(backup)
    if not candidates or not (backup / "xbskill" / "SKILL.md").is_file():
        fail(f"backup is not an xbskill suite: {backup}")
    for current in skill_dirs(target):
        shutil.rmtree(current)
    for directory in candidates:
        shutil.copytree(directory, target / directory.name)
    print(f"RESTORED {target} from {backup}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "manifest"):
        p = sub.add_parser(command)
        p.add_argument("--target", required=True, help="parent skills root")
    p = sub.add_parser("compare")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--backup", required=True)
    p.add_argument(
        "--overwrite-drift",
        action="append",
        default=[],
        metavar="RELATIVE_PATH",
        help="explicitly authorize overwriting one modified or missing managed target file listed by compare",
    )
    p.add_argument("--yes", action="store_true", help="confirm exact source/target/backup")
    p = sub.add_parser("recover-manifest", help="restore a missing manifest from identical official-version files")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--backup", required=True)
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("restore")
    p.add_argument("--backup", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if args.command == "validate":
        return validate(root_path(args.target))
    if args.command == "manifest":
        write_manifest(root_path(args.target))
        return 0
    if args.command == "compare":
        print_diff(root_path(args.source), root_path(args.target))
        return 0
    if args.command == "apply":
        if not args.yes:
            fail("apply requires --yes after the user confirms the exact paths")
        copy_suite(
            root_path(args.source),
            root_path(args.target),
            Path(args.backup).expanduser().resolve(),
            set(args.overwrite_drift),
        )
        return 0
    if args.command == "recover-manifest":
        if not args.yes:
            fail("recover-manifest requires --yes after the user confirms reference, target, and backup")
        recover_manifest(root_path(args.source), root_path(args.target),
                         Path(args.backup).expanduser().resolve())
        return 0
    if args.command == "restore":
        if not args.yes:
            fail("restore requires --yes after the user confirms the exact paths")
        restore_suite(Path(args.backup).expanduser().resolve(), root_path(args.target))
        return validate(root_path(args.target))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
