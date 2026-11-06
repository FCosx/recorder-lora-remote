"""Source bridge manager's authenticated outbound HTTP channel to the Pi."""
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time
from urllib.request import ProxyHandler, Request, build_opener
from urllib.error import HTTPError


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with open(temporary, 'w', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def post(url, body, key=None, timeout=3):
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    request = Request(url, data=json.dumps(body).encode(), headers=headers)
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.load(response)


def register(root, pi_url, domain):
    path = root / 'zenoh/robot-control.json'
    if path.exists():
        credentials = json.loads(path.read_text())
    else:
        credentials = {'id': secrets.token_hex(16), 'key': secrets.token_hex(32)}
        atomic_json(path, credentials)
    post(pi_url.rstrip('/') + '/api/robot-control/register',
         dict(credentials, domain=domain, label=socket.gethostname()))
    return path


def stop_child(child):
    if child is None:
        return
    # The launcher has its own session, so only this managed bridge/helper group
    # is terminated. No robot publishers or unrelated ROS processes are touched.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)


def set_domain(settings_path, settings, domain, result=None):
    if type(domain) is not int or not 0 <= domain <= 232:
        raise ValueError('Invalid Robot ROS domain')
    # This one atomic file is canonical. On reboot the bridge config is always
    # regenerated from it, including after a crash between the two file writes.
    updated = dict(settings, version=2, domain=domain)
    if result is not None:
        updated['control_result'] = result
    atomic_json(settings_path, updated)
    config = Path(updated['config'])
    value = json.loads(config.read_text())
    value['plugins']['ros2dds']['domain'] = domain
    atomic_json(config, value)
    return updated


def run_manager(settings_path, launch, wired_route):
    settings = json.loads(settings_path.read_text())
    credentials = json.loads((Path(settings['root']) / 'zenoh/robot-control.json').read_text())
    child = None
    stopping = False
    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, stop)
    settings = set_domain(settings_path, settings, settings['domain'])
    next_start = 0
    authorized = True
    last_error = 0
    try:
        while not stopping:
            from urllib.parse import urlsplit
            if child is None or child.poll() is not None:
                if child is not None:
                    stop_child(child)
                    child = None
                if authorized and time.monotonic() >= next_start and wired_route(urlsplit(settings['pi_url']).hostname):
                    child = launch(settings)
                    next_start = time.monotonic() + 3
            body = {'id': credentials['id'], 'domain': settings['domain'],
                    'running': child is not None and child.poll() is None,
                    'result': settings.get('control_result')}
            try:
                response = post(settings['pi_url'] + '/api/robot-control/exchange', body, credentials['key'], timeout=1.5)
                authorized = True
                command = response.get('command')
                if command and command['id'] != (settings.get('control_result') or {}).get('id'):
                    claim = post(settings['pi_url'] + '/api/robot-control/exchange',
                                 dict(body, claim=command['id']), credentials['key'])
                    if (claim.get('command') or {}).get('phase') == 'applying':
                        previous = command['previous']
                        stop_child(child)
                        child = None
                        try:
                            settings = set_domain(settings_path, settings, command['domain'])
                            child = launch(settings)
                            deadline = time.monotonic() + 2
                            while not stopping and time.monotonic() < deadline and child.poll() is None:
                                time.sleep(.1)
                            if stopping:
                                break  # Saved target + pending Pi transaction resume on restart.
                            if child.poll() is not None:
                                raise OSError('Bridge could not start in the selected domain')
                            settings['control_result'] = {'id': command['id'], 'ok': True}
                            atomic_json(settings_path, settings)
                            print(f"Robot ROS domain {settings['domain']} applied and saved.", flush=True)
                        except (OSError, ValueError, subprocess.SubprocessError) as error:
                            stop_child(child)
                            child = None
                            settings = set_domain(settings_path, settings, previous,
                                                  {'id': command['id'], 'ok': False})
                            child = launch(settings)
                            print(f'Domain change rolled back: {error}', flush=True)
            except HTTPError as error:
                if error.code == 403:
                    # A replaced robot must not continue feeding the recorder.
                    stop_child(child)
                    child = None
                    authorized = False
                if time.monotonic() - last_error > 30:
                    print(f'Recorder management HTTP {error.code}; retrying.', flush=True)
                    last_error = time.monotonic()
            except (OSError, ValueError) as error:
                if time.monotonic() - last_error > 30:
                    print(f'Recorder management unavailable: {type(error).__name__}; retrying.', flush=True)
                    last_error = time.monotonic()
            for _ in range(10):
                if stopping:
                    break
                time.sleep(.1)
    finally:
        stop_child(child)
