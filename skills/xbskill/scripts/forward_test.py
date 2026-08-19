#!/usr/bin/env python3
"""Run isolated receiver tests for the xbskill suite."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import knowledge_manager as km
import suite_manager as sm


def copy_receiver(source: Path, target: Path) -> None:
    target.mkdir(parents=True)
    for directory in sm.skill_dirs(source):
        shutil.copytree(directory, target / directory.name)


def capture_validate(root: Path) -> tuple[int, str]:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        code = sm.validate(root)
    return code, stream.getvalue()


def capture_knowledge(argv: list[str]) -> tuple[int, str]:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        code = km.main(argv)
    return code, stream.getvalue()


def run_role_tool(root: Path, script_name: str, argv: list[str]) -> tuple[int, str]:
    script = root / "xb-role-knowledge" / "scripts" / script_name
    completed = subprocess.run(
        [sys.executable, str(script), *argv],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


def run_role_knowledge(root: Path, argv: list[str]) -> tuple[int, str]:
    return run_role_tool(root, "role_knowledge.py", argv)


def run_session_store(root: Path, project_root: Path, bundle_path: Path) -> tuple[int, str]:
    script = root / "xb-save" / "scripts" / "session_store.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--project-root", str(project_root), "--bundle", str(bundle_path)],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


OUTPUT_COLLAB_CASE_IDS = tuple(f"X{i:02d}" for i in range(13, 20))
COPY_FORBIDDEN_RE = re.compile(
    r"不是.*而是|不在于|不需要.*需要|不会.*会|真正的|与其说"
)


def markdown_field(text: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}:\s*(\S.*)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def markdown_case_sections(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(X\d{2})\s*$", text, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        require(match.group(1) not in sections, f"duplicate case heading {match.group(1)}")
        sections[match.group(1)] = text[match.end():end]
    return sections


def validate_output_collab_release_evidence(receiver: Path) -> None:
    references = receiver / "xbskill" / "references"
    answers_path = references / "v1.0-output-collab-blind-answers.md"
    review_path = references / "v1.0-output-collab-independent-review.md"
    record_path = references / "v1.0-output-collab-release-record.md"
    for path in (answers_path, review_path, record_path):
        require(path.is_file(), f"missing output/collaboration release evidence: {path}")
    answers = answers_path.read_text(encoding="utf-8")
    review = review_path.read_text(encoding="utf-8")
    record = record_path.read_text(encoding="utf-8")

    answerer = markdown_field(answers, "Answerer")
    reviewer = markdown_field(review, "Reviewer")
    designer = markdown_field(record, "Designer")
    require(answerer and reviewer and designer, "answerer, reviewer, and designer identities must be explicit")
    require(len({answerer, reviewer, designer}) == 3, "answerer, reviewer, and designer must be different")
    require(designer == "root", "release record Designer must be root")
    require(markdown_field(review, "Answerer") == answerer, "review does not bind the frozen answerer")
    require(markdown_field(record, "Answerer") == answerer, "release record answerer differs from frozen answers")
    require(markdown_field(record, "Reviewer") == reviewer, "release record reviewer differs from independent review")
    require(markdown_field(record, "Designer-Patched-Frozen-Answers") == "false", "designer patched frozen answers")
    require(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", markdown_field(answers, "Frozen-At") or "") is not None,
        "Frozen-At is not an explicit UTC timestamp",
    )
    require(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", markdown_field(review, "Reviewed-At") or "") is not None,
        "Reviewed-At is not an explicit UTC timestamp",
    )

    answer_sections = markdown_case_sections(answers)
    review_sections = markdown_case_sections(review)
    expected = set(OUTPUT_COLLAB_CASE_IDS)
    require(set(answer_sections) == expected, "blind answers do not cover exactly X13-X19")
    require(set(review_sections) == expected, "independent review does not cover exactly X13-X19")
    for case_id in OUTPUT_COLLAB_CASE_IDS:
        require(answer_sections[case_id].strip(), f"{case_id} frozen answer is empty")
        section = review_sections[case_id]
        require("G/C/A/P/S/E/R/V: 2/2/2/2/2/2/2/2" in section, f"{case_id} is not all-two")
        require(re.search(r"^Verdict:\s*pass\s*$", section, re.MULTILINE) is not None, f"{case_id} verdict is not pass")
        require(re.search(r"^Release:\s*allow\s*$", section, re.MULTILINE) is not None, f"{case_id} release is not allow")

    require(markdown_field(record, "Answers-SHA256") == sm.digest(answers_path), "answers SHA256 does not match frozen file")
    require(markdown_field(record, "Review-SHA256") == sm.digest(review_path), "review SHA256 does not match frozen file")
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
    for field, expected_value in required_record_fields.items():
        require(markdown_field(record, field) == expected_value, f"release record loses required {field}")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def material_artifact_and_trace(packet: dict, label: str) -> tuple[str, dict]:
    """Build a literal artifact/trace pair that exercises every runtime binding."""

    requirements = packet["delivery_requirements"]
    routing = requirements["routing"]
    lines = [
        f"{label}：岗位知识已进入当前专科的实际交付物。",
        f"current_specialist={routing['current_specialist']}",
        f"task_family={routing['task_family']}",
        f"problem={routing['problem']}",
        f"lifecycle_stage={routing['lifecycle_stage']}",
    ]
    for selected in routing["selected_units"]:
        lines.append(f"selected_unit={selected['unit_id']}")
        lines.extend(selected["match_reasons"])
    for evidence in requirements["evidence"]:
        lines.append(f"evidence_unit={evidence['unit_id']}")
        for claim in evidence["claims"]:
            lines.extend((claim["claim_id"], claim["statement"]))
            for source in claim["source_bindings"]:
                lines.append(
                    f"{source['source_ref']} | {source['registry']} | {source['coordinate_key']}"
                )
        lines.extend(evidence["limitations"])
        lines.extend(evidence["refresh_triggers"])
    lines.append(requirements["completion_boundary"])
    applications: list[dict] = []
    professional_slots = (
        "actions", "artifacts", "validation", "distinguish", "branches",
        "observe", "competing_explanations", "boundaries", "reality_feedback",
    )
    for unit in packet["matched_units"]:
        unit_id = unit["id"]
        professional = next(
            effect
            for slot in professional_slots
            for effect in packet["active_injection"][slot]
            if effect["unit_id"] == unit_id
        )
        artifact_field = f"role_knowledge.{unit_id}.professional_effect_1"
        professional_excerpt = (
            f"[[field:{artifact_field}]]\n专业动作[{unit_id}]：{professional['content']}"
        )
        lines.append(professional_excerpt)
        validation_content = "｜".join(
            effect["content"] for effect in packet["active_injection"]["validation"]
            if effect["unit_id"] == unit_id
        )
        controls: dict[str, dict] = {}
        for control_slot in ("permissions", "risk_gates", "stage_adaptation"):
            selected = [
                effect for effect in packet["active_injection"][control_slot]
                if effect["unit_id"] == unit_id
            ]
            control_excerpt = (
                f"控制[{unit_id}/{control_slot}]："
                + "｜".join(effect["content"] for effect in selected)
            )
            lines.append(control_excerpt)
            controls[control_slot] = {
                "effect_ids": [effect["effect_id"] for effect in selected],
                "artifact_excerpts": [control_excerpt],
            }
        applications.append({
            "unit_id": unit_id,
            "unit_version": unit["version"],
            "claim_ids": [claim["id"] for claim in unit["claims"]],
            "effects": [{
                "effect_id": professional["effect_id"],
                "artifact_field": artifact_field,
                "artifact_excerpt": professional_excerpt,
                "validation_point": {
                    "checker": "当前任务的具名复核负责人",
                    "observable": f"交付物中的专业动作、权限门与风险门可逐项核对；{validation_content}",
                    "acceptance_condition": "复核者确认每项证据、权限和停止条件均有对应记录",
                },
            }],
            "controls": controls,
        })
    feedback_content = "｜".join(
        effect["content"] for effect in packet["active_injection"]["reality_feedback"]
    )
    lines.append(f"现实边界：本轮只交付可执行判断包，现实结果仍待业务验收者观察；{feedback_content}")
    artifact_text = "\n".join(lines)
    trace = {
        "record_type": "RoleKnowledgeApplicationTrace",
        "schema_version": 1,
        "context_digest": packet["context_digest"],
        "current_specialist": packet["request"]["current_specialist"],
        "artifact_sha256": hashlib.sha256(artifact_text.encode("utf-8")).hexdigest(),
        "applications": applications,
        "reality_feedback_point": {
            "observer": "业务验收负责人",
            "observable": f"下游验收记录中的重复、漏数与返工结果；{feedback_content}",
            "when": "本次回填验收完成时",
        },
        "completion_claim": "packet_applied_not_reality_solved",
    }
    return artifact_text, trace


def synthesize_blind_round(fixtures: dict) -> tuple[dict, dict]:
    """Create complete structural fixtures for the forward-test governance chain."""

    answerer_id = "receiver-blind-answerer"
    reviewer_id = "receiver-independent-reviewer"
    answers: list[dict] = []
    reviews: list[dict] = []
    reviewed_clock = dt.datetime.now(dt.timezone.utc)
    answered_clock = reviewed_clock - dt.timedelta(seconds=1)
    answered_at = answered_clock.strftime("%Y-%m-%dT%H:%M:%S") + f".{answered_clock.microsecond:06d}7Z"
    reviewed_at = reviewed_clock.strftime("%Y-%m-%dT%H:%M:%S") + f".{reviewed_clock.microsecond // 1000:03d}Z"
    all_two = {gate: 2 for gate in ("G", "C", "A", "P", "S", "E", "R", "V")}
    for case in fixtures["cases"]:
        packet = case["packet"]
        if packet["status"] == "active":
            answer_text, trace = material_artifact_and_trace(packet, case["case_id"])
        else:
            requirements = packet["delivery_requirements"]
            routing = requirements["routing"]
            no_match_lines = [
                case["case_id"],
                routing["current_specialist"],
                routing["task_family"],
                routing["problem"],
                routing["lifecycle_stage"],
                requirements["status_statement"],
            ]
            for branch in requirements["responsibility_branches"]:
                no_match_lines.extend((branch["hypothesis"], branch["discriminator"], branch["next_action"]))
            no_match_lines.extend(requirements["reality_feedback"].values())
            no_match_lines.append(requirements["completion_boundary"])
            answer_text = "\n".join(no_match_lines)
            trace = None
        answers.append({
            "case_id": case["case_id"],
            "case_kind": case["case_kind"],
            "unit_id": case["unit_id"],
            "answer_text": answer_text,
            "trace": trace,
        })
        reviews.append({
            "case_id": case["case_id"],
            "case_kind": case["case_kind"],
            "unit_id": case["unit_id"],
            "answerer_id": answerer_id,
            "scores": dict(all_two),
            "rationale": (
                "结构回归确认目标与唯一专科、条件分支、用户决定权、六项权限、风险门、"
                "证据翻转、现实边界和逐字可执行绑定均完整。"
            ),
            "verdict": "passed",
        })
    return ({
        "record_type": "RoleKnowledgeBlindAnswers",
        "schema_version": 1,
        "answerer_id": answerer_id,
        "frozen_at": answered_at,
        "cases": answers,
    }, {
        "record_type": "RoleKnowledgeBlindReviews",
        "schema_version": 1,
        "reviewer_id": reviewer_id,
        "reviewed_at": reviewed_at,
        "cases": reviews,
    })


def install_local_knowledge_fixture(root: Path, authority_scope: str = "synthetic receiver fixture") -> None:
    timestamp = "2026-08-09T00:00:00Z"
    content_hash = "a" * 64
    pin = {
        "kind": "sha256",
        "value": content_hash,
        "captured_at": timestamp,
        "verification_method": "receiver_fixture_hash",
    }
    requirement = {
        "record_type": "KnowledgeRequirement",
        "schema_version": 1,
        "id": "req-local",
        "purpose": "receiver test",
        "question": "Which fixed local rule applies?",
        "required_source_ids": ["source-local"],
        "optional_source_ids": [],
        "critical_claims": ["claim-local"],
        "permissions": {"discover": True, "read": True, "execute": False},
        "context_budget": {
            "max_sources": 2,
            "max_evidence_records": 4,
            "max_excerpt_chars": 200,
            "minimum_evidence_per_required_source": 1,
        },
        "conflict_policy": "fail_on_critical",
        "created_at": timestamp,
    }
    source = {
        "record_type": "SourceRecord",
        "schema_version": 1,
        "id": "source-local",
        "source_type": "local",
        "title": "Receiver fixture",
        "locator": "C:/receiver-fixture/source.md",
        "discovered_at": timestamp,
        "permissions": {"discover": True, "read": True, "execute": False},
        "license": {
            "status": "internal_authorized",
            "identifier": "receiver-test-authorization",
            "usage_notes": "Synthetic fixture only.",
        },
        "security": {
            "status": "reviewed",
            "reviewed_at": timestamp,
            "reviewed_by": "receiver-test",
            "notes": "Passive synthetic text; no execution.",
        },
        "pin": pin,
        "content_trust": "local_controlled",
        "status": "approved",
        "notes": "Synthetic fixture.",
    }
    excerpt = "The receiver fixture is pinned."
    evidence = {
        "record_type": "EvidenceRecord",
        "schema_version": 1,
        "id": "evidence-local",
        "requirement_id": "req-local",
        "source_id": "source-local",
        "claim_id": "claim-local",
        "claim": "The selected local rule is fixed to a content hash.",
        "stance": "supports",
        "captured_at": timestamp,
        "source_pin": pin,
        "locator": {
            "kind": "local",
            "path": "C:/receiver-fixture/source.md",
            "content_sha256": content_hash,
            "line_start": 1,
            "line_end": 1,
        },
        "excerpt": excerpt,
        "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        "notes": "Synthetic fixture.",
    }
    for lock_id, note in (("lock-one", "first"), ("lock-two", "second")):
        lock = {
            "record_type": "SourceLock",
            "schema_version": 1,
            "id": lock_id,
            "requirement_id": "req-local",
            "created_at": timestamp,
            "source_pins": [{"source_id": "source-local", "source_type": "local", "pin": pin}],
            "evidence_ids": ["evidence-local"],
            "conflicts": [],
            "conflict_review": {
                "status": "complete",
                "reviewed_at": timestamp,
                "reviewed_by": "receiver-test",
                "notes": "No conflict in synthetic fixture.",
            },
            "authority_decision": {
                "status": "confirmed",
                "decided_by": "receiver-authority",
                "authority_role": "fixture-owner",
                "scope": authority_scope,
                "decided_at": timestamp,
                "supersedes": [],
                "basis": "The fixture owner controls the synthetic scope.",
            },
            "notes": note,
        }
        write_json(root / "locks" / f"{lock_id}.json", lock)
    write_json(root / "registry" / "requirements" / "req-local.json", requirement)
    write_json(root / "sources" / "source-local.json", source)
    write_json(root / "evidence" / "evidence-local.json", evidence)


def main() -> int:
    source = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="xbskill-receiver-") as raw:
        sandbox = Path(raw)

        receiver = sandbox / "receiver" / "skills"
        copy_receiver(source, receiver)
        code, output = capture_validate(receiver)
        require(code == 0, f"clean receiver failed validation:\n{output}")
        require(len(sm.skill_dirs(receiver)) == 35, "receiver did not discover all 35 skills")
        print("PASS clean install and discovery")

        session_protocol = (receiver / "xbskill" / "references" / "session-memory-protocol.md").read_text(encoding="utf-8")
        answer_format = (receiver / "xbskill" / "references" / "answer-format.md").read_text(encoding="utf-8")
        contracts_text = (receiver / "xbskill" / "references" / "contracts.md").read_text(encoding="utf-8")
        shell_text = (receiver / "xbskill" / "SKILL.md").read_text(encoding="utf-8")
        decision_text = (receiver / "xb-decision" / "SKILL.md").read_text(encoding="utf-8")
        save_text = (receiver / "xb-save" / "SKILL.md").read_text(encoding="utf-8")
        restore_text = (receiver / "xb-restore" / "SKILL.md").read_text(encoding="utf-8")
        require(all(term in session_protocol for term in (
            "保存提示｜要把本次会话的可见对话全文和自动分类结果保存到本地",
            "下一个有新内容的会话仍照常提示",
            "既往 `auto_checkpoint: on` 不能替代本次授权",
            "assistant_inference", "needs_identity", "company_tone", "communication_style",
            "禁止把档案标为 `complete`", "本地保存阶段禁止联网",
            "Windows 版 Codex Desktop 安全分支", "禁止调用任务、线程或会话历史接口",
            "list/read/resume/archive/unarchive/fork/rename/pin/send", "禁止查找“原始任务”",
            "用户主动提供的完整导出", "精确当前会话 ID", "副作用无法确认",
            "沿宿主分页游标持续读取", "hasMore=false", "已尝试入口", "任务摘要、压缩摘要",
            "本轮只有一次性、无跨会话价值的简单问答", "仍保留带 Skill 署名的结尾导航条",
        )), "session memory protocol loses prompt, consent, completeness, locality, or safe host-history gates")
        require("session-memory-protocol.md" in shell_text and "在导航条后明确询问一次" in shell_text, "navigation shell does not enforce explicit save prompt")
        require(all(term in answer_format for term in (
            "每个最终回答都在结尾显示一条紧凑导航",
            "Skill：{$xb-* 或 $xbskill}",
            "每轮必填且只能出现一个名称",
            "它必须是本轮唯一公开当前 Skill",
            "支持子调用、知识包、框架、内部维护专科和下一步候选均不进入",
            "简单、一次性问题也保留导航条",
            "本轮无跨会话内容", "不追加保存提示",
        )), "answer format loses the visible single-skill trace")
        require(all(term in shell_text for term in (
            "固定带一个公开当前 Skill 的准确调用名和本轮职责",
            "每轮必填且只显示一个公开当前 Skill",
            "全轮是否恰好一条结尾导航条",
        )), "navigation shell does not enforce the visible single-skill trace")
        require(all(term in contracts_text for term in (
            "每次回答都在结尾导航条显形唯一公开当前 Skill",
            "支持子调用、内部维护专科和下一步候选不得成为第二个署名",
        )), "cross-skill contract allows ambiguous or hidden skill attribution")
        require(all(term in decision_text for term in (
            "向参与者明确标注“内测/验证中”和当前交付方式",
            "只收集完成本次验证所需的数据",
            "样本范围、观察窗口、关键动作的分母、基线、阈值、错误后果和停止条件",
            "任一项待定时只交付待校准方案，不启动外部验证",
        )), "xb-decision loses experiment disclosure, data minimization, or calibration gates")
        direct_specialists = [path for path in receiver.iterdir() if path.is_dir() and path.name.startswith("xb-")]
        missing_contracts = [path.name for path in direct_specialists if "contracts.md" not in (path / "SKILL.md").read_text(encoding="utf-8")]
        require(not missing_contracts, f"direct specialists bypass the shared answer contract: {missing_contracts}")
        require("authorized_current_session=true" in save_text and "session_store.py" in save_text, "xb-save does not require the transactional local writer")
        require(all(term in save_text for term in (
            "Windows 版 Codex Desktop 禁止调用任务/线程/会话历史接口",
            "禁止寻找所谓“原始任务”或关联任务",
            "只用当前可见上下文和用户提供的完整导出",
            "精确当前会话 ID 可证明", "无任务生命周期副作用",
            "报告宿主、分支、已尝试入口与精确缺口",
            "保存现有部分",
        )), "xb-save loses the Codex Windows containment or safe history fallback")
        require("默认不加载 transcript 全文" in restore_text, "xb-restore exposes full sensitive transcript by default")

        session_project = sandbox / "session-project"
        session_project.mkdir()
        bundle_path = sandbox / "session-bundle.json"
        bundle = {
            "schema_version": 1,
            "session_id": "2026-08-18-1030-memory-loop",
            "authorized_current_session": True,
            "network_writes": False,
            "completeness": "complete",
            "completeness_gaps": [],
            "transcript": [
                {"turn": 1, "role": "user", "content": "领导希望先看结论，我偏好直接表达。"},
                {"turn": 2, "role": "assistant", "content": "已记录为用户陈述，等待后续事件验证。"},
            ],
            "classification": [
                {
                    "item_id": "M001", "category": "communication_style", "subject": "self",
                    "content": "用户表述自己偏好直接表达", "evidence_level": "user_statement",
                    "source": "2026-08-18-1030-memory-loop turn 1", "confidence": "中",
                    "target": "context/people/self.md", "action": "candidate_only",
                    "reversal": "用户在不同场景给出相反偏好",
                }
            ],
            "context_updates": [
                {"target": "context/people/self.md", "content": "- [用户陈述｜turn 1｜中] 偏好直接表达；待跨场景验证。"}
            ],
            "session_markdown": "# 会话摘要\n\n- 完整性：complete",
            "classification_markdown": "# 分类账\n\n- M001：communication_style → candidate_only",
            "progress_markdown": "# 当前进度\n\n- 最近会话：2026-08-18-1030-memory-loop",
        }
        write_json(bundle_path, bundle)
        code, output = run_session_store(receiver, session_project, bundle_path)
        require(code == 0 and '"status": "saved"' in output, f"authorized local session save failed:\n{output}")
        memory_root = session_project / "memory" / "xbskill"
        transcript_path = memory_root / "sessions" / bundle["session_id"] / "transcript.md"
        require(transcript_path.is_file() and "第 1 轮 · 用户" in transcript_path.read_text(encoding="utf-8"), "visible transcript was not stored")
        self_path = memory_root / "context" / "people" / "self.md"
        require(self_path.is_file() and "偏好直接表达" in self_path.read_text(encoding="utf-8"), "classification did not fill the local self profile")
        bundle["context_updates"][0]["content"] = "- [用户陈述｜turn 1｜中] 偏好直接表达；第二次保存覆盖同会话块。"
        write_json(bundle_path, bundle)
        code, output = run_session_store(receiver, session_project, bundle_path)
        require(code == 0 and self_path.read_text(encoding="utf-8").count("## 会话增量 2026-08-18-1030-memory-loop") == 1, "same-session incremental save duplicated context blocks")
        unauthorized = dict(bundle)
        unauthorized["authorized_current_session"] = False
        write_json(bundle_path, unauthorized)
        code, output = run_session_store(receiver, session_project, bundle_path)
        require(code != 0 and "E_AUTHORIZATION" in output, "session writer accepted missing current-session authorization")
        escaped = dict(bundle)
        escaped["context_updates"] = [{"target": "context/../../escape.md", "content": "escape"}]
        write_json(bundle_path, escaped)
        code, output = run_session_store(receiver, session_project, bundle_path)
        require(code != 0 and "E_PATH" in output, "session writer allowed path traversal")
        secret = dict(bundle)
        secret["transcript"] = [
            {"turn": 1, "role": "user", "content": "-----BEGIN " + "PRIVATE KEY-----"},
        ]
        write_json(bundle_path, secret)
        code, output = run_session_store(receiver, session_project, bundle_path)
        require(code != 0 and "E_SECRET" in output, "session writer stored a private-key pattern")
        incomplete = dict(bundle)
        incomplete["completeness"] = "complete"
        incomplete["completeness_gaps"] = ["compacted turn 3"]
        write_json(bundle_path, incomplete)
        code, output = run_session_store(receiver, session_project, bundle_path)
        require(code != 0 and "E_COMPLETENESS" in output, "session writer labeled a gapped transcript complete")
        print("PASS per-session prompt, local transcript/classification, incremental update, authorization, path, secret, and completeness gates")

        ui = receiver / "xb-action" / "agents" / "openai.yaml"
        original_ui = ui.read_text(encoding="utf-8")
        ui.write_text(original_ui.replace('display_name: "xbskill ', 'display_name: "', 1), encoding="utf-8")
        code, output = capture_validate(receiver)
        require(code != 0 and "display_name must start with 'xbskill '" in output, "missing xbskill display prefix was not detected")
        ui.write_text(original_ui, encoding="utf-8")
        print("PASS inconsistent public display name is detected")

        ui.write_text(original_ui.replace("xbskill 启动与执行", "xbskill 证据化分析", 1), encoding="utf-8")
        code, output = capture_validate(receiver)
        require(code != 0 and "duplicate display_name" in output, "duplicate public display name was not detected")
        ui.write_text(original_ui, encoding="utf-8")
        print("PASS duplicate public display name is detected")

        missing = receiver / "xbskill" / "references" / "work-model.md"
        held = missing.with_suffix(".md.missing")
        missing.rename(held)
        code, output = capture_validate(receiver)
        require(code != 0 and str(missing) in output, "missing required reference did not fail loudly")
        held.rename(missing)
        print("PASS missing dependency fails loudly")

        session_dependency = receiver / "xbskill" / "references" / "session-memory-protocol.md"
        held_session_dependency = session_dependency.with_suffix(".md.missing")
        session_dependency.rename(held_session_dependency)
        code, output = capture_validate(receiver)
        require(code != 0 and str(session_dependency) in output, "missing session memory protocol did not fail loudly")
        held_session_dependency.rename(session_dependency)
        print("PASS missing session memory protocol fails loudly")

        output_collab_evidence = (
            receiver / "xbskill" / "references" / "v1.0-output-collab-blind-answers.md"
        )
        held_output_collab_evidence = output_collab_evidence.with_suffix(".md.missing")
        output_collab_evidence.rename(held_output_collab_evidence)
        code, output = capture_validate(receiver)
        require(
            code != 0 and str(output_collab_evidence) in output,
            "missing output/collaboration blind evidence did not fail loudly",
        )
        held_output_collab_evidence.rename(output_collab_evidence)
        print("PASS missing output/collaboration release evidence fails loudly")

        routing = receiver / "xbskill" / "references" / "routing.md"
        original = routing.read_text(encoding="utf-8")
        routing.write_text(original + "\n| test | `xb-does-not-exist` | test |\n", encoding="utf-8")
        code, output = capture_validate(receiver)
        require(code != 0 and "xb-does-not-exist" in output, "broken route was not detected")
        routing.write_text(original, encoding="utf-8")
        print("PASS broken route is detected")

        goal_model = (receiver / "xbskill" / "references" / "goal-help-model.md").read_text(encoding="utf-8")
        agency_model = (receiver / "xbskill" / "references" / "agency-model.md").read_text(encoding="utf-8")
        capability_model = (receiver / "xbskill" / "references" / "capability-model.md").read_text(encoding="utf-8")
        people_template = (receiver / "xb-people" / "references" / "people-profile-template.md").read_text(encoding="utf-8")
        company_template = (receiver / "xb-company" / "references" / "company-profile-template.md").read_text(encoding="utf-8")
        require(all(f"G{i}" in goal_model for i in range(6)), "goal model does not cover G0-G5")
        require(all(f"H{i}" in goal_model for i in range(5)), "help model does not cover H0-H4")
        require(
            all(term in agency_model for term in ("容量 Capacity", "安全与尊严 Safety", "控制与清晰 Control", "意义与一致性 Meaning", "选择与支持 Options")),
            "agency model does not cover all five signals",
        )
        require(all(term in agency_model for term in ("稳住", "解卡", "看懂", "改变", "选择")), "agency model misses the value ladder")
        require(all(term in agency_model for term in ("解决 Solve", "调整 Adjust", "退出 Exit")), "agency model misses the choice gate")
        require(all(f"L{i}" in capability_model for i in range(5)), "capability model does not cover L0-L4")
        require(all(role in people_template for role in ("自己", "同事", "领导")), "people template misses a role")
        require(all(f"## {i}." in company_template for i in range(1, 13)), "company template misses sections")
        print("PASS goal, help, agency, capability, people, and company models are complete")

        root_skill = (receiver / "xbskill" / "SKILL.md").read_text(encoding="utf-8")
        require("用户已给出真实需求时不得进入本模式" in root_skill, "tutorial can still block a real request")
        require("只由显式询问触发" in root_skill, "tutorial is not limited to explicit capability questions")
        require("用户说“新手入门”或第一次使用" not in root_skill, "first use still unconditionally triggers the full tutorial")
        work_model = (receiver / "xbskill" / "references" / "work-model.md").read_text(encoding="utf-8")
        routing_text = routing.read_text(encoding="utf-8")
        contracts = (receiver / "xbskill" / "references" / "contracts.md").read_text(encoding="utf-8")
        triage = (receiver / "xb-triage" / "SKILL.md").read_text(encoding="utf-8")
        action = (receiver / "xb-action" / "SKILL.md").read_text(encoding="utf-8")
        wellbeing = (receiver / "xb-wellbeing" / "SKILL.md").read_text(encoding="utf-8")
        career = (receiver / "xb-career" / "SKILL.md").read_text(encoding="utf-8")
        report = (receiver / "xb-report" / "SKILL.md").read_text(encoding="utf-8")
        require("agency-model.md" in root_skill and "五坐标" in work_model and "五坐标" in triage, "agency model is not wired into entry and triage")
        require(all(term in root_skill for term in ("解决", "调整", "退出")), "entry does not expose the choice gate")
        require("简单、明确、低风险" in routing_text and "强迫用户做心理盘问" in routing_text, "simple-task restraint is missing")
        require(all(term in routing_text for term in ("是不是我能力/性格有问题", "必须先进 `xb-analysis`", "不得用目标校准跳过人物/权力归因")), "ambiguous evaluation can still be routed away from causal analysis")
        require("默认优化用户" in contracts and "不默认优化雇主产出" in contracts, "user-side value contract is missing")
        require("不行动有时是保护信号" in action, "action skill still treats every non-action as an execution defect")
        require("不把结构性伤害解释为个人心态问题" in wellbeing, "wellbeing skill can psychologize structural harm")
        require(all(term in career for term in ("方向、准备和不可逆动作", "证据、未知、置信度", "具体辞职日期", "不可逆动作确认点")), "career skill does not guard high-stakes exit recommendations")
        require("面向领导/团队的报告默认排除个人心理支持、健康、边界冲突和去留考虑" in report, "sensitive state data can leak into reports")
        print("PASS user-side value, choice gate, restraint, safety, exit, and privacy are wired")

        resolution = (receiver / "xbskill" / "references" / "resolution-standard.md").read_text(encoding="utf-8")
        lenses = (receiver / "xbskill" / "references" / "intellectual-capabilities.md").read_text(encoding="utf-8")
        knowledge_protocol = (receiver / "xbskill" / "references" / "knowledge-source-protocol.md").read_text(encoding="utf-8")
        knowledge_schema = (receiver / "xbskill" / "references" / "knowledge-source.schema.json").read_text(encoding="utf-8")
        regression = (receiver / "xbskill" / "references" / "workplace-regression.md").read_text(encoding="utf-8")
        require(all(term in resolution for term in ("Question", "Problem", "当前一步已解决", "现实证据或下一反馈点")), "resolution standard is incomplete")
        require("不得只写无范围的“当前这一步已经完成”" in resolution, "unscoped completion is still allowed")
        require(all(name in lenses for name in ("维特根斯坦", "亚里士多德", "波普尔", "杜威", "赫伯特·西蒙", "玛丽·帕克·福列特", "阿伦特", "西蒙娜·薇依", "戴明", "奥斯特罗姆")), "intellectual capability set is incomplete")
        require(all(term in lenses for term in ("每个用户问题最多使用 1–2 个镜头", "禁止第一人称模拟人物", "推翻条件", "不适用边界")), "lens safety or falsification contract is missing")
        require(all(term in knowledge_protocol for term in ("KnowledgeRequirement", "SourceRecord", "EvidenceRecord", "SourceLock", "KnowledgePacket", "discover", "read", "execute", "不可信数据")), "knowledge source object or permission chain is incomplete")
        require("discovery_only" in knowledge_protocol and '"stars_use"' in knowledge_schema, "GitHub stars are not constrained to discovery")
        require(all(f"W{i:02d}" in regression for i in range(1, 11)), "workplace regression does not contain W01-W10")
        require("不得读取本文件" in regression and "另一名评审" in regression, "regression isolation contract is missing")
        for directory in sm.skill_dirs(receiver):
            if directory.name == "xbskill":
                continue
            specialist = (directory / "SKILL.md").read_text(encoding="utf-8")
            require("../xbskill/references/contracts.md" in specialist, f"{directory.name} misses direct-call contracts")
            require("../xbskill/references/resolution-standard.md" in specialist, f"{directory.name} misses direct-call resolution standard")
        print("PASS resolution, intellectual lenses, knowledge protocol, and ten-case regression are wired")

        decision = (receiver / "xb-decision" / "SKILL.md").read_text(encoding="utf-8")
        analysis = (receiver / "xb-analysis" / "SKILL.md").read_text(encoding="utf-8")
        meeting = (receiver / "xb-meeting" / "SKILL.md").read_text(encoding="utf-8")
        upward = (receiver / "xb-upward" / "SKILL.md").read_text(encoding="utf-8")
        conflict = (receiver / "xb-conflict" / "SKILL.md").read_text(encoding="utf-8")
        learning = (receiver / "xb-learning" / "SKILL.md").read_text(encoding="utf-8")
        automation = (receiver / "xb-automation" / "SKILL.md").read_text(encoding="utf-8")
        boundary = (receiver / "xb-boundary" / "SKILL.md").read_text(encoding="utf-8")
        knowledge = (receiver / "xb-knowledge" / "SKILL.md").read_text(encoding="utf-8")
        require(all(term in decision for term in ("| 任务 | 截止 | 失败后果 | 卡住谁/哪一环 | 估时 |", "保留 / 降级 / 延后 / 待授权")), "workload triage still lacks concrete decision fields")
        require(all(term in meeting for term in ("组织者/主持人", "普通参会者", "不得替主持人定议程")), "meeting skill still assumes organizer authority")
        require(all(term in upward for term in ("反馈标准", "偏差例子", "下次动作", "复核日期", "领导确认")), "manager feedback loop is incomplete")
        require(all(term in conflict for term in ("一次具体冲突", "一次上报回应", "不先倾向个人或结构根因")), "conflict triage still over-attributes without events")
        require(all(term in wellbeing for term in ("即时安全", "持续时间", "基本功能", "制度与权限", "不默认“一天”“一周”")), "wellbeing skill still presets leave without four checks")
        require(all(term in career for term in ("标准", "机会", "决定人", "复核日期", "归因写 `待验证`")), "promotion attribution gate is incomplete")
        require(all(term in learning for term in ("结果是否被实际采用", "错误类型与证据坐标", "净节省时间 =", "提高难度、补断点、降低负荷、换方法或停止")), "AI learning evidence loop is incomplete")
        require(all(term in analysis for term in ("抽象评价硬分支", "词义/目标版本", "真实质量/能力", "人物/权力", "当前无唯一最强解释")), "ambiguous feedback can still collapse into a personal ability judgment")
        require(all(term in learning for term in ("交付轨 / 能力轨双轨分账", "AI 生成 / 用户判断 / 用户复核 / 现实采用", "停止/补能力条件")), "delivery and capability help levels are not forced apart")
        require(all(term in automation for term in ("AI + 敏感数据 + 直接外发硬分支", "实际采用率", "实测净节省", "扩大阈值", "降级/停止阈值", "阶段阈值推导硬门", "代表性窗口与样本量", "人工基线及波动", "错误分级与单次后果", "最低净收益", "不得自创数值型上线门")), "AI automation can pass without an evidence-derived net-benefit gate")
        require(all(term in boundary for term in ("来源诚信与再利用硬分支", "公开可访问", "许可/网站条款", "个人信息/保密", "不能被默认视为许可", "来源与使用授权卡", "必测来源诚信用例")), "public source material can still bypass use authorization or independent review")
        goal = (receiver / "xb-goal" / "SKILL.md").read_text(encoding="utf-8")
        plan = (receiver / "xb-plan" / "SKILL.md").read_text(encoding="utf-8")
        data = (receiver / "xb-data" / "SKILL.md").read_text(encoding="utf-8")
        writing = (receiver / "xb-writing" / "SKILL.md").read_text(encoding="utf-8")
        require(all(term in goal for term in ("新简版与旧完整版同时要求", "上层决定未知", "被挤出内容", "模糊评价同时触发自我能力归因", "当前无唯一最强解释")), "changed goals or ambiguous evaluation can hide a required distinction")
        require(all(term in plan for term in ("具体被挤出内容", "取舍决定人", "被挤出页/深度/核验")), "capacity plans can still hide concrete displacement")
        require(all(term in decision for term in ("供应商、采购、合同或试单", "质量/合规/财务复核者", "试单或下单授权者")), "supplier advice can still masquerade as purchase authority")
        require(all(term in data for term in ("十分钟冲突数硬分支", "统计对象与粒度", "ETL/同步批次", "报表/看板版本")), "conflicting metrics can still skip grain or version checks")
        require(all(term in writing for term in ("硬锁不等于事实授权", "文字锁", "事实授权", "仅草稿、不得发布")), "locked wording can still become an unauthorized factual promise")
        require(all(term in meeting for term in ("决定尚未形成", "行动项不可原子化/验收不清", "关键依赖或容量未到位", "才把 M04")), "meeting diagnosis can still jump straight to ownership diffusion")
        require(all(term in knowledge for term in ("权威裁决门", "候选来源清单 + 冲突账 + 待裁决问题", "现实资料治理完成")), "knowledge truth-source authority gate is incomplete")
        print("PASS all baseline one-point gaps have explicit specialist gates")

        role_model = (receiver / "xbskill" / "references" / "role-context-model.md").read_text(encoding="utf-8")
        data_roles = (receiver / "xbskill" / "references" / "data-work-specialties.md").read_text(encoding="utf-8")
        product_roles = (receiver / "xbskill" / "references" / "product-rd-specialties.md").read_text(encoding="utf-8")
        function_roles = (receiver / "xbskill" / "references" / "function-work-specialties.md").read_text(encoding="utf-8")
        finance_marketing_roles = (receiver / "xbskill" / "references" / "finance-marketing-specialties.md").read_text(encoding="utf-8")
        org_genome = (receiver / "xbskill" / "references" / "organization-strategy-genome.md").read_text(encoding="utf-8")
        require(all(term in role_model for term in ("RoleContext", "S0 新手/探路", "S1 入门/独立常规", "S2 老手/复杂系统化", "每轮只问一个", "够用即停", "保存必须征得同意")), "role context, staged help, or progressive interview is incomplete")
        require(all(term in data_roles for term in ("数据分析师", "数据工程师", "数据治理师", "数据产品经理", "用户/决定契约", "回流上游、保留或退役", "DAG 成功不等于数据正确", "四本解释账", "独立查询", "统计对象", "业务 owner", "不得代写原因")), "data role, four-ledger diagnosis, or reality feedback depth is incomplete")
        require(all(term in product_roles for term in ("产品经理", "UX 设计师", "前端工程师", "后端工程师", "架构师", "no-build", "发布合同", "运行反馈包", "破坏性 API", "不得自创“接下来 N 次”", "知会", "不得扩写成审核", "不由“外企/HQ”标签推出")), "product engineering role, calibrated threshold, or matrix-authority depth is incomplete")
        require(all(term in function_roles for term in ("项目管理", "行政", "秘书", "综合办公室", "事项/服务入口卡", "权力与责任图", "会议与决定包", "记录与归档索引", "不能默认拥有的权力")), "functional role or authority depth is incomplete")
        require(all(term in finance_marketing_roles for term in ("状态：已发布", "普通任务按当前岗位族最小加载", "金融/投研", "营销", "投资论点", "证据更新", "催化剂", "客户研究", "增长营销/实验负责人", "不把相关性写成因果")), "finance or marketing active depth/boundary is incomplete")
        require(all(term in org_genome for term in ("国企/中央企业", "民营企业", "外企/跨国公司本地机构", "事业单位", "政府机关", "实际实体层", "candidate", "evidenced", "conflicted", "stale", "不得直接激活动作", "不能激活英语材料", "不给总部追加审核动作", "不能由类别种子生成")), "organization categories can still become stereotypes, invented HQ duties, or unverifiable strategy")
        require(all(term in root_skill for term in ("role-context-model.md", "data-work-specialties.md", "product-rd-specialties.md", "function-work-specialties.md", "finance-marketing-specialties.md", "organization-strategy-genome.md")), "role specialization is not wired into the root entry")
        require("RoleContext.job_family" in contracts and "只读取一套" in contracts, "specialists can skip or indiscriminately load role overlays")
        print("PASS five active role families, staged help, and organization genes are wired")

        source_ledger = (receiver / "xbskill" / "references" / "specialty-source-ledger.md").read_text(encoding="utf-8")
        role_regression = (receiver / "xbskill" / "references" / "role-specialty-regression.md").read_text(encoding="utf-8")
        company_skill = (receiver / "xb-company" / "SKILL.md").read_text(encoding="utf-8")
        require(all(term in source_ledger for term in ("stars_use", "discovery_only", "40 位 commit", "Apache-2.0", "Open Government Licence", "rejected", "不下载、不安装、不执行", "GH-P09", "GH-P10", "GH-P11", "GH-R01", "GH-M01", "GH-X01", "K-Dense-AI/claude-admin-skills")), "specialty sources lack discovery, license, immutable pin, upstream, or execution boundaries")
        require(all(term in role_regression for term in ("D1", "D4", "P1", "P5", "F1", "F4", "I1", "M1", "O1", "O4", "R1", "不得读取“验收观察”", "另一名评审者")), "role regression coverage or answerer-reviewer isolation is incomplete")
        require(all(term in role_regression for term in ("G 目标适配", "C 因果有效", "A 行动权限", "P 权力/结构", "S 安全边界", "E 证据证伪", "R 现实结果", "V 陌生外测")), "role regression redefines or omits the suite-wide eight gates")
        require("八门必须全部为 2" in role_regression and "任一门为 1 留在重写区" in role_regression, "role regression can bypass the suite release gate with a high total score")
        require(all(term in company_skill for term in ("每轮只问一个", "能唯一选择安全动作立即停止", "类别只用于排序候选问题", "未采用的类别刻板假设", "用户明确授权后")), "company interview can still over-question, stereotype, or save without consent")
        print("PASS specialty source ledger, anti-stereotype cases, and blind regression are complete")

        role_forward_record = (receiver / "xbskill" / "references" / "v0.7-role-forward-test-record.md").read_text(encoding="utf-8")
        require(all(term in role_forward_record for term in ("43/48", "48/48", "43/48 → 48/48", "不得发布", "允许发布", "0 分项：0；1 分项：0；2 分项：24")), "v0.7 role forward record loses failure history or final all-two verdict")
        require(all(term in role_forward_record for term in ("类别种子不得直接激活动作", "八门自我一致性审计", "P5 第一次修订试跑", "从发布证据中剔除", "设计者未补写冻结答案")), "v0.7 role forward record hides static, gate-drift, prompt-contamination, or author-patching failures")
        require(all(term in role_forward_record for term in ("D1 冻结重测：16/16", "P5 冻结重测：16/16", "F2 第一轮通过答案", "现实 Problem 已整体解决", "现实组织决定仍未发生")), "v0.7 role forward record can claim reality completion or omit a frozen scenario")
        role_knowledge_record = (receiver / "xbskill" / "references" / "v0.8-role-knowledge-forward-test-record.md").read_text(encoding="utf-8")
        require(all(term in role_knowledge_record for term in ("52/52", "286 条", "130 条", "26 active + 26 no_match", "实际交付物 UTF-8 SHA-256", "不证明任何真实组织已经采用", "用户主动复核点")), "v0.8 role knowledge record loses blind failures, participation proof, or reality boundary")
        require(all(term in role_knowledge_record for term in ("337d9f63e7c8b7665ccd5f554af897bbbefdfad6bd75c0d6e2678b009f159a71", "4f319a9e498691391953abb513e6c97c41dae2cf160324fef95442870742699e", "18082dfab2ffb4c718859ea9562cf04117fc4135f2e0a7abbce9d49967a02331", "65a412a534d5c036998f347256ab8bd72ec9c92fdb14eee140d5037f59bffda6", "702dc09466505a53882fc9409925b17570e6d5e42f3339d21bd49e74e87bcedb")), "v0.8 role knowledge record loses frozen input or evidence digests")
        role_source_update_record = (receiver / "xbskill" / "references" / "v0.9-role-source-update-record.md").read_text(encoding="utf-8")
        require(all(term in role_source_update_record for term in ("8 pass + 8 fail", "active 全部 S=1", "execution_authorized=false", "candidate/pending", "不启动同轮反复改答", "13/13 active", "用户主动复核点")), "v0.9 record hides the failed candidate gate or active-release boundary")
        require(all(term in role_source_update_record for term in ("c28a57473be1d75c824122417bb523de5ebf6c8a4c0f39ac82f9d0ef6f599941", "57413d2bed0423e46a6240ebe3d8bb574fd8ff868b3639905a99c3dd17a92044", "ff1045c0342a9705270d76b528448e2450d970a44bc0810433068859383c8d14", "9f1354350029f6f16db68ea2a2741bbd8c2631a5a88e861b390d05441d7c8828", "cf622b05b496e5368065a2949aa896ade2011e125e8d80b742c51767ec510582")), "v0.9 record loses candidate failure or bridge evidence digests")
        role_v1_release_record = (receiver / "xbskill" / "references" / "v1.0-role-knowledge-release-record.md").read_text(encoding="utf-8")
        require(all(term in role_v1_release_record for term in ("15/15", "五类岗位族", "16/16", "execution_authorized=false", "130 条历史", "Round9", "没有修改 Round9 答案", "用户复核点")), "v1.0 record hides the activation gate, failure history, or reality boundary")
        require(all(term in role_v1_release_record for term in ("06def5b295af435b8080b3fb1a4b696deb804ff6c639aeec8aa0a862fb3f390d", "2ee6cbf21093ab17023952f05c4dcec6a4fd371a4e77fc5d05bc4f2269764598", "400e7949ad84c2be0b0bbf21a94f425682482880df74c16c1ca8bf3e1996b8fc", "bb539a0eff8c073539e2cffe1e4b72e2f80386890d1cef8e59e0cc2e24a54331", "1961b5525b9eac48f916329a911059a9cd86ebc06d7116c50ad59e2c152c96aa", "dbaa80ef10b2c9ed46e14e2bc9c3ab240f8fc7951e3710b7848d1987c78cab37", "e663b7015250c0004e3ccd4a54b8c33d77a728c8b32a0e7616b3425c4c75b943")), "v1.0 record loses frozen Round10, activated release, or updater routing digests")
        print("PASS v0.7-v1.0 role blind failures, clean retests, evidence hashes, and reality boundaries are preserved")

        missing_role = receiver / "xbskill" / "references" / "data-work-specialties.md"
        held_role = missing_role.with_suffix(".md.missing")
        missing_role.rename(held_role)
        code, output = capture_validate(receiver)
        require(code != 0 and str(missing_role) in output, "missing role specialty reference did not fail loudly")
        held_role.rename(missing_role)
        print("PASS missing role specialty reference fails loudly")

        role_skill = (receiver / "xb-role-knowledge" / "SKILL.md").read_text(encoding="utf-8")
        role_protocol = (receiver / "xb-role-knowledge" / "references" / "role-knowledge-protocol.md").read_text(encoding="utf-8")
        role_runtime_schema_path = receiver / "xb-role-knowledge" / "references" / "role-knowledge-runtime.schema.json"
        role_runtime_schema = json.loads(role_runtime_schema_path.read_text(encoding="utf-8"))
        role_catalog_path = receiver / "xb-role-knowledge" / "references" / "builtin-role-knowledge.json"
        role_catalog = json.loads(role_catalog_path.read_text(encoding="utf-8"))
        upstream_registry_path = receiver / "xb-role-knowledge" / "references" / "upstream-role-sources.json"
        upstream_registry = json.loads(upstream_registry_path.read_text(encoding="utf-8"))
        role_ui = (receiver / "xb-role-knowledge" / "agents" / "openai.yaml").read_text(encoding="utf-8")
        require(len(role_catalog["units"]) == 15, "builtin role knowledge catalog does not preserve fifteen released units")
        expected_roles = {
            "数据分析师", "数据工程师", "数据治理师", "数据产品经理", "产品经理", "UX设计师",
            "前端工程师", "后端工程师", "架构师", "项目管理", "行政", "秘书", "综合办公室",
            "金融分析师", "投资研究员", "权益研究员", "投委会支持", "营销经理", "产品营销",
            "增长营销", "营销分析师",
        }
        catalog_roles = {role for unit in role_catalog["units"] for role in unit["roles"]}
        require(expected_roles <= catalog_roles, f"builtin role catalog misses roles: {sorted(expected_roles - catalog_roles)}")
        require(all(unit["status"] == "active" for unit in role_catalog["units"]), "released builtin role unit is not active")
        require(all(unit["review"]["status"] == "passed" and all(score == 2 for score in unit["review"]["scores"].values()) for unit in role_catalog["units"]), "released role unit bypasses all-two review gate")
        require(len(upstream_registry["sources"]) == 7, "upstream role source registry does not contain seven governed repositories")
        upstream_by_id = {item["id"]: item for item in upstream_registry["sources"]}
        require(upstream_by_id["upstream-k-dense-admin-skills"]["availability"] == "expected_unavailable", "missing K-Dense repository is not represented as an explicit unavailable boundary")
        require(
            upstream_by_id["upstream-product-manager-skills-dean"]["intended_use"] == "discovery_only"
            and upstream_by_id["upstream-awesome-agent-skills"]["intended_use"] == "discovery_only",
            "license/curation-limited upstream repositories can become active evidence",
        )
        require(all(term in role_skill for term in ("岗位知识参与闭环", "RoleKnowledgePacket", "E_NO_MATCH", "真实片段", "均视为未参与", "企业类别完全不参与专业单元得分")), "role knowledge runtime or anti-stereotype contract is incomplete")
        require(all(term in role_skill for term in ("upstream_sync.py", "refresh-candidate", "不可信数据", "内化完成", "merge_incremental_evidence.py")), "upstream update or differential evidence contract is not wired into the role knowledge skill")
        require(all(term in role_protocol for term in ("RoleKnowledgeUnit", "RoleKnowledgeRequest", "RoleKnowledgePacket", "ApplicationTrace", "governance_complete=false")), "role knowledge object or project contract is incomplete")
        require(
            role_runtime_schema["$defs"]["RoleKnowledgePacket"]["properties"]["packet_version"]["const"] == "1.3.0"
            and role_runtime_schema["$defs"]["ApplicationTrace"]["properties"]["record_type"]["const"]
            == "RoleKnowledgeApplicationTrace"
            and "role-knowledge-runtime.schema.json" in role_protocol
            and "RoleKnowledgePacket 1.3" in role_skill
            and "RoleKnowledgePacket 1.1" not in role_skill,
            "runtime packet/trace schema or documented packet version drifted",
        )
        require('display_name: "xbskill 岗位知识补充"' in role_ui and "$xb-role-knowledge" in role_ui, "role knowledge UI metadata is not suite-consistent")
        require("`xb-role-knowledge`" in routing.read_text(encoding="utf-8"), "role knowledge skill is not reachable from routing")
        code, output = run_role_tool(receiver, "upstream_sync.py", ["validate"])
        require(code == 0 and "VALID" in output and "sources=7" in output, f"upstream role registry failed offline validation:\n{output}")
        code, output = run_role_tool(receiver, "upstream_sync.py", ["self-test"])
        require(code == 0 and "SELF_TEST_OK" in output and "cases=11" in output, f"upstream updater mocked self-test failed:\n{output}")
        code, output = run_role_knowledge(receiver, ["validate"])
        require(code == 0 and "units=15 active=15" in output, f"released builtin role catalog failed semantic validation:\n{output}")
        receiver_ledger_path = receiver / "xbskill" / "references" / "specialty-source-ledger.md"
        original_ledger_bytes = receiver_ledger_path.read_bytes()
        receiver_ledger_path.write_bytes(original_ledger_bytes + b"\n<!-- coordinate drift probe -->\n")
        code, output = run_role_knowledge(receiver, ["validate"])
        require(code != 0 and "E_SOURCE_COORDINATE" in output, "builtin source ledger coordinates can drift without invalidating active knowledge")
        receiver_ledger_path.write_bytes(original_ledger_bytes)
        receiver_registry_path = receiver / "xb-role-knowledge" / "references" / "builtin-source-registry.json"
        original_registry_bytes = receiver_registry_path.read_bytes()
        changed_registry = json.loads(original_registry_bytes.decode("utf-8"))
        changed_registry["sources"][0]["coordinate"] = "https://example.invalid/replaced-coordinate"
        write_json(receiver_registry_path, changed_registry)
        code, output = run_role_knowledge(receiver, ["validate"])
        require(code != 0 and "E_SOURCE_COORDINATE" in output, "structured source coordinate can drift without invalidating active knowledge")
        receiver_registry_path.write_bytes(original_registry_bytes)
        print("PASS role knowledge child skill, fifteen active units, and all-two gates are wired")

        role_sandbox = sandbox / "role-runtime"
        role_sandbox.mkdir()
        s0_request = {
            "schema_version": 1,
            "current_specialist": "xb-data",
            "job_family": "data",
            "role": "数据工程师",
            "task_family": "数据管道回填",
            "lifecycle_stage": "运行与恢复",
            "proficiency_mode": "S0_new",
            "problem": "DAG 成功但下游发现重复和漏数，需要安全回填",
            "signals": ["DAG 成功但数据错", "重复", "漏数", "回填"],
            "actual_constraints": [],
            "knowledge_requirement": "required",
            "required_unit_ids": [],
            "max_units": 1,
        }
        s0_path = (role_sandbox / "s0-request.json").resolve()
        s0_packet_path = (role_sandbox / "s0-packet.json").resolve()
        write_json(s0_path, s0_request)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(s0_path), "--output", str(s0_packet_path)])
        require(code == 0, f"builtin role resolve failed:\n{output}")
        s0_packet = json.loads(s0_packet_path.read_text(encoding="utf-8"))
        require(s0_packet["used_unit_ids"] == ["rk-data-engineer-pipeline-recovery"], "data engineering request selected the wrong unit")
        require(s0_packet["packet_version"] == "1.3.0", "role packet did not activate the executable delivery/machine-policy contract")
        require(s0_packet["model_prior_fallback"] is False and s0_packet["execution_authorized"] is False, "role packet enables fallback or execution")
        permission_effects = s0_packet["active_injection"]["permissions"]
        require(
            [effect["policy"]["permission"] for effect in permission_effects]
            == ["propose", "decide", "authorize", "execute", "verify", "accept_risk"]
            and permission_effects[0]["policy"]["ai_allowed"] is True
            and all(effect["policy"]["ai_allowed"] is False for effect in permission_effects[1:])
            and all(effect["authority_effect"] is False for effect in permission_effects)
            and all(effect["responsibility_context"] not in effect["content"] for effect in permission_effects),
            "six permissions are not governed by fixed machine policy independently of responsibility prose",
        )
        require(
            all(
                effect["policy"]["execution_allowed"] is False
                and effect["policy"]["human_clearance_required"] is True
                and effect["authority_effect"] is False
                and effect["trigger_context"] not in effect["content"]
                for effect in s0_packet["active_injection"]["risk_gates"]
            ),
            "risk gates can be reversed or expanded by free-text trigger context",
        )
        require(
            all(effect["authority_effect"] is False for effects in s0_packet["active_injection"].values() for effect in effects),
            "a professional or control effect implicitly grants authority",
        )
        require(
            s0_packet["delivery_requirements"]["routing"]["current_specialist"] == "xb-data"
            and s0_packet["delivery_requirements"]["routing"]["lifecycle_stage"] == "运行与恢复"
            and len(s0_packet["delivery_requirements"]["evidence"][0]["claims"]) == 2
            and s0_packet["delivery_requirements"]["evidence"][0]["refresh_triggers"],
            "active delivery requirements omit route, lifecycle, claims, or refresh triggers",
        )
        trace_template = s0_packet["application_trace_template"]
        template_application = trace_template["applications"][0]
        require(
            template_application["effects"][0]["artifact_field"].startswith("role_knowledge.")
            and template_application["effects"][0]["artifact_field"].count(".") >= 2,
            "trace template still asks a stranger to invent a concrete artifact path",
        )
        require(
            f"[[field:{template_application['effects'][0]['artifact_field']}]]"
            in template_application["effects"][0]["artifact_excerpt"],
            "trace template field path is not backed by a literal artifact marker",
        )
        template_control_text = "\n".join(
            excerpt
            for control in template_application["controls"].values()
            for excerpt in control["artifact_excerpts"]
        )
        require(
            all(effect["content"] in template_control_text for effect in permission_effects)
            and all(effect["content"] in template_control_text for effect in s0_packet["active_injection"]["risk_gates"])
            and all(effect["content"] in template_control_text for effect in s0_packet["active_injection"]["stage_adaptation"]),
            "trace template hides exact machine/stage contents that a stranger must render",
        )
        template_validation_text = "\n".join(
            str(value) for value in template_application["effects"][0]["validation_point"].values()
        )
        template_feedback_text = "\n".join(str(value) for value in trace_template["reality_feedback_point"].values())
        require(
            all(effect["content"] in template_validation_text for effect in s0_packet["active_injection"]["validation"])
            and all(effect["content"] in template_feedback_text for effect in s0_packet["active_injection"]["reality_feedback"]),
            "trace template hides selected validation or reality-feedback contents",
        )
        require([item["source_ref"] for item in s0_packet["source_coordinates"]] == s0_packet["source_refs"], "role packet source ids lack exact ledger coordinates")
        require(all(s0_packet["active_injection"][slot] for slot in ("observe", "competing_explanations", "distinguish", "branches", "artifacts", "validation", "reality_feedback")), "selected unit does not change the required action chain")
        require("小样本重放" in " ".join(item["content"] for item in s0_packet["matched_units"][0]["stage_adaptation"]), "S0 adapter lacks guided validation")

        s2_request = dict(s0_request)
        s2_request["proficiency_mode"] = "S2_system"
        s2_path = (role_sandbox / "s2-request.json").resolve()
        s2_packet_path = (role_sandbox / "s2-packet.json").resolve()
        write_json(s2_path, s2_request)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(s2_path), "--output", str(s2_packet_path)])
        require(code == 0, f"S2 role resolve failed:\n{output}")
        s2_packet = json.loads(s2_packet_path.read_text(encoding="utf-8"))
        s0_core_injection = {key: value for key, value in s0_packet["active_injection"].items() if key != "stage_adaptation"}
        s2_core_injection = {key: value for key, value in s2_packet["active_injection"].items() if key != "stage_adaptation"}
        require(s0_packet["claims"] == s2_packet["claims"] and s0_core_injection == s2_core_injection, "stage adapter changed professional facts, permissions, or safety effects")
        require(s0_packet["active_injection"]["stage_adaptation"] != s2_packet["active_injection"]["stage_adaptation"], "stage adapter did not participate in the runtime packet")
        require(s0_packet["matched_units"][0]["stage_adaptation"] != s2_packet["matched_units"][0]["stage_adaptation"], "S0 and S2 help modes are not differentiated")
        require("平台" in " ".join(item["content"] for item in s2_packet["matched_units"][0]["stage_adaptation"]), "S2 adapter lacks system leverage")
        print("PASS builtin resolver changes the action chain while S0/S2 preserve professional facts")

        optional_request = dict(s0_request)
        optional_request.update({
            "role": "实验室协调员",
            "task_family": "陌生设备交接",
            "problem": "没有制度或厂商资料，先判断怎么开始",
            "signals": ["陌生设备"],
            "knowledge_requirement": "optional",
        })
        optional_path = (role_sandbox / "optional-request.json").resolve()
        write_json(optional_path, optional_request)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(optional_path)])
        require(code == 0, f"optional no-match should be a valid explicit result:\n{output}")
        optional_packet = json.loads(output)
        require(optional_packet["status"] == "no_match" and optional_packet["used_unit_ids"] == [] and optional_packet["generic_fallback_allowed"] is True, "optional no-match silently claimed role adaptation")
        require(
            optional_packet["delivery_requirements"]["mode"] == "no_match"
            and len(optional_packet["delivery_requirements"]["responsibility_branches"]) == 3
            and set(optional_packet["delivery_requirements"]["reality_feedback"]) == {"observer", "observable", "when"},
            "no_match delivery omits competing responsibility branches or reality feedback",
        )
        required_request = dict(optional_request)
        required_request["knowledge_requirement"] = "required"
        required_path = (role_sandbox / "required-no-match.json").resolve()
        write_json(required_path, required_request)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(required_path)])
        require(code != 0 and "E_NO_MATCH" in output and "stopped" in output, "required no-match did not stop the affected conclusion")
        stereotype_request = dict(s0_request)
        stereotype_request["organization_category"] = "外企"
        stereotype_path = (role_sandbox / "stereotype-request.json").resolve()
        write_json(stereotype_path, stereotype_request)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(stereotype_path)])
        require(code != 0 and "E_SCHEMA" in output and "organization_category" in output, "organization category can enter professional matching")
        freeform_constraint_request = dict(s0_request)
        freeform_constraint_request["actual_constraints"] = ["华东区域回填规则 v3"]
        freeform_constraint_path = (role_sandbox / "freeform-constraint-request.json").resolve()
        write_json(freeform_constraint_path, freeform_constraint_request)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(freeform_constraint_path)])
        require(code != 0 and "E_SCHEMA" in output and "evidence-bound object" in output, "actual_constraints still accepts a free-form label")
        for index, category in enumerate(("外资企业", "SOE", "SOEs", "某大型国有企业", "国营企业", "政府部门"), start=1):
            disguised_category_request = dict(s0_request)
            disguised_category_request["actual_constraints"] = [{
                "kind": "rule_scope",
                "value": category,
                "evidence_date": "2026-08-11",
                "evidence_ref": "synthetic category must remain unusable",
            }]
            disguised_category_path = (role_sandbox / f"disguised-category-request-{index}.json").resolve()
            write_json(disguised_category_path, disguised_category_request)
            code, output = run_role_knowledge(receiver, ["resolve", "--context", str(disguised_category_path)])
            require(code != 0 and ("E_ORG_STEREOTYPE" in output or "E_AUTHORITY" in output), f"organization synonym entered actual_constraints: {category}")
        missing_specialist_request = dict(s0_request)
        missing_specialist_request["current_specialist"] = "xb-does-not-exist"
        missing_specialist_path = (role_sandbox / "missing-specialist-request.json").resolve()
        write_json(missing_specialist_path, missing_specialist_request)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(missing_specialist_path)])
        require(code != 0 and "E_ROUTE_CONFLICT" in output and "not installed" in output, "a nonexistent current_specialist was accepted")
        malformed_family_request = dict(s0_request)
        malformed_family_request["job_family"] = []
        malformed_family_path = (role_sandbox / "malformed-family-request.json").resolve()
        write_json(malformed_family_path, malformed_family_request)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(malformed_family_path)])
        require(
            code != 0 and "E_SCHEMA" in output and "job_family" in output and "Traceback" not in output,
            "an unhashable request.job_family leaked a traceback instead of E_SCHEMA",
        )
        print("PASS no-match, evidence-bound constraints, organization synonyms, and current specialist existence are deterministic")

        artifact_text, trace = material_artifact_and_trace(s0_packet, "内置数据工程回填判断包")
        artifact_path = (role_sandbox / "delivered-artifact.md").resolve()
        artifact_path.write_text(artifact_text, encoding="utf-8")
        trace_path = (role_sandbox / "trace.json").resolve()
        write_json(trace_path, trace)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(s0_packet_path), "--trace", str(trace_path),
        ])
        require(code != 0 and "--artifact" in output, "verify-trace did not require the actual delivered artifact")
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(s0_packet_path), "--trace", str(trace_path),
            "--artifact", str(artifact_path),
        ])
        require(code == 0 and "TRACE_VALID" in output, f"valid role application trace failed:\n{output}")
        require(
            trace["artifact_sha256"] == hashlib.sha256(artifact_text.encode("utf-8")).hexdigest()
            and trace["applications"][0]["effects"][0]["artifact_excerpt"] in artifact_text
            and isinstance(trace["applications"][0]["effects"][0]["validation_point"], dict)
            and isinstance(trace["reality_feedback_point"], dict)
            and set(trace["applications"][0]["controls"]) == {"permissions", "risk_gates", "stage_adaptation"},
            "positive trace does not bind artifact digest, excerpt, structured validation/reality, and controls",
        )
        malformed_packets: list[tuple[str, dict, str]] = []
        missing_statement_packet = json.loads(json.dumps(s0_packet))
        del missing_statement_packet["matched_units"][0]["claims"][0]["statement"]
        malformed_packets.append(("missing-claim-statement", missing_statement_packet, "JSON Schema violation"))
        missing_claim_sources_packet = json.loads(json.dumps(s0_packet))
        del missing_claim_sources_packet["matched_units"][0]["claims"][0]["source_refs"]
        malformed_packets.append(("missing-claim-source-refs", missing_claim_sources_packet, "JSON Schema violation"))
        empty_evidence_model_packet = json.loads(json.dumps(s0_packet))
        empty_evidence_model_packet["matched_units"][0]["evidence_model"] = {}
        malformed_packets.append(("empty-evidence-model", empty_evidence_model_packet, "JSON Schema violation"))
        dangling_source_packet = json.loads(json.dumps(s0_packet))
        dangling_source_packet["matched_units"][0]["claims"][0]["source_refs"] = ["missing-source"]
        dangling_source_packet["claims"][0]["source_refs"] = ["missing-source"]
        malformed_packets.append(("dangling-claim-source", dangling_source_packet, "absent from source_refs"))
        empty_top_claims_packet = json.loads(json.dumps(s0_packet))
        empty_top_claims_packet["claims"] = []
        malformed_packets.append(("empty-top-level-claims", empty_top_claims_packet, "must exactly equal"))
        duplicate_top_claim_packet = json.loads(json.dumps(s0_packet))
        duplicate_top_claim_packet["claims"].append(json.loads(json.dumps(duplicate_top_claim_packet["claims"][0])))
        malformed_packets.append(("duplicate-top-level-claim", duplicate_top_claim_packet, "must exactly equal"))
        drifted_top_claim_packet = json.loads(json.dumps(s0_packet))
        drifted_top_claim_packet["claims"][0]["statement"] += " forged drift"
        malformed_packets.append(("drifted-top-level-claim", drifted_top_claim_packet, "must exactly equal"))
        for label, malformed_packet, expected_error in malformed_packets:
            malformed_packet_path = (role_sandbox / f"{label}.json").resolve()
            write_json(malformed_packet_path, malformed_packet)
            code, output = run_role_knowledge(receiver, [
                "verify-trace", "--packet", str(malformed_packet_path), "--trace", str(trace_path),
                "--artifact", str(artifact_path),
            ])
            require(
                code != 0 and "E_RK_PACKET" in output and expected_error in output and "Traceback" not in output,
                f"malformed runtime packet was not rejected cleanly ({label}):\n{output}",
            )
        marker = f"[[field:{trace['applications'][0]['effects'][0]['artifact_field']}]]"
        markerless_artifact = artifact_text.replace(marker, "", 1)
        markerless_trace = json.loads(json.dumps(trace))
        markerless_trace["artifact_sha256"] = hashlib.sha256(markerless_artifact.encode("utf-8")).hexdigest()
        markerless_trace["applications"][0]["effects"][0]["artifact_excerpt"] = (
            markerless_trace["applications"][0]["effects"][0]["artifact_excerpt"].replace(marker, "", 1)
        )
        markerless_artifact_path = (role_sandbox / "markerless-artifact.md").resolve()
        markerless_trace_path = (role_sandbox / "markerless-trace.json").resolve()
        markerless_artifact_path.write_text(markerless_artifact, encoding="utf-8")
        write_json(markerless_trace_path, markerless_trace)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(s0_packet_path), "--trace", str(markerless_trace_path),
            "--artifact", str(markerless_artifact_path),
        ])
        require(code != 0 and "E_RK_INERT" in output and "field marker" in output, "a dotted path without a literal artifact marker was accepted")
        forged_permission_packet = json.loads(json.dumps(s0_packet))
        forged_permission_packet["active_injection"]["permissions"][1]["policy"]["ai_allowed"] = True
        forged_permission_packet_path = (role_sandbox / "forged-permission-policy-packet.json").resolve()
        write_json(forged_permission_packet_path, forged_permission_packet)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(forged_permission_packet_path), "--trace", str(trace_path),
            "--artifact", str(artifact_path),
        ])
        require(code != 0 and "E_RK_PACKET" in output and "machine control policy" in output, "AI was allowed to decide by mutating a permission policy")
        forged_risk_packet = json.loads(json.dumps(s0_packet))
        forged_risk_packet["active_injection"]["risk_gates"][0]["policy"]["required_action"] = "continue_and_delete"
        forged_risk_packet_path = (role_sandbox / "forged-risk-policy-packet.json").resolve()
        write_json(forged_risk_packet_path, forged_risk_packet)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(forged_risk_packet_path), "--trace", str(trace_path),
            "--artifact", str(artifact_path),
        ])
        require(code != 0 and "E_RK_PACKET" in output and "machine control policy" in output, "a stop gate was reversed into an execution action")
        inert_trace = json.loads(json.dumps(trace))
        inert_trace["applications"] = []
        inert_trace_path = (role_sandbox / "inert-trace.json").resolve()
        write_json(inert_trace_path, inert_trace)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(s0_packet_path), "--trace", str(inert_trace_path),
            "--artifact", str(artifact_path),
        ])
        require(code != 0 and "E_RK_INERT" in output, "knowledge can be cited without changing the current specialist")
        placeholder_trace = json.loads(json.dumps(trace))
        placeholder_trace["applications"][0]["effects"][0]["artifact_excerpt"] = "<exact excerpt>"
        placeholder_trace_path = (role_sandbox / "placeholder-trace.json").resolve()
        write_json(placeholder_trace_path, placeholder_trace)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(s0_packet_path), "--trace", str(placeholder_trace_path),
            "--artifact", str(artifact_path),
        ])
        require(code != 0 and "E_RK_INERT" in output, "placeholder ApplicationTrace was accepted as material participation")
        semantic_placeholders = (
            ("checker-cn", "validation", "checker", "待定"),
            ("acceptance-cn", "validation", "acceptance_condition", "待补充"),
            ("observer-en", "feedback", "observer", "placeholder"),
            ("when-cn", "feedback", "when", "以后再说"),
            ("checker-en", "validation", "checker", "to be determined"),
        )
        for label, section, field, placeholder in semantic_placeholders:
            semantic_placeholder_trace = json.loads(json.dumps(trace))
            if section == "validation":
                semantic_placeholder_trace["applications"][0]["effects"][0]["validation_point"][field] = placeholder
            else:
                semantic_placeholder_trace["reality_feedback_point"][field] = placeholder
            semantic_placeholder_path = (role_sandbox / f"semantic-placeholder-{label}.json").resolve()
            write_json(semantic_placeholder_path, semantic_placeholder_trace)
            code, output = run_role_knowledge(receiver, [
                "verify-trace", "--packet", str(s0_packet_path), "--trace", str(semantic_placeholder_path),
                "--artifact", str(artifact_path),
            ])
            require(
                code != 0 and "E_RK_INERT" in output and "placeholder" in output and "Traceback" not in output,
                f"semantic placeholder was accepted in ApplicationTrace ({label}):\n{output}",
            )
        unrelated_professional_text = artifact_text + "\n本轮已形成一个可供查看的岗位判断段落。"
        unrelated_professional_path = (role_sandbox / "unrelated-professional-artifact.md").resolve()
        unrelated_professional_path.write_text(unrelated_professional_text, encoding="utf-8")
        unrelated_professional_trace = json.loads(json.dumps(trace))
        unrelated_professional_trace["artifact_sha256"] = hashlib.sha256(unrelated_professional_text.encode("utf-8")).hexdigest()
        unrelated_professional_trace["applications"][0]["effects"][0]["artifact_excerpt"] = "本轮已形成一个可供查看的岗位判断段落。"
        unrelated_professional_trace_path = (role_sandbox / "unrelated-professional-trace.json").resolve()
        write_json(unrelated_professional_trace_path, unrelated_professional_trace)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(s0_packet_path), "--trace", str(unrelated_professional_trace_path),
            "--artifact", str(unrelated_professional_path),
        ])
        require(
            code != 0
            and "E_RK_INERT" in output
            and ("exact field marker" in output or "selected professional effect content" in output),
            "an unrelated generic paragraph proved a professional effect",
        )
        unrelated_control_text = artifact_text + "\n本轮还附带一个控制说明段落。"
        unrelated_control_path = (role_sandbox / "unrelated-control-artifact.md").resolve()
        unrelated_control_path.write_text(unrelated_control_text, encoding="utf-8")
        unrelated_control_trace = json.loads(json.dumps(trace))
        unrelated_control_trace["artifact_sha256"] = hashlib.sha256(unrelated_control_text.encode("utf-8")).hexdigest()
        for binding in unrelated_control_trace["applications"][0]["controls"].values():
            binding["artifact_excerpts"] = ["本轮还附带一个控制说明段落。"]
        unrelated_control_trace_path = (role_sandbox / "unrelated-control-trace.json").resolve()
        write_json(unrelated_control_trace_path, unrelated_control_trace)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(s0_packet_path), "--trace", str(unrelated_control_trace_path),
            "--artifact", str(unrelated_control_path),
        ])
        require(
            code != 0
            and "E_RK_INERT" in output
            and ("must exactly bind every selected control effect" in output or "omit selected control content" in output),
            "an unrelated generic paragraph proved permission/risk/stage controls",
        )
        forged_packet = json.loads(json.dumps(s0_packet))
        forged_packet["active_injection"]["distinguish"][0]["content"] = "forged effect content"
        forged_packet_path = (role_sandbox / "forged-packet.json").resolve()
        write_json(forged_packet_path, forged_packet)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(forged_packet_path), "--trace", str(trace_path),
            "--artifact", str(artifact_path),
        ])
        require(code != 0 and "E_RK_PACKET" in output, "packet that cannot be reproduced from governed catalogs passed trace verification")
        print("PASS ApplicationTrace binds exact professional/control content and rejects missing, inert, unrelated, placeholder, and forged participation")

        project_root = (role_sandbox / "project").resolve()
        project_root.mkdir()
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(s0_path), "--project-root", str(project_root)])
        require(code != 0 and "E_PROJECT_UNINITIALIZED" in output and "catalog.json" in output, "explicit uninitialized project silently fell back to builtin")
        code, output = run_role_knowledge(receiver, ["init-project", "--project-root", str(project_root), "--yes"])
        require(code == 0 and "units=0 governance_complete=false" in output, f"project initialization claimed knowledge completion:\n{output}")
        project_catalog_path = project_root / "memory" / "xbskill" / "role-knowledge" / "catalog.json"
        initialized_project_catalog = json.loads(project_catalog_path.read_text(encoding="utf-8"))
        project_scope_id = initialized_project_catalog["catalog_id"]
        require(
            project_scope_id.startswith("project-role-") and len(project_scope_id) == len("project-role-") + 16,
            "project initialization did not mint a root-bound project scope id",
        )
        unsafe_unit = json.loads(json.dumps(role_catalog["units"][0]))
        unsafe_unit.update({"id": "rk-project-unsafe", "origin": "project", "status": "candidate"})
        unsafe_unit["tests"]["evidence_refs"] = []
        unsafe_unit["review"] = {
            "status": "pending", "answerer_isolated": False, "reviewer_independent": False,
            "scores": {gate: 0 for gate in ("G", "C", "A", "P", "S", "E", "R", "V")},
            "evidence_refs": [], "reviewed_at": None, "reviewer_id": None,
        }
        unsafe_catalog = {
            "record_type": "RoleKnowledgeCatalog", "schema_version": 1,
            "catalog_id": project_scope_id, "catalog_version": "0.2.0",
            "origin": "project", "published_at": "2026-08-11T00:00:00Z",
            "governance_complete": False, "units": [unsafe_unit],
        }
        write_json(project_catalog_path, unsafe_catalog)
        code, output = run_role_knowledge(receiver, ["validate", "--project-root", str(project_root)])
        require(code == 0 and "units=16" in output, f"unbound project candidate did not remain reviewable-only:\n{output}")
        code, output = run_role_knowledge(receiver, [
            "resolve", "--context", str(s0_path), "--project-root", str(project_root),
        ])
        require(
            code == 0 and "rk-project-unsafe" not in json.loads(output)["used_unit_ids"],
            "unbound project candidate entered runtime injection",
        )
        print("PASS project knowledge requires explicit initialization; unbound candidates remain non-injectable")

        project_knowledge_root = project_root / "memory" / "xbskill" / "knowledge"
        code, output = capture_knowledge(["init", "--root", str(project_knowledge_root), "--yes"])
        require(code == 0, f"project knowledge root init failed:\n{output}")
        local_scope = "华东区域数据管道回填流程"
        install_local_knowledge_fixture(project_knowledge_root, authority_scope=local_scope)
        code, output = capture_knowledge(["validate", "--root", str(project_knowledge_root)])
        require(code == 0, f"project source fixture failed full validation:\n{output}")
        local_packet_path = project_knowledge_root / "packets" / "role-local.json"
        code, output = capture_knowledge([
            "packet", "--root", str(project_knowledge_root), "--lock", "lock-one", "--output", str(local_packet_path),
        ])
        require(code == 0, f"project KnowledgePacket creation failed:\n{output}")
        local_source_packet = json.loads(local_packet_path.read_text(encoding="utf-8"))
        local_packet_sha256 = hashlib.sha256(local_packet_path.read_bytes()).hexdigest()
        authority_decision_sha256 = canonical_sha256(local_source_packet["authority_decision"])

        old_unit_id = "rk-data-engineer-pipeline-recovery"
        builtin_data_engineer = next(unit for unit in role_catalog["units"] if unit["id"] == old_unit_id)
        local_unit = json.loads(json.dumps(builtin_data_engineer))
        local_unit.update({
            "id": "rk-project-data-engineer-local-recovery",
            "origin": "project",
            "status": "candidate",
            "authority_scope": local_scope,
            "supersedes": [old_unit_id],
        })
        local_unit["lifecycle_stages"] = ["运行与恢复"]
        local_unit["source_refs"] = ["source-local"]
        local_unit["claims"] = [{
            "id": "claim-local",
            "statement": "在已确认的华东回填范围内，项目固定规则参与当前恢复判断。",
            "conditions": ["请求 actual_constraints 精确命中该权威范围"],
            "source_refs": ["source-local"],
            "disconfirming_signals": ["权威范围、固定版本或项目来源包失效"],
        }]
        source_packet_binding = {
            "binding_version": 1,
            "scope_kind": "project_rule",
            "project_scope_id": project_scope_id,
            "packet_file": "knowledge/packets/role-local.json",
            "packet_sha256": local_packet_sha256,
            "lock_id": local_source_packet["lock_id"],
            "lock_digest": local_source_packet["lock_digest"],
            "authority_decided_at": local_source_packet["authority_decision"]["decided_at"],
            "authority_decision_sha256": authority_decision_sha256,
            "rule_scope_digest": "",
            "claim_ids": ["claim-local"],
        }
        local_scope_binding = {
            "binding_version": 1,
            "scope_kind": "project_rule",
            "project_scope_id": project_scope_id,
            "packet_file": source_packet_binding["packet_file"],
            "packet_sha256": source_packet_binding["packet_sha256"],
            "authority_decision_sha256": source_packet_binding["authority_decision_sha256"],
            "claim_ids": source_packet_binding["claim_ids"],
            "claims_sha256": canonical_sha256(local_unit["claims"]),
            "job_family": local_unit["job_family"],
            "roles": local_unit["roles"],
            "task_families": local_unit["task_families"],
            "lifecycle_stages": local_unit["lifecycle_stages"],
        }
        local_rule_scope_digest = "sha256:" + canonical_sha256(local_scope_binding)
        source_packet_binding["rule_scope_digest"] = local_rule_scope_digest
        local_unit["source_packet"] = source_packet_binding
        local_unit["tests"]["evidence_refs"] = []
        local_unit["review"] = {
            "status": "pending", "answerer_isolated": False, "reviewer_independent": False,
            "scores": {gate: 0 for gate in ("G", "C", "A", "P", "S", "E", "R", "V")},
            "evidence_refs": [], "reviewed_at": None, "reviewer_id": None,
        }
        local_catalog = {
            "record_type": "RoleKnowledgeCatalog", "schema_version": 1,
            "catalog_id": project_scope_id, "catalog_version": "0.3.0",
            "origin": "project", "published_at": "2026-08-11T00:00:00Z",
            "governance_complete": False, "units": [local_unit],
        }
        local_catalog["units"] = [local_unit]
        write_json(project_catalog_path, local_catalog)

        bad_matcher_catalog = json.loads(json.dumps(local_catalog))
        bad_matcher_catalog["units"][0]["task_families"].append("国企回填")
        write_json(project_catalog_path, bad_matcher_catalog)
        code, output = run_role_knowledge(receiver, [
            "validate", "--catalog", str(project_catalog_path), "--project-root", str(project_root),
        ])
        require(code != 0 and "E_ORG_STEREOTYPE" in output and "matcher key" in output, "an organization category entered a professional matcher key")
        write_json(project_catalog_path, local_catalog)

        category_scope_catalog = json.loads(json.dumps(local_catalog))
        category_scope_catalog["units"][0]["source_packet"]["scope_kind"] = "organization_category"
        write_json(project_catalog_path, category_scope_catalog)
        code, output = run_role_knowledge(receiver, [
            "validate", "--catalog", str(project_catalog_path), "--project-root", str(project_root),
        ])
        require(code != 0 and "E_AUTHORITY" in output and "project_rule" in output, "an organization category became a governed project rule scope")

        copied_scope_catalog = json.loads(json.dumps(local_catalog))
        copied_scope_catalog["units"][0]["source_packet"]["project_scope_id"] = "another-project-role-knowledge"
        write_json(project_catalog_path, copied_scope_catalog)
        code, output = run_role_knowledge(receiver, [
            "validate", "--catalog", str(project_catalog_path), "--project-root", str(project_root),
        ])
        require(code != 0 and "E_AUTHORITY" in output and "different project scope" in output, "a project rule scope was copied across project ids")

        other_project_root = (role_sandbox / "other-project").resolve()
        other_project_root.mkdir()
        code, output = run_role_knowledge(receiver, ["init-project", "--project-root", str(other_project_root), "--yes"])
        require(code == 0, f"second project initialization failed:\n{output}")
        other_project_catalog = other_project_root / "memory" / "xbskill" / "role-knowledge" / "catalog.json"
        write_json(other_project_catalog, local_catalog)
        code, output = run_role_knowledge(receiver, ["validate", "--project-root", str(other_project_root)])
        require(code != 0 and "E_AUTHORITY" in output and "exact project root" in output, "a complete project catalog copied into another project kept its authority")

        stale_professional_scope_catalog = json.loads(json.dumps(local_catalog))
        stale_professional_scope_catalog["units"][0]["task_families"].append("恢复复核")
        write_json(project_catalog_path, stale_professional_scope_catalog)
        code, output = run_role_knowledge(receiver, [
            "validate", "--catalog", str(project_catalog_path), "--project-root", str(project_root),
        ])
        require(code != 0 and "E_AUTHORITY" in output and "exact project rule scope" in output, "task/lifecycle scope expanded without refreshing its rule digest")

        stale_claim_scope_catalog = json.loads(json.dumps(local_catalog))
        stale_claim_scope_catalog["units"][0]["claims"][0]["statement"] += " 未经重新治理的扩展。"
        write_json(project_catalog_path, stale_claim_scope_catalog)
        code, output = run_role_knowledge(receiver, [
            "validate", "--catalog", str(project_catalog_path), "--project-root", str(project_root),
        ])
        require(code != 0 and "E_AUTHORITY" in output and "exact project rule scope" in output, "claim semantics changed without refreshing its rule digest")
        write_json(project_catalog_path, local_catalog)

        escaped_catalog_path = (role_sandbox / "escaped-project-catalog.json").resolve()
        write_json(escaped_catalog_path, local_catalog)
        code, output = run_role_knowledge(receiver, [
            "validate", "--catalog", str(escaped_catalog_path), "--project-root", str(project_root),
        ])
        require(code != 0 and "E_PATH_BOUNDARY" in output and str(project_catalog_path.resolve()) in output, "a project catalog outside the governed path was accepted")

        original_packet_bytes = local_packet_path.read_bytes()
        tampered_knowledge_packet = json.loads(original_packet_bytes.decode("utf-8"))
        tampered_knowledge_packet["model_prior_fallback"] = True
        write_json(local_packet_path, tampered_knowledge_packet)
        tampered_catalog = json.loads(json.dumps(local_catalog))
        tampered_catalog["units"][0]["source_packet"]["packet_sha256"] = hashlib.sha256(local_packet_path.read_bytes()).hexdigest()
        tampered_scope_binding = json.loads(json.dumps(local_scope_binding))
        tampered_scope_binding["packet_sha256"] = tampered_catalog["units"][0]["source_packet"]["packet_sha256"]
        tampered_catalog["units"][0]["source_packet"]["rule_scope_digest"] = "sha256:" + canonical_sha256(tampered_scope_binding)
        write_json(project_catalog_path, tampered_catalog)
        tampered_evidence_path = (role_sandbox / "tampered-knowledge-evidence.json").resolve()
        code, output = run_role_tool(receiver, "deterministic_test.py", [
            "--catalog", str(project_catalog_path), "--output", str(tampered_evidence_path),
            "--actor-id", "receiver-deterministic", "--project-root", str(project_root),
        ])
        require(code != 0 and "E_SOURCE_PACKET" in output, "a field-tampered KnowledgePacket passed after rebinding its file digest")
        local_packet_path.write_bytes(original_packet_bytes)
        write_json(project_catalog_path, local_catalog)
        require(
            local_unit["source_packet"]["packet_sha256"] == hashlib.sha256(local_packet_path.read_bytes()).hexdigest(),
            "project source_packet does not bind the exact KnowledgePacket file digest",
        )

        scope_mismatch_catalog = json.loads(json.dumps(local_catalog))
        scope_mismatch_catalog["units"][0]["authority_scope"] = "其他区域数据管道回填流程"
        write_json(project_catalog_path, scope_mismatch_catalog)
        scope_mismatch_evidence_path = (role_sandbox / "scope-mismatch-evidence.json").resolve()
        code, output = run_role_tool(receiver, "deterministic_test.py", [
            "--catalog", str(project_catalog_path), "--output", str(scope_mismatch_evidence_path),
            "--actor-id", "receiver-deterministic", "--project-root", str(project_root),
        ])
        require(code != 0 and "E_AUTHORITY" in output, "project authority_scope drifted from its governed KnowledgePacket")
        write_json(project_catalog_path, local_catalog)
        print("PASS project matcher, path, packet digest/content, and authority boundaries fail loudly")

        role_evidence_root = project_catalog_path.parent / "evidence"
        role_evidence_root.mkdir(parents=True, exist_ok=True)
        deterministic_path = (role_evidence_root / "project-deterministic.json").resolve()
        missing_root_evidence = (role_sandbox / "missing-root-deterministic.json").resolve()
        code, output = run_role_tool(receiver, "deterministic_test.py", [
            "--catalog", str(project_catalog_path), "--output", str(missing_root_evidence),
            "--actor-id", "receiver-deterministic",
        ])
        require(code != 0 and "E_PROJECT_UNINITIALIZED" in output, "project deterministic testing omitted its exact project root")
        code, output = run_role_tool(receiver, "deterministic_test.py", [
            "--catalog", str(project_catalog_path), "--output", str(deterministic_path),
            "--actor-id", "receiver-deterministic", "--project-root", str(project_root),
        ])
        require(code == 0 and "records=4 failed=0" in output, f"project deterministic four-case run failed:\n{output}")
        deterministic_registry = json.loads(deterministic_path.read_text(encoding="utf-8"))
        require(
            len(deterministic_registry["records"]) == 4
            and all(record["result"] == "passed" for record in deterministic_registry["records"]),
            "project deterministic evidence is not exactly four passed records",
        )

        blind_path = (role_sandbox / "project-blind-fixture.json").resolve()
        missing_root_blind = (role_sandbox / "missing-root-blind.json").resolve()
        code, output = run_role_tool(receiver, "blind_fixture.py", [
            "--catalog", str(project_catalog_path), "--output", str(missing_root_blind),
        ])
        require(code != 0 and "E_PROJECT_UNINITIALIZED" in output, "project blind fixture omitted its exact project root")
        code, output = run_role_tool(receiver, "blind_fixture.py", [
            "--catalog", str(project_catalog_path), "--output", str(blind_path),
            "--project-root", str(project_root),
        ])
        require(code == 0 and "cases=4" in output, f"project blind four-case fixture failed:\n{output}")
        blind_fixture = json.loads(blind_path.read_text(encoding="utf-8"))
        require(
            len(blind_fixture["cases"]) == 4
            and {case["case_kind"] for case in blind_fixture["cases"]}
            == {"positive_s0", "positive_s2", "negative", "overturn"},
            "project blind fixture does not contain the exact four scenario kinds",
        )
        blind_answers, blind_reviews = synthesize_blind_round(blind_fixture)
        answers_path = (role_sandbox / "project-blind-answers.json").resolve()
        reviews_path = (role_sandbox / "project-blind-reviews.json").resolve()
        write_json(answers_path, blind_answers)
        write_json(reviews_path, blind_reviews)
        assembled_path = (role_evidence_root / "project-regression.json").resolve()
        code, output = run_role_tool(receiver, "assemble_evidence.py", [
            "--deterministic", str(deterministic_path), "--fixtures", str(blind_path),
            "--answers", str(answers_path), "--reviews", str(reviews_path),
            "--output", str(assembled_path),
        ])
        require(code == 0 and "records=12" in output and "failed_reviews=0" in output, f"project evidence assembly failed:\n{output}")
        assembled_registry = json.loads(assembled_path.read_text(encoding="utf-8"))
        require(
            len(assembled_registry["records"]) == 12
            and sum(record["kind"] == "independent_review" for record in assembled_registry["records"]) == 4,
            "assembled project registry does not bind four deterministic, four answers, and four reviews",
        )

        activated_catalog_path = (role_sandbox / "activated-project-catalog.json").resolve()
        missing_root_activated = (role_sandbox / "missing-root-activated.json").resolve()
        code, output = run_role_tool(receiver, "activate_catalog.py", [
            "--catalog", str(project_catalog_path), "--evidence", str(assembled_path),
            "--output", str(missing_root_activated), "--catalog-version", "1.0.0", "--yes",
        ])
        require(code != 0 and "E_PROJECT_UNINITIALIZED" in output, "project activation omitted its exact project root")
        code, output = run_role_tool(receiver, "activate_catalog.py", [
            "--catalog", str(project_catalog_path), "--evidence", str(assembled_path),
            "--output", str(activated_catalog_path), "--catalog-version", "1.0.0",
            "--project-root", str(project_root), "--yes",
        ])
        require(code == 0 and "units=1" in output, f"fully tested project candidate did not activate:\n{output}")
        activated_catalog = json.loads(activated_catalog_path.read_text(encoding="utf-8"))
        require(
            activated_catalog["governance_complete"] is True
            and activated_catalog["units"][0]["status"] == "active"
            and all(score == 2 for score in activated_catalog["units"][0]["review"]["scores"].values()),
            "activation output lacks governed active/all-two state",
        )
        shutil.copyfile(activated_catalog_path, project_catalog_path)
        code, output = run_role_knowledge(receiver, ["validate", "--project-root", str(project_root)])
        require(code == 0 and "units=16" in output, f"activated project catalog failed governed runtime validation:\n{output}")
        print("PASS project candidate completes deterministic(4), blind(4), assembly, and all-two activation without copied builtin evidence")

        local_result_path = (role_sandbox / "local-packet.json").resolve()
        local_request = dict(s0_request)
        local_request["actual_constraints"] = [{
            "kind": "rule_scope", "value": local_rule_scope_digest, "evidence_date": "2026-08-11",
            "evidence_ref": "knowledge/packets/role-local.json",
        }]
        local_request_path = (role_sandbox / "local-request.json").resolve()
        write_json(local_request_path, local_request)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(local_request_path), "--project-root", str(project_root), "--output", str(local_result_path)])
        require(code == 0, f"authorized project unit failed to resolve:\n{output}")
        local_result = json.loads(local_result_path.read_text(encoding="utf-8"))
        require(local_result["used_unit_ids"] == ["rk-project-data-engineer-local-recovery"], "authorized project supersession did not replace builtin in exact scope")
        hand_hashed_category_request = json.loads(json.dumps(local_request))
        hand_hashed_category_request["actual_constraints"][0]["value"] = (
            "sha256:" + canonical_sha256({"authority_scope": "国企"})
        )
        hand_hashed_category_request["required_unit_ids"] = ["rk-project-data-engineer-local-recovery"]
        hand_hashed_category_path = (role_sandbox / "hand-hashed-category-request.json").resolve()
        write_json(hand_hashed_category_path, hand_hashed_category_request)
        code, output = run_role_knowledge(receiver, [
            "resolve", "--context", str(hand_hashed_category_path), "--project-root", str(project_root),
        ])
        require(code != 0 and "E_AUTHORITY" in output, "a hand-hashed organization label matched a governed project rule")
        require(
            local_result["matched_units"][0]["authority_binding"] == {
                "scope_binding": local_scope_binding,
                "rule_scope_digest": local_rule_scope_digest,
                "packet_file": "knowledge/packets/role-local.json",
                "packet_sha256": local_packet_sha256,
                "authority_decided_at": local_source_packet["authority_decision"]["decided_at"],
            },
            "project RoleKnowledgePacket does not expose its exact packet/scope authority binding",
        )
        require(local_result["supersession_notices"] == [{
            "unit_id": "rk-project-data-engineer-local-recovery",
            "supersedes": "rk-data-engineer-pipeline-recovery",
            "scope_digest": local_rule_scope_digest,
        }], "project override was not explicit and auditable without leaking raw scope")
        require(
            any("task_hits=" in reason for reason in local_result["matched_units"][0]["match_reasons"])
            and any("signal_hits=" in reason for reason in local_result["matched_units"][0]["match_reasons"])
            and any("lifecycle_hits=" in reason for reason in local_result["matched_units"][0]["match_reasons"])
            and "authorized_project_scope" in local_result["matched_units"][0]["match_reasons"],
            "project supersession was not bound by task, signal, lifecycle, and evidenced scope together",
        )

        local_artifact_text, local_trace = material_artifact_and_trace(local_result, "项目数据工程回填判断包")
        local_artifact_path = (role_sandbox / "local-delivered-artifact.md").resolve()
        local_trace_path = (role_sandbox / "local-trace.json").resolve()
        local_artifact_path.write_text(local_artifact_text, encoding="utf-8")
        write_json(local_trace_path, local_trace)
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(local_result_path), "--trace", str(local_trace_path),
            "--artifact", str(local_artifact_path),
        ])
        require(code != 0 and "E_PROJECT_UNINITIALIZED" in output, "project-derived packet trace replay omitted its exact project root")
        code, output = run_role_knowledge(receiver, [
            "verify-trace", "--packet", str(local_result_path), "--trace", str(local_trace_path),
            "--artifact", str(local_artifact_path), "--project-root", str(project_root),
        ])
        require(code == 0 and "TRACE_VALID" in output, f"project-derived packet did not replay against its exact root:\n{output}")

        lifecycle_mismatch = dict(local_request)
        lifecycle_mismatch["lifecycle_stage"] = "采集与摄取"
        lifecycle_mismatch_path = (role_sandbox / "lifecycle-mismatch-request.json").resolve()
        write_json(lifecycle_mismatch_path, lifecycle_mismatch)
        code, output = run_role_knowledge(receiver, [
            "resolve", "--context", str(lifecycle_mismatch_path), "--project-root", str(project_root),
        ])
        require(code == 0, f"lifecycle-mismatched superseder caused resolution failure:\n{output}")
        lifecycle_result = json.loads(output)
        require(
            lifecycle_result["used_unit_ids"] == [old_unit_id]
            and lifecycle_result["supersession_notices"] == [],
            "lifecycle-mismatched project unit blacked out builtin knowledge",
        )

        required_old = dict(local_request)
        required_old["required_unit_ids"] = [old_unit_id]
        required_old_path = role_sandbox / "required-old-request.json"
        write_json(required_old_path, required_old)
        code, output = run_role_knowledge(receiver, ["resolve", "--context", str(required_old_path), "--project-root", str(project_root)])
        require(code == 0 and json.loads(output)["used_unit_ids"] == [old_unit_id], "explicitly required builtin unit was silently replaced")

        over_limit_required = dict(local_request)
        over_limit_required["required_unit_ids"] = [old_unit_id, local_unit["id"]]
        over_limit_required["max_units"] = 1
        over_limit_required_path = (role_sandbox / "over-limit-required-request.json").resolve()
        write_json(over_limit_required_path, over_limit_required)
        code, output = run_role_knowledge(receiver, [
            "resolve", "--context", str(over_limit_required_path), "--project-root", str(project_root),
        ])
        require(code != 0 and "E_REQUIRED_UNIT" in output and "cannot silently truncate" in output, "max_units silently truncated required unit ids")
        print("PASS project supersession needs full task/signal/lifecycle/scope match, preserves old requirements, and never truncates required ids")

        dependency_targets = [
            receiver / "xb-role-knowledge" / "references" / "role-knowledge-protocol.md",
            receiver / "xb-role-knowledge" / "references" / "role-knowledge.schema.json",
            receiver / "xb-role-knowledge" / "references" / "role-knowledge-runtime.schema.json",
            receiver / "xb-role-knowledge" / "references" / "role-knowledge-evidence.schema.json",
            receiver / "xb-role-knowledge" / "references" / "builtin-source-registry.json",
            receiver / "xb-role-knowledge" / "references" / "builtin-source-registry.schema.json",
            receiver / "xb-role-knowledge" / "references" / "upstream-role-sources.json",
            receiver / "xb-role-knowledge" / "references" / "upstream-role-sources.schema.json",
            receiver / "xb-role-knowledge" / "references" / "role-knowledge-regression.json",
            receiver / "xb-role-knowledge" / "scripts" / "role_knowledge.py",
            receiver / "xb-role-knowledge" / "scripts" / "prepare_candidate.py",
            receiver / "xb-role-knowledge" / "scripts" / "deterministic_test.py",
            receiver / "xb-role-knowledge" / "scripts" / "blind_fixture.py",
            receiver / "xb-role-knowledge" / "scripts" / "assemble_evidence.py",
            receiver / "xb-role-knowledge" / "scripts" / "activate_catalog.py",
            receiver / "xb-role-knowledge" / "scripts" / "merge_incremental_evidence.py",
            receiver / "xb-role-knowledge" / "scripts" / "upstream_sync.py",
        ]
        for dependency in dependency_targets:
            held_dependency = dependency.with_name(dependency.name + ".missing")
            dependency.rename(held_dependency)
            code, output = capture_validate(receiver)
            require(code != 0 and str(dependency) in output, f"missing role dependency did not report exact path: {dependency}\n{output}")
            held_dependency.rename(dependency)
        print("PASS role protocol, catalog/evidence schemas, matcher, and governance-chain dependencies fail loudly on a clean receiver")

        rewrite_method = (receiver / "xbskill" / "references" / "specialist-rewrite-method.md").read_text(encoding="utf-8")
        reuse_case = (receiver / "xbskill" / "references" / "dbs-reuse-case.md").read_text(encoding="utf-8")
        specialist_regression = (receiver / "xbskill" / "references" / "specialist-regression.md").read_text(encoding="utf-8")
        forward_record = (receiver / "xbskill" / "references" / "v0.5-forward-test-record.md").read_text(encoding="utf-8")
        require(all(term in rewrite_method for term in ("保留 Keep", "重写 Re-derive", "拒绝 Reject", "竞争解释", "翻转条件", "G 目标适配", "V 陌生外测")), "white-box rewrite method is incomplete")
        require("任一门为 0，拒绝上线" in rewrite_method and "任一门为 1，只能留在重写区" in rewrite_method, "rewrite acceptance gates can be bypassed")
        require(all(term in rewrite_method for term in ("单位/分母", "代表性样本或窗口", "基线及波动", "错误后果", "决定/批准者", "公开可访问或如实标注")), "threshold or source-use evidence can still be replaced by a plausible-looking label")
        require(all(term in reuse_case for term in ("dbs-good-question", "dbs-learning", "dbs-decision", "一手材料追踪", "功能重实现", "三项能力如何接成一个闭环")), "DBS reuse argument is incomplete or untraceable")
        require(all(f"X{i:02d}" in specialist_regression for i in range(1, 20)), "specialist regression does not contain X01-X19")
        require("不得读取本文件" in specialist_regression and "另一名未参与作答的评审者" in specialist_regression, "specialist regression isolation contract is missing")
        require(all(term in forward_record for term in ("177/192", "189/192", "177 → 189 → 192", "不得发布", "192/192", "0 分项：0", "1 分项：0", "允许发布", "无法验证唯一真值", "v0.5-retest-x07b-raw.md", "v0.5-retest-x12b-raw.md")), "v0.5 forward-test failure and retest record is incomplete")
        validate_output_collab_release_evidence(receiver)
        writing_text = (receiver / "xb-writing" / "SKILL.md").read_text(encoding="utf-8")
        presentation_text = (receiver / "xb-presentation" / "SKILL.md").read_text(encoding="utf-8")
        talk_text = (receiver / "xb-talk" / "SKILL.md").read_text(encoding="utf-8")
        for name, text in (("xb-writing", writing_text), ("xb-presentation", presentation_text)):
            require(COPY_FORBIDDEN_RE.search(text) is None, f"{name} still contains a forbidden copy pattern")
        require(
            all(term in talk_text for term in (
                "回复点/截止", "等待窗口", "接收渠道", "对方回应权限",
                "催办次数只记录沟通轨迹，不能单独触发升级",
                "缺少回复点时，先发低风险确认",
            )),
            "xb-talk can still escalate on repeated silence without reply point, waiting, reachability, and authority gates",
        )
        require("两次无回应" not in talk_text, "xb-talk still uses two non-responses as an independent gate")
        print("PASS white-box rewrite, three-part reuse argument, nineteen-case regression, and X13-X19 release evidence are wired")

        task_patterns = (receiver / "xbskill" / "references" / "task-domain-patterns.md").read_text(encoding="utf-8")
        people_patterns = (receiver / "xbskill" / "references" / "people-domain-patterns.md").read_text(encoding="utf-8")
        require(all(term in task_patterns for term in ("最小主张链", "R0 只读", "R4 难逆或高影响", "| 正常 |", "| 边界 |", "| 错误 |", "| 重复 |", "结果回流卡")), "task-domain protocol is incomplete")
        require(all(term in people_patterns for term in ("原子事件", "P/R/F/I", "权力—责任—成本账", "M01", "M12", "不可逆授权", "结果回流协议")), "people-domain protocol is incomplete")
        for name in sm.TASK_DEPTH_SKILLS:
            specialist = (receiver / name / "SKILL.md").read_text(encoding="utf-8")
            require("../xbskill/references/task-domain-patterns.md" in specialist, f"{name} does not load task-domain patterns")
        for name in sm.PEOPLE_DEPTH_SKILLS:
            specialist = (receiver / name / "SKILL.md").read_text(encoding="utf-8")
            require("../xbskill/references/people-domain-patterns.md" in specialist, f"{name} does not load people-domain patterns")
        print("PASS task and people domain models are loaded by every rewritten specialist")

        shared = receiver / "xbskill" / "references" / "task-domain-patterns.md"
        held_shared = shared.with_suffix(".md.missing")
        shared.rename(held_shared)
        code, output = capture_validate(receiver)
        require(code != 0 and str(shared) in output, "missing shared specialist protocol did not fail loudly")
        held_shared.rename(shared)
        print("PASS missing shared specialist protocol fails loudly")

        knowledge_root = (sandbox / "project" / "memory" / "xbskill" / "knowledge").resolve()
        code, output = capture_knowledge(["init", "--root", str(knowledge_root), "--yes"])
        require(code == 0 and "governance_complete=false" in output, f"knowledge init failed or claimed governance completion:\n{output}")
        install_local_knowledge_fixture(knowledge_root)
        code, output = capture_knowledge(["validate", "--root", str(knowledge_root)])
        require(code == 0 and "VALID" in output, f"valid knowledge fixture failed:\n{output}")
        packet_path = (knowledge_root / "packets" / "packet-one.json").resolve()
        code, output = capture_knowledge(["packet", "--root", str(knowledge_root), "--lock", "lock-one", "--output", str(packet_path)])
        require(code == 0 and packet_path.is_file(), f"knowledge packet failed:\n{output}")
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        require(packet["model_prior_fallback"] is False and packet["execution_authorized"] is False, "packet silently enables prior fallback or execution")
        require(capture_knowledge(["activate", "--root", str(knowledge_root), "--lock", "lock-one", "--yes"])[0] == 0, "first lock activation failed")
        require(capture_knowledge(["activate", "--root", str(knowledge_root), "--lock", "lock-two", "--yes"])[0] == 0, "second lock activation failed")
        require(capture_knowledge(["rollback", "--root", str(knowledge_root), "--yes"])[0] == 0, "knowledge rollback failed")
        state = json.loads((knowledge_root / "registry" / "root.json").read_text(encoding="utf-8"))
        require(state["active_lock_id"] == "lock-one" and state["previous_lock_id"] == "lock-two", "rollback did not restore the previous immutable lock")
        print("PASS knowledge init, validate, packet, activate, and rollback lifecycle")

        blocked_root = (sandbox / "blocked" / "memory" / "xbskill" / "knowledge").resolve()
        require(capture_knowledge(["init", "--root", str(blocked_root), "--yes"])[0] == 0, "blocked fixture init failed")
        install_local_knowledge_fixture(blocked_root)
        blocked_source_path = blocked_root / "sources" / "source-local.json"
        blocked_source = json.loads(blocked_source_path.read_text(encoding="utf-8"))
        blocked_source["permissions"]["read"] = False
        blocked_source["license"] = {"status": "unknown", "identifier": None, "usage_notes": "not reviewed"}
        blocked_source["security"] = {"status": "unreviewed", "reviewed_at": None, "reviewed_by": None, "notes": "not reviewed"}
        blocked_source["pin"] = None
        blocked_source["status"] = "candidate"
        write_json(blocked_source_path, blocked_source)
        blocked_lock_path = blocked_root / "locks" / "lock-one.json"
        blocked_lock = json.loads(blocked_lock_path.read_text(encoding="utf-8"))
        blocked_lock["authority_decision"]["status"] = "candidate_only"
        blocked_lock["authority_decision"]["decided_by"] = None
        blocked_lock["authority_decision"]["authority_role"] = None
        blocked_lock["authority_decision"]["decided_at"] = None
        blocked_lock["conflict_review"]["status"] = "incomplete"
        blocked_lock["conflict_review"]["reviewed_at"] = None
        blocked_lock["conflict_review"]["reviewed_by"] = None
        write_json(blocked_lock_path, blocked_lock)
        code, output = capture_knowledge(["validate", "--root", str(blocked_root)])
        require(code != 0 and all(term in output for term in ("E_PERMISSION", "E_LICENSE", "E_SECURITY", "E_PIN", "E_AUTHORITY", "E_CONFLICT")), f"unsafe knowledge candidate did not fail every gate:\n{output}")
        blocked_packet = (blocked_root / "packets" / "blocked.json").resolve()
        require(capture_knowledge(["packet", "--root", str(blocked_root), "--lock", "lock-one", "--output", str(blocked_packet)])[0] != 0, "unsafe knowledge candidate produced a packet")
        require(capture_knowledge(["activate", "--root", str(blocked_root), "--lock", "lock-one", "--yes"])[0] != 0, "unsafe knowledge candidate became active")
        print("PASS missing permission, license, security, pin, authority, and conflict review fail loudly")

        target = sandbox / "installed" / "skills"
        copy_receiver(source, target)
        local = target / "xb-goal" / "LOCAL-LESSONS.md"
        local.write_text("receiver-owned patch\n", encoding="utf-8")
        changed = target / "xb-goal" / "SKILL.md"
        changed.write_text(changed.read_text(encoding="utf-8") + "\nlocal drift\n", encoding="utf-8")
        backup = sandbox / "backup"
        sm.copy_suite(source, target, backup)
        require(local.read_text(encoding="utf-8") == "receiver-owned patch\n", "LOCAL patch was overwritten")
        require(sm.digest(changed) == sm.digest(source / "xb-goal" / "SKILL.md"), "managed drift was not updated")
        print("PASS update preserves LOCAL files and repairs managed drift")

        changed.write_text("broken after update\n", encoding="utf-8")
        sm.restore_suite(backup, target)
        require("local drift" in changed.read_text(encoding="utf-8"), "rollback did not restore pre-update state")
        require(local.read_text(encoding="utf-8") == "receiver-owned patch\n", "rollback lost LOCAL patch")
        print("PASS backup rollback restores exact pre-update suite")

    print("SUMMARY 32/32 receiver tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
