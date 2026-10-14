"""Bounded sequential contract check: five real n8n executions, six checks."""
import hashlib
import json
import socket
import sqlite3
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
import n8n_probe as probe
from mock_crm import Conflict, server
from n8n_engine_test import (ROOT, BIN, BASE_URL, WEBHOOK, TracedStore, request,
                             wait_for, row, execution_data, submit)

E=ROOT/'evidence/contracts-v3'
probe.EVIDENCE=E

class ContractStore(TracedStore):
    def __init__(self,path):
        super().__init__(path)
        self.reserve_errors=[]
    def reserve(self,data):
        try:
            return super().reserve(data)
        except ValueError as exc:
            self.reserve_errors.append({'request_id':data.get('request_id'),
                'http_status':409 if isinstance(exc,Conflict) else 400,'message':str(exc)})
            raise

def version():
    return json.loads((ROOT/'n8n-local/node_modules/n8n/package.json').read_text())['version']

if __name__=='__main__':
    E.mkdir(parents=True, exist_ok=True)
    receipt={'started_at':datetime.now(timezone.utc).isoformat(),'n8n_version':version(),
             'scope':'sequential local synthetic example.test; scripted decisions',
             'workflow_sha256':hashlib.sha256((ROOT/'workflow/form-to-crm.json').read_bytes()).hexdigest(),
             'checks':[]}
    engine=httpd=thread=None
    try:
        with tempfile.TemporaryDirectory(prefix='n8n-contract-v3-') as folder:
            folder=Path(folder);env=probe.isolated_env(folder)
            try:
                for port in (8765,18765,18766):
                    with socket.socket() as check: check.bind(('127.0.0.1',port))
                assert probe.run(['import:workflow','--input='+str(ROOT/'workflow/form-to-crm.json')],env,'import.txt')==0
                db=folder/'.n8n/database.sqlite'
                with sqlite3.connect(db) as c:
                    wid=c.execute('SELECT id FROM workflow_entity').fetchone()[0]
                assert probe.run(['export:workflow','--id='+wid,'--output='+str(E/'roundtrip.json')],env,'export.txt')==0
                source=json.loads((ROOT/'workflow/form-to-crm.json').read_text())
                exported=json.loads((E/'roundtrip.json').read_text())[0]
                assert all(source[k]==exported[k] for k in ('nodes','connections','settings','id','active'))
                assert probe.run(['publish:workflow','--id='+wid],env,'local-activation.txt')==0
                store=ContractStore(folder/'mock.sqlite')
                httpd=server(store,8765)
                thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
                with (E/'server.txt').open('w') as log:
                    engine=subprocess.Popen(['node',str(BIN),'start'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                    def ready():
                        if engine.poll() is not None: raise RuntimeError('n8n exited')
                        try: return request('/healthz/readiness')[0]==200
                        except (HTTPError,URLError): return False
                    wait_for(ready,'readiness',90)
                    def form_ready():
                        try: return request('/form/'+WEBHOOK)[0]==200
                        except HTTPError as exc:
                            if exc.code==404:return False
                            raise
                    wait_for(form_ready,'form registration')

                    def latest_after(prior):
                        with sqlite3.connect(db) as c:
                            r=c.execute('SELECT id,status FROM execution_entity WHERE id>? ORDER BY id DESC LIMIT 1',(prior,)).fetchone()
                        return r if r and r[1] in ('success','error','waiting') else None
                    def send(rid,email,name):
                        with sqlite3.connect(db) as c: prior=c.execute('SELECT coalesce(max(id),0) FROM execution_entity').fetchone()[0]
                        submit(rid,email,name)
                        return wait_for(lambda:latest_after(prior),'execution result')
                    def save(label,eid):
                        d=execution_data(db,eid)
                        (E/(label+'-execution.json')).write_text(json.dumps(d,indent=2)+'\n')
                        return d
                    def add(label,eid,state,expected,**extra):
                        receipt['checks'].append({'contract':label,'execution_id':str(eid),'n8n_status':state,
                            'expected':expected,'result':'PASS',**extra})
                        print(label,'PASS',flush=True)
                    def decide(eid,decision):
                        d=execution_data(db,eid)
                        url=d['resultData']['runData']['Review context'][0]['data']['main'][0][0]['json']['resume_url']
                        assert url.startswith(BASE_URL+'/')
                        request(url[len(BASE_URL):],{'decision':decision,'reviewer':'synthetic-contract-test'})
                        return wait_for(lambda:(r if (r:=row(db,eid))['status'] in ('success','error') else None),'decision result')

                    rid='submission-001';email='person1@example.test';name='Synthetic Person 1'
                    eid,state=send(rid,email,name)
                    assert state=='waiting' and store.snapshot()['contacts']==[] and store.calls==[]
                    pending=store.snapshot();assert pending['requests'][0]['state']=='pending'
                    save('pending',eid)
                    add('pending_no_write',eid,state,'0 contacts; 0 commit calls',snapshot=pending)
                    final=decide(eid,'approve');assert final['status']=='success'
                    snapshot=store.snapshot();assert len(snapshot['contacts'])==1 and snapshot['contacts'][0]['writes']==1 and len(store.calls)==1
                    save('approved',eid)
                    add('new_submission_approved',eid,final['status'],'1 contact; 1 write',snapshot=snapshot)

                    did,state=send(rid,email,name);d=save('replay',did)
                    assert state=='success' and 'Duplicate stopped' in d['resultData']['runData']
                    assert 'Human approval' not in d['resultData']['runData']
                    assert store.snapshot()==snapshot and len(store.calls)==1
                    add('identical_replay',did,state,'no additional record/write/approval',snapshot=store.snapshot())

                    rejected,state=send('submission-002','person2@example.test','Synthetic Person 2')
                    assert state=='waiting'
                    final=decide(rejected,'reject');assert final['status']=='success'
                    d=save('rejected',rejected);assert 'Rejected stopped' in d['resultData']['runData']
                    after=store.snapshot();assert after['contacts']==snapshot['contacts'] and len(store.calls)==1
                    assert next(r for r in after['requests'] if r['request_id']=='submission-002')['state']=='rejected'
                    add('rejected_no_write',rejected,final['status'],'0 additional CRM writes',snapshot=after)

                    before=store.snapshot()
                    invalid,state=send('invalid id','invalid-case@example.test','Synthetic Invalid ID')
                    d=save('invalid',invalid)
                    assert state=='error' and 'Commit CRM' not in d['resultData']['runData']
                    errors=[r for r in store.reserve_errors if r['request_id']=='invalid id']
                    assert errors and all(r['http_status']==400 for r in errors)
                    assert store.snapshot()==before and len(store.calls)==1
                    add('invalid_field_rejected',invalid,state,'400 at Reserve; no reservation or CRM write',adapter_errors=errors,snapshot=store.snapshot())

                    conflict,state=send(rid,email,'Changed Synthetic Name')
                    d=save('conflict',conflict)
                    assert state=='error' and 'Commit CRM' not in d['resultData']['runData']
                    errors=[r for r in store.reserve_errors if r['request_id']==rid]
                    assert errors and all(r['http_status']==409 and 'manual review required' in r['message'] for r in errors)
                    assert store.snapshot()==before and len(store.calls)==1
                    add('same_id_changed_content',conflict,state,'409; manual review required; existing data unchanged',adapter_errors=errors,snapshot=store.snapshot())
                    receipt['final_snapshot']=store.snapshot()
                    with sqlite3.connect(db) as c:
                        receipt['execution_count']=c.execute('SELECT count(*) FROM execution_entity').fetchone()[0]
                        receipt['credential_count']=c.execute('SELECT count(*) FROM credentials_entity').fetchone()[0]
                        receipt['users_with_password']=c.execute('SELECT count(*) FROM user WHERE password IS NOT NULL').fetchone()[0]
                    assert receipt['execution_count']==5
                    assert receipt['credential_count']==receipt['users_with_password']==0
                    receipt['result']='PASS'
            finally:
                if engine and engine.poll() is None:
                    engine.terminate()
                    try:engine.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        engine.kill();engine.wait();receipt['forced_stop_required']=True
                if httpd:httpd.shutdown();httpd.server_close()
                if thread:thread.join(timeout=5)
                receipt['engine_exit_code']=engine.returncode if engine else None
        receipt['temporary_data_removed']=True
    except Exception as exc:
        receipt['result']='BLOCKED_OR_FAILED';receipt['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        receipt['completed_at']=datetime.now(timezone.utc).isoformat()
        (E/'results.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('Task services stopped; temporary data removed.',flush=True)
