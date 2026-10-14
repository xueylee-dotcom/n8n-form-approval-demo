"""Synthetic, local-only fixture. No real authentication or production use."""
import argparse
import json
import re
import sqlite3
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

class Conflict(ValueError):
    pass

class Store:
    def __init__(self, path, fault='none'):
        self.path, self.fault, self.attempts = str(path), fault, {}
        with self.db() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY, email TEXT, name TEXT, owner TEXT,
                state TEXT, decision TEXT, reviewer TEXT);
              CREATE TABLE IF NOT EXISTS contacts (
                email TEXT PRIMARY KEY, name TEXT, writes INTEGER);
            ''')

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def text(data, key):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(f'invalid {key}')
        return value.strip()

    def reserve(self, data):
        rid, owner = self.text(data, 'request_id'), self.text(data, 'owner')
        email, name = self.text(data, 'email').lower(), self.text(data, 'name')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', rid):
            raise ValueError('invalid request_id')
        if not re.fullmatch(r'[^\s@]+@example\.test', email):
            raise ValueError('only synthetic example.test email allowed')
        with self.db() as c:
            row = c.execute('SELECT * FROM requests WHERE request_id=?', (rid,)).fetchone()
            if row:
                if (row['email'], row['name']) != (email, name):
                    raise Conflict('submission_id reused with changed payload; manual review required')
                review = row['owner'] == owner and row['state'] == 'pending'
                return {'request_id': rid, 'owner': owner, 'state': row['state'],
                        'should_review': review, 'duplicate': True}
            c.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?)',
                      (rid, email, name, owner, 'pending', None, None))
            return {'request_id': rid, 'owner': owner, 'state': 'pending',
                    'should_review': True, 'duplicate': False}

    def owned(self, c, data):
        rid, owner = self.text(data, 'request_id'), self.text(data, 'owner')
        row = c.execute('SELECT * FROM requests WHERE request_id=?', (rid,)).fetchone()
        if not row or row['owner'] != owner:
            raise Conflict('unknown request or wrong execution owner')
        return row

    def decide(self, data):
        decision, reviewer = self.text(data, 'decision'), self.text(data, 'reviewer')
        if decision not in ('approve', 'reject'):
            raise ValueError('decision must be approve or reject')
        with self.db() as c:
            row = self.owned(c, data)
            if row['decision'] and (row['decision'] != decision or row['reviewer'] != reviewer):
                raise Conflict('decision is immutable')
            state = row['state']
            if state == 'pending':
                state = 'approved' if decision == 'approve' else 'rejected'
                c.execute('UPDATE requests SET state=?, decision=?, reviewer=? WHERE request_id=?',
                          (state, decision, reviewer, row['request_id']))
            return {'request_id': row['request_id'], 'owner': row['owner'], 'state': state,
                    'approved': state in ('approved', 'committed')}

    def commit(self, data):
        with self.db() as c:
            row = self.owned(c, data)
            rid = row['request_id']
            if row['state'] == 'committed':
                return {'request_id': rid, 'state': 'committed', 'replayed': True}
            if row['state'] != 'approved':
                raise Conflict('explicit approval required')
            self.attempts[rid] = self.attempts.get(rid, 0) + 1
            first = self.attempts[rid] == 1
            if self.fault == 'always' or (first and self.fault == 'before-once'):
                raise TimeoutError('injected timeout before CRM write')
            c.execute('''INSERT INTO contacts VALUES (?,?,1) ON CONFLICT(email)
                         DO UPDATE SET name=excluded.name, writes=contacts.writes+1''',
                      (row['email'], row['name']))
            c.execute("UPDATE requests SET state='committed' WHERE request_id=?", (rid,))
        if first and self.fault == 'after-once':
            raise TimeoutError('injected lost response AFTER committed CRM write')
        return {'request_id': rid, 'state': 'committed', 'replayed': False}

    def snapshot(self):
        with self.db() as c:
            return {table: [dict(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY 1')]
                    for table in ('requests', 'contacts')}


def server(store, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send(self, code, result):
            raw = json.dumps(result).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            if self.path == '/snapshot':
                self.send(200, store.snapshot())
            else:
                self.send(404, {'error': 'unknown endpoint'})
        def do_POST(self):
            routes = {'/reserve': store.reserve, '/decide': store.decide, '/commit': store.commit}
            if self.path not in routes:
                return self.send(404, {'error': 'unknown endpoint'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('invalid body size')
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('JSON content type required')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('JSON object required')
                self.send(200, routes[self.path](data))
            except TimeoutError as e:
                self.send(504, {'error': str(e), 'synthetic_fault': True})
            except Conflict as e:
                self.send(409, {'error': str(e)})
            except ValueError as e:
                self.send(400, {'error': str(e)})
    return HTTPServer(('127.0.0.1', port), Handler)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', default='evidence/manual.sqlite')
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--fault', choices=['none', 'before-once', 'after-once', 'always'], default='none')
    a = p.parse_args()
    httpd = server(Store(a.db, a.fault), a.port)
    print(f'SYNTHETIC ONLY — http://127.0.0.1:{httpd.server_port}; Ctrl-C to stop', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
