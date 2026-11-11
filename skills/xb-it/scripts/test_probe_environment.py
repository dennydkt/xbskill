"""Behavioral checks for the environment probe; no third-party dependencies."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest import mock


PROBE_PATH = Path(__file__).resolve().with_name("probe_environment.py")
spec = importlib.util.spec_from_file_location("xb_environment_probe_under_test", PROBE_PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class EnvironmentProbeTests(unittest.TestCase):
    def test_scope_rejected_before_discovery(self):
        with mock.patch.object(probe, "_platform_status") as discover:
            for scope, confirmed in (("user-device", False), ("execution-host", True), ("other", True)):
                with self.subTest(scope=scope, confirmed=confirmed), self.assertRaises(probe.ScopeError):
                    probe.collect_environment(scope, confirmed)
            discover.assert_not_called()

    def test_default_never_claims_user_device(self):
        with mock.patch.object(probe.importlib.util, "find_spec", return_value=None), mock.patch.object(probe.shutil, "which", return_value=None):
            report = probe.collect_environment()
        self.assertEqual(report["scope"], "execution-host")
        self.assertEqual(report["scope_basis"], "execution_context_only")
        self.assertTrue(all(v == "unknown" for v in report["unverified"].values()))
        self.assertEqual(report["python"]["modules"]["tkinter"]["availability"], "unavailable")
        self.assertEqual(report["programs"]["node"]["availability"], "unavailable")
        self.assertEqual(report["programs"]["browser"]["installed_on_device"], "unknown")

    def test_local_confirmation_does_not_claim_runtime_validation(self):
        with mock.patch.object(probe.importlib.util, "find_spec", return_value=object()), mock.patch.object(probe.shutil, "which", return_value="C:/Users/private/bin/tool.exe"):
            report = probe.collect_environment("user-device", True)
        self.assertEqual(report["scope_basis"], "explicit_local_confirmation")
        self.assertTrue(all(v == "unknown" for v in report["unverified"].values()))
        for item in list(report["python"]["modules"].values()) + list(report["programs"].values()):
            self.assertEqual(item["availability"], "available")
            self.assertEqual(item["runtime_test"], "unknown")

    def test_private_paths_and_exception_messages_are_not_output(self):
        secret_path = "C:/Users/PRIVATE_PERSON/secret-token/tool.exe"
        def locate(name):
            if name == "node":
                raise OSError(secret_path)
            return secret_path
        with mock.patch.object(probe.importlib.util, "find_spec", side_effect=ImportError(secret_path)), mock.patch.object(probe.shutil, "which", side_effect=locate), mock.patch.object(probe.platform, "machine", return_value=secret_path):
            encoded = json.dumps(probe.collect_environment())
        self.assertNotIn("PRIVATE_PERSON", encoded)
        self.assertNotIn("secret-token", encoded)
        self.assertNotIn(secret_path, encoded)
        self.assertNotRegex(encoded, r"[A-Za-z]:[\\/]|/Users/|/home/")
        report = json.loads(encoded)
        self.assertEqual(report["platform"]["reported_architecture"], "unknown")
        self.assertEqual(report["python"]["modules"]["pandas"]["availability"], "unknown")
        self.assertEqual(report["programs"]["node"]["reason"], "discovery_error")

    def test_discovery_errors_are_unknown_not_absent(self):
        with mock.patch.object(probe.shutil, "which", side_effect=OSError("private")):
            result = probe._program_status(("node", "nodejs"))
        self.assertEqual(result["availability"], "unknown")
        self.assertEqual(result["commands"], [])

    def test_discovery_uses_only_fixed_top_level_names(self):
        with mock.patch.object(probe.importlib.util, "find_spec", return_value=None) as modules, mock.patch.object(probe.shutil, "which", return_value=None) as commands:
            probe.collect_environment()
        self.assertEqual([call.args[0] for call in modules.call_args_list], list(probe.MODULE_NAMES))
        self.assertTrue(all(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) for name in probe.MODULE_NAMES))
        self.assertEqual([call.args[0] for call in commands.call_args_list], [name for names in probe.PROGRAM_NAMES.values() for name in names])

    def test_probe_itself_never_launches_a_program(self):
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("program launch forbidden")):
            report = probe.collect_environment()
        self.assertIn(report["platform"]["system"], ("Windows", "macOS", "Linux", "unknown"))
        self.assertRegex(report["python"]["version"], r"^\d+\.\d+\.\d+$")
        self.assertIn(report["platform"]["interpreter_pointer_bits"], (32, 64))
        self.assertEqual(json.loads(json.dumps(report)), report)

    def test_main_emits_structured_error(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            status = probe.main(["--scope", "user-device"])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(stream.getvalue())["error"], "invalid_scope_confirmation")

    def test_real_cli_default_and_confirmation(self):
        for arguments, expected_status in (([], 0), (["--scope", "user-device"], 2), (["--scope", "user-device", "--confirmed-local"], 0)):
            with self.subTest(arguments=arguments):
                completed = subprocess.run([sys.executable, "-B", str(PROBE_PATH), *arguments], capture_output=True, text=True, timeout=20)
                self.assertEqual(completed.returncode, expected_status, completed.stderr)
                self.assertEqual(completed.stderr, "")
                result = json.loads(completed.stdout)
                if expected_status == 0:
                    self.assertEqual(result["scope"], "user-device" if arguments else "execution-host")
                    self.assertTrue(all(v == "unknown" for v in result["unverified"].values()))
                else:
                    self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
