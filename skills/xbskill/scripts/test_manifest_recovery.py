"""Exercise missing-manifest recovery in isolated installations."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import suite_manager as sm


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.target = self.root / 'reference', self.root / 'installed'
        (self.source / 'xbskill').mkdir(parents=True)
        (self.source / 'xbskill/VERSION').write_text('1.0.0\n', encoding='utf-8')
        (self.source / 'xbskill/SKILL.md').write_text('original\n', encoding='utf-8')
        sm.write_manifest(self.source)
        shutil.copytree(self.source, self.target)
        (self.target / sm.MANIFEST).unlink()
        self.backup = self.root / 'backup'

    def snapshot(self):
        return {p.relative_to(self.target).as_posix(): p.read_bytes()
                for p in self.target.rglob('*') if p.is_file()}

    def reject(self):
        before = self.snapshot()
        with self.assertRaises(SystemExit):
            sm.recover_manifest(self.source, self.target, self.backup)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.backup.exists())

    def test_compare_is_readonly_and_reports_unknown_history(self):
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            changes = sm.print_diff(self.source, self.target)
        self.assertTrue(changes['baseline_missing'])
        self.assertIn('LOCAL_DRIFT UNKNOWN', stream.getvalue())
        self.assertEqual(before, self.snapshot())
        (self.target / 'xbskill/SKILL.md').write_text('local edit', encoding='utf-8')
        self.assertIn('xbskill/SKILL.md', sm.diff(self.source, self.target)['modified'])

    def test_exact_recovery_preserves_local_and_restores_original_absence(self):
        (self.target / 'xbskill/LOCAL-NOTES.md').write_text('my patch', encoding='utf-8')
        before = self.snapshot()
        sm.recover_manifest(self.source, self.target, self.backup)
        self.assertEqual(sm.load_manifest(self.target), sm.load_manifest(self.source))
        self.assertEqual('my patch', (self.target / 'xbskill/LOCAL-NOTES.md').read_text(encoding='utf-8'))
        self.assertFalse((self.backup / sm.MANIFEST).exists())
        sm.restore_suite(self.backup, self.target)
        self.assertEqual(before, self.snapshot())

    def test_modified_missing_extra_and_version_mismatch_rejected(self):
        for rel, content in [('xbskill/SKILL.md', 'modified'), ('xbskill/SKILL.md', None),
                             ('xbskill/notes.txt', 'user file'), ('xbskill/VERSION', '2.0.0')]:
            with self.subTest(rel=rel, content=content):
                path = self.target / rel
                original = path.read_bytes() if path.exists() else None
                if content is None:
                    path.unlink()
                else:
                    path.write_text(content, encoding='utf-8')
                self.reject()
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    def test_bad_reference_and_existing_manifest_rejected(self):
        path = self.source / 'xbskill/SKILL.md'
        original = path.read_bytes()
        path.write_text('tampered reference', encoding='utf-8')
        self.reject()
        path.write_bytes(original)
        (self.target / sm.MANIFEST).write_text('{broken', encoding='utf-8')
        self.reject()

    def test_cli_requires_confirmation_and_apply_still_blocks(self):
        before = self.snapshot()
        result = subprocess.run([sys.executable, '-B', sm.__file__, 'recover-manifest',
            '--source', str(self.source), '--target', str(self.target), '--backup', str(self.backup)],
            capture_output=True, timeout=10)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.snapshot())
        with self.assertRaises(SystemExit):
            sm.copy_suite(self.source, self.target, self.backup)
        self.assertFalse(self.backup.exists())

    def test_links_and_backup_change_rejected(self):
        real = sm.is_link_or_reparse
        with patch.object(sm, 'is_link_or_reparse', side_effect=lambda p: p == self.target / 'xbskill' or real(p)):
            self.reject()
        copy = shutil.copytree
        def changing_copy(src, dst, **kwargs):
            result = copy(src, dst, **kwargs)
            (self.target / 'xbskill/SKILL.md').write_text('concurrent edit', encoding='utf-8')
            return result
        with patch.object(sm.shutil, 'copytree', side_effect=changing_copy):
            with self.assertRaises(SystemExit):
                sm.recover_manifest(self.source, self.target, self.backup)
        self.assertFalse((self.target / sm.MANIFEST).exists())


if __name__ == '__main__':
    unittest.main()
