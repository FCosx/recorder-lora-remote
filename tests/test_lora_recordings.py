"""Recording management over small authenticated radio frames; no real bags deleted."""
import copy
import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from lora.agent import Agent, Journal
from lora.protocol import CATALOG_REQUEST, JSONTransfer, MAX_FRAME, Op, Request, Result, ZERO, recording_token
from lora.remote import Remote

KEY = bytes(range(32))


class SavedAPI:
    def __init__(self):
        self.value = {'state': 'idle', 'name': None, 'topics': [], 'can_start': True}
        self.rows = [{'name': f'recording-20261029-12000{i}', 'bytes': 2048+i, 'started_at': '2026-10-29T12:00:00',
                      'duration_seconds': 10.5, 'total_messages': 21} for i in range(7)]
        self.deleted = []
        self.lose_delete = False
        self.detail_health = {}
        self.topic_rows = [{'name': '/sensor_'+secrets.token_hex(25), 'messages': 21, 'type': 'sensor_msgs/msg/Image'} for _ in range(70)]

    def status(self):
        return copy.deepcopy(self.value)

    def recordings(self, offset):
        return {'recordings': self.rows[offset:offset+5], 'total': len(self.rows),
                'next_offset': offset+5 if offset+5 < len(self.rows) else None}

    def recording_info(self, name):
        return {'bag_size_bytes': 2048, 'duration_seconds': 10.5, 'total_messages': 1470, 'topics': self.topic_rows,
                'health': self.detail_health.get(name)}

    def delete(self, name):
        self.deleted.append(name)
        self.rows = [row for row in self.rows if row['name'] != name]
        if self.lose_delete:
            raise TimeoutError('Delete accepted but API reply lost')


class RecordingRadioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = SavedAPI()
        self.journal = Journal(Path(self.temp.name)/'pi.db')
        self.addCleanup(self.journal.close)
        self.agent = Agent(self.api, self.journal, lambda: 1000)
        self.remote = Remote(KEY, Path(self.temp.name)/'remote.db', 'unused')
        self.remote.latest = self.agent.handle(Request(Op.STATUS, 1))
        self.remote.received_at = time.monotonic()
        self.remote.synchronized = True
        self.remote.needs_refresh = False
        self.number = 10

    def fetch(self, op=Op.RECORDINGS, selector=bytes(2)):
        transfer = JSONTransfer()
        self.remote.data_transfer = {'op': op, 'selector': selector, 'name': selector.decode() if op==Op.BAG_INFO else None, 'transfer': transfer}
        first = None
        for _ in range(1000):
            self.number += 1
            request = Request(op, self.number, data=transfer.request()+selector)
            response = self.agent.handle(request)
            self.assertEqual(response.result, Result.OK)
            self.assertLessEqual(len(response.encode(KEY)), MAX_FRAME)
            self.assertLessEqual(len(request.encode(KEY)), MAX_FRAME)
            if first is None:
                first = response.data
                self.assertEqual(self.agent.handle(request).data, first, 'Retry must not rebuild first chunk')
            self.remote.accept_metadata(response)
            self.assertIsNone(self.remote.recordings_error)
            if self.remote.data_transfer is None:
                return
        self.fail('Transfer did not finish')

    def deletion(self, data=None, number=None, **kwargs):
        self.number += 1
        return Request(Op.DELETE, number or self.number, tick=1000, boot=self.agent.boot,
                       data=data or self.remote.recordings_revision+recording_token(self.api.rows[0]['name']), **kwargs)

    def test_pages_and_large_topic_details_fit_frames_and_keep_counts(self):
        self.fetch()
        self.assertEqual(len(self.remote.recordings), 5)
        self.assertEqual(self.remote.recordings_next, 5)
        self.assertEqual(self.remote.recordings_total, 7)
        name = self.remote.recordings[0][0]
        self.fetch(Op.BAG_INFO, name.encode())
        info = self.remote.recording_info[name]
        self.assertEqual(info['m'], 1470)
        self.assertEqual(len(info['topics']), 70)
        self.assertEqual(info['topics'][0][1:], [21, 'sensor_msgs/msg/Image'])
        self.fetch(selector=(5).to_bytes(2, 'big'))
        self.assertEqual(self.remote.recordings_offset, 5)
        self.assertEqual(len(self.remote.recordings), 2)
        self.assertIsNone(self.remote.recordings_next)

    def test_warning_error_and_full_details_survive_radio_without_changing_row_format(self):
        name = self.api.rows[0]['name']
        warning = {'state':'warning','brief':'Warning: No messages on /imu'}
        error = {'state':'error','brief':'Error: Recorder exited with code 1'}
        self.api.rows[0]['health'] = warning
        self.api.rows[1]['health'] = error
        self.detail_health = dict(warning, message='No messages recorded for: /imu')
        self.api.detail_health[name] = self.detail_health
        self.fetch()
        self.assertTrue(all(len(row) == 5 for row in self.remote.recordings))
        self.assertEqual(self.remote.status()['recordings_health'][name], warning)
        self.assertEqual(self.remote.recordings_health[self.api.rows[1]['name']], error)
        self.assertNotIn(self.api.rows[2]['name'], self.remote.recordings_health)
        self.fetch(Op.BAG_INFO, name.encode())
        self.assertEqual(self.remote.recording_info[name]['h'], self.detail_health)
        self.api.rows[0]['health'] = None
        self.fetch()
        self.assertNotIn(name, self.remote.recordings_health)
        self.assertNotIn(name, self.remote.recording_info, 'Do not retain old warning details after a refreshed summary changes')

    def test_malformed_warning_is_rejected(self):
        self.api.rows[0]['health'] = {'state':'warning','brief':'x'*129}
        transfer = JSONTransfer()
        self.remote.data_transfer = {'op':Op.RECORDINGS,'selector':bytes(2),'name':None,'transfer':transfer}
        for number in range(200,1000):
            response = self.agent.handle(Request(Op.RECORDINGS,number,data=transfer.request()+bytes(2)))
            self.remote.accept_metadata(response)
            if self.remote.data_transfer is None: break
        self.assertIn('warning', self.remote.recordings_error)
        self.assertFalse(self.remote.recordings_loaded)

    def test_confirmed_delete_only_targets_loaded_recording_and_retry_is_idempotent(self):
        self.fetch()
        name = self.api.rows[0]['name']
        request = self.deletion()
        self.assertEqual(self.agent.handle(request).result, Result.ACCEPTED)
        self.assertEqual(self.agent.handle(request).result, Result.ACCEPTED)
        self.assertEqual(self.api.deleted, [name])
        self.assertEqual(len(self.api.rows), 6)

    def test_delete_refuses_busy_expired_restarted_and_unlisted_targets(self):
        self.fetch()
        self.api.value['state'] = 'recording'
        self.assertEqual(self.agent.handle(self.deletion()).result, Result.BUSY)
        self.api.value['state'] = 'idle'
        request = self.deletion()
        from dataclasses import replace
        self.assertEqual(self.agent.handle(replace(request, tick=900)).result, Result.EXPIRED)
        self.assertEqual(self.agent.handle(replace(self.deletion(), boot=b'old-boot')).result, Result.EXPIRED)
        self.assertEqual(self.agent.handle(self.deletion(data=self.remote.recordings_revision+recording_token('../private'))).result, Result.INVALID_RECORDING)
        self.assertEqual(self.agent.handle(self.deletion(data=b'old-rev!'+recording_token(self.api.rows[0]['name']))).result, Result.INVALID_RECORDING)
        self.assertFalse(self.api.deleted)

    def test_uncertain_delete_is_never_reexecuted_even_after_agent_restart(self):
        self.fetch()
        self.api.lose_delete = True
        request = self.deletion()
        with self.assertLogs('lora.agent', level='ERROR'):
            self.assertEqual(self.agent.handle(request).result, Result.UNKNOWN)
        restarted = Agent(self.api, self.journal, lambda: 1000)
        self.assertEqual(restarted.handle(request).result, Result.UNKNOWN)
        self.assertEqual(len(self.api.deleted), 1)

    def test_remote_delete_requires_fresh_idle_and_matching_list_revision(self):
        self.fetch()
        name = self.remote.recordings[0][0]
        with self.assertRaises(ValueError): self.remote.delete_recording(name, '0000000000000000')
        with self.assertRaises(ValueError): self.remote.delete_recording('../elsewhere', self.remote.recordings_revision.hex())
        self.remote.received_at -= 20
        with self.assertRaises(ValueError): self.remote.delete_recording(name, self.remote.recordings_revision.hex())
        self.remote.received_at = time.monotonic()
        self.remote.delete_recording(name, self.remote.recordings_revision.hex())
        op, _, payload = self.remote.queue.get_nowait()
        self.assertEqual(op, Op.DELETE)
        self.assertEqual(payload, self.remote.recordings_revision+recording_token(name))

    def test_changed_revision_and_truncated_compressed_data_are_rejected(self):
        self.remote.refresh_recordings()
        response = self.agent.handle(Request(Op.RECORDINGS, 100, data=CATALOG_REQUEST.pack(ZERO, 0)+bytes(2)))
        self.remote.accept_metadata(response)
        if self.remote.data_transfer is not None:
            from dataclasses import replace
            damaged = replace(response, data=b'wrongrev'+response.data[8:])
            self.remote.accept_metadata(damaged)
            self.assertIsNotNone(self.remote.recordings_error)
        with self.assertRaises(ValueError): self.remote.fetch_recording('../etc/passwd')

    def test_browser_requires_delete_confirmation_and_rejects_record_all_and_download(self):
        from lora.remote import make_handler
        from http.server import ThreadingHTTPServer
        from urllib.request import Request as HTTPRequest, urlopen
        from urllib.error import HTTPError
        import re, threading
        self.fetch()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Mock())
        server.RequestHandlerClass = make_handler(self.remote, server.server_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base) as response:
                html = response.read().decode()
            token = re.search(r"'X-LoRa-Control':'([^']+)'", html).group(1)
            headers = {'X-LoRa-Control': token, 'Content-Type': 'application/json'}
            for path, body in [('/api/start', {'mode':'all'}),
                               ('/api/delete', {'name':self.remote.recordings[0][0], 'revision':self.remote.recordings_revision.hex()})]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(HTTPRequest(base+path, data=json.dumps(body).encode(), headers=headers))
                self.assertEqual(error.exception.code,409)
            with self.assertRaises(HTTPError) as error:
                urlopen(base+'/api/recordings/recording-0/download')
            self.assertEqual(error.exception.code,404)
            self.assertTrue(self.remote.queue.empty())
        finally:
            server.shutdown(); server.server_close(); thread.join()


class RecorderMetadataAPITests(unittest.TestCase):
    def test_paginated_preview_compact_info_and_delete_use_only_temporary_bags(self):
        try:
            import app
        except ImportError:
            self.skipTest('Pi recorder backend is not part of the standalone remote repository')
        from types import SimpleNamespace
        from lora.agent import RecorderAPI
        from http.server import ThreadingHTTPServer
        import threading
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i in range(7):
                bag = root/f'recording-{i}'
                bag.mkdir(); (bag/'metadata.yaml').write_text('test-only')
                (bag/'recording_0.mcap').write_bytes(bytes(2048))
            health = {'state':'warning','message':'No messages recorded for: /imu','topics':[{'name':'/imu','messages':0}]}
            for i in (0,6):
                (root/f'recording-{i}'/app.HEALTH_FILE).write_text(json.dumps(health))
            metadata = SimpleNamespace(starting_time=SimpleNamespace(nanoseconds=1793260800000000000),
                duration=SimpleNamespace(nanoseconds=10500000000), message_count=21,
                topics_with_message_count=[SimpleNamespace(topic_metadata=SimpleNamespace(name='/camera',type='sensor_msgs/msg/Image'),message_count=21)])
            ros = SimpleNamespace(MetadataIo=lambda:SimpleNamespace(read_metadata=lambda _:metadata))
            class Quiet(app.Handler):
                def log_message(self,*args): pass
            recorder = app.Recorder()
            with patch.object(app,'RECORDINGS',root), patch.object(app,'LOGS',root/'logs'), patch.object(app,'RECORDER',recorder), patch.dict('sys.modules',{'rosbag2_py':ros}), patch.object(app.subprocess,'run') as process:
                server = ThreadingHTTPServer(('127.0.0.1',0),Quiet)
                thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    api = RecorderAPI(f'http://127.0.0.1:{server.server_port}')
                    page = api.recordings(0)
                    self.assertEqual(len(page['recordings']),5)
                    self.assertEqual(page['next_offset'],5)
                    self.assertEqual(page['recordings'][0]['duration_seconds'],10.5)
                    self.assertIsNotNone(page['recordings'][0]['started_at'])
                    self.assertEqual(page['recordings'][0]['health']['brief'],'Warning: No messages on /imu')
                    self.assertNotIn('message',page['recordings'][0]['health'])
                    info = api.recording_info('recording-0')
                    self.assertEqual(info['total_messages'],21)
                    self.assertEqual(info['bag_size_bytes'],2048)
                    self.assertEqual(info['health']['message'],health['message'])
                    process.assert_not_called()
                    api.delete('recording-0')
                    self.assertFalse((root/'recording-0').exists())
                    self.assertTrue((root/'recording-1').exists())
                    recorder.process=Mock();recorder.process.poll.return_value=None
                    with self.assertRaises(ValueError): recorder.delete_recording('recording-1')
                    self.assertTrue((root/'recording-1').exists())
                finally:
                    server.shutdown();server.server_close();thread.join()

    def test_warning_reasons_match_lan_and_old_quality_only_warning_stays_hidden(self):
        try:
            import app
        except ImportError:
            self.skipTest('Pi backend not part of the remote repo')
        self.assertIsNone(app.recording_notice(None))
        self.assertIsNone(app.recording_notice({'state':'ok'}))
        warning = {'state':'warning','message':'Automatically stopped because Pi storage is low.',
                   'topics':[{'name':'/camera','messages':0},{'name':'/imu','messages':0}]}
        self.assertEqual(app.recording_notice(warning)['brief'],'Warning: Stopped: low Pi storage · No messages on 2 topics')
        error = {'state':'error','exit_code':2,'message':'The recorder stopped without a completed bag.'}
        self.assertEqual(app.recording_notice(error)['brief'],'Error: Recorder exited with code 2 · Bag did not finish')
        long = app.recording_notice({'state':'warning','message':'long '*500},detail=True)
        self.assertLessEqual(len(long['brief']),128)
        self.assertEqual(len(long['message']),1024)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/app.HEALTH_FILE).write_text(json.dumps({'state':'warning','message':'Bag metadata reports messages for all selected topics. Source sequence gaps were found; see the quality report.','quality':{'unused':True}}))
            self.assertIsNone(app.recording_notice(app.recording_health(path)))
