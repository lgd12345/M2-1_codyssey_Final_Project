"""Opt-in local browser integration, always backed by a disposable database."""
import os
from pathlib import Path
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


def unused_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def wait_for(url, process):
    for _ in range(100):
        if process.poll() is not None:
            pytest.fail('Test server exited before becoming ready')
        try:
            if httpx.get(url, timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    pytest.fail('Test server did not become ready')


def test_browser_intake_through_real_auth_api_and_database(setup, tmp_path):
    clients, _equipment = setup
    node = os.getenv('NODE_BINARY') or shutil.which('node')
    assert node, 'Node.js is required for browser E2E'
    backend_port, frontend_port = unused_port(), unused_port()
    environment = {**os.environ,
        'RAG_DATABASE_URL': os.environ['TEST_DATABASE_URL'],
        'DATABASE_URL': os.environ['TEST_DATABASE_URL'],
        'APP_COOKIE_SECURE': '0', 'STATIC_DIR': str(tmp_path / 'no-static'),
        'VITE_API_PROXY_TARGET': f'http://127.0.0.1:{backend_port}',
        'E2E_BASE_URL': f'http://127.0.0.1:{frontend_port}',
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
            wait_for(f'http://127.0.0.1:{backend_port}/api/health', backend)
            frontend = subprocess.Popen([node, 'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
                                         '--port', str(frontend_port), '--strictPort'], cwd=ROOT / 'frontend',
                                        env=environment, stdout=log, stderr=subprocess.STDOUT)
            processes.append(frontend)
            wait_for(environment['E2E_BASE_URL'], frontend)
            result = subprocess.run([node, 'node_modules/@playwright/test/cli.js', 'test'], cwd=ROOT / 'frontend',
                                    env=environment, capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=600)
            assert result.returncode == 0, result.stdout + result.stderr
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
