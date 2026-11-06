"""Select and verify recorder-maintained, corrected Zenoh bridge packages."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import tarfile
import tempfile

VERSION = '1.10.1'
PATCH_SHA256 = '30462d2b7c3a20360dc968d5b4f68ac219061d2bd10f1940f88fbb739bc03827'
SOURCE_SHA256 = '2c66aec0ab999d346c17497f2a6e84600478e57a197bb8c1dc5e6dd5bbbe5c03'
PACKAGE_ID = VERSION + '-route-listener-v1'
ARCHES = {'amd64': 'x86_64', 'x86_64': 'x86_64', 'arm64': 'aarch64', 'aarch64': 'aarch64'}
PACKAGE_FILES = ('manifest.json',) + tuple(f'bridge-{PACKAGE_ID}-{arch}.tar.gz'
                                        for arch in ('x86_64', 'aarch64'))
MAX_ARCHIVE = 64 * 1024**2
MAX_BINARY = 128 * 1024**2


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def select(manifest, distro, machine=None, libc=None):
    if (manifest.get('format') != 1 or manifest.get('bridge_version') != VERSION or
            manifest.get('patch_sha256') != PATCH_SHA256 or manifest.get('source_sha256') != SOURCE_SHA256):
        raise ValueError('Bridge package manifest does not match the required corrected bridge')
    arch = ARCHES.get(machine or platform.machine())
    if arch is None:
        raise ValueError('No prebuilt bridge for this CPU; use --build-from-source if required')
    name, version = libc or platform.libc_ver()
    if name != 'glibc' or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('Cannot identify a compatible Linux runtime')
    for package in manifest.get('packages', []):
        if package.get('arch') != arch or distro not in package.get('ros_distros', []):
            continue
        minimum = package.get('min_glibc')
        if not isinstance(minimum, str) or not re.fullmatch(r'\d+\.\d+', minimum):
            raise ValueError('Invalid package runtime requirement')
        if tuple(map(int, version.split('.'))) < tuple(map(int, minimum.split('.'))):
            raise ValueError(f'This prebuilt bridge requires glibc {minimum} or newer')
        if package.get('file') != f'bridge-{PACKAGE_ID}-{arch}.tar.gz':
            raise ValueError('Unexpected bridge package filename')
        for key in ('sha256', 'binary_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', package.get(key, '')):
                raise ValueError('Invalid bridge checksum in manifest')
        return package
    raise ValueError(f'No compatible corrected bridge package for {arch}/{distro}')


def validate_binary(path, arch):
    with Path(path).open('rb') as source:
        header = source.read(20)
    if (len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or
            struct.unpack('<H', header[18:20])[0] != {'x86_64': 62, 'aarch64': 183}[arch]):
        raise ValueError('Package contains a binary for the wrong CPU architecture')
    result = subprocess.run([str(path), '--version'], capture_output=True, text=True, check=True, timeout=15)
    if not re.search(r'\bzenoh-bridge-ros2dds\s+v?1\.10\.1(?:\s|$)', result.stdout + result.stderr):
        raise ValueError('Unexpected bridge version')


def install(archive, package, root):
    """Never extract arbitrary paths or replace the installed binary on failure."""
    archive, root = Path(archive), Path(root)
    if archive.stat().st_size > MAX_ARCHIVE or digest(archive) != package['sha256']:
        raise ValueError('Bridge download checksum failed; existing bridge was preserved')
    expected = {'bridge/zenoh-bridge-ros2dds-fixed', 'bridge/BUILD.json', 'bridge/LICENSE', 'bridge/NOTICE.md'}
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if (len(members) != len(expected) or {item.name for item in members} != expected or
                any(not item.isfile() or item.size < 0 or item.size > MAX_BINARY for item in members)):
            raise ValueError('Invalid bridge package members')
        metadata = bundle.extractfile('bridge/BUILD.json')
        if metadata is None or bundle.getmember('bridge/BUILD.json').size > 16384:
            raise ValueError('Invalid bridge build metadata')
        build = json.load(metadata)
        if (build.get('bridge_version') != VERSION or build.get('patch_sha256') != PATCH_SHA256 or
                build.get('source_sha256') != SOURCE_SHA256 or build.get('arch') != package['arch'] or
                build.get('binary_sha256') != package['binary_sha256']):
            raise ValueError('Bridge package provenance mismatch')
        (root / 'bin').mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.bridge-', dir=root / 'bin')
        try:
            with os.fdopen(fd, 'wb') as destination:
                source = bundle.extractfile('bridge/zenoh-bridge-ros2dds-fixed')
                if source is None:
                    raise ValueError('Bridge binary is missing')
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    destination.write(block)
            temporary = Path(temporary)
            if digest(temporary) != package['binary_sha256']:
                raise ValueError('Bridge binary checksum failed')
            temporary.chmod(0o755)
            validate_binary(temporary, package['arch'])
            os.replace(temporary, root / 'bin/zenoh-bridge-ros2dds-fixed')
            write_json(root / '.bridge-package.json', build)
        finally:
            Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def installed(root):
    path, record = root / 'bin/zenoh-bridge-ros2dds-fixed', root / '.bridge-package.json'
    if not path.is_file() or not record.is_file():
        return False
    try:
        value = json.loads(record.read_text())
        return (value.get('bridge_version') == VERSION and value.get('patch_sha256') == PATCH_SHA256 and
                value.get('source_sha256') == SOURCE_SHA256 and value.get('arch') == ARCHES.get(platform.machine())
                and digest(path) == value.get('binary_sha256'))
    except (OSError, ValueError):
        return False
