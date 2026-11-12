#!/usr/bin/env python3
"""Install or run the robot-side bridge as a persistent user service."""
import argparse
import getpass
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

UNIT = 'robot-recorder-source-bridge.service'
MARKER = '# Managed by Robot Recorder source bridge setup'


def unit_quote(value):
    value = str(value)
    if any(character in value for character in '\n\r\x00'):
        raise ValueError('Invalid service path')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def setup_files(distro, environment=os.environ, extra=()):
    if extra:
        raise ValueError('Workspace loading is no longer supported; use standard ROS message types')
    return [str(Path('/opt/ros') / distro / 'setup.bash')]


def service_text(root, settings, python=sys.executable):
    return (MARKER + '\n[Unit]\nDescription=Robot Recorder source bridge and rate helper\n'
            'StartLimitIntervalSec=0\n\n[Service]\nType=exec\n'
            f'WorkingDirectory={str(root).replace("%", "%%")}\n'
            f'ExecStart=:{unit_quote(python)} -B {unit_quote(root / "tools/robot_bridge_service.py")} '
            f'run --settings {unit_quote(settings)}\n'
            'Restart=always\nRestartSec=3\nTimeoutStopSec=15\nKillMode=control-group\n'
            'Environment=PYTHONUNBUFFERED=1\n\n[Install]\nWantedBy=default.target\n')


def physical_wired(name, sys_net=Path('/sys/class/net'), visited=None):
    visited = set() if visited is None else visited
    if name in visited or len(visited) > 8:
        return False
    visited.add(name)
    interface = sys_net / name
    if (interface / 'wireless').exists():
        return False
    if (interface / 'device').exists():
        return True
    # Support an Ethernet bridge or VLAN as well as a direct physical NIC.
    lowers = list(interface.glob('lower_*'))
    bridge = interface / 'brif'
    if bridge.is_dir():
        lowers += list(bridge.iterdir())
    return any(physical_wired(item.name.removeprefix('lower_'), sys_net, visited) for item in lowers)


def wired_route(host, runner=subprocess.run, sys_net=Path('/sys/class/net')):
    try:
        query = runner(['ip', '-j', '-4', 'route', 'get', host], capture_output=True,
                       text=True, check=True, timeout=5)
        route = json.loads(query.stdout)[0]
        name = route.get('dev')
        if (not name or route.get('gateway') or not route.get('prefsrc') or
                not physical_wired(name, sys_net)):
            return None
        if (sys_net / name / 'operstate').read_text().strip() not in ('up', 'unknown'):
            return None
        return name
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return None


def launch_command(root, config, setups, domain=None, distro=None):
    commands = ['set -e']
    commands += ['source ' + shlex.quote(path) for path in setups]
    if domain is not None:
        commands += ['unset ROS_LOCALHOST_ONLY',
                     'export ROS_DOMAIN_ID=' + str(domain) + ' RMW_IMPLEMENTATION=rmw_cyclonedds_cpp '
                     'ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET ROS_DISTRO=' + shlex.quote(distro)]
    commands += ['exec bash ' + shlex.quote(str(root / 'tools/start_zenoh_bridge.sh')) + ' ' +
                 shlex.quote(str(config))]
    return '; '.join(commands)


def run(settings):
    if __package__:
        from .robot_control_client import run_manager
    else:
        from robot_control_client import run_manager
    def launch(value):
        root, config = Path(value['root']), Path(value['config'])
        environment = dict(os.environ, ROS_DISTRO=value['ros_distro'],
                           ROS_DOMAIN_ID=str(value['domain']), RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',
                           ROS_AUTOMATIC_DISCOVERY_RANGE='SUBNET')
        environment.pop('ROS_LOCALHOST_ONLY', None)
        return subprocess.Popen(['/bin/bash', '-c', launch_command(root, config,
                    setup_files(value['ros_distro']), value['domain'], value['ros_distro'])],
                    env=environment, start_new_session=True)
    run_manager(settings, launch, wired_route)


def manual_launchers(root, proc_root=Path('/proc')):
    matches = []
    expected = (root / 'tools/start_zenoh_bridge.sh').resolve()
    for proc in proc_root.iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            argv = (proc / 'cmdline').read_bytes().decode().strip('\0').split('\0')
            if len(argv) < 2 or Path(argv[0]).name not in ('bash', 'sh'):
                continue
            script = Path(argv[1])
            if not script.is_absolute():
                script = (proc / 'cwd').resolve() / script
            if script.resolve() == expected:
                matches.append(int(proc.name))
        except (OSError, UnicodeError):
            pass
    return matches


def assert_idle(pi_url):
    with build_opener(ProxyHandler({})).open(pi_url.rstrip('/') + '/api/status', timeout=5) as response:
        state = json.load(response)
    if state.get('state') != 'idle':
        raise ValueError('Stop recording before changing the robot bridge service')


def unmanaged_bridges(root, launchers):
    expected = (root / 'bin/zenoh-bridge-ros2dds-fixed').resolve()
    result = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != os.getuid() or (proc / 'exe').resolve() != expected:
                continue
            stat = (proc / 'stat').read_text()
            parent = int(stat[stat.rfind(')')+2:].split()[1])
            if parent not in launchers:
                result.append(int(proc.name))
        except (OSError, ValueError):
            pass
    return result


def install(args):
    if os.geteuid() == 0:
        raise ValueError('Run setup as the normal ROS user, not root')
    root, config = args.root.expanduser().resolve(), args.config.expanduser().resolve()
    bridge = root / 'bin/zenoh-bridge-ros2dds-fixed'
    if not bridge.is_file() or not os.access(bridge, os.X_OK):
        raise ValueError('The corrected bridge must be installed first')
    source = json.loads(config.read_text())
    domain = int(source['plugins']['ros2dds']['domain'])
    if not 0 <= domain <= 232:
        raise ValueError('ROS domain must be 0–232')
    unit = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user' / UNIT
    if unit.exists() and MARKER not in unit.read_text():
        raise ValueError(f'Preserve or remove the existing unmanaged service first: {unit}')
    manager = ['systemctl', '--user']
    active = subprocess.run(manager + ['is-active', '--quiet', UNIT]).returncode == 0
    manual = [] if active else manual_launchers(root)
    if not active and unmanaged_bridges(root, manual):
        raise ValueError('A bridge was started outside the recorder launcher; stop it before enabling automatic startup')
    if active or manual:
        # Never interrupt an in-progress recording, including an update run.
        assert_idle(args.pi_url)
    plan_path = getattr(args, 'environment_plan', None)
    if plan_path:
        plan = json.loads(plan_path.read_text())
        if plan.get('ros_distro') != args.ros_distro or plan.get('domain') != domain:
            raise ValueError('Resolved ROS settings do not match the bridge configuration')
        base = str(Path('/opt/ros') / args.ros_distro / 'setup.bash')
        if not isinstance(plan.get('setup_files'), list) or not plan['setup_files'] or plan['setup_files'][0] != base:
            raise ValueError('Invalid resolved ROS workspace list')
        setups = setup_files(args.ros_distro, environment={})
    else:
        setups = setup_files(args.ros_distro, extra=args.setup)
    if __package__:
        from . import dds_transport
    else:
        import dds_transport
    dds_transport.configure()
    dds_transport.write_source_profile(root)
    values = {'version': 2, 'root': str(root), 'config': str(config), 'ros_distro': args.ros_distro,
              'domain': domain, 'pi_url': args.pi_url.rstrip('/'),
              'setup_files': setups}
    settings = root / 'zenoh/robot-service.json'
    if __package__:
        from .robot_control_client import register, atomic_json
    else:
        from robot_control_client import register, atomic_json
    register(root, args.pi_url, domain)
    atomic_json(settings, values)
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(service_text(root, settings))
    linger = subprocess.run(['loginctl', '--no-ask-password', 'enable-linger', getpass.getuser()],
                            capture_output=True, text=True)
    if linger.returncode:
        # Some hosts require an administrator for persistent user services.
        subprocess.run(['sudo', 'loginctl', 'enable-linger', getpass.getuser()], check=True)
    subprocess.run(manager + ['daemon-reload'], check=True)
    subprocess.run(manager + ['enable', UNIT], check=True)
    if active or manual:
        assert_idle(args.pi_url)
    marker = getattr(args, 'activation_marker', None)
    if marker:
        marker.touch()
    for pid in manual:
        print(f'Replacing the existing manual recorder bridge (PID {pid}).', flush=True)
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 15
    while manual_launchers(root) and not active:
        if time.monotonic() >= deadline:
            raise ValueError('The manual bridge did not stop; inspect it before starting the service')
        time.sleep(.2)
    subprocess.run(manager + ['restart', UNIT], check=True)
    print('Automatic bridge startup enabled. No terminal needs to remain open.', flush=True)
    print(f'Status: systemctl --user status {UNIT} --no-pager', flush=True)
    print('The bridge waits for its Ethernet connection and reconnects when the Pi becomes available.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('run')
    start.add_argument('--settings', type=Path, required=True)
    setup = commands.add_parser('install')
    setup.add_argument('--root', type=Path, required=True)
    setup.add_argument('--config', type=Path, required=True)
    setup.add_argument('--ros-distro', choices=('humble', 'jazzy'), required=True)
    setup.add_argument('--pi-url', required=True)
    setup.add_argument('--setup', action='append', default=[])
    setup.add_argument('--environment-plan', type=Path)
    setup.add_argument('--activation-marker', type=Path)
    args = parser.parse_args()
    try:
        run(args.settings) if args.command == 'run' else install(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Bridge service setup error: {error}\n')


if __name__ == '__main__':
    main()
