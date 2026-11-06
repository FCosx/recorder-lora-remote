"""Resolve only the ROS settings needed by the recorder's source bridge.

Detection reads local process metadata; it never subscribes, probes other ROS
domains, sources shell startup files, or changes a robot's running nodes.
"""
import json
import os
from pathlib import Path
import re
import time

SUPPORTED = ('humble', 'jazzy')
ROS_KEYS = {'ROS_DISTRO', 'ROS_DOMAIN_ID'}


def domain_number(value):
    if not re.fullmatch(r'[0-9]{1,3}', str(value)) or not 0 <= int(value) <= 232:
        raise ValueError('ROS domain must be an integer from 0 to 232')
    return int(value)


def process_evidence(proc=Path('/proc'), uid=None, budget=1.0):
    """Inspect readable, same-user ROS nodes, excluding recorder infrastructure."""
    uid = os.getuid() if uid is None else uid
    deadline = time.monotonic() + budget
    result = []
    for item in proc.iterdir():
        if time.monotonic() > deadline:
            break
        if not item.name.isdigit() or int(item.name) == os.getpid():
            continue
        try:
            if item.stat().st_uid != uid:
                continue
            argv = (item / 'cmdline').read_bytes().split(b'\0')
            if any(Path(os.fsdecode(arg)).name in (
                    'robot_bandwidth.py', 'estimate_bandwidth.py', '_ros2_daemon',
                    'zenoh-bridge-ros2dds', 'zenoh-bridge-ros2dds-fixed') for arg in argv if arg):
                continue
            maps = (item / 'maps').read_text(errors='replace')
            if not re.search(r'/librcl(?:cpp|py|_action|_lifecycle)?(?:\.[^/\s]*)?\.so', maps):
                continue
            # Never retain or print unrelated environment entries or command arguments.
            values = {}
            for entry in (item / 'environ').read_bytes().split(b'\0'):
                key, separator, value = entry.partition(b'=')
                name = os.fsdecode(key)
                if separator and name in ROS_KEYS:
                    values[name] = os.fsdecode(value)
            distro = values.get('ROS_DISTRO')
            if distro not in SUPPORTED:
                distros = set(re.findall(r'/opt/ros/(humble|jazzy)/', maps))
                distro = next(iter(distros)) if len(distros) == 1 else None
            if distro is None:
                continue
            result.append({'pid': int(item.name), 'distro': distro,
                           'domain': domain_number(values.get('ROS_DOMAIN_ID', '0')),
                           'environment': values})
        except (OSError, ValueError):
            continue
    return result


def read_saved(root):
    path = root / 'zenoh/robot-service.json'
    if not path.exists():
        config = root / 'zenoh/robot.json5'
        if not config.exists():
            return {}
        try:
            domain = json.loads(config.read_text())['plugins']['ros2dds']['domain']
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError('Cannot read existing bridge configuration; preserve it before setup') from error
        return {'domain': domain_number(domain)}
    try:
        value = json.loads(path.read_text())
        value['domain'] = domain_number(value['domain'])
        if (value['ros_distro'] not in SUPPORTED or not isinstance(value.get('setup_files'), list)
                or any(not isinstance(path, str) for path in value['setup_files'])):
            raise ValueError('Invalid saved ROS settings')
        config = root / 'zenoh/robot.json5'
        if config.exists():
            configured = domain_number(json.loads(config.read_text())['plugins']['ros2dds']['domain'])
            if value.get('version', 1) < 2 and configured != value['domain']:
                raise ValueError('Saved bridge domain and service settings disagree')
        return value
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f'Cannot safely reuse existing ROS settings: {error}') from error


def choose_value(label, values, choose):
    values = sorted(set(values), key=str)
    if len(values) == 1:
        return values[0]
    if not values:
        return None
    if choose is None:
        flag = '--domain' if label == 'ROS domain' else '--ros-distro'
        raise ValueError(f'Multiple {label} choices ({", ".join(map(str, values))}); specify {flag}')
    selected = choose(label, values)
    if selected not in values:
        raise ValueError(f'Invalid {label} selection')
    return selected


def detect(root, distro=None, domain=None, setups=(), no_workspaces=False,
           environment=None, evidence=None, ros_root=Path('/opt/ros'), choose=None):
    environment = dict(os.environ) if environment is None else environment
    saved = read_saved(root)
    installed = [name for name in SUPPORTED if (ros_root / name / 'setup.bash').is_file()]
    if not installed:
        raise ValueError('Install ROS 2 Humble or Jazzy before setup')
    evidence = process_evidence() if evidence is None else evidence
    evidence = [row for row in evidence if row['distro'] in installed]
    preferred = distro or saved.get('ros_distro')
    domain_evidence = [row for row in evidence if not preferred or row['distro'] == preferred]

    if domain is not None:
        domain, domain_source = domain_number(domain), 'explicit option'
    elif 'domain' in saved:
        domain, domain_source = saved['domain'], 'existing settings'
    else:
        domains = [row['domain'] for row in domain_evidence]
        if (environment.get('ROS_DOMAIN_ID', '') and
                (not preferred or environment.get('ROS_DISTRO') in (None, '', preferred))):
            try:
                domains.append(domain_number(environment['ROS_DOMAIN_ID']))
            except ValueError:
                pass  # An unreadable/invalid automatic hint uses the UI's domain-0 fallback.
        domain = domains[0] if len(set(domains)) == 1 else 0
        domain_source = 'running nodes/current environment' if len(set(domains)) == 1 else 'default'

    if distro:
        distro_source = 'explicit option'
    elif saved.get('ros_distro'):
        distro, distro_source = saved['ros_distro'], 'existing settings'
    else:
        candidates = [row['distro'] for row in evidence if row['domain'] == domain] or [row['distro'] for row in evidence]
        if environment.get('ROS_DISTRO') in installed:
            candidates.append(environment['ROS_DISTRO'])
        distro = choose_value('ROS version', candidates or installed, choose)
        distro_source = 'running nodes/current environment' if candidates else 'installed ROS'
    if distro not in installed:
        raise ValueError(f'ROS {distro} is not installed; choose an installed version with --ros-distro')

    base = str((ros_root / distro / 'setup.bash').resolve())
    files = [base]
    if setups:
        raise ValueError('Workspace loading is no longer used; only standard ROS message types are supported')
    notes = []
    if domain_source == 'default':
        notes.append('No unique robot ROS domain detected; using 0. Change Robot ROS domain in the recorder UI if needed.')
    observed = {row['domain'] for row in evidence}
    if domain_source == 'existing settings' and observed and domain not in observed:
        notes.append('Existing domain kept; running nodes were seen in ' + ', '.join(map(str, sorted(observed))) +
                     '. Use --domain to change the bridge deliberately.')
    return {'version': 1, 'ros_distro': distro, 'domain': domain, 'setup_files': files,
            'domain_source': domain_source, 'ros_distro_source': distro_source, 'notes': notes}
