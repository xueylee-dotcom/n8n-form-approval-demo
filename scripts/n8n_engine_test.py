"""Real n8n Form/Wait/HTTP execution against the local synthetic CRM.
No browser login, API key, external address, or persistent n8n data.
"""
import json
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
from mock_crm import Store, server
from n8n_probe import ROOT, BIN, isolated_env, run

E = ROOT / 'evidence/n8n'
BASE_URL = 'http://127.0.0.1:18765'
HTTP = build_opener(ProxyHandler({}))

class TracedStore(Store):
    def __init__(self,path):
        super().__init__(path)
        self.calls=[]
    def commit(self,data):
        event={'request_id':data.get('request_id'),'fault':self.fault}
        try:
            result=super().commit(data)
            event['result']=result
            return result
        except Exception as exc:
            event['exception']=type(exc).__name__+': '+str(exc)
            raise
        finally:
            self.calls.append(event)

def request(path, data=None, content_type='application/json'):
    if isinstance(data,dict): data=json.dumps(data).encode()
    with HTTP.open(Request(BASE_URL+path,data,{'Content-Type':content_type}),timeout=10) as r:
        return r.status,r.read().decode()

def wait_for(fn, description, seconds=30):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=fn()
        if value: return value
        time.sleep(.25)
    raise TimeoutError(description)

def decode_flatted(raw):
    values=json.loads(raw)
    if not isinstance(values,list): return values
    cache={}
    def resolve(index):
        if index in cache: return cache[index]
        value=values[index]
        if isinstance(value,dict):
            result={}; cache[index]=result
            result.update({k:resolve(int(v)) if isinstance(v,str) else v for k,v in value.items()})
        elif isinstance(value,list):
            result=[]; cache[index]=result
            result.extend(resolve(int(v)) if isinstance(v,str) else v for v in value)
        else:
            result=value; cache[index]=result
        return result
    return resolve(0)

def row(db,eid):
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row
        r=c.execute('SELECT id,status,finished FROM execution_entity WHERE id=?',(eid,)).fetchone()
        return dict(r) if r else None

def execution_data(db,eid):
    with sqlite3.connect(db) as c:
        raw=c.execute('SELECT data FROM execution_data WHERE executionId=?',(eid,)).fetchone()[0]
    return decode_flatted(raw)

def submit(rid,email,name):
    boundary='n8n-local-test-boundary'
    fields={'field-0':rid,'field-1':email,'field-2':name}
    body=''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                 for key,value in fields.items())+f'--{boundary}--\r\n'
    return request('/form/'+WEBHOOK,body.encode(),'multipart/form-data; boundary='+boundary)

WORKFLOW=json.loads((ROOT/'workflow/form-to-crm.json').read_text())
WEBHOOK=next(n['webhookId'] for n in WORKFLOW['nodes'] if n['type'].endswith('formTrigger'))

if __name__=='__main__':
    receipt={'started_at':datetime.now(timezone.utc).isoformat(),'engine':'n8n 2.35.7',
             'reviewer':'automated synthetic POST; no human identity verification','scenarios':[]}
    engine=None; httpd=None; thread=None
    with tempfile.TemporaryDirectory(prefix='n8n-real-engine-') as folder:
        folder=Path(folder); env=isolated_env(folder)
        try:
            # Fail if our n8n port is occupied. Never stop any existing process.
            with socket.socket() as check: check.bind(('127.0.0.1',18765))
            run(['import:workflow','--input='+str(ROOT/'workflow/form-to-crm.json')],env,'engine-import.txt')
            db=folder/'.n8n/database.sqlite'
            with sqlite3.connect(db) as c:
                wid=c.execute('SELECT id FROM workflow_entity').fetchone()[0]
            run(['publish:workflow','--id='+wid],env,'engine-local-activation.txt')
            store=TracedStore(folder/'mock.sqlite')
            httpd=server(store,8765)
            thread=threading.Thread(target=httpd.serve_forever,daemon=True); thread.start()
            with (E/'engine-server.txt').open('w') as log:
                engine=subprocess.Popen(['node',str(BIN),'start'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                def ready():
                    if engine.poll() is not None: raise RuntimeError('n8n exited; inspect engine-server.txt')
                    try: return request('/healthz/readiness')[0]==200
                    except (HTTPError,URLError): return False
                wait_for(ready,'n8n readiness',90)
                def form_ready():
                    try: return request('/form/'+WEBHOOK)
                    except HTTPError as exc:
                        if exc.code==404: return False
                        raise
                status,html=wait_for(form_ready,'form registration',30)
                (E/'served-form.html').write_text(html)
                assert status==200
                cases=[('normal','none','approve',1,1),('before_timeout','before-once','approve',1,2),
                       ('after_lost_response','after-once','approve',1,2),
                       ('retry_exhausted','always','approve',0,3),('rejected','none','reject',0,0)]
                for i,(case,fault,decision,writes,tries) in enumerate(cases,1):
                    rid=f'engine-{i:03d}'; email=f'person{i}@example.test'; store.fault=fault
                    status,_=submit(rid,email,'Synthetic Person '+str(i))
                    def pending():
                        return next((r for r in store.snapshot()['requests'] if r['request_id']==rid),None)
                    reservation=wait_for(pending,'reservation '+case)
                    eid=reservation['owner']
                    wait_for(lambda: row(db,eid)['status']=='waiting','waiting '+case)
                    before=store.snapshot()
                    assert not any(c['email']==email for c in before['contacts'])
                    data=execution_data(db,eid)
                    url=data['resultData']['runData']['Review context'][0]['data']['main'][0][0]['json']['resume_url']
                    assert url.startswith(BASE_URL+'/')
                    request(url[len(BASE_URL):],{'decision':decision,'reviewer':'synthetic-engine-test'})
                    final=wait_for(lambda: (r if (r:=row(db,eid))['status'] in ('success','error') else None),'completion '+case)
                    expected_status='error' if case=='retry_exhausted' else 'success'
                    assert final['status']==expected_status,final
                    snapshot=store.snapshot()
                    actual=sum(c['writes'] for c in snapshot['contacts'] if c['email']==email)
                    calls=[r for r in store.calls if r['request_id']==rid]
                    assert actual==writes,(case,actual,writes)
                    assert len(calls)==tries,(case,calls)
                    data=execution_data(db,eid)
                    (E/(case+'-execution.json')).write_text(json.dumps(data,indent=2)+'\n')
                    receipt['scenarios'].append({'case':case,'execution_id':eid,'status':final['status'],
                        'before_approval':before,'final':snapshot,'commit_calls':calls,'assertions':'PASS'})
                    print(case,'PASS',flush=True)
                    if case=='normal':
                        with sqlite3.connect(db) as c: prior=c.execute('SELECT max(id) FROM execution_entity').fetchone()[0]
                        submit(rid,email,'Synthetic Person '+str(i))
                        def duplicate_done():
                            with sqlite3.connect(db) as c:
                                q=c.execute('SELECT id,status FROM execution_entity WHERE id>? ORDER BY id DESC LIMIT 1',(prior,)).fetchone()
                            return q if q and q[1] in ('success','error') else None
                        did,state=wait_for(duplicate_done,'duplicate finish')
                        d=execution_data(db,did)
                        assert state=='success'
                        assert 'Duplicate stopped' in d['resultData']['runData']
                        assert 'Human approval' not in d['resultData']['runData']
                        assert len([r for r in store.calls if r['request_id']==rid])==1
                        (E/'duplicate-execution.json').write_text(json.dumps(d,indent=2)+'\n')
                        receipt['scenarios'].append({'case':'duplicate','execution_id':str(did),'status':state,
                            'assertions':'PASS: duplicate stop, no second approval or CRM call'})
                        print('duplicate PASS',flush=True)
                with sqlite3.connect(db) as c:
                    receipt['credential_count']=c.execute('SELECT count(*) FROM credentials_entity').fetchone()[0]
                    receipt['users_with_password']=c.execute('SELECT count(*) FROM user WHERE password IS NOT NULL').fetchone()[0]
                receipt['result']='PASS'
        except Exception as exc:
            receipt['result']='BLOCKED_OR_FAILED'
            receipt['error']=type(exc).__name__+': '+str(exc)
            raise
        finally:
            if engine and engine.poll() is None:
                engine.terminate()
                try: engine.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    engine.kill(); engine.wait()
                    receipt['forced_stop_required']=True
            if httpd:
                httpd.shutdown(); httpd.server_close()
            if thread: thread.join(timeout=5)
            receipt['engine_exit_code']=engine.returncode if engine else None
            receipt['completed_at']=datetime.now(timezone.utc).isoformat()
            (E/'engine-results.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('Temporary runtime data removed; both task services stopped.',flush=True)
