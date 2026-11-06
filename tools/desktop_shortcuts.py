"""Create owned application-menu entries without launching a browser."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

MARKER = '# Managed by Robot Recorder shortcuts'


def exec_quote(value):
    value = str(value)
    if any(character in value for character in '\n\r\x00'):
        raise ValueError('Invalid shortcut argument')
    return '"' + ''.join('\\' + char if char in '\\"`$' else char for char in value).replace('%', '%%') + '"'


def install(name, title, argv, comment, data_home=None, desktop=None):
    if any(char in title + comment for char in '\r\n\x00') or '/' in name:
        raise ValueError('Invalid shortcut name')
    data_home = Path(data_home or os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))
    paths = [data_home/'applications'/name]
    if desktop is None and shutil.which('xdg-user-dir'):
        query = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=3)
        candidate = Path(query.stdout.strip()) if query.returncode == 0 and query.stdout.strip() else None
        if candidate and candidate.is_absolute() and candidate != Path.home() and candidate.is_dir():
            desktop = candidate
    if desktop is not None and Path(desktop).is_dir():
        paths.append(Path(desktop)/name)
    text = (MARKER + '\n[Desktop Entry]\nType=Application\nVersion=1.0\n'
            f'Name={title}\nComment={comment}\nExec=' + ' '.join(map(exec_quote, argv)) +
            '\nIcon=network-workgroup\nTerminal=false\nCategories=Utility;Network;\n')
    written = []
    for path in paths:
        if path.exists() and MARKER not in path.read_text():
            continue  # Never replace another application's shortcut.
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.recorder-shortcut-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(text)
            os.chmod(temporary, 0o755 if path.parent == desktop else 0o644)
            os.replace(temporary, path)
            written.append(str(path))
        finally:
            Path(temporary).unlink(missing_ok=True)
    return written


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    args = parser.parse_args()
    from urllib.parse import urlsplit
    parsed = urlsplit(args.url)
    if parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password:
        parser.error('Expected the local recorder HTTP address')
    install('robot-recorder.desktop', 'Robot Recorder', ['xdg-open', args.url],
            'Open the local recorder on the supplied Ethernet network')
    print('Robot Recorder shortcut added to the application menu; the browser was not opened.')
