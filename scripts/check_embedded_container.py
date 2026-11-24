"""Exercise an already built image with disposable data and no external network."""

import argparse
import json
import subprocess
import time
import uuid


HTTP_PROBE = r'''
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

base = f'http://127.0.0.1:{os.environ["PORT"]}'
origin = 'https://pdf-agent.example.test'

def call(path, *, body=None, headers=None, expected=200):
    request = urllib.request.Request(base + path, data=body, headers=headers or {})
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (path.split('/')[1], response.status, expected)
        return response.read(), response.headers

def source(session, *, stream=False, question='Show the sources.'):
    path = '/sessions/' + session['session_id']
    headers = {'Authorization': 'Bearer ' + session['session_token']}
    suffix = '/ask/stream' if stream else '/ask'
    data, response_headers = call(path + suffix, body=json.dumps({'question': question}).encode(),
                                  headers=headers | {'Content-Type': 'application/json'})
    if stream:
        assert response_headers['Content-Type'].startswith('text/event-stream')
        event = next(part for part in data.decode().split('\n\n') if part.startswith('event: result\n'))
        data = event.split('data: ', 1)[1]
    result = json.loads(data)
    assert result['steps'] == ['source'] and result['sources'] and result['usage']['llm_calls'] == 0

def synthetic_pdf():
    line = (b'Synthetic release fixture for source retrieval and vector persistence. ' * 13).strip()
    stream = b'BT /F1 11 Tf 48 740 Td (' + line + b') Tj ET'
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream',
    ]
    content = bytearray(b'%PDF-1.4\n')
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content += f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(content)
    content += b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets:
        content += f'{offset:010} 00000 n \n'.encode()
    return content + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()

def create_and_upload():
    assert b'<html' in call('/')[0].lower()
    browser = {'X-PDF-Agent-Client': 'browser', 'Origin': origin}
    call('/sessions', body=b'', headers=browser | {'Origin': 'https://wrong.example.test'}, expected=403)
    data, headers = call('/sessions', body=b'', headers=browser)
    cookie = headers['Set-Cookie']
    for expected in ('Secure', 'HttpOnly', 'SameSite=strict'):
        assert expected in cookie
    call('/sessions/' + json.loads(data)['session_id'], headers=browser | {'Cookie': cookie.split(';', 1)[0]})
    session = json.loads(call('/sessions', body=b'', headers={'X-Session-Mode': 'bearer'})[0])
    path = '/sessions/' + session['session_id']
    call(path, expected=404)
    headers = {'Authorization': 'Bearer ' + session['session_token'],
               'Content-Type': 'multipart/form-data; boundary=check'}
    body = (b'--check\r\nContent-Disposition: form-data; name="files"; filename="synthetic.pdf"\r\n'
            b'Content-Type: application/pdf\r\n\r\n' + synthetic_pdf() + b'\r\n--check--\r\n')
    assert json.loads(call(path + '/pdfs', body=body, headers=headers)[0])['total_documents'] == 1
    source(session)
    source(session, stream=True)
    long_question = ('\u5217\u51fa\u8d44\u6599\u6765\u6e90\u3002' + '\u5408\u6210\u6587\u6863\u7532\u4e59\u4e19\u4e01\u620a\u5df1' * 240)[:2000]
    source(session, question=long_question)
    return session

def verify_persisted(session):
    path = '/sessions/' + session['session_id']
    body, _ = call(path, headers={'Authorization': 'Bearer ' + session['session_token']})
    assert json.loads(body)['message_count'] == 6
    source(session, stream=True)

def memory_peak():
    cgroup = Path('/sys/fs/cgroup')
    events = dict(line.split() for line in (cgroup / 'memory.events').read_text().splitlines())
    assert events['oom'] == '0' and events['oom_kill'] == '0', events
    return int((cgroup / 'memory.peak').read_text())
'''


def docker(*args: str, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(['docker', *args], input=input_text, text=True, encoding='utf-8',
                            capture_output=True, check=False, timeout=180)
    if check and result.returncode:
        raise RuntimeError(f'docker {args[0]} failed ({result.returncode}): {result.stderr.strip()}')
    return result


def wait_ready(container: str) -> None:
    start = time.monotonic()
    for _ in range(90):
        probe = docker('exec', container, 'python', '-c',
                       'import os, urllib.request; urllib.request.urlopen('
                       '"http://127.0.0.1:" + os.environ["PORT"] + "/health", timeout=2)', check=False)
        if probe.returncode == 0:
            print(f'HTTP ready in {time.monotonic() - start:.2f}s', flush=True)
            return
        if docker('inspect', '-f', '{{.State.Running}}', container).stdout.strip() != 'true':
            raise RuntimeError('container exited during startup')
        time.sleep(1)
    raise RuntimeError('container did not become ready')


def sql(container: str, database: str, statement: str) -> str:
    return docker('exec', '-u', 'postgres', container, '/usr/lib/postgresql/17/bin/psql',
                  '-X', '-At', '-v', 'ON_ERROR_STOP=1', '-h', '/run/pdf-agent-postgres',
                  '-d', database, '-c', statement).stdout.strip()


def verify_backup(container: str) -> None:
    pg = '/usr/lib/postgresql/17/bin/'
    operator = ('exec', '-u', 'postgres', container)
    socket = ('-h', '/run/pdf-agent-postgres')
    archive = '/tmp/embedded-restore-check.dump'
    docker(*operator, pg + 'pg_dump', *socket, '-Fc', '-f', archive, 'pdf_agent')
    docker(*operator, pg + 'createdb', *socket, 'restore_check')
    docker(*operator, pg + 'pg_restore', *socket, '--exit-on-error', '--single-transaction',
           '-d', 'restore_check', archive)
    tables = ('alembic_version', 'sessions', 'session_messages', 'session_documents',
              'document_chunks', 'session_owner_credentials', 'session_request_leases')
    for table in tables:
        query = ("SELECT count(*) || ':' || COALESCE(md5(string_agg(to_jsonb(t)::text, chr(10) "
                 f"ORDER BY to_jsonb(t)::text)), '') FROM {table} t")
        assert sql(container, 'pdf_agent', query) == sql(container, 'restore_check', query), table
    release = sql(container, 'restore_check', 'SELECT version_num FROM alembic_version')
    extension = sql(container, 'restore_check', "SELECT extversion FROM pg_extension WHERE extname='vector'")
    assert release == '0004_session_credentials' and extension
    print(f'Native backup restored and seven tables matched ({release}, pgvector {extension})', flush=True)


def verify(image: str) -> None:
    prefix = 'pdf-agent-embed-check-' + uuid.uuid4().hex[:10]
    volume = prefix + '-volume'
    container = prefix + '-app'
    mount = f'{volume}:/data'
    marker = ("from pathlib import Path; Path('/data/sessions.db').write_bytes(b'untouched synthetic legacy data'); "
              "Path('/data/vectorstores').mkdir(); Path('/data/vectorstores/index.faiss').write_bytes(b'fixture')")
    docker('volume', 'create', volume)
    try:
        missing = docker('run', '--rm', '--pull', 'never', '--network', 'none', '-e', 'RENDER=true',
                         image, check=False)
        assert missing.returncode != 0 and 'requires a persistent mount' in missing.stdout
        low_disk = docker('run', '--rm', '--pull', 'never', '--network', 'none', '-e', 'RENDER=true',
                          '--mount', 'type=tmpfs,destination=/data,tmpfs-size=67108864', image, check=False)
        assert low_disk.returncode != 0 and 'less than 192 MiB free' in low_disk.stdout
        docker('run', '--rm', '--pull', 'never', '--network', 'none', '-v', mount, '--entrypoint',
               'python', image, '-c', marker)
        options = ('run', '-d', '--pull', 'never', '--name', container, '--network', 'none',
                   '--cpus', '1', '--memory', '2g', '--memory-swap', '2g', '-v', mount,
                   '-e', 'PDF_AGENT_DISABLE_LLM_API=1', '-e', 'RENDER=true', '-e', 'PORT=10000',
                   '-e', 'RENDER_EXTERNAL_URL=https://pdf-agent.example.test')
        docker(*options, image)
        wait_ready(container)
        result = docker('exec', '-i', container, 'python', '-', input_text=HTTP_PROBE + '''
session = create_and_upload()
print(json.dumps({'session': session, 'peak': memory_peak()}))
''')
        first = json.loads(result.stdout)
        connection = sql(container, 'pdf_agent', "SELECT current_setting('listen_addresses'), "
                         "has_schema_privilege('pdf_agent_runtime', 'public', 'CREATE'), "
                         "has_table_privilege('pdf_agent_runtime', 'alembic_version', 'UPDATE'), "
                         "rolcanlogin FROM pg_roles WHERE rolname='pdf_agent_migrate'")
        assert connection == '127.0.0.1|f|f|f', connection
        print(f'Cookie, Bearer, PDF upload, BGE-M3, JSON/SSE passed; peak {first["peak"]} bytes', flush=True)
        disk_mib = docker('exec', container, 'du', '-sm', '/data/pdf-agent-postgres').stdout.split()[0]
        print(f'Embedded cluster disk usage after synthetic workflow: {disk_mib} MiB', flush=True)
        verify_backup(container)
        docker('stop', '--time', '30', container)
        assert docker('inspect', '-f', '{{.State.ExitCode}}', container).stdout.strip() == '0'
        docker('rm', container)
        docker(*options, image)
        wait_ready(container)
        result = docker('exec', '-i', container, 'python', '-', input_text=HTTP_PROBE + f'''
verify_persisted({first['session']!r})
assert Path('/data/sessions.db').read_bytes() == b'untouched synthetic legacy data'
assert Path('/data/vectorstores/index.faiss').read_bytes() == b'fixture'
print(memory_peak())
''')
        print(f'Recreated container retained session, vector, and legacy marker; peak {result.stdout.strip()} bytes',
              flush=True)
        log = docker('logs', container)
        assert first['session']['session_token'] not in log.stdout + log.stderr
        docker('exec', '--user', 'postgres', container, '/usr/lib/postgresql/17/bin/pg_ctl',
               '-D', '/data/pdf-agent-postgres/pg17', '-m', 'fast', 'stop')
        assert docker('wait', container).stdout.strip() == '1'
        print('Unexpected PostgreSQL exit stopped the service with a nonzero status', flush=True)
    except Exception:
        result = docker('logs', '--tail', '20', container, check=False)
        print(result.stdout + result.stderr, flush=True)
        raise
    finally:
        docker('rm', '-f', container, check=False)
        docker('volume', 'rm', volume)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    verify(parser.parse_args().image)
