"""Temporary, credential-free CLI probe of the unchanged n8n candidate."""
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence/n8n'
BIN = ROOT / 'n8n-local/node_modules/n8n/bin/n8n'

def isolated_env(folder):
    # Do not inherit cloud credentials, proxy settings or any existing n8n profile.
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TMPDIR') if k in os.environ}
    env.update({
        'N8N_USER_FOLDER': str(folder),
        'N8N_DIAGNOSTICS_ENABLED': 'false',
        'N8N_VERSION_NOTIFICATIONS_ENABLED': 'false',
        'N8N_TEMPLATES_ENABLED': 'false',
        'N8N_PERSONALIZATION_ENABLED': 'false',
        'N8N_LICENSE_AUTO_RENEW_ENABLED': 'false',
        'N8N_COMMUNITY_PACKAGES_ENABLED': 'false',
        'N8N_LISTEN_ADDRESS': '127.0.0.1',
        'N8N_HOST': '127.0.0.1',
        'N8N_PORT': '18765',
        'N8N_RUNNERS_BROKER_LISTEN_ADDRESS': '127.0.0.1',
        'N8N_RUNNERS_BROKER_PORT': '18766',
        'N8N_EDITOR_BASE_URL': 'http://127.0.0.1:18765',
        'WEBHOOK_URL': 'http://127.0.0.1:18765/',
        'NODE_OPTIONS': '--max-old-space-size=768',
        'UV_THREADPOOL_SIZE': '2',
        'OMP_NUM_THREADS': '1',
        'N8N_LOG_LEVEL': 'info',
        'N8N_BLOCK_ENV_ACCESS_IN_NODE': 'true',
        'ENABLE_OBSERVABILITY': 'false',
        'ENABLE_A365_OBSERVABILITY_EXPORTER': 'false',
    })
    return env

def run(args, env, name, timeout=90):
    with (EVIDENCE/name).open('w') as out:
        result = subprocess.run(['node',str(BIN),*args],cwd=ROOT,env=env,
                                stdout=out,stderr=subprocess.STDOUT,timeout=timeout)
    print(name, 'exit',result.returncode, flush=True)
    return result.returncode

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='n8n-cli-probe-') as folder:
        env = isolated_env(folder)
        run(['--version'],env,'version.txt')
        run(['import:workflow','--input='+str(ROOT/'workflow/form-to-crm.json')], env,'cli-import.txt')
        db = Path(folder)/'.n8n/database.sqlite'
        if not db.exists():
            raise SystemExit('No database created; inspect cli-import.txt')
        with sqlite3.connect(db) as c:
            workflows = c.execute('SELECT id,name FROM workflow_entity').fetchall()
            if not workflows:
                raise SystemExit('No workflow imported; inspect cli-import.txt')
            wid = workflows[0][0]
            # Store only aggregate checks, never database credentials/configuration.
            proof = {'workflow_count':len(workflows), 'workflow_id':wid,
                     'credential_count':c.execute('SELECT count(*) FROM credentials_entity').fetchone()[0],
                     'users_with_password':c.execute('SELECT count(*) FROM user WHERE password IS NOT NULL').fetchone()[0]}
        (EVIDENCE/'cli-import-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
        run(['export:workflow','--id='+wid,'--output='+str(EVIDENCE/'cli-roundtrip.json')],env,'cli-export.txt')
        run(['execute','--id='+wid],env,'cli-execute-original.txt')
    print('Temporary n8n data/config removed; no lasting login credentials created.',flush=True)
