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
import re
import shutil
import subprocess
import sys
from pathlib import Path


MANIFEST = "xbskill/manifest.json"
MANAGED_RE = re.compile(r"^xb(?:skill|-[a-z0-9-]+)$")
NAME_RE = re.compile(r"^name:\s*([a-z0-9-]+)\s*$", re.MULTILINE)
ROUTE_RE = re.compile(r"`(xb-[a-z0-9-]+)`")
UI_STRING_RE = re.compile(r'^\s{2}([a-z_]+):\s*"([^"\n]+)"\s*$', re.MULTILINE)
DEPENDENCY_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:\.\./xbskill/(?:references|scripts)|(?:references|scripts))/[A-Za-z0-9._/-]+\.(?:md|json|py))"
)
CORE_REFERENCES = (
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
    "xb-stakeholder": ("触发与权力模型", "可观察信号词典", "模式与条件分支", "微型分支", "验证、失败与翻转"),
    "xb-conflict": ("触发与核心因果模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-boundary": ("触发与核心因果模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-people": ("触发与核心因果模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-company": ("触发与核心系统模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-wellbeing": ("触发与核心因果模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-career": ("触发与核心职业模型", "可观察信号词典", "模式与条件分支", "边界例", "验证、失败与翻转"),
    "xb-role-knowledge": ("触发与核心模型", "可观察信号词典", "岗位知识参与闭环", "匹配与条件分支", "验证、失败与翻转"),
}

TASK_DEPTH_SKILLS = {
    "xb-it", "xb-data", "xb-automation", "xb-writing", "xb-presentation", "xb-report", "xb-review"
}
PEOPLE_DEPTH_SKILLS = {
    "xb-meeting", "xb-talk", "xb-upward", "xb-stakeholder", "xb-conflict",
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
    return sorted(
        [p for p in root.iterdir() if p.is_dir() and MANAGED_RE.fullmatch(p.name)],
        key=lambda p: p.name,
    )


def is_local(rel: str) -> bool:
    return any(part.upper().startswith("LOCAL-") for part in Path(rel).parts)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def current_manifest(root: Path) -> dict:
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
    path = root / MANIFEST
    if not path.is_file():
        return current_manifest(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid manifest {path}: {exc}")
    if data.get("schema") != 1 or not isinstance(data.get("files"), dict):
        fail(f"unsupported manifest schema: {path}")
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


def validate(root: Path) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    dirs = skill_dirs(root)
    names = {p.name for p in dirs}
    display_names: dict[str, Path] = {}
    if "xbskill" not in names:
        errors.append(f"missing root skill: {root / 'xbskill'}")
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
            if display_name and not display_name.startswith("xbskill "):
                errors.append(f"display_name must start with 'xbskill ': {ui}")
            elif display_name == "xbskill ":
                errors.append(f"display_name must include a user-facing function name: {ui}")
            elif display_name:
                previous = display_names.get(display_name)
                if previous:
                    errors.append(f"duplicate display_name {display_name!r}: {previous} and {ui}")
                else:
                    display_names[display_name] = ui
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
            completed = subprocess.run(
                [sys.executable, str(role_manager), "validate"],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
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
        if noncritical_drift:
            warnings.append(
                "manifest differs for "
                f"{len(noncritical_drift)} non-critical file(s); run the manifest command"
            )
    except SystemExit:
        errors.append("manifest could not be read")

    for item in errors:
        print(f"ERROR: {item}")
    for item in warnings:
        print(f"WARN: {item}")
    print(f"SUMMARY skills={len(dirs)} errors={len(errors)} warnings={len(warnings)}")
    return 1 if errors else 0


def diff(source: Path, target: Path) -> dict[str, list[str]]:
    src = load_manifest(source)["files"]
    dst = load_manifest(target)["files"]
    return {
        "added": sorted(src.keys() - dst.keys()),
        "modified": sorted(k for k in src.keys() & dst.keys() if src[k] != dst[k]),
        "removed": sorted(dst.keys() - src.keys()),
    }


def print_diff(source: Path, target: Path) -> dict[str, list[str]]:
    changes = diff(source, target)
    print(f"SOURCE version={load_manifest(source).get('version')} path={source}")
    print(f"TARGET version={load_manifest(target).get('version')} path={target}")
    for group in ("added", "modified", "removed"):
        print(f"{group.upper()} {len(changes[group])}")
        for rel in changes[group]:
            print(f"  {rel}")
    local = []
    for directory in skill_dirs(target):
        local.extend(p.relative_to(target).as_posix() for p in directory.rglob("LOCAL-*") if p.is_file())
    print(f"PRESERVED_LOCAL {len(local)}")
    for rel in sorted(local):
        print(f"  {rel}")
    return changes


def copy_suite(source: Path, target: Path, backup: Path) -> None:
    if source == target:
        fail("source and target are the same directory")
    if backup == target or target in backup.parents:
        fail("backup must not be inside the target skills root")
    if backup.exists():
        fail(f"backup path already exists: {backup}")
    backup.mkdir(parents=True)
    for directory in skill_dirs(target):
        shutil.copytree(directory, backup / directory.name)
    print(f"BACKUP {backup}")

    old = load_manifest(target)["files"]
    new = load_manifest(source)["files"]
    for rel in sorted(old.keys() - new.keys()):
        path = target / rel
        if path.is_file() and not is_local(rel):
            path.unlink()
    for rel in sorted(new):
        src = source / rel
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copy2(source / MANIFEST, target / MANIFEST)
    if validate(target):
        restore_suite(backup, target)
        fail(f"validation failed; restored backup from {backup}", 1)
    print(f"UPDATED {target}")


def restore_suite(backup: Path, target: Path) -> None:
    if not backup.is_dir():
        fail(f"backup does not exist: {backup}")
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
    p.add_argument("--yes", action="store_true", help="confirm exact source/target/backup")
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
        copy_suite(root_path(args.source), root_path(args.target), Path(args.backup).expanduser().resolve())
        return 0
    if args.command == "restore":
        if not args.yes:
            fail("restore requires --yes after the user confirms the exact paths")
        restore_suite(Path(args.backup).expanduser().resolve(), root_path(args.target))
        return validate(root_path(args.target))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
