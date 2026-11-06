#!/usr/bin/env python3
"""On-demand setup checks. No sensor readers, rate sampling or recorder changes."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

if __package__:
    from . import robot_bridge_service
else:
    import robot_bridge_service


def processes(proc=Path('/proc')):
    bridges, helpers = [], []
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        try:
            if item.stat().st_uid != os.getuid():
                continue
            executable = (item/'exe').resolve()
            argv = [os.fsdecode(arg) for arg in (item/'cmdline').read_bytes().split(b'\0') if arg]
            if executable.name in ('zenoh-bridge-ros2dds', 'zenoh-bridge-ros2dds-fixed'):
                bridges.append({'pid': int(item.name), 'executable': str(executable)})
            if any(Path(arg).name == 'robot_bandwidth.py' for arg in argv) and '--role' in argv:
                index = argv.index('--role')+1
                if index < len(argv) and argv[index] == 'source':
                    helpers.append({'pid': int(item.name)})
        except (OSError, ValueError):
            continue
    return bridges, helpers


def request(url, timeout=3):
    with build_opener(ProxyHandler({})).open(url, timeout=timeout) as response:
        return json.load(response)


def tcp_connection(host,pid,runner=subprocess.run):
    try:
        query=runner(['ss','-H','-tnp','state','established'],capture_output=True,text=True,check=True,timeout=3)
        return any(f'{host}:7447' in line.split() and re.search(r'\bpid='+str(int(pid))+r',',line)
                   for line in query.stdout.splitlines())
    except (OSError,ValueError,subprocess.SubprocessError):
        return None


def checks(root, pi_url, wait=10, fetch=request, route=robot_bridge_service.wired_route,
           inspect=processes, runner=subprocess.run, connected=tcp_connection):
    root = Path(root).resolve()
    rows = []
    def add(name, state, detail, next_step=None):
        rows.append(dict(name=name, state=state, detail=detail, **({'next':next_step} if next_step else {})))
    host = urlsplit(pi_url).hostname
    interface = route(host)
    add('Ethernet', 'pass' if interface else 'fail', interface or 'No direct wired route to the Pi',
        None if interface else 'Connect the switch and use DHCP, or ask for a compatible wired address.')
    try:
        service = runner(['systemctl','--user','is-active',robot_bridge_service.UNIT],
                         capture_output=True,text=True,timeout=4)
    except (OSError,subprocess.SubprocessError) as error:
        service = subprocess.CompletedProcess([],1,'Unavailable: '+str(error))
    add('Automatic bridge', 'pass' if service.returncode == 0 else 'fail', service.stdout.strip() or 'Unavailable',
        None if service.returncode == 0 else 'Check: journalctl --user -u '+robot_bridge_service.UNIT+' -n 30 --no-pager')
    # The service can be active while waiting for its wired route. Allow bounded startup settling.
    deadline = time.monotonic()+max(0, wait)
    while True:
        bridges, helpers = inspect()
        if bridges and helpers or time.monotonic() >= deadline or not interface:
            break
        time.sleep(.3)
    expected = str(root/'bin/zenoh-bridge-ros2dds-fixed')
    correct = len(bridges) == 1 and bridges[0]['executable'] == expected
    add('Bridge instance', 'pass' if correct else 'fail',
        'One corrected bridge' if correct else f'{len(bridges)} bridge process(es); expected one corrected instance',
        None if correct else 'Stop old manual bridges; rerun setup while the recorder is idle.')
    if correct:
        current=connected(host,bridges[0]['pid'])
        while current is False and interface and time.monotonic()<deadline:
            time.sleep(.3)
            current=connected(host,bridges[0]['pid'])
        add('Bridge TCP','pass' if current else 'warn' if current is None else 'fail',
            'Connected to Pi port 7447' if current else 'Cannot inspect TCP sockets' if current is None else 'No current connection to Pi port 7447',
            None if current else 'Check Pi bridge power/service and TCP port 7447; a cached heartbeat alone is not a connection test.')
    add('Rate helper', 'pass' if len(helpers) == 1 else 'fail',
        'One source helper' if len(helpers) == 1 else f'{len(helpers)} source helpers; expected one',
        None if len(helpers) == 1 else 'Restart the managed bridge while the recorder is idle.')
    try:
        status = fetch(pi_url+'/api/status')
        while status.get('robot_link') != 'connected' and time.monotonic() < deadline and correct:
            time.sleep(.4)
            status = fetch(pi_url+'/api/status')
        add('Pi recorder', 'pass', 'Reachable; '+str(status.get('state', 'unknown')))
        linked = status.get('robot_link') == 'connected'
        add('Robot connection', 'pass' if linked else 'fail', 'Connected' if linked else 'Not connected',
            None if linked else 'Check the bridge log, its ROS domain and TCP port 7447 to the Pi.')
        add('Recording space', 'warn' if status.get('storage_warning') or not status.get('can_start',True) else 'pass',
            f'{status.get("free_bytes",0)/1024**3:.1f} GiB free',
            'Free recording space before recording.' if status.get('storage_warning') else None)
        # Existing metadata-only catalog; never POST a bandwidth request or subscribe to sensor payloads.
        topics = fetch(pi_url+'/api/topics').get('topics',[])
        count = sum(isinstance(row,dict) and row.get('name') not in ('/rosout','/parameter_events') for row in topics)
        add('Topic discovery','pass' if count else 'warn',f'{count} sensor/application topic(s) visible',
            None if count else 'Start the robot publishers, then Refresh topics. No topics alone does not prove a connection fault.')
    except (OSError,ValueError,TimeoutError) as error:
        add('Pi recorder','fail','Cannot read recorder status/topics: '+str(error),
            'Check Pi power, its recording SSD and the supplied wired IP. Browser proxies are bypassed by this check.')
    return {'ok':not any(row['state']=='fail' for row in rows),'checks':rows,'pi_url':pi_url}


def show(result):
    for row in result['checks']:
        print(f"[{row['state'].upper()}] {row['name']}: {row['detail']}",flush=True)
        if row.get('next'):
            print('  '+row['next'],flush=True)
    return result['ok']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--pi-url')
    parser.add_argument('--json',action='store_true')
    parser.add_argument('--wait',type=float,default=10)
    args=parser.parse_args()
    url=args.pi_url or json.loads((args.root/'zenoh/robot-service.json').read_text())['pi_url']
    value=checks(args.root,url,wait=min(20,max(0,args.wait)))
    if args.json: print(json.dumps(value,indent=2))
    else: show(value)
    return 0 if value['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
