"""Clean-project regressions for topic registration and startup lookup."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from startup_recall import locate_topic, recall_memory
from test_startup_recall import store

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "xb-config/scripts/config_manager.py"
RECALL = ROOT / "xb-memory/scripts/startup_recall.py"


class TopicTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="topic-clean-")
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name).resolve()
        self.project = self.workspace / "项目甲"
        self.other = self.workspace / "项目乙"
        self.material = self.workspace / "外部 材料" / "汇总工具"
        self.material.mkdir(parents=True)
        self.project.mkdir()
        self.other.mkdir()
        self.source = self.workspace / "旧留档.md"
        self.source.write_text(f"每周汇总工具（周报小工具）\n位置：{self.material}\n已经完成试运行。\n排除日巡检。\n",
                               encoding="utf-8")
        self.nav = self.workspace / "导航.md"
        self.nav.write_text("# 项目导航\n\n已有正文。\n", encoding="utf-8")
        self.index = self.workspace / "topic-index.json"

    def config(self, allow=True):
        command = [sys.executable, "-B", str(CONFIG), "set-topic-index", "--project", str(self.workspace),
                   "--path", str(self.index)]
        if allow:
            command.append("--user-confirmed")
        result = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0 if allow else 2, result.stderr)

    @staticmethod
    def preview(bundle):
        c = bundle["topic_registration"]["coordinates"]
        values = [c["canonical_name"], *c["aliases"], c["material_path"], c["status"], *c["exclusions"]]
        bundle["transcript"][1]["content"] = "请确认专题坐标\n" + "\n".join(filter(None, values))

    def bundle(self, number=1, navigation=None, index=False):
        sid = f"2026-11-01-120{number}-topic-sample"
        date = f"2026-11-01T12:0{number}:00+00:00"
        transcript = [
            {"turn": 1, "role": "user", "content": "以后从汇总助手这个名字找，补登旧留档并保存这次对话。"},
            {"turn": 2, "role": "assistant", "content": "请逐项确认专题坐标。"},
            {"turn": 3, "role": "user", "content": "确认专题坐标"},
            {"turn": 4, "role": "assistant", "content": f"是否写入专题索引？\n{self.index}"},
            {"turn": 5, "role": "user", "content": "同意写入专题索引"},
            {"turn": 6, "role": "assistant", "content": f"是否写入专题导航？\n{self.nav}"},
            {"turn": 7, "role": "user", "content": "不写" if navigation == "decline" else "同意写入专题导航"},
        ]
        raw = {"mode": "import", "confirmed_fields": ["aliases", "canonical_name", "exclusions",
                                                       "material_path", "status"],
               "normal_coordinates_confirmed": True, "confirmation_turn": 3,
               "sources": [{"root": str(self.workspace), "file": str(self.source)}],
               "coordinates": {"canonical_name": "每周汇总工具", "aliases": ["周报小工具", "汇总助手"],
                               "material_path": str(self.material), "status": "已经完成试运行。",
                               "exclusions": ["日巡检"]}}
        if navigation:
            raw["navigation"] = {"path": str(self.nav), "decision": navigation, "confirmation_turn": 7,
                                 "user_confirmed": True}
        if index:
            raw["index"] = {"decision": "write", "config_root": str(self.workspace), "path": str(self.index),
                            "confirmation_turn": 5, "user_confirmed": True, "initialize": True}
        bundle = {"schema_version": 2, "session_id": sid, "authorized_current_session": True,
                "network_writes": False, "completeness": "complete", "completeness_gaps": [],
                "transcript": transcript, "session_markdown": "# 专题登记", "progress_markdown": "# 近况\n\n原记录",
                "ontology_delta": {"schema_version": 1, "session_id": sid, "generated_at": date,
                                   "authorized_current_session": True, "authorized_sensitive_long_term": False,
                                   "entities": [], "assertions": []},
                "topic_registration": raw}
        self.preview(bundle)
        return bundle

    def save(self, **kwargs):
        return store.atomic_store(self.project, self.bundle(**kwargs))

    def test_import_lookup_and_no_source_mutation(self):
        original = self.source.read_bytes()
        receipt = self.save()
        self.assertEqual(receipt["startup_query"], "not_recorded")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(self.index.exists())
        result = recall_memory(self.project, "继续周报小工具")
        self.assertEqual(result["material_paths"][0]["path"], str(self.material))
        for alias in ("周报小工具", "汇总助手"):
            topic = locate_topic(self.project, "迭代" + alias)
            self.assertEqual(topic["status"], "matched")
            self.assertEqual(topic["topics"][0]["material_path"], str(self.material))
        excluded = locate_topic(self.project, "继续汇总助手日巡检")
        self.assertEqual(excluded["status"], "ask_location")
        progress = self.project / "memory/xbskill/progress.md"
        self.assertIn("## 冷启动提示卡", progress.read_text(encoding="utf-8").splitlines()[:4])
        bundle = self.bundle(number=2)
        bundle.pop("topic_registration")
        bundle["progress_markdown"] = progress.read_text(encoding="utf-8")
        store.atomic_store(self.project, bundle)
        saved = progress.read_text(encoding="utf-8")
        self.assertIn("周报小工具", saved)
        self.assertIn("原记录", saved)
        self.assertEqual(saved.count("## 冷启动提示卡"), 1)

    def test_cross_root_order_and_navigation(self):
        self.config()
        receipt = self.save(index=True, navigation="write")
        self.assertEqual(receipt["topic_effects"]["navigation"]["path"], str(self.nav))
        self.assertEqual(receipt["topic_effects"]["index"]["status"], "written")
        self.assertIn("已有正文。", self.nav.read_text(encoding="utf-8"))
        self.assertIn("排除相近入口 日巡检", self.nav.read_text(encoding="utf-8"))
        self.save(index=True, navigation="write")
        self.assertEqual(self.nav.read_text(encoding="utf-8").count("<!-- xbskill-topic "), 1)
        other_nav = self.workspace / "另一个导航.md"
        other_nav.write_text("# 项目导航\n", encoding="utf-8")
        cli = subprocess.run([sys.executable, "-B", str(RECALL), "--locate", "--project-root", str(self.other),
                              "--workspace-root", str(self.workspace), "--navigation", str(other_nav),
                              "--task", "接着做汇总助手"], capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        result = json.loads(cli.stdout)
        self.assertEqual([s["step"] for s in result["steps"]], ["project_memory", "navigation", "topic_index"])
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["topics"][0]["material_path"], str(self.material))
        self.assertEqual(locate_topic(self.other, "继续汇总助手", self.nav, self.workspace)["steps"][-1]["step"],
                         "navigation")
        missed = locate_topic(self.other, "继续没有登记的项目", self.nav, self.workspace)
        self.assertEqual(missed["status"], "ask_location")
        self.assertEqual(len(missed["steps"]), 3)
        self.material.rmdir()
        self.assertEqual(locate_topic(self.other, "继续汇总助手", self.nav, self.workspace)["status"],
                         "material_missing")

    def test_missing_and_invalid_targets_do_not_create_files(self):
        self.config()
        with self.assertRaisesRegex(ValueError, "E_TOPIC_INDEX"):
            locate_topic(self.other, "继续汇总助手", self.nav, self.workspace)
        self.nav.unlink()
        with self.assertRaisesRegex(ValueError, "E_TOPIC_READ"):
            locate_topic(self.other, "继续汇总助手", self.nav, self.workspace)
        receipt = self.save(navigation="write")
        self.assertEqual(receipt["status"], "saved_with_topic_errors")
        self.assertEqual(receipt["topic_effects"]["navigation"]["status"], "error")
        self.assertFalse(self.nav.exists())
        self.assertFalse(self.index.exists())
        self.assertTrue((self.project / "memory/xbskill/progress.md").is_file())

    def test_unauthorized_destinations_and_unsupported_path(self):
        self.config(allow=False)
        self.assertFalse((self.workspace / ".xbskill").exists())
        original = self.nav.read_bytes()
        for field in ("index", "navigation"):
            bundle = self.bundle(index=True, navigation="write")
            bundle["topic_registration"][field]["user_confirmed"] = False
            with self.assertRaisesRegex(ValueError, "E_TOPIC_AUTH"):
                store.atomic_store(self.project, bundle)
        bundle = self.bundle()
        bundle["topic_registration"]["coordinates"]["material_path"] = str(self.material.parent)
        self.preview(bundle)
        with self.assertRaisesRegex(ValueError, "E_TOPIC_EVIDENCE"):
            store.atomic_store(self.project, bundle)
        self.assertFalse((self.project / "memory").exists())
        self.assertEqual(self.nav.read_bytes(), original)
        self.assertFalse(self.index.exists())
        self.source.write_text("每周汇总工具（周报小工具）\n材料是桌面文件。\n已经完成试运行。\n排除日巡检。",
                               encoding="utf-8")
        bundle["topic_registration"]["coordinates"]["material_path"] = None
        self.preview(bundle)
        store.atomic_store(self.project, bundle)
        result = locate_topic(self.project, "继续汇总助手")
        self.assertEqual(result["status"], "material_unrecorded")
        self.assertIsNone(result["topics"][0]["material_path"])

    def test_distinct_confirmation_rejects_refusal_and_wrong_destination(self):
        self.config()
        original = self.nav.read_bytes()
        for turn in (5, 7):
            bundle = self.bundle(index=True, navigation="write")
            bundle["transcript"][turn - 1]["content"] = "不同意写入"
            with self.assertRaisesRegex(ValueError, "E_TOPIC_AUTH"):
                store.atomic_store(self.project, bundle)
        bundle = self.bundle(index=True)
        wrong = self.workspace / "未经确认.json"
        bundle["topic_registration"]["index"]["path"] = str(wrong)
        with self.assertRaisesRegex(ValueError, "E_TOPIC_AUTH"):
            store.atomic_store(self.project, bundle)
        bundle = self.bundle(index=True)
        bundle["transcript"][3]["content"] += ".backup"
        with self.assertRaisesRegex(ValueError, "E_TOPIC_AUTH"):
            store.atomic_store(self.project, bundle)
        self.assertFalse((self.project / "memory").exists())
        self.assertFalse(self.index.exists())
        self.assertFalse(wrong.exists())
        self.assertEqual(self.nav.read_bytes(), original)

    def test_excluded_identity_cannot_reenter_from_older_records(self):
        self.config()
        self.save(index=True)
        payload = json.loads(self.index.read_text(encoding="utf-8"))
        payload["topics"][0]["exclusions"] = []
        self.index.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        bundle = self.bundle(number=2)
        bundle.pop("topic_registration")
        ref = dict(session_id=bundle["session_id"], turn=1, role="user", excerpt="汇总助手")
        normal = self.project / "memory/xbskill/ontology"
        entity = json.loads((normal / "entities.json").read_text(encoding="utf-8"))["entities"][0]
        assertion = json.loads((normal / "assertions.json").read_text(encoding="utf-8"))["assertions"][0]
        entity.update(entity_id="project:old-topic", source_refs=[ref])
        assertion.update(assertion_id="a:old-topic", subject_id=entity["entity_id"], source_refs=[ref],
                         qualifiers={"material_path": str(self.material)})
        bundle["ontology_delta"]["entities"] = [entity]
        bundle["ontology_delta"]["assertions"] = [assertion]
        store.atomic_store(self.project, bundle)
        result = locate_topic(self.project, "继续汇总助手日巡检", self.nav, self.workspace)
        self.assertEqual(result["status"], "ask_location")
        self.assertEqual(result["topics"], [])

    def test_corrupt_index_and_path_prefix_are_rejected(self):
        self.config()
        self.index.write_text('{"schema_version":1,"topics":[null],"topics":[]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate field"):
            locate_topic(self.other, "继续汇总助手", self.nav, self.workspace)
        self.source.write_text(f"每周汇总工具（周报小工具）\n位置：{self.material},备份\n已经完成试运行。\n排除日巡检。",
                               encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "E_TOPIC_EVIDENCE"):
            self.save()
        topic = store.load_topics()
        with self.assertRaisesRegex(ValueError, "local absolute path"):
            topic.path_of("//server/share/test.json")

    def test_decline_and_retry_once(self):
        original = self.nav.read_bytes()
        self.assertEqual(self.save(navigation="offer")["topic_effects"]["navigation"]["status"], "offer")
        self.assertEqual(self.save(navigation="decline")["topic_effects"]["navigation"]["status"], "declined")
        self.assertEqual(self.save(number=2, navigation="offer")["topic_effects"]["navigation"]["status"], "offer")
        self.assertEqual(self.save(number=3, navigation="offer")["topic_effects"]["navigation"]["status"], "suppressed")
        self.assertEqual(self.nav.read_bytes(), original)

    def test_navigation_code_examples_are_neither_routes_nor_append_targets(self):
        fence = chr(96) * 3
        quoted = chr(96) + str(self.material) + chr(96)
        example = (f"# 项目导航\n\n{fence}markdown\n## xbskill 专题入口\n"
                   f"| 影子专题 | {quoted} |\n{fence}\n\n## 正文\n已有说明。\n")
        self.nav.write_bytes(example.encode("utf-8"))
        result = locate_topic(self.other, "继续影子专题", self.nav)
        self.assertEqual(result["status"], "ask_location")
        self.assertEqual(self.save(navigation="write")["topic_effects"]["navigation"]["status"], "written")
        saved = self.nav.read_text(encoding="utf-8")
        self.assertTrue(saved.startswith(example))
        self.assertIn("<!-- xbskill-topic ", saved[len(example):])
        self.assertEqual(locate_topic(self.other, "继续汇总助手", self.nav)["status"], "matched")

    def test_alias_collision_and_startup_receipt(self):
        self.config()
        self.save(index=True)
        new = self.workspace / "另一工具"
        new.mkdir()
        self.source.write_text(f"每周汇总工具（周报小工具）\n位置：{new}\n已经完成试运行。\n排除日巡检。",
                               encoding="utf-8")
        bundle = self.bundle(number=2, index=True)
        bundle["topic_registration"]["coordinates"]["material_path"] = str(new)
        self.preview(bundle)
        bundle["startup_check"] = locate_topic(self.project, bundle["transcript"][0]["content"])
        receipt = store.atomic_store(self.project, bundle)
        self.assertEqual(receipt["startup_query"], "recorded")
        result = locate_topic(self.other, "继续汇总助手", self.nav, self.workspace)
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual({item["material_path"] for item in result["topics"]}, {str(self.material), str(new)})
        wrong = copy.deepcopy(bundle)
        wrong["startup_check"]["project_root"] = str(self.other)
        with self.assertRaisesRegex(ValueError, "E_STARTUP_RECEIPT"):
            store.atomic_store(self.project, wrong)


if __name__ == "__main__":
    unittest.main()
