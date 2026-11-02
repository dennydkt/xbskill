"""Isolated context checkpoint save, resume, supersession and consent regression."""
import os
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]

def invoke(script, *args):
    return subprocess.run([sys.executable, '-B', str(ROOT / script), *map(str,args)], capture_output=True, text=True, encoding='utf-8', timeout=30, env={**os.environ, 'PYTHONIOENCODING':'utf-8'})

def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')

def bundle(sid, state, previous=None):
    now='2026-11-02T12:00:00+08:00'
    text=f'职场环境同步：{state}；地点已覆盖，人物拒答；下一问：当前工作由谁验收？'
    ref={'session_id':sid,'turn':2,'role':'assistant','excerpt':text}
    assertion={'assertion_id':f'a:{sid}:checkpoint','subject_id':'work_item:context-org-a','predicate':'has_status',
       'object':{'kind':'literal','value':state,'value_type':'status'},'epistemic_status':'artifact_evidence',
       'confidence':'high','lifecycle':'active','retention':'long_term','sensitivity':'normal',
       'scope':'project:fixture','observed_at':now,'valid_from':None,'valid_until':None,'source_refs':[ref],
       'reversal':'用户更正进度或组织改变','supersedes':[previous] if previous else [],
       'qualifiers':{'tracker':'workplace_context','sync_id':'context:org-a','organization_scope':'org-a',
        'current_domain':'role','next_question':'当前工作由谁验收？','domain_location':'covered',
        'domain_role':'pending','domain_people':'declined','domain_company':'unknown','domain_changes':'unknown'}}
    return {'schema_version':2,'session_id':sid,'authorized_current_session':True,'network_writes':False,
      'completeness':'complete','completeness_gaps':[],
      'transcript':[{'turn':1,'role':'user','content':'远程，人物关系不聊。保存对话。'}, {'turn':2,'role':'assistant','content':text}],
      'session_markdown':'# 环境同步\n\n'+text,'progress_markdown':'# 当前进度\n\n'+text,
      'ontology_delta':{'schema_version':1,'session_id':sid,'generated_at':now,'authorized_current_session':True,
       'authorized_sensitive_long_term':False,'entities':[{'entity_id':'work_item:context-org-a','entity_type':'work_item',
       'canonical_name':'职场环境同步','aliases':['环境同步进度'],'scope':'project:fixture','sensitivity':'normal','status':'active','source_refs':[ref]}],
       'assertions':[assertion]}}

def main():
 with tempfile.TemporaryDirectory(prefix='xb-context-receiver-') as tmp:
    root=Path(tmp); project=root/'project'; project.mkdir(); file=root/'bundle.json'
    first=bundle('2026-11-02-1200-context-first','in_progress')
    denied=copy.deepcopy(first);denied['authorized_current_session']=False;dump(file,denied)
    result=invoke('xb-save/scripts/session_store.py','--project-root',project,'--bundle',file)
    assert result.returncode != 0 and not (project/'memory').exists(), result.stdout+result.stderr
    dump(file,first);result=invoke('xb-save/scripts/session_store.py','--project-root',project,'--bundle',file)
    assert result.returncode == 0, result.stdout+result.stderr
    second=bundle('2026-11-02-1210-context-second','paused',first['ontology_delta']['assertions'][0]['assertion_id'])
    dump(file,second);result=invoke('xb-save/scripts/session_store.py','--project-root',project,'--bundle',file)
    assert result.returncode == 0, result.stdout+result.stderr
    request={'schema_version':1,'request_id':'context-resume','task':'职场环境同步','entity_ids':['work_item:context-org-a'],
      'entity_types':['work_item'],'predicates':['has_status'],'as_of':None,'max_assertions':10,'include_candidates':False,
      'include_disputed':True,'include_restricted':False,'authorized_sensitive_read':False}
    req=root/'query.json';dump(req,request)
    result=invoke('xb-memory/scripts/memory_ontology.py','query','--project-root',project,'--request',req)
    assert result.returncode == 0, result.stdout+result.stderr
    packet=json.loads(result.stdout)
    assertions=packet['assertions'];assert len(assertions)==1,packet
    current=assertions[0];assert current['object']['value']=='paused',current
    assert current['qualifiers']['domain_people']=='declined' and current['qualifiers']['next_question']=='当前工作由谁验收？',current
    stored=json.loads((project/'memory/xbskill/ontology/assertions.json').read_text(encoding='utf-8'))
    assert len(stored['assertions'])==2,stored
    for sid in (first['session_id'],second['session_id']):
      assert (project/'memory/xbskill/sessions'/sid/'session.md').is_file()
    bad=bundle('2026-11-02-1220-context-bad','paused');bad['ontology_delta']['assertions'][0]['source_refs'][0]['excerpt']='不存在的进度'
    dump(file,bad);before=(project/'memory/xbskill/ontology/assertions.json').read_bytes()
    result=invoke('xb-save/scripts/session_store.py','--project-root',project,'--bundle',file)
    assert result.returncode!=0 and before==(project/'memory/xbskill/ontology/assertions.json').read_bytes()
    print('PASS context: no-consent zero-write; schema2 transaction; separate-process resume; declined preserved; supersedes latest-only; original sessions retained; fabricated source rejected')
if __name__=='__main__':main()
