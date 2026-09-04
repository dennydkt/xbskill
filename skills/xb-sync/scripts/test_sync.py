#!/usr/bin/env python3
"""Portable black-box regression suite. Run with Python 3.10+ in the full suite.

Uses only synthetic data in a fresh temporary directory. Requires xb-memory as
a sibling skill. Link tests explicitly skip if the operating system denies link
creation. No user memory or host configuration is read or changed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("xb_sync.py")
MEMORY = SCRIPT.parents[2] / "xb-memory" / "scripts" / "memory_ontology.py"


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xb-sync-test-")
        self.base = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def root(self, name):
        path = self.base / name / "memory" / "xbskill"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def registry(self, roots, canonical=None):
        path = self.base / "registry.json"
        self.put(path, json.dumps({"version": 1, "canonical": str(canonical) if canonical else None,
                                  "roots": [{"path": str(root)} for root in roots]}))
        return path

    def cli(self, *args, ok=True):
        proc = subprocess.run([sys.executable, "-B", str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        else:
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    @staticmethod
    def snapshot(root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file()}

    @staticmethod
    def contents(root, name):
        return [p.read_text(encoding="utf-8") for p in root.rglob(name) if p.is_file()]

    def test_discover_root_itself_and_explicit_apply(self):
        home = self.root("home")
        reg = self.base / "registry.json"
        result = self.cli("discover", "--scan-root", home, "--registry", reg)
        self.assertIn("memory roots found: 1", result.stdout)
        self.assertFalse(reg.exists())
        self.cli("discover", "--scan-root", home, "--registry", reg, "--apply")
        data = json.loads(reg.read_text())
        self.assertEqual([r["path"] for r in data["roots"]], [str(home)])

    def test_normal_multiroot_dry_copy_quarantine_and_canonical(self):
        home, first, second = self.root("home"), self.root("first"), self.root("second")
        self.put(first / "sessions/one/transcript.md", "first transcript")
        self.put(second / "sessions/two/transcript.md", "second transcript")
        self.put(first / "context/company.md", "first project context")
        self.put(second / "notes.md", "second project notes")
        self.put(first / "progress.md", "local progress")
        self.put(first / "memory-settings.md", "local settings")
        self.put(first / "ontology/entities.json", "{}")
        reg = self.registry([home, first, second])
        before = self.snapshot(self.base)
        self.cli("sync", "--registry", reg, "--home", home)
        self.assertEqual(before, self.snapshot(self.base))
        satellites = [self.snapshot(first), self.snapshot(second)]
        self.cli("sync", "--registry", reg, "--home", home, "--apply")
        self.assertEqual([self.snapshot(first), self.snapshot(second)], satellites)
        self.assertCountEqual(self.contents(home / "sessions", "transcript.md"),
                         ["first transcript", "second transcript"])
        self.assertFalse((home / "context").exists())
        self.assertFalse((home / "notes.md").exists())
        for name in ("progress.md", "memory-settings.md", "ontology"):
            self.assertFalse((home / name).exists())
        self.assertEqual(self.contents(home / "imports", "company.md"), ["first project context"])
        self.assertEqual(self.contents(home / "imports", "notes.md"), ["second project notes"])
        self.assertTrue(list((home / "imports/receipts").glob("*.json")))
        self.assertEqual(json.loads(reg.read_text())["canonical"], str(home))
        self.cli("sync", "--registry", reg)

    def test_multiroot_same_session_path_preserves_both_sources(self):
        home, first, second = self.root("home"), self.root("first"), self.root("second")
        for root, value in ((first, "first"), (second, "second")):
            self.put(root / "sessions/same/transcript.md", value)
        reg = self.registry([home, first, second], home)
        self.cli("sync", "--registry", reg, "--apply")
        self.assertEqual((home / "sessions/same/transcript.md").read_text(), "first")
        self.assertEqual(self.contents(home / "conflicts", "transcript.md"), ["second"])

    def test_whole_session_collision_prevents_mixed_provenance(self):
        home, satellite = self.root("home"), self.root("satellite")
        self.put(home / "sessions/same/transcript.md", "home source")
        self.put(satellite / "sessions/same/transcript.md", "satellite source")
        self.put(satellite / "sessions/same/ontology.json", '{"source":"satellite source"}')
        reg = self.registry([home, satellite], home)
        self.cli("sync", "--registry", reg, "--apply")
        self.assertFalse((home / "sessions/same/ontology.json").exists())
        transcripts = list((home / "conflicts").rglob("transcript.md"))
        self.assertEqual(len(transcripts), 1)
        self.assertEqual(transcripts[0].read_text(), "satellite source")
        self.assertEqual(json.loads(transcripts[0].with_name("ontology.json").read_text()),
                         {"source": "satellite source"})

    def test_conflict_source_name_collision_and_prior_versions_preserved(self):
        home = self.root("home")
        suffix = "x" * 64
        first, second = self.root("first/" + suffix), self.root("second/" + suffix)
        self.put(home / "sessions/same/transcript.md", "home")
        self.put(first / "sessions/same/transcript.md", "first")
        self.put(second / "sessions/same/transcript.md", "second")
        reg = self.registry([home, first, second], home)
        self.cli("sync", "--registry", reg, "--apply")
        self.assertCountEqual(self.contents(home / "conflicts", "transcript.md"), ["first", "second"])
        self.put(first / "sessions/same/transcript.md", "first updated")
        self.cli("sync", "--registry", reg, "--apply")
        self.assertCountEqual(self.contents(home / "conflicts", "transcript.md"),
                              ["first", "second", "first updated"])

    def test_missing_root_rejected_by_sync_status_and_query(self):
        home = self.root("home")
        reg = self.registry([home, self.base / "missing/memory/xbskill"], home)
        request = self.request()
        for args in (("sync",), ("status",), ("query", "--request", request)):
            with self.subTest(command=args[0]):
                result = self.cli(*args, "--registry", reg, ok=False)
                self.assertIn("E_ROOT_MISSING", result.stderr)

    def test_updated_conflict_version_keeps_unchanged_session_files(self):
        home, satellite = self.root("home"), self.root("satellite")
        self.put(home / "sessions/same/transcript.md", "home")
        self.put(satellite / "sessions/same/transcript.md", "first version")
        self.put(satellite / "sessions/same/ontology.json", '{"provenance":"stable"}')
        reg = self.registry([home, satellite], home)
        self.cli("sync", "--registry", reg, "--apply")
        self.put(satellite / "sessions/same/transcript.md", "second version")
        self.cli("sync", "--registry", reg, "--apply")
        snapshots = list((home / "conflicts").rglob("transcript.md"))
        self.assertEqual(len(snapshots), 2)
        self.assertCountEqual([path.read_text() for path in snapshots], ["first version", "second version"])
        for transcript in snapshots:
            self.assertTrue(transcript.with_name("ontology.json").is_file())
            self.assertEqual(json.loads(transcript.with_name("ontology.json").read_text()),
                             {"provenance": "stable"})

    def test_query_rejects_incomplete_packet_shape(self):
        home = self.root("home")
        (home / "ontology").mkdir()
        reg = self.registry([home])
        stub = self.base / "malformed_query.py"
        self.put(stub, 'print(\'{"status":"matched"}\')\n')
        result = self.cli("query", "--registry", reg, "--request", self.request(),
                          "--memory-script", stub, ok=False)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["status"], "partial_failure")
        self.assertEqual(packet["results"], [])
        self.assertEqual(packet["errors"][0]["code"], "E_QUERY")

    def test_private_tool_paths_rejected(self):
        satellite = self.root("satellite")
        self.put(satellite / "sessions/one/transcript.md", "synthetic")
        for name in (".codex", ".claude", ".kimi", ".zcode", ".kimi_openclaw", "Doubao"):
            with self.subTest(name=name):
                home = self.root(name + "/project")
                reg = self.registry([home, satellite], home)
                result = self.cli("sync", "--registry", reg, "--apply", ok=False)
                self.assertIn("E_PRIVATE_PATH", result.stderr)
                self.assertEqual(self.snapshot(home), {})

    def test_source_file_symlink_rejected(self):
        home, satellite = self.root("home"), self.root("satellite")
        external = self.base / "external.txt"
        self.put(external, "synthetic external source")
        try:
            os.symlink(external, satellite / "linked.txt")
        except OSError as exc:
            self.skipTest("OS denied file symlink creation: " + str(exc))
        reg = self.registry([home, satellite], home)
        result = self.cli("sync", "--registry", reg, "--apply", ok=False)
        self.assertIn("E_LINK", result.stderr)
        self.assertEqual(self.snapshot(home), {})

    def test_destination_directory_link_rejected(self):
        home, satellite = self.root("home"), self.root("satellite")
        external = self.base / "external"
        external.mkdir()
        link = home / "sessions"
        if os.name == "nt":
            # PowerShell is used only to construct a Windows junction fixture.
            def quote(path):
                return "'" + str(path).replace("'", "''") + "'"
            result = subprocess.run(["powershell", "-NoProfile", "-Command",
                                     "New-Item -ItemType Junction -Path " + quote(link) +
                                     " -Target " + quote(external) + " | Out-Null"], capture_output=True)
            if result.returncode:
                self.skipTest("OS denied junction creation")
        else:
            try:
                os.symlink(external, link, target_is_directory=True)
            except OSError as exc:
                self.skipTest("OS denied directory symlink creation: " + str(exc))
        self.put(satellite / "sessions/one/transcript.md", "synthetic")
        reg = self.registry([home, satellite], home)
        result = self.cli("sync", "--registry", reg, "--apply", ok=False)
        self.assertIn("E_LINK", result.stderr)
        self.assertEqual(self.snapshot(external), {})

    def request(self):
        path = self.base / "request.json"
        self.put(path, json.dumps({"schema_version": 1, "request_id": "query-test-001", "task": "sample",
                                  "entity_ids": [], "entity_types": [], "predicates": [], "as_of": None,
                                  "max_assertions": 5, "include_candidates": True, "include_disputed": False,
                                  "include_restricted": False, "authorized_sensitive_read": False}))
        return path

    def ontology_store(self, root, source):
        self.assertTrue(MEMORY.is_file(), "E_DEPENDENCY: install the complete xbskill suite")
        spec = importlib.util.spec_from_file_location("xb_sync_test_ontology", MEMORY)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        predicate, rule = next((k, v) for k, v in module.load_registry().items() if v.get("object") == "literal")
        session = "2026-01-01-0900-test"
        ref = {"session_id": session, "turn": 1, "role": "user", "excerpt": source}
        kind = rule["subjects"][0]
        entity = {"entity_id": kind + ":sample", "entity_type": kind, "canonical_name": "sample",
                  "aliases": [], "scope": "project:sample", "sensitivity": "normal", "status": "active", "source_refs": [ref]}
        assertion = {"assertion_id": "a:test:001", "subject_id": entity["entity_id"], "predicate": predicate,
                     "object": {"kind": "literal", "value": source, "value_type": "string"},
                     "epistemic_status": "user_statement", "confidence": "high", "lifecycle": "candidate",
                     "retention": "long_term", "sensitivity": "normal", "scope": "project:sample",
                     "observed_at": "2026-01-01T00:00:00Z", "valid_from": None, "valid_until": None,
                     "source_refs": [ref], "reversal": "User changes fact", "supersedes": [], "qualifiers": {}}
        delta = {"schema_version": 1, "session_id": session, "generated_at": "2026-01-01T00:00:00Z",
                 "authorized_current_session": True, "authorized_sensitive_long_term": False,
                 "entities": [entity], "assertions": [assertion]}
        writes, _ = module.plan_ontology_writes(root, delta)
        module.atomic_write_set(root, writes)

    def test_real_query_matches_and_failure_is_nonzero(self):
        first, second = self.root("first"), self.root("second")
        self.ontology_store(first, "sample first source")
        self.ontology_store(second, "sample second source")
        reg = self.registry([first, second])
        request = self.request()
        result = self.cli("query", "--registry", reg, "--request", request)
        packet = json.loads(result.stdout)
        self.assertEqual(len(packet["results"]), 2)
        self.assertEqual(packet["errors"], [])
        values = []
        for item in packet["results"]:
            self.assertIn(item["root"], [str(first), str(second)])
            self.assertEqual(item["packet"]["status"], "matched")
            assertion = item["packet"]["assertions"][0]
            self.assertEqual(assertion["assertion_id"], "a:test:001")
            self.assertEqual(assertion["source_refs"][0]["excerpt"], assertion["object"]["value"])
            values.append(assertion["object"]["value"])
        self.assertCountEqual(values, ["sample first source", "sample second source"])
        for root in (first, second):
            self.put(root / "ontology/index.json", "{}")
        result = self.cli("query", "--registry", reg, "--request", request, ok=False)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["status"], "partial_failure")
        self.assertEqual(len(packet["errors"]), 2)
        self.assertTrue(all("E_INDEX_DRIFT" in item["detail"] for item in packet["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
