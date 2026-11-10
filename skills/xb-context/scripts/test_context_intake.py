"""Reject missing dependencies or an inconsistent background form."""

import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('suite', ROOT / 'xbskill/scripts/suite_manager.py')
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.references = self.root / 'xb-context/references'
        shutil.copytree(ROOT / 'xb-context/references', self.references)
        self.form = self.references / 'environment-dialogue.md'

    def errors(self):
        errors = []
        suite.validate_context_intake(self.root, errors)
        return errors

    def change_form(self, original, replacement):
        self.form.write_text(self.form.read_text('utf-8').replace(original, replacement), encoding='utf-8')

    def test_shipped_form(self):
        self.assertEqual([], self.errors())

    def test_missing_dependencies(self):
        for name in ('document-intake.md', 'company-research.md', 'continuation.md'):
            with self.subTest(name=name):
                (self.references / name).unlink()
                self.assertIn(f'context intake dependency missing: {name}', self.errors())

    def test_extra_row(self):
        end = '<!-- context-group-end -->'
        self.change_form(end, '| 额外信息 | 例子 | 用处 |\n' + end)
        self.assertIn('context intake group size invalid: context', self.errors())

    def test_missing_examples(self):
        self.change_form('回答例子', '必填项')
        self.assertIn('context intake group loses examples or use: context', self.errors())

    def test_oversized_group(self):
        self.change_form('<!-- context-group-start -->', '<!-- context-group-start -->\n' + '额外说明' * 200)
        self.assertIn('context intake group size invalid: context', self.errors())

    def test_missing_field(self):
        self.change_form('| 称呼 |', '| 姓名 |')
        self.assertIn('context intake fields invalid: context', self.errors())

    def test_missing_document_group(self):
        self.change_form('documents-group-start', 'missing-group-start')
        self.assertIn('context intake group markers invalid: documents', self.errors())


if __name__ == '__main__':
    unittest.main()
