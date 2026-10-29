"""Remote laptop: one serial worker and a browser UI bound to localhost only."""

import json
import logging
import math
import queue
import secrets
import sqlite3
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .common import SerialLink
from .protocol import CATALOG_REQUEST, CATALOG_RESPONSE, JSONTransfer, RECORDING_NAME, SPLIT_LIMITS, SYNC_RESPONSE, ZERO, Op, Request, Response, Result, RESULT_TEXT, State, recording_token, split_limits


LOG = logging.getLogger(__name__)
FRESH_SECONDS = 15


def validate_notice(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or value.get("state") not in ("warning", "error")
            or not isinstance(value.get("brief"), str) or not 0 < len(value["brief"]) <= 128
            or ("message" in value and (not isinstance(value["message"], str) or len(value["message"]) > 1024))):
        raise ValueError("Invalid recording warning")
    return {key: value[key] for key in ("state", "brief", "message") if key in value}


class Counter:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY CHECK (id=1), value INTEGER)")
        self.db.execute("INSERT OR IGNORE INTO counter VALUES (1, 0)")
        self.db.commit()

    def next(self):
        with self.db:
            self.db.execute("UPDATE counter SET value=value+1 WHERE id=1")
            return self.db.execute("SELECT value FROM counter WHERE id=1").fetchone()[0]

    def ensure_at_least(self, value):
        if type(value) is not int or not 0 <= value < 2**63 - 1:
            raise ValueError("Invalid Pi command high-water mark")
        with self.db:
            self.db.execute("UPDATE counter SET value=MAX(value, ?) WHERE id=1", (value,))

    def close(self):
        self.db.close()


class Remote:
    def __init__(self, key, state_file, port, poll_seconds=2, timeout=8, attempts=3):
        self.key = key
        self.state_file = state_file
        self.link = SerialLink(port)
        self.poll_seconds = poll_seconds
        self.timeout = timeout
        self.attempts = attempts
        self.lock = threading.RLock()
        self.queue = queue.Queue(maxsize=1)
        self.stopped = threading.Event()
        self.latest = None
        self.received_at = None
        self.pending = None
        self.command = None
        self.error = None
        self.needs_refresh = True
        self.synchronized = False
        self.worker = None
        self.catalog = []
        self.catalog_revision = ZERO
        self.topic_transfer = None
        self.topic_error = None
        self.recordings = []
        self.recordings_health = {}
        self.recordings_revision = ZERO
        self.recordings_total = 0
        self.recordings_offset = 0
        self.recordings_next = None
        self.recordings_loaded = False
        self.recording_info = {}
        self.data_transfer = None
        self.recordings_error = None
        self.delete_target = None
        self.segment_sample = None
        self.completion_target = None
        self.completion_refresh_due = False
        self.completed_recording = None
        self.completed_at = None

    def status(self):
        with self.lock:
            age = None if self.received_at is None else max(0, time.monotonic() - self.received_at)
            online = age is not None and age <= FRESH_SECONDS
            data = self.latest.as_dict() if self.latest else {"state": "unknown"}
            if self.latest and self.segment_sample and self.segment_sample[:2] == (self.latest.boot, self.latest.recording):
                data["segment_count"] = self.segment_sample[2]
            completed_age = None if self.completed_at is None else max(0, time.monotonic() - self.completed_at)
            return {
                "radio_connected": online, "age_seconds": age,
                "synchronized": self.synchronized,
                "status": data, "pending": self.pending, "last_command": self.command,
                "error": self.error, "poll_seconds": self.poll_seconds,
                "fresh_seconds": FRESH_SECONDS,
                "completed_recording": self.completed_recording if completed_age is not None and completed_age < 10 else None,
                "completion_age_seconds": completed_age,
                "completion_pending": self.completion_refresh_due or bool(self.data_transfer and self.data_transfer.get("completion")),
                "topics": self.catalog, "topics_revision": self.catalog_revision.hex(),
                "topics_loading": self.topic_transfer is not None,
                "topics_received_bytes": len(self.topic_transfer["data"]) if self.topic_transfer else 0,
                "topics_total_bytes": self.topic_transfer["total"] if self.topic_transfer else None,
                "topics_error": self.topic_error,
                "recording_management": bool(self.latest and self.latest.flags & 16),
                "splitting_supported": bool(self.latest and self.latest.flags & 32),
                "recordings": self.recordings, "recordings_revision": self.recordings_revision.hex(),
                "recordings_health": self.recordings_health,
                "recordings_total": self.recordings_total, "recordings_next": self.recordings_next,
                "recordings_offset": self.recordings_offset,
                "recordings_loaded": self.recordings_loaded, "recording_info": self.recording_info,
                "recordings_error": self.recordings_error,
                "metadata_loading": self.data_transfer is not None,
                "metadata_name": self.data_transfer["name"] if self.data_transfer else None,
                "metadata_progress": (int(100 * len(self.data_transfer["transfer"].data) / self.data_transfer["transfer"].total)
                                      if self.data_transfer and self.data_transfer["transfer"].total else 0),
                "can_start": online and self.synchronized and not self.needs_refresh and not self.pending
                             and data["state"] == "idle" and data.get("can_start", False),
                "can_stop": online and self.synchronized and not self.needs_refresh and not self.pending
                            and data["state"] in ("starting", "recording"),
            }

    def submit(self, op, selected=None, revision=None, size=None, duration=None):
        with self.lock:
            status = self.status()
            if not status["can_start" if op in (Op.START, Op.START_SELECTED) else "can_stop"]:
                raise ValueError("Wait for fresh status and any pending command before acting")
            data = b""
            if op == Op.START_SELECTED:
                if (self.catalog_revision == ZERO or revision != self.catalog_revision.hex()
                        or self.topic_transfer is not None
                        or not isinstance(selected, list) or not selected
                        or any(type(index) is not int or not 0 <= index < len(self.catalog) for index in selected)):
                    raise ValueError("Refresh topics and select at least one topic before starting")
                mask = sum(1 << index for index in set(selected))
                data = self.catalog_revision + mask.to_bytes(13, "big")
                size, duration = split_limits(size, duration)
                if size or duration:
                    if not status["splitting_supported"]:
                        raise ValueError("Update the Pi LoRa agent before using file splitting")
                    data += SPLIT_LIMITS.pack(size, duration)
            self.pending = "start" if op in (Op.START, Op.START_SELECTED) else "stop"
            self.queue.put_nowait((op, self.latest, data))

    def check_metadata_ready(self):
        status = self.status()
        if (not status["radio_connected"] or not self.synchronized or self.needs_refresh
                or self.pending or self.data_transfer is not None or self.topic_transfer is not None):
            raise ValueError("Wait for fresh radio status and the current request to finish")
        if not status["recording_management"]:
            raise ValueError("Update the Pi LoRa agent before using recording management")

    def refresh_recordings(self, offset=0):
        with self.lock:
            self.check_metadata_ready()
            if type(offset) is not int or not 0 <= offset <= 65535:
                raise ValueError("Invalid recording page")
            self.data_transfer = {"op": Op.RECORDINGS, "selector": offset.to_bytes(2, "big"),
                                  "name": None, "transfer": JSONTransfer()}
            self.recordings_error = None

    def fetch_recording(self, name):
        with self.lock:
            self.check_metadata_ready()
            if not isinstance(name, str) or not RECORDING_NAME.fullmatch(name) or not any(row[0] == name for row in self.recordings):
                raise ValueError("Refresh recordings and choose one from the list")
            self.data_transfer = {"op": Op.BAG_INFO, "selector": name.encode("ascii"),
                                  "name": name, "transfer": JSONTransfer()}
            self.recordings_error = None

    def delete_recording(self, name, revision):
        with self.lock:
            self.check_metadata_ready()
            if (self.latest.state != State.IDLE or not isinstance(name, str)
                    or revision != self.recordings_revision.hex() or self.recordings_revision == ZERO
                    or not any(row[0] == name for row in self.recordings)):
                raise ValueError("Stop recording, refresh recordings and select the bag to delete")
            self.pending, self.delete_target = "delete", name
            self.queue.put_nowait((Op.DELETE, self.latest, self.recordings_revision + recording_token(name)))

    def accept_metadata(self, response):
        transfer = self.data_transfer
        if transfer is None:
            return
        try:
            if response.result != Result.OK:
                raise ValueError(RESULT_TEXT[response.result])
            value = transfer["transfer"].accept(response.data)
            if value is None:
                return
            def number(value):
                return value is None or (type(value) in (int, float) and math.isfinite(value) and value >= 0)
            if not isinstance(value, dict):
                raise ValueError("Invalid recording metadata")
            if transfer["op"] == Op.RECORDINGS:
                rows = value.get("r")
                if (not isinstance(rows, list) or len(rows) > 5 or type(value.get("t")) is not int or value["t"] < 0
                        or (value.get("n") is not None and (type(value["n"]) is not int or not 0 <= value["n"] <= 65535))
                        or any(not isinstance(row, list) or len(row) != 5 or not isinstance(row[0], str)
                               or not RECORDING_NAME.fullmatch(row[0]) or not number(row[1])
                               or (row[2] is not None and (not isinstance(row[2], str) or len(row[2]) > 40))
                               or not number(row[3]) or not number(row[4]) for row in rows)
                        or len({row[0] for row in rows}) != len(rows)):
                    raise ValueError("Invalid recording list")
                health = value.get("h", {})
                if not isinstance(health, dict) or not set(health).issubset({row[0] for row in rows}):
                    raise ValueError("Invalid recording warnings")
                health = {name: validate_notice(notice) for name, notice in health.items()}
                self.recording_info = {name: info for name, info in self.recording_info.items()
                                       if any(row[0] == name for row in rows)
                                       and self.recordings_health.get(name) == health.get(name)}
                self.recordings = rows
                self.recordings_health = health
                self.recordings_revision = transfer["transfer"].revision
                self.recordings_total, self.recordings_next = value["t"], value["n"]
                self.recordings_offset = int.from_bytes(transfer["selector"], "big")
                self.recordings_loaded = True
                finished = next((row for row in rows if row[0] == self.completion_target), None)
                if finished is not None and finished[3] is not None:
                    self.completed_recording = {"name": finished[0], "bag_bytes": finished[1],
                                                "duration_seconds": finished[3], "messages": finished[4]}
                    self.completed_at = time.monotonic()
                    self.completion_target = None
                    self.completion_refresh_due = False
                elif transfer.get("completion"):
                    self.completion_target = None
            else:
                topics = value.get("topics")
                if (not all(number(value.get(field)) for field in ("s", "d", "m"))
                        or not isinstance(topics, list) or len(topics) > 100
                        or any(not isinstance(topic, list) or len(topic) != 3
                               or not isinstance(topic[0], str) or len(topic[0]) > 255 or not topic[0].startswith("/")
                               or not number(topic[1]) or not isinstance(topic[2], str) or len(topic[2]) > 255 for topic in topics)):
                    raise ValueError("Invalid recorded topic details")
                value["h"] = validate_notice(value.get("h"))
                self.recording_info[transfer["name"]] = value
            self.data_transfer = None
        except (ValueError, zlib.error, KeyError, TypeError) as error:
            self.recordings_error = str(error)
            self.data_transfer = None

    def refresh_topics(self):
        with self.lock:
            if not self.status()["radio_connected"] or not self.synchronized or self.pending:
                raise ValueError("Wait for radio status and any pending recording command")
            if self.topic_transfer is not None or self.data_transfer is not None:
                raise ValueError("A topic refresh is already running")
            self.catalog = []
            self.catalog_revision = ZERO
            self.topic_error = None
            self.topic_transfer = {"revision": ZERO, "data": bytearray(), "total": None}

    def accept_topics(self, response):
        transfer = self.topic_transfer
        if transfer is None:
            return
        try:
            if response.result != Result.OK:
                raise ValueError(RESULT_TEXT[response.result])
            if len(response.data) <= CATALOG_RESPONSE.size:
                raise ValueError("Incomplete topic-list reply")
            revision, offset, total = CATALOG_RESPONSE.unpack(response.data[:CATALOG_RESPONSE.size])
            if (not 0 < total <= 30000 or offset != len(transfer["data"])
                    or transfer["revision"] not in (ZERO, revision)
                    or transfer["total"] not in (None, total)):
                raise ValueError("Topic-list chunks do not match; refresh again")
            transfer["revision"], transfer["total"] = revision, total
            transfer["data"].extend(response.data[CATALOG_RESPONSE.size:])
            if len(transfer["data"]) > total:
                raise ValueError("Oversized topic-list reply")
            if len(transfer["data"]) == total:
                inflater = zlib.decompressobj()
                raw = inflater.decompress(transfer["data"], 30001)
                if len(raw) > 30000 or not inflater.eof or inflater.unused_data:
                    raise ValueError("Invalid compressed topic list")
                topics = json.loads(raw)
                if (not isinstance(topics, list) or len(topics) > 100
                        or any(not isinstance(name, str) or len(name) > 255 or not name.startswith("/") for name in topics)):
                    raise ValueError("Invalid topic list")
                self.catalog, self.catalog_revision = topics, revision
                self.topic_transfer = None
        except (ValueError, zlib.error) as error:
            self.topic_error = str(error)
            self.topic_transfer = None

    def accept_snapshot(self, response):
        previous = self.latest
        if previous is not None and previous.boot != response.boot:
            self.completion_target = None
            self.completion_refresh_due = False
            self.completed_recording = None
            self.completed_at = None
            self.segment_sample = None
        elif (previous is not None and previous.name and previous.state in (State.STARTING, State.RECORDING, State.STOPPING)
              and response.state == State.IDLE and response.flags & 16):
            self.completion_target = previous.name
            self.completion_refresh_due = True
            self.completed_recording = None
            self.completed_at = None
        if response.op == Op.STATUS:
            self.segment_sample = (response.boot, response.recording, response.as_dict()["segment_count"])
        if self.latest is not None and self.latest.boot != response.boot and response.op != Op.SYNC:
            self.synchronized = False
        self.latest = response
        self.received_at = time.monotonic()
        self.error = None
        self.needs_refresh = False

    def exchange(self, request):
        frame = request.encode(self.key)
        for attempt in range(self.attempts):
            if self.stopped.is_set():
                return None
            try:
                self.link.send(frame)
                deadline = time.monotonic() + self.timeout
                while not self.stopped.is_set() and time.monotonic() < deadline:
                    for received in self.link.read():
                        try:
                            response = Response.decode(received, self.key)
                        except ValueError:
                            continue
                        if response.number == request.number and response.op == request.op:
                            if request.op == Op.SYNC and (len(response.data) != SYNC_RESPONSE.size
                                    or response.data[:16] != request.data):
                                continue
                            return response
            except Exception as error:
                LOG.warning("Serial attempt %s: %s", attempt + 1, error)
                self.link.close()
            self.stopped.wait(0.4)
        return None

    def _run(self):
        counter = Counter(self.state_file)
        next_poll = 0
        try:
            while not self.stopped.is_set():
                if not self.synchronized:
                    op, snapshot, data = Op.SYNC, None, secrets.token_bytes(16)
                else:
                    try:
                        op, snapshot, data = self.queue.get(timeout=0.1)
                    except queue.Empty:
                        with self.lock:
                            if time.monotonic() >= next_poll:
                                op, snapshot, data = Op.STATUS, None, b""
                            elif self.topic_transfer is not None:
                                op, snapshot = Op.TOPICS, None
                                transfer = self.topic_transfer
                                data = CATALOG_REQUEST.pack(transfer["revision"], len(transfer["data"]))
                            elif self.data_transfer is not None:
                                op, snapshot = self.data_transfer["op"], None
                                data = self.data_transfer["transfer"].request() + self.data_transfer["selector"]
                            elif self.completion_refresh_due and not self.pending:
                                self.completion_refresh_due = False
                                self.data_transfer = {"op": Op.RECORDINGS, "selector": bytes(2), "name": None,
                                                      "transfer": JSONTransfer(), "completion": True}
                                continue
                            else:
                                continue
                request = Request(op, counter.next(), **({
                    "tick": snapshot.tick, "boot": snapshot.boot, "recording": snapshot.recording,
                } if snapshot is not None else {}), data=data)
                response = self.exchange(request)
                with self.lock:
                    sync_error = None
                    if response is not None and op == Op.SYNC:
                        try:
                            if response.result != Result.OK:
                                raise ValueError("Pi rejected radio synchronization")
                            nonce, highest = SYNC_RESPONSE.unpack(response.data)
                            if nonce != data:
                                raise ValueError("Radio synchronization challenge does not match")
                            counter.ensure_at_least(highest)
                            self.synchronized = True
                        except Exception as error:
                            sync_error = str(error)
                            response = None
                    if response is not None:
                        self.accept_snapshot(response)
                    else:
                        self.synchronized = False
                        self.needs_refresh = True
                        self.error = sync_error or "No authenticated reply. Check radio power, settings, or range."
                    if op == Op.TOPICS:
                        if response is not None:
                            self.accept_topics(response)
                        else:
                            self.topic_error = "No topic-list reply; refresh when the radio link is available"
                            self.topic_transfer = None
                    elif op in (Op.RECORDINGS, Op.BAG_INFO):
                        if response is not None:
                            self.accept_metadata(response)
                        else:
                            self.recordings_error = "No recording reply; reconnect and refresh recordings"
                            self.data_transfer = None
                    elif op not in (Op.STATUS, Op.SYNC):
                        result = response.result if response else Result.UNKNOWN
                        action = "delete" if op == Op.DELETE else "start" if op in (Op.START, Op.START_SELECTED) else "stop"
                        self.command = {"id": str(request.number), "action": action, "name": self.delete_target if op == Op.DELETE else None, "result": result.name.lower(),
                                        "message": RESULT_TEXT[result]}
                        self.pending = None
                        self.needs_refresh = response is None
                        if op == Op.DELETE and result == Result.ACCEPTED:
                            if self.completed_recording and self.completed_recording["name"] == self.delete_target:
                                self.completed_recording = None
                                self.completed_at = None
                            self.recording_info.pop(self.delete_target, None)
                            self.recordings_health.pop(self.delete_target, None)
                            self.recordings = [row for row in self.recordings if row[0] != self.delete_target]
                            self.recordings_total = max(0, self.recordings_total - 1)
                            self.data_transfer = {"op": Op.RECORDINGS, "selector": bytes(2), "name": None, "transfer": JSONTransfer()}
                        if result in (Result.OLD_COMMAND, Result.ID_CONFLICT):
                            self.synchronized = False
                            self.needs_refresh = True
                        LOG.info("%s: %s", op.name, RESULT_TEXT[result])
                # Wait after each reply; commands take priority over the next status poll.
                if op == Op.SYNC and response is None:
                    self.stopped.wait(1)
                if op not in (Op.TOPICS, Op.RECORDINGS, Op.BAG_INFO):
                    next_poll = time.monotonic() + (0.5 if op != Op.STATUS else self.poll_seconds)
                elif self.stopped.wait(0.3):
                    break
        finally:
            self.link.close()
            counter.close()

    def start(self):
        self.worker = threading.Thread(target=self._run, name="lora-serial", daemon=True)
        self.worker.start()

    def close(self):
        self.stopped.set()
        if self.worker:
            self.worker.join(timeout=5)


def make_handler(remote, port):
    token = secrets.token_urlsafe(24)
    html = (Path(__file__).parent / "remote.html").read_text().replace("__CONTROL_TOKEN__", token).encode()
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, data, content_type="application/json"):
            payload = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def valid_host(self):
            return self.headers.get("Host") in hosts

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "Open this page using localhost"})
            path = urlsplit(self.path).path
            if path == "/":
                self.reply(200, html, "text/html; charset=utf-8")
            elif path == "/api/status":
                self.reply(200, remote.status())
            else:
                self.reply(404, {"error": "Unknown endpoint"})

        def do_POST(self):
            origin = self.headers.get("Origin")
            if (not self.valid_host() or self.headers.get("X-LoRa-Control") != token
                    or (origin is not None and origin != "http://" + self.headers.get("Host", ""))):
                return self.reply(403, {"error": "Open the local control page before sending commands"})
            if self.path not in ("/api/start", "/api/stop", "/api/topics", "/api/recordings", "/api/recording-info", "/api/delete"):
                return self.reply(404, {"error": "Unknown endpoint"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 2048:
                    raise ValueError("Request too large")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("Expected an object")
                if self.path == "/api/topics":
                    remote.refresh_topics()
                elif self.path == "/api/recordings":
                    remote.refresh_recordings(body.get("offset", 0))
                elif self.path == "/api/recording-info":
                    remote.fetch_recording(body.get("name"))
                elif self.path == "/api/delete":
                    if body.get("confirm") is not True:
                        raise ValueError("Confirm deletion of this recording first")
                    remote.delete_recording(body.get("name"), body.get("revision"))
                elif self.path == "/api/start":
                    if body.get("mode", "selected") != "selected":
                        raise ValueError("Select the topics to record")
                    remote.submit(Op.START_SELECTED, body.get("indices"), body.get("revision"),
                                  body.get("max_bag_size_mib"), body.get("max_bag_duration_seconds"))
                else:
                    remote.submit(Op.STOP)
                self.reply(202, {"queued": True})
            except ValueError as error:
                self.reply(409, {"error": str(error)})

    return Handler


def run_remote(config, key, state_file, port, web_port):
    remote = Remote(key, state_file, port)
    server = ThreadingHTTPServer(("127.0.0.1", web_port), make_handler(remote, web_port))
    server.daemon_threads = True
    remote.start()
    print(f"LoRa remote: http://127.0.0.1:{web_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        remote.close()
