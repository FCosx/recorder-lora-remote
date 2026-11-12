"""Provision recorder DDS receive buffers without changing routes or camera drivers."""
import os
from pathlib import Path
import subprocess
import tempfile

SOCKET_BYTES = 4 * 1024**2
KERNEL_CAP = 8 * 1024**2
MARKER = '# Managed by Robot Recorder DDS transport'
SYSCTL = Path('/etc/sysctl.d/70-robot-recorder-dds.conf')
LIMIT = Path('/proc/sys/net/core/rmem_max')
SOURCE_PROFILE = '''<CycloneDDS xmlns="https://cdds.io/config">
  <!-- Managed by Robot Recorder DDS transport. No interface or domain override. -->
  <Domain Id="any">
    <Internal><SocketReceiveBufferSize min="4MiB" max="4MiB" /></Internal>
  </Domain>
</CycloneDDS>
'''


def configure(limit=LIMIT, config=SYSCTL, runner=subprocess.run, sudo=None):
    """Raise only the receive-buffer ceiling; never lower an existing higher cap."""
    current = int(limit.read_text().strip())
    if current >= KERNEL_CAP:
        return {'rmem_max': current, 'changed': False}
    previous = config.read_text() if config.exists() else None
    if previous is not None and not previous.startswith(MARKER+'\n'):
        raise ValueError(f'Preserve the unmanaged DDS sysctl file first: {config}')
    prefix = (['sudo'] if os.geteuid() else []) if sudo is None else sudo
    if prefix:
        # Authentication is interactive and may legitimately take longer than
        # a sysctl operation. Never time it out or prompt again in cleanup.
        print('Administrator access is needed to configure DDS receive buffers.',flush=True)
        runner(prefix+['-v'],check=True)
        prefix = prefix+['-n']
    value = f'{MARKER}\nnet.core.rmem_max = {KERNEL_CAP}\n'
    staging = config.with_name('.'+config.name+'.new')
    with tempfile.TemporaryDirectory(prefix='recorder-dds-') as temp:
        source = Path(temp)/'dds.conf'
        source.write_text(value)
        applied = False
        try:
            runner(prefix+['sysctl','-w',f'net.core.rmem_max={KERNEL_CAP}'],check=True,
                   capture_output=True,text=True,timeout=15)
            applied = True
            if int(limit.read_text().strip()) < KERNEL_CAP:
                raise ValueError('Kernel did not accept the required DDS receive-buffer ceiling')
            runner(prefix+['install','-m','644',str(source),str(staging)],check=True,timeout=15)
            runner(prefix+['mv','-f',str(staging),str(config)],check=True,timeout=15)
        except Exception:
            if applied:
                try:
                    runner(prefix+['sysctl','-w',f'net.core.rmem_max={current}'],check=False,
                           capture_output=True,text=True,timeout=15)
                except (OSError,subprocess.SubprocessError):
                    pass
            try:
                runner(prefix+['rm','-f',str(staging)],check=False,timeout=15)
            except (OSError,subprocess.SubprocessError):
                pass
            raise
    return {'rmem_max': KERNEL_CAP, 'changed': True}


def write_source_profile(root):
    path = Path(root)/'zenoh/source-cyclonedds.xml'
    if path.exists() and 'Managed by Robot Recorder DDS transport' not in path.read_text():
        return False
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(SOURCE_PROFILE)
    return True


if __name__ == '__main__':
    print(configure())
