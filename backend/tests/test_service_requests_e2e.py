"""Opt-in local browser integration, always backed by a disposable database."""
import os
import json
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time

import httpx
import pytest

from test_service_requests_api import setup, PASSWORD

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_E2E') != '1', reason='RUN_BROWSER_E2E=1 is opt-in')
ROOT = Path(__file__).resolve().parents[2]
# Split by individual Playwright tests, not files: the large screens spec must not serialize most of the suite.
# Every shard still has a separate disposable DB, server and browser.
SHARDS = int(os.getenv('TEST_WORKERS', '4'))


def unused_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def wait_for(url, process):
    with httpx.Client(timeout=0.5, trust_env=False) as client:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail('Test server exited before becoming ready')
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    pytest.fail('Test server did not become ready')


@pytest.mark.parametrize('shard', range(1, SHARDS + 1))
def test_browser_flows_through_real_auth_api_and_database(setup, tmp_path, shard):
    clients, _equipment = setup
    node = os.getenv('NODE_BINARY') or shutil.which('node')
    assert node, 'Node.js is required for browser E2E'
    backend_port = unused_port()
    dist = ROOT / 'frontend' / 'dist'
    assert (dist / 'index.html').is_file(), 'Build frontend before browser E2E'
    environment = {**os.environ,
        'DATABASE_URL': os.environ['TEST_DATABASE_URL'],
        'APP_COOKIE_SECURE': '0', 'STATIC_DIR': str(dist),
        'E2E_BASE_URL': f'http://127.0.0.1:{backend_port}',
        'E2E_PASSWORD': PASSWORD,
    }
    for key, who in [('E2E_CUSTOMER', 'alice'), ('E2E_COLLEAGUE', 'colleague'),
                     ('E2E_OTHER_CUSTOMER', 'bob'), ('E2E_STAFF', 'staff'), ('E2E_UNASSIGNED', 'unassigned')]:
        environment[key] = clients[who].get('/api/v1/auth/me').json()['user']['login_id']
    processes = []
    with (tmp_path / 'servers.log').open('w', encoding='utf-8') as log:
        try:
            backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', '--app-dir', 'tests', 'e2e_app:app', '--host', '127.0.0.1',
                                        '--port', str(backend_port)], cwd=ROOT / 'backend', env=environment,
                                       stdout=log, stderr=subprocess.STDOUT)
            processes.append(backend)
            # Exercise the deployment path: FastAPI serves dist and API from the same origin.
            # No second Vite process or proxy hop for each browser shard.
            wait_for(f'http://127.0.0.1:{backend_port}/api/health', backend)
            # E2E_PLAYWRIGHT_ARGS narrows development runs, e.g. "-g intake".
            extra = shlex.split(os.getenv('E2E_PLAYWRIGHT_ARGS', ''))
            result = subprocess.run([node, 'node_modules/@playwright/test/cli.js', 'test', f'--shard={shard}/{SHARDS}',
                                     '--reporter=json', '--output', str(tmp_path / 'browser-results'), *extra], cwd=ROOT / 'frontend',
                                    env=environment, capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=600)
            assert result.returncode == 0, result.stdout + result.stderr
            report = json.loads(result.stdout)

            def timings(suites):
                for suite in suites:
                    for spec in suite.get('specs', []):
                        seconds = sum(result['duration'] for test in spec['tests'] for result in test.get('results', [])) / 1000
                        print(f"browser shard {shard}: {seconds:.2f}s {spec['title']}")
                    timings(suite.get('suites', []))

            timings(report['suites'])
        finally:
            for process in reversed(processes):
                if os.name == 'nt':
                    # Windows venv launchers may have a child interpreter. Stop
                    # only the process tree this test started, not other servers.
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
