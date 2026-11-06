"""Optional desktop entry and on-demand user service for the LoRa controller."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

UNIT = 'robot-recorder-lora-remote.service'
MARKER = '# Managed by Robot Recorder LoRa launcher'


def fingerprint(key):
    return hashlib.sha256(key).hexdigest()


@contextmanager
def controller_lock(key, directory=None):
    directory = Path(directory or os.environ.get('XDG_RUNTIME_DIR', f'/tmp/robot-recorder-lora-{os.getuid()}'))
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o022:
        raise ValueError('Controller lock directory is not private to this user')
    path = directory/('robot-recorder-lora-'+fingerprint(key)[:24]+'.lock')
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        try: fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('This recorder already has a LoRa controller running. Use its existing page; do not start another controller.') from error
        try: yield
        finally: fcntl.flock(stream,fcntl.LOCK_UN)


def unit_quote(value):
    value=str(value)
    if any(character in value for character in '\r\n\x00'):
        raise ValueError('Invalid service argument')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


def service_text(root,config,web_port=8081,port=None,poll_seconds=1):
    argv=[sys.executable,'-B',str(root/'tools/lora_recorder.py'),'remote',
          '--config',str(config),'--web-port',str(web_port),'--poll-seconds',str(poll_seconds)]
    if port: argv+=['--port',port]
    return (MARKER+'\n[Unit]\nDescription=Robot Recorder LoRa remote\nStartLimitIntervalSec=0\n'
            '\n[Service]\nType=exec\nExecStart=:'+' '.join(map(unit_quote,argv))+
            '\nRestart=on-failure\nRestartSec=5\nTimeoutStopSec=10\nKillMode=control-group\n'
            'Environment=PYTHONUNBUFFERED=1\n\n[Install]\nWantedBy=default.target\n')


def shortcut(root,config,data_home=None,desktop=None):
    from tools.desktop_shortcuts import install
    return install('robot-recorder-lora.desktop','Robot Recorder LoRa',
        [sys.executable,'-B',str(root/'tools/lora_recorder.py'),'open','--config',str(config)],
        'Start or reuse the local LoRa controller and open its page',data_home,desktop)


def info(web_port):
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{web_port}/api/launcher-info',timeout=.5) as response:
            value=json.load(response)
            if not isinstance(value,dict) or value.get('application') != 'robot-recorder-lora':
                raise ValueError('This local port is used by another application')
            return value
    except HTTPError as error:
        raise ValueError('An older controller or another application uses this port; close it before using the new launcher.') from error
    except URLError:
        return None


def unit_path():
    return Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'systemd/user'/UNIT


def open_remote(root,config,key,web_port=8081,port=None,poll_seconds=1,browser=True):
    root,config=Path(root).resolve(),Path(config).resolve()
    existing=info(web_port)
    if existing is not None and existing.get('pairing') != fingerprint(key):
        raise ValueError('The running controller belongs to a different recorder')
    if existing is None:
        # A controller on another web port must also prevent a second instance.
        with controller_lock(key): pass
        unit=unit_path()
        if unit.exists() and MARKER not in unit.read_text():
            raise ValueError('An unmanaged LoRa service already exists; preserve it before setup')
        unit.parent.mkdir(parents=True,exist_ok=True)
        text=service_text(root,config,web_port,port,poll_seconds)
        active=subprocess.run(['systemctl','--user','is-active','--quiet',UNIT],capture_output=True).returncode == 0
        if active and (not unit.exists() or unit.read_text() != text):
            raise ValueError('The background controller uses different settings. Stop it before changing settings.')
        unit.write_text(text)
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','start',UNIT],check=True)
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            existing=info(web_port)
            if existing is not None: break
            time.sleep(.2)
        if existing is None:
            raise ValueError('Controller did not open. Connect the radio and check: journalctl --user -u '+UNIT+' -n 20 --no-pager')
        if existing.get('pairing') != fingerprint(key):
            raise ValueError('A different controller opened this port')
    url=f'http://127.0.0.1:{web_port}'
    if browser and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        webbrowser.open(url,new=2)
    print('LoRa controller: '+url+' (running in the background; closing this terminal does not stop it).',flush=True)
    print('Stop it with: systemctl --user stop '+UNIT,flush=True)
    return existing


def stop_remote():
    unit=unit_path()
    if not unit.is_file() or MARKER not in unit.read_text():
        raise ValueError('No managed controller is installed. Close the original foreground controller with Ctrl+C.')
    subprocess.run(['systemctl','--user','stop',UNIT],check=True)
    print('Background LoRa controller stopped.')
