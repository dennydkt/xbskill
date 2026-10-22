"""Isolated preference and invocation tests; no user configuration is written."""
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import config_manager as manager


def config(call="high", save="low"):
    return {"schema_version": 1, "call_intensity": call, "save_prompt": save}


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name).resolve()

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(manager.ConfigError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_missing_read_does_not_initialize(self):
        self.assertEqual(manager.load_config(self.project), manager.empty_config())
        self.assertEqual(list(self.project.iterdir()), [])

    def test_explicit_choices_and_atomic_roundtrip(self):
        for call, save in itertools.product(("high", "medium", "low"), ("high", "low")):
            with self.subTest(call=call, save=save):
                value = config(call, save)
                path = manager.write_config(self.project, value, user_confirmed=True)
                self.assertEqual(manager.load_config(self.project), value)
                self.assertEqual(Path(path), self.project / ".xbskill" / "config.json")
                self.assertEqual(len(list(Path(path).parent.iterdir())), 1)

    def test_no_auth_or_partial_write(self):
        self.assert_error("E_CONFIG_AUTH", manager.write_config, self.project, config())
        self.assert_error("E_CONFIG_AUTH", manager.write_config, self.project, config(), user_confirmed=1)
        self.assert_error("E_CONFIG_INCOMPLETE", manager.write_config, self.project, config(None), user_confirmed=True)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_strict_schema_and_unconfigured_fields(self):
        for value, code in (([], "E_CONFIG_TYPE"), ({}, "E_CONFIG_VERSION"),
                            ({"schema_version": True}, "E_CONFIG_VERSION"),
                            ({"schema_version": 2}, "E_CONFIG_VERSION"),
                            ({**config(), "auto_checkpoint": True}, "E_CONFIG_FIELDS"),
                            (config("ask"), "E_CONFIG_VALUE"), (config(save=[]), "E_CONFIG_VALUE")):
            self.assert_error(code, manager.validate_config, value)
        self.assertEqual(manager.validate_config({"schema_version": 1}), manager.empty_config())

    def test_corruption_is_not_overwritten(self):
        folder = self.project / ".xbskill"
        folder.mkdir()
        path = folder / "config.json"
        for content, code in (("{", "E_CONFIG_JSON"), ('{"schema_version":1,"schema_version":1}', "E_CONFIG_FIELDS"),
                              (json.dumps({**config(), "legacy": True}), "E_CONFIG_FIELDS")):
            path.write_text(content, encoding="utf-8")
            self.assert_error(code, manager.load_config, self.project)
            self.assert_error(code, manager.write_config, self.project, config(), user_confirmed=True)
            self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_failed_replace_keeps_previous_and_removes_temp(self):
        manager.write_config(self.project, config("low"), user_confirmed=True)
        with patch.object(manager.os, "replace", side_effect=OSError("denied")):
            self.assert_error("E_CONFIG_WRITE", manager.write_config, self.project, config(), user_confirmed=True)
        self.assertEqual(manager.load_config(self.project), config("low"))
        self.assertEqual(len(list((self.project / ".xbskill").iterdir())), 1)

    def test_invalid_project_and_parent(self):
        self.assert_error("E_CONFIG_PROJECT", manager.load_config, None)
        self.assert_error("E_CONFIG_PROJECT", manager.load_config, "relative")
        (self.project / ".xbskill").write_text("file", encoding="utf-8")
        self.assert_error("E_CONFIG_PATH", manager.load_config, self.project)

    def test_gate_matrix_and_external_priority(self):
        for call, save in itertools.product(("high", "medium", "low"), ("high", "low")):
            value = config(call, save)
            gate = lambda **kwargs: manager.decide_gate(value, task_id="t1", specialist="xb-review", **kwargs)["decision"]
            self.assertEqual(gate(natural_match=True), {"high": "allow", "medium": "confirm", "low": "deny"}[call])
            self.assertEqual(gate(), "deny")
            self.assertEqual(gate(explicit_xb=True), "allow")
            self.assertEqual(gate(explicit_external=True, explicit_xb=True, natural_match=True), "allow")
            self.assertEqual(gate(refused_xb=True, explicit_xb=True), "deny")
            self.assertEqual(gate(authorized_task="t1", authorized_specialist="xb-review"), "allow")
        self.assertEqual(manager.decide_gate({}, task_id="", specialist="", explicit_external=True)["decision"], "deny")

    def test_medium_confirmation_scope(self):
        for task, specialist in (("t2", "xb-review"), ("t1", "xb-writing"), (None, None)):
            result = manager.decide_gate(config("medium"), task_id="t1", specialist="xb-review", natural_match=True,
                                         authorized_task=task, authorized_specialist=specialist)
            self.assertEqual(result["decision"], "confirm")

    def test_joint_save_and_refusal_sequence(self):
        for call, save in itertools.product(("high", "medium", "low"), ("high", "low")):
            value = config(call, save)
            invoke = lambda **kw: manager.decide_gate(value, task_id="budget", specialist="xb-data", **kw)
            self.assertEqual(invoke(explicit_xb=True, explicit_external=True)["reason"], "joint_request")
            self.assertEqual(invoke(authorized_task="budget", authorized_specialist="xb-data")["decision"], "allow")
            self.assertEqual(invoke(explicit_external=True, authorized_task="budget", authorized_specialist="xb-data")["decision"], "deny")
            self.assert_error("E_GATE_SCOPE", invoke, save_requested=True, explicit_external=True)
            self.assertEqual(manager.decide_gate(value, task_id="budget", specialist="xb-save",
                                                 save_requested=True, explicit_external=True)["reason"], "save_request")
            self.assertEqual(invoke(save_requested=True, refused_xb=True)["reason"], "user_refusal")
        self.assertEqual(manager.decide_gate(manager.empty_config(), task_id="t", specialist="xbskill",
                                            explicit_xb=True, explicit_external=True)["decision"], "configure")
        self.assertEqual(manager.decide_gate({}, task_id="t", specialist="xb-save", save_requested=True)["decision"], "allow")
        self.assert_error("E_GATE_TYPE", manager.decide_gate, config(), task_id="t", specialist="xb-save", save_requested="yes")

    def test_cli_joint_reads_config_but_save_does_not_depend_on_it(self):
        script = str(Path(manager.__file__).resolve())
        folder = self.project / ".xbskill"
        folder.mkdir()
        path = folder / "config.json"
        path.write_text("{broken", encoding="utf-8")
        def run(*flags):
            return subprocess.run([sys.executable, "-B", script, "gate", "--project", str(self.project),
                                   "--task-id", "t", "--specialist", "xb-save", *flags],
                                  text=True, capture_output=True, timeout=10)
        self.assertEqual(run("--explicit-external").returncode, 0)
        self.assertEqual(run("--explicit-external", "--explicit-xb").returncode, 2)
        saved = run("--explicit-external", "--save-requested")
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertEqual(json.loads(saved.stdout)["reason"], "save_request")
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
        self.assertFalse((self.project / "memory").exists())

    def test_unconfigured_never_natural_triggers(self):
        for value in (manager.empty_config(), config(None), config(save=None)):
            self.assertEqual(manager.decide_gate(value, task_id="t", specialist="xb-review", natural_match=True)["decision"], "deny")
            self.assertEqual(manager.decide_gate(value, task_id="t", specialist="xb-review", explicit_xb=True)["decision"], "configure")
            self.assertFalse(manager.should_prompt_save(value))

    def test_save_prompt_has_no_write_permission(self):
        for call, save, final, active in itertools.product(("high", "medium", "low"), ("high", "low"), (True, False), (True, False)):
            self.assertEqual(manager.should_prompt_save(config(call, save), final_response=final, xb_active=active),
                             final and active and save == "high")
        self.assertEqual(list(self.project.iterdir()), [])

    def test_cli_read_and_error(self):
        script = str(Path(manager.__file__).resolve())
        def run(*args):
            return subprocess.run([sys.executable, "-B", script, *args], text=True, capture_output=True, timeout=10)
        result = run("read", "--project", str(self.project))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "unconfigured")
        result = run("set", "--project", str(self.project), "--call-intensity", "high", "--save-prompt", "high")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"], "E_CONFIG_AUTH")


if __name__ == "__main__":
    unittest.main()
