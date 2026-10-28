#!/usr/bin/env python3
"""Isolated startup recall regressions with synthetic, source-bound archives."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from startup_recall import recall_memory, check_memory
from memory_ontology import OntologyError

STORE = Path(__file__).resolve().parents[2] / 'xb-save/scripts/session_store.py'
spec = importlib.util.spec_from_file_location('session_store', STORE)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='recall-clean-')
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / '中文 项目'
        self.project.mkdir()
        self.sid = '2026-10-23-1428-tag-review'
        self.text = '标签系统专题又叫患者标签体系；待核实周三会议结论。'
        self.ref = {'session_id': self.sid, 'turn': 1, 'role': 'user', 'excerpt': self.text}

    def save(self, restricted=False, closed=False):
        entity = {'entity_id': 'work_item:tag-review', 'entity_type': 'work_item',
                  'canonical_name': '核实患者标签体系周三会议结论', 'aliases': ['标签系统专题'],
                  'scope': 'project:fixture', 'sensitivity': 'normal', 'status': 'active',
                  'source_refs': [self.ref]}
        assertion = {'assertion_id': 'a:tag-review', 'subject_id': entity['entity_id'],
                     'predicate': 'has_status', 'object': {'kind': 'literal', 'value': 'pending', 'value_type': 'status'},
                     'epistemic_status': 'user_statement', 'confidence': 'high', 'lifecycle': 'active',
                     'retention': 'session_only' if restricted else 'long_term',
                     'sensitivity': 'restricted' if restricted else 'normal', 'scope': 'project:fixture',
                     'observed_at': '2026-10-23T14:28:00+08:00', 'valid_from': None, 'valid_until': None,
                     'source_refs': [self.ref], 'reversal': '会议结论回流或用户取消核实', 'supersedes': [],
                     'qualifiers': {'memory_kind': 'open_item', 'material_path': str(self.project / '外部 材料')}}
        assertions = [assertion]
        if closed:
            new = copy.deepcopy(assertion)
            new.update(assertion_id='a:tag-closed', supersedes=['a:tag-review'])
            new['object']['value'] = 'closed'
            assertions.append(new)
        delta = {'schema_version': 1, 'session_id': self.sid, 'generated_at': '2026-10-23T14:28:00+08:00',
                 'authorized_current_session': True, 'authorized_sensitive_long_term': False,
                 'entities': [entity], 'assertions': assertions}
        bundle = {'schema_version': 2, 'session_id': self.sid, 'authorized_current_session': True,
                  'network_writes': False, 'completeness': 'complete', 'completeness_gaps': [],
                  'transcript': [{'turn': 1, 'role': 'user', 'content': self.text}], 'ontology_delta': delta,
                  'session_markdown': '# 患者标签体系\n待验证：周三会议结论。',
                  'progress_markdown': '# 近况\n其他五项近况，标签已滚出。'}
        store.validate_bundle(bundle)
        store.atomic_store(self.project, bundle)

    def test_saved_chinese_alias_open_item_path_and_date(self):
        self.save()
        before = {str(p): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        result = recall_memory(self.project, '标签系统专题，新增录音纪要请读取')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['source_sessions'][0]['date'], '2026-10-23')
        self.assertEqual(len(result['open_items']), 1)
        self.assertFalse(result['material_paths'][0]['exists'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.project.rglob('*') if p.is_file()})
        cli = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('startup_recall.py')),
                              '--project-root', str(self.project), '--task', '标签系统专题'],
                             capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertTrue(json.loads(cli.stdout)['query_executed'])

    def test_irrelevant_is_not_latest(self):
        self.save()
        result = recall_memory(self.project, '量子花园观星')
        self.assertEqual(result['status'], 'no_match')
        self.assertEqual(result['source_sessions'], [])

    def test_restricted_cannot_fall_back_to_summary(self):
        self.save(restricted=True)
        result = recall_memory(self.project, '标签系统专题')
        self.assertEqual(result['status'], 'no_match')
        self.assertEqual(result['open_items'], [])
        self.assertNotIn('legacy_candidates', result)

    def test_closed_item_not_returned_as_open(self):
        self.save(closed=True)
        result = recall_memory(self.project, '标签系统专题')
        self.assertEqual(result['open_items'], [])
        self.assertEqual(result['assertions'][0]['assertion_id'], 'a:tag-closed')

    def test_no_archive_does_not_create_one(self):
        self.assertEqual(recall_memory(self.project, '标签系统')['status'], 'no_archive')
        self.assertFalse((self.project / 'memory').exists())

    def test_legacy_is_review_not_no_match(self):
        path = self.project / 'memory/xbskill/sessions' / self.sid / 'session.md'
        path.parent.mkdir(parents=True)
        path.write_text('会话级敏感正文不得自动注入', encoding='utf-8')
        result = recall_memory(self.project, '标签系统')
        self.assertEqual(result['status'], 'legacy_review_required')
        self.assertEqual(result['assertions'], [])
        self.assertNotIn('敏感正文', json.dumps(result, ensure_ascii=False))

    def test_broken_store_is_error(self):
        (self.project / 'memory/xbskill/ontology').mkdir(parents=True)
        with self.assertRaises(OntologyError):
            recall_memory(self.project, '标签系统')

    def test_missing_source_is_error(self):
        self.save()
        (self.project / 'memory/xbskill/sessions' / self.sid / 'session.md').unlink()
        with self.assertRaisesRegex(OntologyError, 'E_MEMORY_HEALTH'):
            recall_memory(self.project, '标签系统专题')

    def test_first_use_health_is_read_only_and_detects_invalid_fields(self):
        self.save()
        self.assertEqual(check_memory(self.project)['status'], 'healthy')
        path = self.project / 'memory/xbskill/ontology/entities.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['entities'][0]['entity_type'] = 'unregistered_type'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        before = path.read_bytes()
        result = check_memory(self.project)
        self.assertEqual(result['status'], 'repair_required')
        self.assertTrue(any('entities.json:' in x['location'] for x in result['issues']))
        self.assertEqual(before, path.read_bytes())
        cli = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('startup_recall.py')),
                              '--project-root', str(self.project), '--check'],
                             capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(cli.returncode, 2)
        self.assertEqual(json.loads(cli.stdout)['status'], 'repair_required')

    def test_health_keeps_mixed_role_sources(self):
        self.save()
        root = self.project / 'memory/xbskill/ontology'
        path = root / 'assertions.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        item = data['assertions'][0]
        item['source_refs'].insert(0, dict(self.ref, role='assistant', turn=2))
        # Rebuild the derived index/meta so this tests role semantics, not index drift.
        from memory_ontology import build_index, pretty_json
        import hashlib
        entities = json.loads((root / 'entities.json').read_text(encoding='utf-8'))['entities']
        index = build_index(entities, data['assertions'])
        path.write_text(pretty_json(data), encoding='utf-8')
        (root / 'index.json').write_text(pretty_json(index), encoding='utf-8')
        meta = json.loads((root / 'meta.json').read_text(encoding='utf-8'))
        meta['index_sha256'] = hashlib.sha256(pretty_json(index).encode('utf-8')).hexdigest()
        (root / 'meta.json').write_text(pretty_json(meta), encoding='utf-8')
        self.assertEqual(check_memory(self.project)['status'], 'healthy')


if __name__ == '__main__':
    unittest.main()
