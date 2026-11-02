#!/usr/bin/env python3
"""Short robot-local byte counters and a metadata-only Pi coordinator.

Uses standard ROS messages over the existing bridge; no extra ROS package build.
Only the source role creates sensor subscriptions. Both roles retain counters,
never sensor payloads. Internal topics stay out of the recorder's topic picker.
"""
import argparse
import json
import math
import queue
import secrets
import signal
import sys
import threading
import time

REQUEST = '/_robot_recorder_bandwidth/request'
REPLY = '/_robot_recorder_bandwidth/reply'
MAX_TOPICS = 100
SAMPLE_SECONDS = 1.0
SOURCE_DEADLINE = 1.6
REQUEST_DEADLINE = 2.0


def visible(name):
    return name.startswith('/') and not any(part.startswith('_') for part in name.split('/'))


def decode(text):
    if not isinstance(text, str) or len(text) > 65536:
        raise ValueError('Oversized preview message')
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Invalid preview message')
    return value


class Window:
    """Serialized lengths and monotonic receive times, with no retained payload."""
    def __init__(self):
        self.bytes = self.messages = self.first_bytes = 0
        self.first = self.last = None

    def add(self, size, now):
        if self.first is None:
            self.first, self.first_bytes = now, size
        self.last = now
        self.bytes += size
        self.messages += 1

    def rate(self):
        span = self.last - self.first if self.first is not None else 0
        if self.messages < 3 or span < .1:
            return None
        return (self.bytes - self.first_bytes) / span


class Source:
    """Single-executor state machine. A stop ACK is sent after reader destruction."""
    def __init__(self, send, catalog, subscribe, destroy, clock=time.monotonic):
        self.send, self.catalog, self.subscribe, self.destroy, self.clock = send, catalog, subscribe, destroy, clock
        self.boot = secrets.token_hex(16)
        self.epoch = secrets.token_hex(16)
        self.epochs = {self.epoch: self.clock()+3}
        self.active = None
        self.last = {}
        self.highest = {}
        self.next_presence = 0

    def presence(self):
        now = self.clock()
        self.epochs = {token: end for token, end in self.epochs.items() if end > now}
        self.epoch = secrets.token_hex(16)
        self.epochs[self.epoch] = now+3
        self.send({'op': 'presence', 'source': self.boot, 'epoch': self.epoch})

    def reply(self, request, **value):
        value.update(op=request['op'], client=request['client'], seq=request['seq'],
                     source=self.boot, epoch=self.epoch)
        self.last[request['client']] = value
        self.send(value)

    def close_readers(self):
        sample, self.active = self.active, None
        if sample:
            # A failed destroy prevents an acknowledgment and forces the process
            # to exit; callers must not mistake it for a successful barrier.
            for reader in sample['readers']:
                if self.destroy(reader) is False:
                    raise RuntimeError('Could not destroy temporary sensor subscription')
        return sample

    def handle(self, request):
        if request.get('op') == 'discover':
            self.presence()
            return
        client, seq, op = request.get('client'), request.get('seq'), request.get('op')
        if (request.get('source') != self.boot or not isinstance(client, str) or len(client) != 32
                or type(seq) is not int or not 0 < seq < 2**53 or op not in ('sample', 'stop')):
            return
        highest = self.highest.get(client, 0)
        if seq <= highest:
            old = self.last.get(client)
            if seq == highest and old and old['op'] == op:
                self.send(old)
            return
        # Bound metadata memory; a new client cannot inherit an old epoch.
        if client not in self.highest and len(self.highest) >= 32:
            return
        self.highest[client] = seq
        if op == 'stop':
            sample = self.close_readers()
            self.epoch = secrets.token_hex(16)  # Reject every pre-barrier delayed SAMPLE.
            self.epochs = {self.epoch: self.clock()+3}
            if sample:
                self.reply(sample['request'], closed=True, error='Estimation canceled')
            self.reply(request, closed=True)
            return
        if self.epochs.get(request.get('epoch'), 0) <= self.clock():
            self.reply(request, closed=True, error='Preview generation changed; refresh topics')
            return
        if self.active:
            self.reply(request, closed=False, error='Another preview is active')
            return
        started = self.clock()
        sample = {'request': request, 'started': started, 'first_data': None,
                  'readers': [], 'windows': {}, 'types': {}}
        self.active = sample
        for topic in self.catalog()[:MAX_TOPICS]:
            if self.clock() - started >= SOURCE_DEADLINE:
                break
            name, type_name = topic['name'], topic['type']
            if not visible(name):
                continue
            sample['windows'][name] = Window()
            sample['types'][name] = type_name

            def callback(data, name=name, sample=sample):
                if self.active is not sample:
                    return
                now = self.clock()
                sample['windows'][name].add(len(data), now)
                if sample['first_data'] is None:
                    sample['first_data'] = now

            try:
                reader = self.subscribe(type_name, name, callback)
            except (ImportError, AttributeError, ValueError):
                continue  # Missing robot-side custom definitions leave this rate unknown.
            sample['readers'].append(reader)

    def step(self):
        now = self.clock()
        sample = self.active
        if sample and (now - sample['started'] >= SOURCE_DEADLINE or
                       (sample['first_data'] is not None and now - sample['first_data'] >= SAMPLE_SECONDS)):
            rows = {name: {'type': sample['types'][name], 'bytes_per_second': window.rate(),
                           'messages': window.messages} for name, window in sample['windows'].items()}
            self.close_readers()
            self.reply(sample['request'], closed=True, topics=rows, measured_at=time.time(),
                       sample_seconds=now - sample['started'])
        if now >= self.next_presence:
            self.presence()
            self.next_presence = now + 1


class Coordinator:
    """Pi-side control/metadata only: never subscribes to sensor topics."""
    def __init__(self, send, emit, clock=time.monotonic):
        self.send, self.emit, self.clock = send, emit, clock
        self.client = secrets.token_hex(16)
        self.seq = 0
        self.peers = {}
        self.pending = {}
        self.used_sources = set()
        self.next_discover = 0

    def finish(self, job, **data):
        self.pending.pop(job['seq'], None)
        self.emit(dict(data, id=job['id']))

    def receive(self, value):
        source, epoch = value.get('source'), value.get('epoch')
        if not isinstance(source, str) or len(source) != 32 or not isinstance(epoch, str) or len(epoch) != 32:
            return
        if source not in self.peers and len(self.peers) >= 32:
            return
        self.peers[source] = {'epoch': epoch, 'seen': self.clock()}
        if value.get('client') != self.client:
            return
        seq = value.get('seq')
        job = self.pending.get(seq) if type(seq) is int else None
        if not job or value.get('op') != job['op'] or source not in job['targets']:
            return
        if job['op'] == 'sample':
            if value.get('closed') is True and not value.get('error') and isinstance(value.get('topics'), dict):
                self.used_sources.discard(source)
            self.finish(job, **{k: value.get(k) for k in ('closed', 'topics', 'measured_at', 'error', 'sample_seconds')})
        elif value.get('closed') is True:
            job['targets'].remove(source)
            if not job['targets']:
                self.used_sources.clear()
                self.finish(job, closed=True)

    def command(self, value):
        op, identity = value.get('op'), value.get('id')
        if op not in ('sample', 'stop') or not isinstance(identity, str):
            return
        fresh = {source for source, peer in self.peers.items() if self.clock() - peer['seen'] < 4}
        if op == 'sample':
            if self.clock() >= value.get('expires', self.clock()+REQUEST_DEADLINE):
                self.emit({'id': identity, 'closed': not self.used_sources, 'error': 'Rate snapshot timed out'})
                return
            if len(fresh) != 1:
                self.emit({'id': identity, 'closed': not self.used_sources,
                           'error': 'Robot rate helper unavailable' if not fresh else 'Multiple robot rate helpers detected'})
                return
            targets = fresh
            self.used_sources.update(targets)
        else:
            # Cancel locally queued samples before sending the remote barrier.
            for job in list(self.pending.values()):
                if job['op'] == 'sample':
                    self.finish(job, closed=False, error='Estimation canceled')
            targets = fresh | self.used_sources
            if not targets:
                self.emit({'id': identity, 'closed': True})
                return
        self.seq += 1
        job = {'seq': self.seq, 'id': identity, 'op': op, 'targets': set(targets),
               'deadline': min(self.clock()+REQUEST_DEADLINE, value.get('expires', self.clock()+REQUEST_DEADLINE)) if op == 'sample' else self.clock()+2.5}
        self.pending[self.seq] = job
        for source in targets:
            self.send({'op': op, 'client': self.client, 'seq': self.seq, 'source': source,
                       'epoch': self.peers.get(source, {}).get('epoch')})

    def step(self):
        now = self.clock()
        for job in list(self.pending.values()):
            if now >= job['deadline']:
                self.finish(job, closed=False, error='Robot rate helper did not confirm stopping' if job['op'] == 'stop'
                            else 'Rate snapshot timed out')
        if now >= self.next_discover:
            self.send({'op': 'discover'})
            self.next_discover = now + 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=('source', 'coordinator'), required=True)
    parser.add_argument('--domain', type=int, required=True)
    args = parser.parse_args()
    import rclpy
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from rosidl_runtime_py.utilities import get_message
    from std_msgs.msg import String

    context = Context()
    context.init(args=['--ros-args', '-r', f'__node:=_recorder_bandwidth_{args.role}'], initialize_logging=False,
                 domain_id=args.domain)
    node = rclpy.create_node('_recorder_bandwidth_' + args.role, context=context,
                             enable_rosout=False, start_parameter_services=False)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(node)
    control = QoSProfile(depth=16, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
    reports = QoSProfile(depth=16, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
    sensor = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                        durability=DurabilityPolicy.VOLATILE)
    source = args.role == 'source'
    publisher = node.create_publisher(String, REPLY if source else REQUEST, reports if source else control)

    def send(value):
        message = String();message.data = json.dumps(value, separators=(',', ':'))
        publisher.publish(message)

    def emit(value):
        print(json.dumps(value, separators=(',', ':')), flush=True)

    def catalog():
        return [{'name': name, 'type': types[0]} for name, types in sorted(node.get_topic_names_and_types())
                if visible(name) and len(types) == 1 and node.count_publishers(name) > 0][:MAX_TOPICS]

    state = Source(send, catalog, lambda type_name, name, cb: node.create_subscription(
        get_message(type_name), name, cb, sensor, raw=True), node.destroy_subscription) if source else Coordinator(send, emit)

    def receive(message):
        try:
            value = decode(message.data)
        except (ValueError, TypeError):
            return
        if source:
            state.handle(value)
        else:
            state.receive(value)

    node.create_subscription(String, REQUEST if source else REPLY, receive, control if source else reports)
    inbox = queue.Queue(maxsize=16)
    closed = threading.Event()
    if not source:
        def read_commands():
            try:
                while True:
                    line = sys.stdin.readline(65537)
                    if not line:
                        break
                    inbox.put(decode(line))
            except Exception:
                pass
            finally:
                closed.set()
        threading.Thread(target=read_commands, daemon=True).start()
        emit({'ready': True})
    try:
        while context.ok() and not closed.is_set():
            if not source:
                for _ in range(16):
                    try:
                        value = inbox.get_nowait()
                    except queue.Empty:
                        break
                    if value.get('op') == 'catalog':
                        emit({'id': value.get('id'), 'topics': catalog()})
                    else:
                        state.command(value)
            executor.spin_once(timeout_sec=.005)
            state.step()
    finally:
        if source:
            state.close_readers()
        executor.shutdown()
        node.destroy_node()
        context.shutdown()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    main()
