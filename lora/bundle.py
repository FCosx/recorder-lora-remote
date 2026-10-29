"""Build a public installer or a private pre-paired installer."""

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

from .common import load_config


def build_bundle(root, config_path, destination, encrypted_pairing=None):
    import serial
    root = Path(root).resolve()
    key = load_config(config_path, "remote")[1] if config_path is not None else None
    files = {}
    for path in (root / "lora").glob("*.py"):
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    for name in ("lora/remote.html", "tools/lora_recorder.py", "tools/lora_offline_bootstrap.py",
                 "lora/licenses/pyserial-LICENSE.txt", "docs/lora-remote.md"):
        files[name] = (root / name).read_bytes()
    files["__main__.py"] = (root / "tools/lora_offline_bootstrap.py").read_bytes()
    serial_root = Path(serial.__file__).resolve().parent
    for path in serial_root.rglob("*.py"):
        files["vendor/serial/" + path.relative_to(serial_root).as_posix()] = path.read_bytes()
    files["vendor/pyserial-LICENSE.txt"] = (root / "lora/licenses/pyserial-LICENSE.txt").read_bytes()
    if key is not None:
        files["pairing/remote.json"] = (json.dumps({
            "version": 1, "role": "remote", "key": key.hex(), "state_file": "remote-state.sqlite3",
        }, indent=2) + "\n").encode()
    if encrypted_pairing is not None:
        if key is not None:
            raise ValueError("Use encrypted pairing only with a public build")
        encrypted = Path(encrypted_pairing).read_bytes()
        envelope = json.loads(encrypted)
        if envelope.get("format") != "recorder-pairing-encrypted-v1" or "key" in envelope:
            raise ValueError("Expected an encrypted pairing file, never plaintext")
        files["pairing/remote.enc.json"] = encrypted
    manifest = {"version": 1, "paired": key is not None, "serial_version": serial.__version__,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files["manifest.json"] = json.dumps(manifest, indent=2).encode()
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".lora-bundle-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in sorted(files.items()):
                    archive.writestr(name, data)
        os.chmod(temporary, 0o600 if key is not None else 0o644)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination
