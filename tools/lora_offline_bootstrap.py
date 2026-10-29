#!/usr/bin/env python3
"""Public/private .pyz installer entry point; uses Python's stdlib only."""

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


PAIRING_FORMAT = "recorder-pairing-encrypted-v1"
PAIRING_ITERATIONS = 600000


def pairing_id(config):
    return hashlib.sha256(bytes.fromhex(config["key"])).hexdigest()


def openssl_pairing(data, passcode, decrypt=False):
    """Keep passcodes out of process arguments, environment and disk."""
    executable = shutil.which("openssl")
    if executable is None:
        raise ValueError("OpenSSL is required for first-time passcode setup; on Ubuntu run: sudo apt install openssl")
    password = passcode.encode("utf-8")
    if not password or len(password) > 1024 or b"\n" in password or b"\r" in password:
        raise ValueError("Passcode must be one nonempty line (at most 1024 bytes)")
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, password + b"\n")
        os.close(write_fd)
        write_fd = None
        result = subprocess.run([executable, "enc", "-aes-256-cbc", "-pbkdf2",
                                 "-iter", str(PAIRING_ITERATIONS), "-md", "sha256",
                                 "-pass", f"fd:{read_fd}"] + (["-d"] if decrypt else []),
                                input=data, capture_output=True, pass_fds=(read_fd,), timeout=30)
        if result.returncode:
            raise ValueError("Pairing encryption/decryption failed")
        return result.stdout
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


def envelope_data(envelope):
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()


def encrypt_pairing(config, passcode):
    # Encrypt-then-MAC: authenticate the metadata and ciphertext before decrypting.
    salt = os.urandom(32)
    envelope = {"format": PAIRING_FORMAT, "cipher": "AES-256-CBC+HMAC-SHA256",
                "iterations": PAIRING_ITERATIONS, "key_id": pairing_id(config),
                "salt": base64.b64encode(salt).decode(),
                "ciphertext": base64.b64encode(openssl_pairing(json.dumps(config).encode(), passcode)).decode()}
    key = hashlib.pbkdf2_hmac("sha256", passcode.encode(), salt, PAIRING_ITERATIONS)
    envelope["mac"] = hmac.new(key, envelope_data(envelope), "sha256").hexdigest()
    return (json.dumps(envelope, indent=2) + "\n").encode()


def decrypt_pairing(envelope, passcode):
    envelope = dict(envelope)
    if (set(envelope) != {"format", "cipher", "iterations", "key_id", "salt", "ciphertext", "mac"}
            or envelope["format"] != PAIRING_FORMAT
            or envelope["cipher"] != "AES-256-CBC+HMAC-SHA256"
            or envelope["iterations"] != PAIRING_ITERATIONS):
        raise ValueError("Unsupported encrypted pairing format")
    salt = base64.b64decode(envelope["salt"], validate=True)
    ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
    if len(salt) != 32 or not 32 <= len(ciphertext) <= 8192:
        raise ValueError("Invalid encrypted pairing size")
    mac = envelope.pop("mac")
    key = hashlib.pbkdf2_hmac("sha256", passcode.encode(), salt, PAIRING_ITERATIONS)
    if not isinstance(mac, str) or not hmac.compare_digest(hmac.new(key, envelope_data(envelope), "sha256").hexdigest(), mac):
        raise ValueError("Incorrect passcode or damaged pairing file")
    config_bytes = openssl_pairing(ciphertext, passcode, decrypt=True)
    if pairing_id(json.loads(config_bytes)) != envelope["key_id"]:
        raise ValueError("Encrypted pairing identity mismatch")
    return config_bytes


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


def install(bundle, directory, config_dir, pairing_file=None, passcode=None):
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
            if name not in ("__main__.py", "pairing/remote.json", "pairing/remote.enc.json") and not install_path(name):
                raise ValueError("Unexpected installer path")
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Installer checksum mismatch")
        config_bytes = archive.read("pairing/remote.json") if "pairing/remote.json" in files else None
        encrypted = json.loads(archive.read("pairing/remote.enc.json")) if "pairing/remote.enc.json" in files else None
        config_path = config_dir / "remote.json"
        if pairing_file is not None:
            supplied = Path(pairing_file).expanduser().read_bytes()
            value = json.loads(supplied)
            if value.get("format") == PAIRING_FORMAT:
                if encrypted is not None and encrypted["key_id"] != value["key_id"]:
                    raise ValueError("Supplied pairing belongs to a different recorder")
                encrypted = value
            else:
                if config_bytes is not None and json.loads(config_bytes).get("key") != value.get("key"):
                    raise ValueError("Supplied pairing does not match the private installer")
                config_bytes = supplied
        if encrypted is not None:
            if config_bytes is not None and pairing_id(json.loads(config_bytes)) != encrypted["key_id"]:
                raise ValueError("Supplied pairing belongs to a different recorder")
            if config_path.exists():
                if pairing_id(json.loads(config_path.read_text())) != encrypted["key_id"]:
                    raise ValueError("This account is paired to a different recorder; use a different --config-dir")
            elif config_bytes is None:
                if passcode is None:
                    passcode = getpass.getpass("Recorder pairing passcode: ")
                config_bytes = decrypt_pairing(encrypted, passcode)
        config = json.loads(config_bytes) if config_bytes is not None else None
        if config is not None and (config.get("version") != 1 or config.get("role") != "remote"
                or len(bytes.fromhex(config["key"])) != 32
                or config.get("state_file") != "remote-state.sqlite3"):
            raise ValueError("Invalid pairing configuration")
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
            if name in ("__main__.py", "pairing/remote.json", "pairing/remote.enc.json"):
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
    parser.add_argument("--pairing", type=Path, help="Optional private or passcode-encrypted recorder pairing file")
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
