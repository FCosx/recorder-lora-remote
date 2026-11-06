#!/usr/bin/env python3
"""Install a verified source bridge; preserve existing robot ROS settings."""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

if __package__:
    from . import bridge_packages as packages, robot_environment
else:
    import bridge_packages as packages
    import robot_environment

ASSETS = {
    'build_zenoh_bridge.sh': 'tools/build_zenoh_bridge.sh',
    'start_zenoh_bridge.sh': 'tools/start_zenoh_bridge.sh',
    'robot_bandwidth.py': 'tools/robot_bandwidth.py',
    'robot_control_client.py': 'tools/robot_control_client.py',
    'robot_bridge_service.py': 'tools/robot_bridge_service.py',
    'route-listener-lifetime.patch': 'zenoh/patches/1.10.1-route-listener-lifetime.patch',
    'install_robot_bridge.py': 'tools/install_robot_bridge.py',
    'robot_environment.py': 'tools/robot_environment.py',
    'bridge_packages.py': 'tools/bridge_packages.py',
    'check_robot_setup.py': 'tools/check_robot_setup.py',
    'desktop_shortcuts.py': 'tools/desktop_shortcuts.py',
}


def existing_install_root(config_home=None, runner=subprocess.run):
    config_home = config_home or Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    unit = config_home / 'systemd/user/robot-recorder-source-bridge.service'
    if not unit.is_file() or '# Managed by Robot Recorder source bridge setup' not in unit.read_text():
        return None
    query = runner(['systemctl', '--user', 'show', unit.name, '-p', 'WorkingDirectory', '--value'],
                   capture_output=True, text=True, timeout=5)
    value = query.stdout.strip()
    if query.returncode or not value or not Path(value).is_absolute():
        raise ValueError('Cannot locate the existing bridge folder; specify --install-dir')
    root = Path(value).resolve()
    try:
        settings = json.loads((root / 'zenoh/robot-service.json').read_text())
        if Path(settings['root']).resolve() != root:
            raise ValueError('Existing service and settings point to different folders')
    except (OSError, ValueError, KeyError) as error:
        raise ValueError('Cannot safely reuse the existing bridge folder; specify --install-dir') from error
    return root


def pi_address(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or not parsed.hostname or not parsed.port or parsed.username or
            parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Use --pi-url http://PI_WIRED_IP:8080')
    ipaddress.IPv4Address(parsed.hostname)
    return value.rstrip('/'), parsed.hostname


def read_status(pi_url, opener):
    with opener.open(pi_url + '/api/status', timeout=6) as response:
        status = json.load(response)
    if status.get('state') != 'idle':
        raise ValueError('Stop recording before installing or changing the robot bridge')


def download(pi_url, name, destination, limit=1024 * 1024):
    request = Request(pi_url + '/setup/' + name)
    opener = build_opener(ProxyHandler({}))
    size = 0
    with opener.open(request, timeout=30) as response, destination.open('wb') as output:
        for block in iter(lambda: response.read(1024 * 1024), b''):
            size += len(block)
            if size > limit:
                raise ValueError('Setup download exceeds its expected size')
            output.write(block)


def choose(label, values):
    print(f'{label} choices: ' + ', '.join(map(str, values)), flush=True)
    if not sys.stdin.isatty():
        raise ValueError('Selection is ambiguous; use --domain, --ros-distro explicitly')
    answer = input(f'{label} to use: ').strip()
    for value in values:
        if answer == str(value):
            return value
    raise ValueError(f'Invalid {label} selection')


def config_text(plan, host, existing=None, previous_host=None):
    if existing is not None:
        value = json.loads(json.dumps(existing))
        value.setdefault('plugins', {}).setdefault('ros2dds', {})['domain'] = plan['domain']
        if previous_host is None:
            hosts = [match.group(1) for entry in value.get('connect', {}).get('endpoints', [])
                     if (match := re.fullmatch(r'tcp/([0-9.]+):7447', entry))]
            previous_host = hosts[0] if len(hosts) == 1 else None
        if previous_host and previous_host != host:
            old, new = f'tcp/{previous_host}:7447', f'tcp/{host}:7447'
            endpoints = value.setdefault('connect', {}).setdefault('endpoints', [])
            value['connect']['endpoints'] = [new if entry == old else entry for entry in endpoints]
            if new not in value['connect']['endpoints']:
                value['connect']['endpoints'].append(new)
        return value
    return {'mode': 'router', 'listen': {'endpoints': ['tcp/127.0.0.1:7447']},
            'connect': {'endpoints': [f'tcp/{host}:7447']},
            'scouting': {'multicast': {'enabled': False}},
            'plugins': {'ros2dds': {'domain': plan['domain'], 'ros_localhost_only': False,
                                   'ros_automatic_discovery_range': 'SUBNET'}}}


def startup_text(root, plan):
    text = '#!/usr/bin/env bash\nset -e\n'
    for path in plan['setup_files']:
        text += 'source ' + shlex.quote(path) + '\n'
    text += 'unset ROS_LOCALHOST_ONLY\n'
    text += ('export ROS_DISTRO=' + shlex.quote(plan['ros_distro']) + ' ROS_DOMAIN_ID=' + str(plan['domain']) +
             ' RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET\n')
    return text


def install_dependencies(distro, from_source):
    required = ['curl', 'util-linux', f'ros-{distro}-rmw-cyclonedds-cpp',
                f'ros-{distro}-rclpy', f'ros-{distro}-rosidl-runtime-py']
    if from_source:
        required += ['build-essential', 'cmake', 'libclang-dev', 'pkg-config',
                     'ca-certificates', 'patch', 'git']
    missing = []
    for name in required:
        query = subprocess.run(['dpkg-query', '-W', '-f=${Status}', name],
                               capture_output=True, text=True)
        if query.returncode or query.stdout.strip() != 'install ok installed':
            missing.append(name)
    if missing:
        subprocess.run(['sudo', 'apt-get', 'update'], check=True)
        subprocess.run(['sudo', 'apt-get', 'install', '-y', '--no-install-recommends'] + missing, check=True)


def atomic_copy(source, destination, mode=0o644):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + destination.name, dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream, source.open('rb') as incoming:
            shutil.copyfileobj(incoming, stream)
        os.chmod(name, mode)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def legacy_verified(root):
    record = root / '.bridge-build.sha256'
    binary = root / 'bin/zenoh-bridge-ros2dds-fixed'
    patch = root / ASSETS['route-listener-lifetime.patch']
    if not record.is_file() or not binary.is_file() or not patch.is_file():
        return False
    try:
        first = record.read_text().splitlines()[0].split(maxsplit=1)
        return (len(first) == 2 and Path(first[1].lstrip('*')).resolve() == binary.resolve() and
                packages.digest(binary) == first[0] and packages.digest(patch) == packages.PATCH_SHA256)
    except (OSError, ValueError, IndexError):
        return False


def native_build(root):
    environment = dict(os.environ)
    environment['PATH'] = str(Path.home() / '.cargo/bin') + ':' + environment['PATH']
    environment['ZENOH_BUILD_JOBS'] = environment.get('ZENOH_BUILD_JOBS', '2')
    if not shutil.which('rustup', path=environment['PATH']):
        with tempfile.TemporaryDirectory(prefix='recorder-rust-') as directory:
            path = Path(directory) / 'rustup.sh'
            subprocess.run(['curl', '-q', '-fL', '--retry', '3', 'https://sh.rustup.rs', '-o', str(path)], check=True)
            subprocess.run(['sh', str(path), '-y', '--profile', 'minimal', '--default-toolchain',
                            'none', '--no-modify-path'], check=True, env=environment)
    subprocess.run(['rustup', 'toolchain', 'install', '1.97.1', '--profile', 'minimal'], check=True, env=environment)
    subprocess.run(['bash', str(root / 'tools/build_zenoh_bridge.sh')], check=True, env=environment)
    entries = [root / 'bin/zenoh-bridge-ros2dds-fixed', root / ASSETS['route-listener-lifetime.patch'],
               root / 'tools/build_zenoh_bridge.sh']
    (root / '.bridge-build.sha256').write_text(''.join(packages.digest(path) + '  ' + str(path) + '\n'
                                                    for path in entries))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pi-url', required=True)
    parser.add_argument('--install-dir', type=Path)
    parser.add_argument('--ros-distro', choices=robot_environment.SUPPORTED)
    parser.add_argument('--domain', type=robot_environment.domain_number)
    parser.add_argument('--setup', action='append', default=[], help=argparse.SUPPRESS)
    parser.add_argument('--no-workspaces', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--configure-only', action='store_true')
    parser.add_argument('--skip-dependencies', action='store_true')
    parser.add_argument('--build-from-source', action='store_true', help='Explicit fallback for unsupported packages')
    parser.add_argument('--dry-run', action='store_true', help='Resolve settings without modifying files or services')
    parser.add_argument('--no-service', action='store_true', help='Prepare an isolated/manual installation without replacing a service')
    parser.add_argument('--check-only', action='store_true', help='Check the installed setup without changing or restarting it')
    parser.add_argument('--no-shortcuts', action='store_true', help='Do not add a browser shortcut')
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        raise ValueError('Run as the normal ROS user; setup requests sudo when needed')
    selected_root = args.install_dir if args.install_dir is not None else existing_install_root() or Path.home() / 'robot-recorder'
    if not selected_root.is_absolute():
        raise ValueError('--install-dir must be an absolute path')
    root = selected_root.expanduser().resolve()
    pi_url, host = pi_address(args.pi_url)
    if args.check_only:
        check = root/'tools/check_robot_setup.py'
        if not check.is_file():
            raise ValueError('Run the updated installer once before using --check-only')
        return subprocess.run([sys.executable,'-B',str(check),'--root',str(root),'--pi-url',pi_url]).returncode
    opener = build_opener(ProxyHandler({}))
    read_status(pi_url, opener)
    plan = robot_environment.detect(root, args.ros_distro, args.domain, args.setup,
                                    args.no_workspaces, choose=choose)
    print(f"ROS {plan['ros_distro']} ({plan['ros_distro_source']}); domain {plan['domain']} ({plan['domain_source']}).", flush=True)
    print('ROS setup: ' + ', '.join(plan['setup_files']), flush=True)
    for note in plan.get('notes', []):
        print(note, flush=True)
    if args.dry_run:
        print(json.dumps(plan, indent=2), flush=True)
        return 0
    binary = root / 'bin/zenoh-bridge-ros2dds-fixed'
    if args.configure_only and not binary.is_file():
        raise ValueError('Corrected bridge not installed; run setup without --configure-only first')
    reuse = args.configure_only or packages.installed(root) or legacy_verified(root)
    if reuse:
        arch = packages.ARCHES.get(platform.machine())
        try:
            if arch is None:
                raise ValueError('No verified bridge runtime for this CPU')
            packages.validate_binary(binary, arch)
        except (ValueError, subprocess.SubprocessError, OSError):
            if args.configure_only:
                raise ValueError('Installed bridge does not run on this CPU; run full setup')
            reuse = False
    with tempfile.TemporaryDirectory(prefix='recorder-bridge-setup-') as directory:
        stage = Path(directory)
        package, archive = None, None
        for name in ASSETS:
            download(pi_url, name, stage / name)
        if packages.digest(stage / 'route-listener-lifetime.patch') != packages.PATCH_SHA256:
            raise ValueError('Incorrect bridge correction; installation canceled')
        if not reuse and not args.build_from_source:
            download(pi_url, 'bridge-packages/manifest.json', stage / 'manifest.json')
            package = packages.select(json.loads((stage / 'manifest.json').read_text()), plan['ros_distro'])
            archive = stage / package['file']
            print('Downloading verified prebuilt bridge for ' + package['arch'] + '.', flush=True)
            download(pi_url, 'bridge-packages/' + package['file'], archive, packages.MAX_ARCHIVE)
            # Verify/exercise the new executable before touching the existing installation.
            packages.install(archive, package, stage / 'verified')
        if not args.skip_dependencies and not args.configure_only:
            install_dependencies(plan['ros_distro'], args.build_from_source)
        for setup in plan['setup_files']:
            subprocess.run(['bash', '-n', setup], check=True)
        read_status(pi_url, opener)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = root / 'backups/bridge-setup' / stamp
        names = list(ASSETS.values()) + ['zenoh/robot.json5', 'zenoh/robot-service.json',
                'tools/start_robot_bridge.sh', 'tools/publish_bridge_test.sh',
                'bin/zenoh-bridge-ros2dds-fixed', '.bridge-package.json', '.bridge-build.sha256']
        previous = {}
        for name in names:
            path = root / name
            previous[name] = path.exists()
            if path.is_file():
                (backup / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup / name)
        unit = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user/robot-recorder-source-bridge.service'
        old_unit = unit.read_bytes() if unit.is_file() else None
        manager = ['systemctl', '--user']
        old_active = old_enabled = False
        marker = stage / 'activation-started'
        if not args.no_service:
            old_active = subprocess.run(manager + ['is-active', '--quiet', unit.name]).returncode == 0
            old_enabled = subprocess.run(manager + ['is-enabled', '--quiet', unit.name],
                                          capture_output=True).returncode == 0
        try:
            for name, target in ASSETS.items():
                atomic_copy(stage / name, root / target)
            if not reuse:
                if args.build_from_source:
                    native_build(root)
                else:
                    packages.install(archive, package, root)
            if not os.access(binary, os.X_OK):
                raise ValueError('Corrected bridge is not executable')
            existing = root / 'zenoh/robot.json5'
            saved = robot_environment.read_saved(root)
            previous_host = urlsplit(saved['pi_url']).hostname if saved.get('pi_url') else None
            packages.write_json(existing, config_text(plan, host,
                json.loads(existing.read_text()) if existing.exists() else None, previous_host))
            header = startup_text(root, plan)
            (root / 'tools/start_robot_bridge.sh').write_text(header + 'exec bash ' +
                shlex.quote(str(root / 'tools/start_zenoh_bridge.sh')) + ' ' +
                shlex.quote(str(root / 'zenoh/robot.json5')) + '\n')
            (root / 'tools/publish_bridge_test.sh').write_text(header +
                'exec ros2 topic pub -r 2 /zenoh_test std_msgs/msg/String "{data: \'hello over Zenoh\'}"\n')
            packages.write_json(stage / 'environment.json', plan)
            if not args.no_service:
                read_status(pi_url, opener)
                subprocess.run([sys.executable, '-B', str(root / 'tools/robot_bridge_service.py'),
                    'install', '--root', str(root), '--config', str(root / 'zenoh/robot.json5'),
                    '--ros-distro', plan['ros_distro'], '--pi-url', pi_url,
                    '--environment-plan', str(stage / 'environment.json'),
                    '--activation-marker', str(marker)], check=True)
            else:
                settings = dict(plan, root=str(root), config=str(root / 'zenoh/robot.json5'), pi_url=pi_url)
                packages.write_json(root / 'zenoh/robot-service.json', settings)
        except Exception:
            if not args.no_service and marker.exists():
                subprocess.run(manager + ['stop', unit.name], check=False)
            for name, existed in previous.items():
                path = root / name
                if existed and (backup / name).is_file():
                    atomic_copy(backup / name, path, (backup / name).stat().st_mode & 0o777)
                elif not existed:
                    path.unlink(missing_ok=True)
            if not args.no_service:
                if old_unit is None:
                    subprocess.run(manager + ['disable', unit.name], capture_output=True, check=False)
                    unit.unlink(missing_ok=True)
                else:
                    unit.write_bytes(old_unit)
                subprocess.run(manager + ['daemon-reload'], check=False)
                if old_unit is not None and not old_enabled:
                    subprocess.run(manager + ['disable', unit.name], capture_output=True, check=False)
                if old_active and marker.exists():
                    subprocess.run(manager + ['start', unit.name], check=False)
            raise
        if not args.no_service:
            if not args.no_shortcuts:
                shortcut = subprocess.run([sys.executable,'-B',str(root/'tools/desktop_shortcuts.py'),'--url',pi_url],check=False)
                if shortcut.returncode:
                    print('Browser shortcut unavailable; open '+pi_url+' after setup.',flush=True)
            result = subprocess.run([sys.executable,'-B',str(root/'tools/check_robot_setup.py'),
                                     '--root',str(root),'--pi-url',pi_url],check=False)
            if result.returncode:
                print('Setup installed; self-check needs attention. Follow the steps above; no second bridge is needed.',flush=True)
                return 2
        print('Setup complete. ' + ('Manual test installation prepared.' if args.no_service else
              'The bridge starts automatically; no open terminal is required.'), flush=True)
        if backup.exists():
            print('Previous files preserved at ' + str(backup), flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Setup error: {error}. Existing files are preserved on installation failure.', file=sys.stderr)
        sys.exit(1)
