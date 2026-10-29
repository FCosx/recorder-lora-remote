"""Pi-side command handler. All recording operations use the local HTTP API."""

import json
import logging
import math
import re
import secrets
import sqlite3
import time
import zlib
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request as HTTPRequest, build_opener

from .common import SerialLink
from .protocol import (
    CATALOG_REQUEST, CATALOG_RESPONSE, COMMAND_LIFETIME, MAX_PAYLOAD, RESPONSE,
    RECORDING_NAME, SPLIT_LIMITS, SYNC_RESPONSE, UNKNOWN32, UNKNOWN64, ZERO, Op, Request, Response, Result, State, recording_token, split_limits,
)


LOG = logging.getLogger(__name__)
TOPIC = re.compile(r"/[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*\Z")


class APIRejected(Exception):
    pass


class RecorderAPI:
    def __init__(self, base="http://127.0.0.1:8080"):
        parts = urlsplit(base)
        if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("The Pi agent must use its local recorder API")
        self.base = base.rstrip("/")
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, body=None, timeout=3):
        data = None if body is None else json.dumps(body).encode()
        request = HTTPRequest(self.base + path, data=data,
                              headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                result = json.load(response)
                if not isinstance(result, dict):
                    raise ValueError("Invalid recorder API response")
                return result
        except HTTPError as error:
            detail = error.read(1024).decode(errors="replace")
            if 400 <= error.code < 500:
                raise APIRejected(f"HTTP {error.code}: {detail}") from error
            raise OSError(f"HTTP {error.code}: {detail}") from error

    def status(self):
        status = self.request("/api/status")
        if status.get("state") not in ("idle", "recording", "stopping"):
            raise ValueError("Unrecognized recorder state")
        return status

    def topics(self):
        return self.request("/api/topics", timeout=20)["topics"]

    def start(self, topics, size=0, duration=0):
        size, duration = split_limits(size, duration)
        body = {"topics": topics}
        if size or duration:
            body.update(max_bag_size_mib=size, max_bag_duration_seconds=duration)
        return self.request("/api/start", body, timeout=5)

    def stop(self, name):
        return self.request("/api/stop", {"expected_name": name, "wait": False}, timeout=5)

    def recordings(self, offset):
        return self.request(f"/api/recording-summaries?offset={offset}", timeout=5)

    def recording_info(self, name):
        if not RECORDING_NAME.fullmatch(name):
            raise ValueError("Invalid recording name")
        return self.request(f"/api/recordings/{name}/info?compact=1", timeout=5)

    def delete(self, name):
        if not RECORDING_NAME.fullmatch(name):
            raise ValueError("Invalid recording name")
        return self.request(f"/api/recordings/{name}/delete", {"name": name}, timeout=5)


class Journal:
    """Persist the intent BEFORE executing: retries never repeat an API action.

    A crash between writing intent and saving its result has an UNKNOWN outcome.
    It is deliberately not retried against the recorder after a service restart.
    """

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS commands (id INTEGER PRIMARY KEY, body BLOB, result INTEGER)")
        self.db.commit()

    def begin(self, request):
        old = self.db.execute("SELECT body, result FROM commands WHERE id=?", (request.number,)).fetchone()
        if old is not None:
            return Result(old[1]) if bytes(old[0]) == request.payload() else Result.ID_CONFLICT
        highest = self.highest()
        if request.number <= highest:
            return Result.OLD_COMMAND
        self.db.execute("INSERT INTO commands VALUES (?, ?, ?)",
                        (request.number, request.payload(), int(Result.UNKNOWN)))
        self.db.commit()
        return None

    def highest(self):
        return self.db.execute("SELECT MAX(id) FROM commands").fetchone()[0] or 0

    def finish(self, number, result):
        self.db.execute("UPDATE commands SET result=? WHERE id=?", (int(result), number))
        # Bound storage while retaining a high-water command ID and recent replies.
        self.db.execute("DELETE FROM commands WHERE id NOT IN (SELECT id FROM commands ORDER BY id DESC LIMIT 256)")
        self.db.commit()

    def close(self):
        self.db.close()


def unsigned(value, maximum):
    if value is None:
        return maximum
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return maximum
    return min(maximum - 1, int(number))


class Agent:
    def __init__(self, api, journal, clock=time.monotonic, temperature_path="/sys/class/thermal/thermal_zone0/temp"):
        self.api = api
        self.journal = journal
        self.clock = clock
        self.boot = secrets.token_bytes(8)
        self.temperature_path = Path(temperature_path)
        self.catalog = None
        self.catalog_request_id = None
        self.recording_transfers = {}

    def recording_response(self, request):
        if len(request.data) < CATALOG_REQUEST.size:
            return self.snapshot(request, Result.INVALID_RECORDING)
        revision, offset = CATALOG_REQUEST.unpack(request.data[:CATALOG_REQUEST.size])
        selector = request.data[CATALOG_REQUEST.size:]
        cached = self.recording_transfers.get(request.op)
        if revision == ZERO and offset == 0:
            if cached is None or cached["request_id"] != request.number:
                if request.op == Op.RECORDINGS:
                    if len(selector) != 2:
                        return self.snapshot(request, Result.INVALID_RECORDING)
                    page = self.api.recordings(int.from_bytes(selector, "big"))
                    rows = [row for row in page["recordings"] if RECORDING_NAME.fullmatch(row["name"])]
                    value = {"r": [[row["name"], row["bytes"], row["started_at"], row["duration_seconds"],
                                     row["total_messages"]] for row in rows],
                             "h": {row["name"]: row["health"] for row in rows if row.get("health")},
                             "t": page["total"], "n": page["next_offset"]}
                else:
                    name = selector.decode("ascii")
                    if not RECORDING_NAME.fullmatch(name):
                        return self.snapshot(request, Result.INVALID_RECORDING)
                    info = self.api.recording_info(name)
                    value = {"s": info["bag_size_bytes"], "d": info["duration_seconds"], "m": info["total_messages"],
                             "h": info.get("health"),
                             "topics": [[topic["name"], topic["messages"], topic["type"]] for topic in info["topics"]]}
                raw = json.dumps(value, separators=(",", ":")).encode()
                packed = zlib.compress(raw)
                if len(raw) > 30000 or len(packed) > 30000:
                    return self.snapshot(request, Result.TOO_LARGE)
                cached = {"request_id": request.number, "revision": secrets.token_bytes(8),
                          "selector": selector, "packed": packed, "value": value, "created": self.clock()}
                self.recording_transfers[request.op] = cached
        if (cached is None or cached["selector"] != selector or revision not in (ZERO, cached["revision"])
                or self.clock() - cached["created"] > 3600 or offset >= len(cached["packed"])):
            return self.snapshot(request, Result.INVALID_RECORDING)
        response = self.snapshot(request, Result.OK)
        room = MAX_PAYLOAD - RESPONSE.size - 1 - len(response.name.encode("ascii")[:48]) - CATALOG_RESPONSE.size
        return replace(response, data=CATALOG_RESPONSE.pack(cached["revision"], offset, len(cached["packed"]))
                       + cached["packed"][offset:offset + room])

    def discover(self):
        topics = list(dict.fromkeys(item["name"] for item in self.api.topics()))
        if len(topics) > 100:
            return Result.TOO_MANY_TOPICS, []
        if any(not isinstance(name, str) or len(name) > 255 or not TOPIC.fullmatch(name) for name in topics):
            return Result.INVALID_TOPICS, []
        return Result.OK, topics

    def topics_response(self, request):
        if len(request.data) != CATALOG_REQUEST.size:
            return self.snapshot(request, Result.INVALID_TOPICS)
        revision, offset = CATALOG_REQUEST.unpack(request.data)
        if revision == ZERO and offset == 0:
            if self.catalog_request_id != request.number or self.catalog is None:
                result, topics = self.discover()
                if result != Result.OK:
                    return self.snapshot(request, result)
                packed = zlib.compress(json.dumps(topics, separators=(",", ":")).encode())
                self.catalog = {"revision": secrets.token_bytes(8), "topics": topics,
                                "packed": packed, "created": self.clock()}
                self.catalog_request_id = request.number
        elif self.catalog is None or revision != self.catalog["revision"]:
            return self.snapshot(request, Result.CATALOG_CHANGED)
        packed = self.catalog["packed"]
        if offset >= len(packed):
            return self.snapshot(request, Result.INVALID_TOPICS)
        response = self.snapshot(request, Result.OK)
        room = MAX_PAYLOAD - RESPONSE.size - 1 - len(response.name.encode("ascii")[:48]) - CATALOG_RESPONSE.size
        data = CATALOG_RESPONSE.pack(self.catalog["revision"], offset, len(packed)) + packed[offset:offset + room]
        return replace(response, data=data)

    def fresh(self, request):
        return request.boot == self.boot and 0 <= int(self.clock()) - request.tick <= COMMAND_LIFETIME

    def execute(self, request):
        if not self.fresh(request):
            return Result.EXPIRED
        status = self.api.status()
        if request.op in (Op.START, Op.START_SELECTED):
            size, duration = 0, 0
            if status["state"] == "stopping":
                return Result.BUSY
            if status["state"] != "idle":
                return Result.ALREADY_RECORDING
            if not status.get("can_start", False):
                return Result.LOW_STORAGE
            if request.recording != recording_token(status.get("name")):
                return Result.CHANGED_RECORDING
            if request.op == Op.START_SELECTED:
                if len(request.data) not in (21, 21 + SPLIT_LIMITS.size):
                    return Result.INVALID_SPLIT
                if (self.catalog is None
                        or request.data[:8] != self.catalog["revision"]
                        or self.clock() - self.catalog["created"] > 3600):
                    return Result.CATALOG_CHANGED
                if len(request.data) > 21:
                    try:
                        size, duration = split_limits(*SPLIT_LIMITS.unpack(request.data[21:]))
                    except ValueError:
                        return Result.INVALID_SPLIT
                mask = int.from_bytes(request.data[8:21], "big")
                if mask == 0 or mask >> len(self.catalog["topics"]):
                    return Result.INVALID_TOPICS
                topics = [name for index, name in enumerate(self.catalog["topics"]) if mask & (1 << index)]
            else:
                result, topics = self.discover()
                if result != Result.OK:
                    return result
            if not topics:
                return Result.NO_TOPICS
            # Topic discovery can take seconds; never execute a now-expired Start.
            if not self.fresh(request):
                return Result.EXPIRED
            if size or duration:
                self.api.start(topics, size, duration)
            else:
                self.api.start(topics)
        elif request.op == Op.STOP:
            if status["state"] == "idle":
                return Result.ALREADY_IDLE
            if request.recording != recording_token(status.get("name")):
                return Result.CHANGED_RECORDING
            if status["state"] == "stopping":
                return Result.BUSY
            if not self.fresh(request):
                return Result.EXPIRED
            self.api.stop(status["name"])
        elif request.op == Op.DELETE:
            if status["state"] != "idle":
                return Result.BUSY
            cached = self.recording_transfers.get(Op.RECORDINGS)
            if (len(request.data) != 16 or cached is None or request.data[:8] != cached["revision"]
                    or self.clock() - cached["created"] > 3600):
                return Result.INVALID_RECORDING
            name = next((row[0] for row in cached["value"]["r"] if recording_token(row[0]) == request.data[8:]), None)
            if name is None or not self.fresh(request):
                return Result.INVALID_RECORDING
            self.api.delete(name)
        return Result.ACCEPTED

    def snapshot(self, request, result):
        try:
            status = self.api.status()
            state = {"idle": State.IDLE, "recording": State.RECORDING, "stopping": State.STOPPING}[status["state"]]
            if state == State.RECORDING and status.get("elapsed_seconds") is None:
                state = State.STARTING
        except Exception:
            status = {}
            state = State.UNAVAILABLE
        flags = 16 | 32 | int(bool(status.get("storage_warning"))) | (int(bool(status.get("can_start"))) << 1)
        health = status.get("last_result") or {}
        flags |= int(health.get("state") == "warning") << 2
        flags |= int(health.get("state") == "error") << 3
        try:
            temperature = int(round(float(self.temperature_path.read_text().strip()) / 100))
            if not -32768 <= temperature < 32767:
                temperature = 32767
        except (OSError, ValueError):
            temperature = 32767
        elapsed = status.get("elapsed_seconds")
        return Response(
            request.op, request.number, result, state, flags,
            unsigned(None if elapsed is None else elapsed * 1000, UNKNOWN32),
            unsigned(status.get("bag_bytes"), UNKNOWN64),
            unsigned(status.get("free_bytes"), UNKNOWN64),
            unsigned(status.get("total_bytes"), UNKNOWN64),
            temperature, min(65535, len(status.get("topics", []))),
            recording_token(status.get("name")), self.boot, int(self.clock()),
            status.get("name") or "",
        )

    def handle(self, request):
        if request.op == Op.SYNC:
            if len(request.data) != 16:
                return self.snapshot(request, Result.INVALID_TOPICS)
            response = self.snapshot(request, Result.OK)
            return replace(response, data=SYNC_RESPONSE.pack(request.data, self.journal.highest()))
        if request.op == Op.TOPICS:
            try:
                return self.topics_response(request)
            except Exception:
                LOG.exception("Topic discovery failed")
                return self.snapshot(request, Result.API_ERROR)
        if request.op in (Op.RECORDINGS, Op.BAG_INFO):
            try:
                return self.recording_response(request)
            except APIRejected:
                return self.snapshot(request, Result.NOT_FOUND)
            except Exception:
                LOG.exception("Recording metadata failed")
                return self.snapshot(request, Result.API_ERROR)
        result = Result.OK
        if request.op != Op.STATUS:
            result = self.journal.begin(request)
            if result is None:
                try:
                    result = self.execute(request)
                except APIRejected as error:
                    LOG.warning("Recorder rejected command %s: %s", request.number, error)
                    result = Result.API_ERROR
                except Exception:
                    LOG.exception("Uncertain outcome for command %s", request.number)
                    result = Result.UNKNOWN
                self.journal.finish(request.number, result)
                LOG.info("Command %s %s: %s", request.number, request.op.name, result.name)
        return self.snapshot(request, result)


def run_agent(config, key, state_file, port):
    journal = Journal(state_file)
    agent = Agent(RecorderAPI(config.get("api_url", "http://127.0.0.1:8080")), journal)
    link = SerialLink(port)
    LOG.info("Pi LoRa agent on %s; commands do not stop recording when radio contact is lost", port)
    try:
        while True:
            try:
                for frame in link.read():
                    try:
                        request = Request.decode(frame, key)
                    except ValueError:
                        continue
                    response = agent.handle(request)
                    # Give the half-duplex radio time to finish its receive phase.
                    time.sleep(0.3)
                    link.send(response.encode(key))
            except Exception as error:
                # Reopen after USB unplug/replug without changing recorder state.
                LOG.warning("Serial link unavailable: %s", error)
                link.close()
                time.sleep(3)
    finally:
        link.close()
        journal.close()
