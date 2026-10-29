"""Versioned, authenticated frames small enough for the radio's 230-byte packet.

Base64url avoids newlines and the radio's +++ AT escape sequence. The HMAC
authenticates commands and telemetry, but does not encrypt their contents.
"""

import base64
import hashlib
import hmac
import struct
from dataclasses import dataclass
from enum import IntEnum


VERSION = 2
PREFIX = b"LR2:"
MAX_FRAME = 230
ZERO = bytes(8)
UNKNOWN32 = 2**32 - 1
UNKNOWN64 = 2**64 - 1
REQUEST = struct.Struct("!BBQI8s8s")
RESPONSE = struct.Struct("!BBQBBBIQQQhH8s8sI")
TAG_BYTES = 16
COMMAND_LIFETIME = 30
MAX_PAYLOAD = ((MAX_FRAME - len(PREFIX) - 1) // 4) * 3 - TAG_BYTES
CATALOG_REQUEST = struct.Struct("!8sH")
CATALOG_RESPONSE = struct.Struct("!8sHH")
SYNC_RESPONSE = struct.Struct("!16sQ")


class Op(IntEnum):
    STATUS = 0
    START = 1
    STOP = 2
    TOPICS = 3
    START_SELECTED = 4
    SYNC = 5


class State(IntEnum):
    IDLE = 0
    STARTING = 1
    RECORDING = 2
    STOPPING = 3
    UNAVAILABLE = 4


class Result(IntEnum):
    OK = 0
    ACCEPTED = 1
    ALREADY_RECORDING = 2
    ALREADY_IDLE = 3
    BUSY = 4
    NO_TOPICS = 5
    EXPIRED = 6
    CHANGED_RECORDING = 7
    API_ERROR = 8
    UNKNOWN = 9
    OLD_COMMAND = 10
    ID_CONFLICT = 11
    LOW_STORAGE = 12
    TOO_MANY_TOPICS = 13
    INVALID_TOPICS = 14
    CATALOG_CHANGED = 15


RESULT_TEXT = {
    Result.OK: "Status received",
    Result.ACCEPTED: "Command accepted by recorder",
    Result.ALREADY_RECORDING: "A recording is already running",
    Result.ALREADY_IDLE: "Recorder is already idle",
    Result.BUSY: "Recorder is finishing a bag; wait",
    Result.NO_TOPICS: "No topics available to record",
    Result.EXPIRED: "Command expired or Pi restarted; refresh and try again",
    Result.CHANGED_RECORDING: "Recording changed; refresh before stopping",
    Result.API_ERROR: "Recorder API returned an error; inspect the Pi log",
    Result.UNKNOWN: "Command outcome uncertain; check fresh status before acting",
    Result.OLD_COMMAND: "Old command rejected; synchronizing over LoRa",
    Result.ID_CONFLICT: "Command ID conflict; synchronizing over LoRa",
    Result.LOW_STORAGE: "Not enough free storage to start",
    Result.TOO_MANY_TOPICS: "More than 100 topics; this recorder supports up to 100",
    Result.INVALID_TOPICS: "Topic discovery returned unsupported topic names",
    Result.CATALOG_CHANGED: "Topic list expired or changed; refresh it before starting",
}


def recording_token(name):
    return hashlib.sha256(name.encode("utf-8")).digest()[:8] if name else ZERO


def seal(payload, key):
    tag = hmac.digest(key, payload, "sha256")[:TAG_BYTES]
    frame = PREFIX + base64.urlsafe_b64encode(payload + tag) + b"\n"
    if len(frame) > MAX_FRAME:
        raise ValueError("LoRa frame exceeds packet size")
    return frame


def unseal(frame, key):
    if not frame.startswith(PREFIX) or not frame.endswith(b"\n") or len(frame) > MAX_FRAME:
        raise ValueError("Invalid frame")
    try:
        raw = base64.b64decode(frame[len(PREFIX):-1], altchars=b"-_", validate=True)
    except ValueError as error:
        raise ValueError("Invalid frame encoding") from error
    if len(raw) <= TAG_BYTES:
        raise ValueError("Short frame")
    payload, tag = raw[:-TAG_BYTES], raw[-TAG_BYTES:]
    if not hmac.compare_digest(tag, hmac.digest(key, payload, "sha256")[:TAG_BYTES]):
        raise ValueError("Unauthenticated frame")
    return payload


@dataclass(frozen=True)
class Request:
    op: Op
    number: int
    tick: int = 0
    boot: bytes = ZERO
    recording: bytes = ZERO
    data: bytes = b""

    def payload(self):
        return REQUEST.pack(VERSION, int(self.op), self.number, self.tick, self.boot, self.recording) + self.data

    def encode(self, key):
        return seal(self.payload(), key)

    @classmethod
    def decode(cls, frame, key):
        payload = unseal(frame, key)
        if len(payload) < REQUEST.size:
            raise ValueError("Invalid request length")
        version, op, number, tick, boot, recording = REQUEST.unpack(payload[:REQUEST.size])
        if version != VERSION or not 1 <= number < 2**63:
            raise ValueError("Invalid request version/ID")
        return cls(Op(op), number, tick, boot, recording, payload[REQUEST.size:])


@dataclass(frozen=True)
class Response:
    op: Op
    number: int
    result: Result
    state: State
    flags: int
    elapsed_ms: int
    bag_bytes: int
    free_bytes: int
    total_bytes: int
    temperature_tenths: int
    topic_count: int
    recording: bytes
    boot: bytes
    tick: int
    name: str = ""
    data: bytes = b""

    def encode(self, key):
        name = self.name.encode("ascii")[:48]
        body = RESPONSE.pack(
            VERSION, 128 | int(self.op), self.number, int(self.result), int(self.state), self.flags,
            self.elapsed_ms, self.bag_bytes, self.free_bytes, self.total_bytes,
            self.temperature_tenths, self.topic_count, self.recording, self.boot, self.tick,
        )
        return seal(body + bytes([len(name)]) + name + self.data, key)

    @classmethod
    def decode(cls, frame, key):
        payload = unseal(frame, key)
        if not RESPONSE.size + 1 <= len(payload) <= MAX_PAYLOAD:
            raise ValueError("Invalid response length")
        version, op, *values = RESPONSE.unpack(payload[:RESPONSE.size])
        if version != VERSION or op not in tuple(128 | int(value) for value in Op):
            raise ValueError("Invalid response version/op")
        values[1] = Result(values[1])
        values[2] = State(values[2])
        size = payload[RESPONSE.size]
        if size > 48 or len(payload) < RESPONSE.size + 1 + size:
            raise ValueError("Invalid recording name length")
        offset = RESPONSE.size + 1
        return cls(Op(op & 127), *values, name=payload[offset:offset + size].decode("ascii"),
                   data=payload[offset + size:])

    def as_dict(self):
        return {
            "state": self.state.name.lower(), "name": self.name or None,
            "elapsed_seconds": None if self.elapsed_ms == UNKNOWN32 else self.elapsed_ms / 1000,
            "bag_bytes": None if self.bag_bytes == UNKNOWN64 else self.bag_bytes,
            "free_bytes": None if self.free_bytes == UNKNOWN64 else self.free_bytes,
            "total_bytes": None if self.total_bytes == UNKNOWN64 else self.total_bytes,
            "temperature_c": None if self.temperature_tenths == 32767 else self.temperature_tenths / 10,
            "topic_count": self.topic_count, "storage_warning": bool(self.flags & 1),
            "can_start": bool(self.flags & 2), "last_recording_warning": bool(self.flags & 4),
            "last_recording_error": bool(self.flags & 8),
        }


class Framer:
    """Recover from split reads, noise, and oversized input with bounded memory."""

    def __init__(self):
        self.buffer = bytearray()
        self.overflow = False

    def feed(self, data):
        frames = []
        for byte in data:
            if byte == 10:
                if not self.overflow:
                    frames.append(bytes(self.buffer) + b"\n")
                self.buffer.clear()
                self.overflow = False
            elif not self.overflow:
                self.buffer.append(byte)
                if len(self.buffer) >= MAX_FRAME:
                    self.buffer.clear()
                    self.overflow = True
        return frames
