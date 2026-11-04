"""Reject missing intake dependencies, overloaded opening groups and missing value examples."""
from pathlib import Path
import importlib.util,tempfile,shutil,unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('suite',ROOT/'xbskill/scripts/suite_manager.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class IntakeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  target=self.root/'xb-context/references';target.mkdir(parents=True)
  for name in ('environment-dialogue.md','document-intake.md','continuation.md','company-research.md','recruiter-interview-method.md'):shutil.copy2(ROOT/'xb-context/references'/name,target/name)
  self.path=target/'environment-dialogue.md'
 def errors(self):
  errors=[];m.validate_context_intake(self.root,errors);return errors
 def test_shipped_group_fits_reading_budget(self):self.assertEqual([],self.errors())
 def test_missing_reading_contract_fails_loudly(self):
  (self.root/'xb-context/references/document-intake.md').unlink();self.assertTrue(any('dependency missing' in x for x in self.errors()))
 def test_seventh_row_rejected(self):
  self.path.write_text(self.path.read_text('utf-8').replace('<!-- context-group-end -->','| 额外信息 | 例子 | 用处 |\n<!-- context-group-end -->'),encoding='utf-8')
  self.assertIn('context intake group overload',self.errors())
 def test_missing_examples_rejected(self):
  self.path.write_text(self.path.read_text('utf-8').replace('回答例子','必填项'),encoding='utf-8');self.assertIn('context intake group loses examples or use',self.errors())
 def test_oversized_preamble_rejected(self):
  self.path.write_text(self.path.read_text('utf-8').replace('<!-- context-group-start -->','<!-- context-group-start -->'+'额外说明'*200),encoding='utf-8');self.assertIn('context intake group overload',self.errors())
 def test_missing_company_research_fails_loudly(self):
  (self.root/'xb-context/references/company-research.md').unlink();self.assertTrue(any('dependency missing' in x for x in self.errors()))
 def test_missing_basic_field_rejected(self):
  self.path.write_text(self.path.read_text('utf-8').replace('上下级关系','关系'),encoding='utf-8');self.assertIn('context intake basic fields missing',self.errors())
if __name__=='__main__':unittest.main()
