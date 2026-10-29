"""Serial transport and private pairing configuration."""

import json
import hashlib
import os
import sqlite3
from pathlib import Path

from .protocol import Framer


def write_private(path, value):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_config(path, role):
    path = Path(path).expanduser().resolve()
    if path.stat().st_mode & 0o077:
        raise ValueError(f"Pairing file must be private: chmod 600 {path}")
    config = json.loads(path.read_text())
    if config.get("version") != 1 or config.get("role") != role:
        raise ValueError(f"Expected a version 1 {role} pairing file")
    key = bytes.fromhex(config["key"])
    if len(key) != 32:
        raise ValueError("Pairing key must contain 32 bytes")
    state = Path(config["state_file"]).expanduser()
    if not state.is_absolute():
        state = path.parent / state
    state.parent.mkdir(parents=True, exist_ok=True)
    return config, key, state


def pairing_status(path):
    """Read the Pi's command high-water mark over SSH; never expose its key."""
    _, key, state = load_config(path, "agent")
    highest = 0
    if state.exists():
        with sqlite3.connect(state.as_uri() + "?mode=ro", uri=True) as db:
            highest = db.execute("SELECT MAX(id) FROM commands").fetchone()[0] or 0
    return {"pairing_fingerprint": hashlib.sha256(key).hexdigest(), "last_command": highest}


class SerialLink:
    def __init__(self, path, baud=9600):
        self.path = path
        self.baud = baud
        self.serial = None
        self.framer = Framer()

    def open(self):
        import serial
        self.close()
        self.serial = serial.Serial(
            port=None, baudrate=self.baud, timeout=0.1, write_timeout=2, exclusive=True,
        )
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = self.path
        self.serial.open()
        self.framer = Framer()

    def close(self):
        if self.serial is not None:
            self.serial.close()
            self.serial = None

    def send(self, frame):
        if self.serial is None:
            self.open()
        if self.serial.write(frame) != len(frame):
            raise OSError("Incomplete serial write")
        self.serial.flush()

    def read(self):
        if self.serial is None:
            self.open()
        return self.framer.feed(self.serial.read(512))
