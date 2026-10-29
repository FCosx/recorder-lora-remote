#!/usr/bin/env python3
"""Pair, run the Pi radio agent, or open the remote laptop's control server."""

import argparse
import json
import logging
import os
import secrets
import signal
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))

from lora.common import load_config, pairing_status, write_private


def select_port(value):
    if value:
        return value
    from serial.tools.list_ports import comports
    ports = [port.device for port in comports() if (port.vid, port.pid) == (0x1A86, 0x7523)]
    if len(ports) != 1:
        raise ValueError("Connect one CH340 radio or select it with --port /dev/serial/by-path/...")
    return ports[0]


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair", help="Create a new private Pi/remote pairing; does not access radios")
    pair.add_argument("--directory", type=Path, default=Path.home() / ".config/robot-recorder-lora")
    status = commands.add_parser("pair-status", help="Read pairing fingerprint and last command ID for a new remote installation")
    status.add_argument("--config", type=Path, default=Path.home() / ".config/robot-recorder-lora/pi.json")
    export = commands.add_parser("export-remote", help="Maintainer: export one private pre-paired offline installer")
    export.add_argument("--config", type=Path, default=Path.home() / ".config/robot-recorder-lora/remote.json")
    export.add_argument("--output", type=Path, default=ROOT / "dist/recorder-lora-remote.pyz")
    public = commands.add_parser("build-public", help="Build an installer without pairing keys for public distribution")
    public.add_argument("--output", type=Path, default=ROOT / "dist/recorder-lora-remote-public.pyz")
    for role in ("agent", "remote"):
        command = commands.add_parser(role)
        command.add_argument("--config", type=Path,
                             default=Path.home() / ".config/robot-recorder-lora" / ("pi.json" if role == "agent" else "remote.json"))
        command.add_argument("--port", help="Serial port; auto-detects when exactly one CH340 is connected")
        if role == "remote":
            command.add_argument("--web-port", type=int, default=8081)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "pair":
        directory = args.directory.expanduser()
        pi, remote = directory / "pi.json", directory / "remote.json"
        if pi.exists() or remote.exists():
            parser.error("Pairing files already exist. Preserve them and their state databases; use another directory to create a different pair.")
        key = secrets.token_hex(32)
        write_private(pi, {"version": 1, "role": "agent", "key": key,
                           "api_url": "http://127.0.0.1:8080", "state_file": "pi-state.sqlite3"})
        write_private(remote, {"version": 1, "role": "remote", "key": key, "state_file": "remote-state.sqlite3"})
        print(f"Pair created. Keep these files private.\nPi: {pi}\nRemote laptop: {remote}")
        return

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        if args.command in ("export-remote", "build-public"):
            from lora.bundle import build_bundle
            destination = build_bundle(ROOT, args.config if args.command == "export-remote" else None, args.output)
            if args.command == "export-remote":
                print(f"Private offline installer created: {destination}")
                print("Supply this file with the remote radio. It contains a pairing secret; do not publish it.")
            else:
                print(f"Public installer created without pairing credentials: {destination}")
            return
        if args.command == "pair-status":
            print(json.dumps(pairing_status(args.config)))
            return
        if args.command == "remote" and not args.config.expanduser().exists():
            parser.error("Recorder pairing is missing. Run the downloaded installer with --pairing /path/to/recorder-pairing.json supplied by your recorder maintainer.")
        config, key, state_file = load_config(args.config, args.command)
        port = select_port(args.port)
        if args.command == "agent":
            from lora.agent import run_agent
            run_agent(config, key, state_file, port)
        else:
            from lora.remote import run_remote
            if not 1 <= args.web_port <= 65535:
                parser.error("web port must be between 1 and 65535")
            run_remote(config, key, state_file, port, args.web_port)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        parser.exit(1, f"LoRa setup error: {error}\n")


if __name__ == "__main__":
    main()
