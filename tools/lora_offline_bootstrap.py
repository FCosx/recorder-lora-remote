#!/usr/bin/env python3
"""Public/private .pyz installer entry point; uses Python's stdlib only."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def install_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        return False
    return (name in ("tools/lora_recorder.py", "tools/lora_offline_bootstrap.py", "docs/lora-remote.md")
            or (name.startswith("lora/") and path.suffix in (".py", ".html", ".service", ".txt"))
            or (name.startswith("vendor/serial/") and path.suffix == ".py")
            or name == "vendor/pyserial-LICENSE.txt")


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".lora-install-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(bundle, directory, config_dir, pairing_file=None):
    directory = Path(directory).expanduser().resolve()
    config_dir = Path(config_dir).expanduser().resolve()
    with zipfile.ZipFile(bundle) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or len(names) > 500:
            raise ValueError("Invalid installer file list")
        if any(entry.file_size > 2 * 1024**2 for entry in entries) or sum(entry.file_size for entry in entries) > 20 * 1024**2:
            raise ValueError("Installer is unexpectedly large")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict):
            raise ValueError("Unsupported installer manifest")
        files = manifest["files"]
        if set(names) != set(files) | {"manifest.json"}:
            raise ValueError("Installer contents do not match its manifest")
        for name, digest in files.items():
            if name not in ("__main__.py", "pairing/remote.json") and not install_path(name):
                raise ValueError("Unexpected installer path")
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Installer checksum mismatch")
        config_bytes = archive.read("pairing/remote.json") if "pairing/remote.json" in files else None
        if pairing_file is not None:
            supplied = Path(pairing_file).expanduser().read_bytes()
            if config_bytes is not None and json.loads(config_bytes).get("key") != json.loads(supplied).get("key"):
                raise ValueError("Supplied pairing does not match the private installer")
            config_bytes = supplied
        config = json.loads(config_bytes) if config_bytes is not None else None
        if config is not None and (config.get("version") != 1 or config.get("role") != "remote"
                or len(bytes.fromhex(config["key"])) != 32
                or config.get("state_file") != "remote-state.sqlite3"):
            raise ValueError("Invalid pairing configuration")
        config_path = config_dir / "remote.json"
        if config_path.exists():
            previous = json.loads(config_path.read_text())
            if (previous.get("version") != 1 or previous.get("role") != "remote"
                    or len(bytes.fromhex(previous.get("key", ""))) != 32):
                raise ValueError("Invalid existing pairing configuration")
            if config is not None and previous.get("key") != config["key"]:
                raise ValueError("This account is paired to a different recorder; use a different --config-dir")
            if config_path.stat().st_mode & 0o077:
                raise ValueError(f"Existing pairing file must be private: chmod 600 {config_path}")
        directory.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in files:
            if name in ("__main__.py", "pairing/remote.json"):
                continue
            target = directory / name
            try:
                target.resolve().relative_to(directory)
            except ValueError as error:
                raise ValueError("Install destination contains a link outside its directory") from error
            atomic_write(target, archive.read(name), 0o644)
        if config_bytes is not None and not config_path.exists():
            atomic_write(config_path, config_bytes, 0o600)
    return directory, config_path


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Install the LoRa remote locally. No Pi IP, network, pip, or apt is used by installation.")
    parser.add_argument("command", nargs="?", choices=["install"], default="install")
    parser.add_argument("--directory", type=Path, default=Path.home() / "robot-recorder")
    parser.add_argument("--config-dir", type=Path, default=Path.home() / ".config/robot-recorder-lora")
    parser.add_argument("--pairing", type=Path, help="Private recorder pairing file supplied separately by its maintainer")
    args = parser.parse_args()
    try:
        directory, config = install(sys.argv[0], args.directory, args.config_dir, args.pairing)
    except Exception as error:
        parser.exit(1, f"Offline setup error: {error}\n")
    if config.exists():
        print("Offline setup complete. Pairing and any existing command counter were preserved.")
    else:
        print("Public software installed. Recorder authorization is still required.")
        print("Get recorder-pairing.json privately from its maintainer, then rerun this installer with --pairing /path/to/recorder-pairing.json")
    print("The remote synchronizes with the Pi over LoRa when it starts; no Pi IP is needed.")
    import shlex
    command = f"python3 -B {shlex.quote(str(directory / 'tools/lora_recorder.py'))} remote"
    if config != Path.home() / ".config/robot-recorder-lora/remote.json":
        command += " --config " + shlex.quote(str(config))
    print(f"\nKeep this command running:\n{command}\nThen open http://127.0.0.1:8081 on this laptop.")


if __name__ == "__main__":
    main()
