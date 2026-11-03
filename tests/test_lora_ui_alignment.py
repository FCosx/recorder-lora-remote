"""Bounded telemetry and one-shot completion metadata; no real recording actions."""
import tempfile,time,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from lora.agent import Agent,Journal
from lora.remote import Remote
from lora.protocol import MAX_FRAME,Op,Request,Response,State,STATUS_SEGMENTS,JSONTransfer,recording_token
from test_lora_recordings import SavedAPI
import test_lora_recordings as recording_tests

class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.api=SavedAPI();self.journal=Journal(Path(self.temp.name)/'pi.db');self.addCleanup(self.journal.close)
        self.agent=Agent(self.api,self.journal)
        self.remote=Remote(bytes(32),Path(self.temp.name)/'remote.db','unused')
    def snapshot(self,state='idle',name=None,segments=None):
        self.api.value.update(state=state,name=name,segment_count=segments)
        return self.agent.handle(Request(Op.STATUS,1))
    def test_compact_status_survives_interleaved_metadata(self):
        name=self.api.rows[0]['name']
        status=self.snapshot('recording',name,7)
        self.assertEqual(len(status.data),3)
        self.assertLessEqual(len(status.encode(bytes(32))),MAX_FRAME)
        self.assertEqual(Response.decode(status.encode(bytes(32)),bytes(32)).as_dict()['segment_count'],7)
        self.remote.accept_snapshot(status)
        self.remote.accept_snapshot(replace(status,op=Op.TOPICS,data=b'metadata'))
        self.assertEqual(self.remote.status()['status']['segment_count'],7)
        other=replace(status,name='another-bag',recording=recording_token('another-bag'),op=Op.TOPICS,data=b'')
        self.remote.accept_snapshot(other)
        self.assertIsNone(self.remote.status()['status']['segment_count'])
        unknown=self.snapshot('recording',name,None)
        self.assertIsNone(unknown.as_dict()['segment_count'])
        self.assertIsNone(replace(status,data=b'').as_dict()['segment_count'],'Old status packets remain readable')
    def test_completion_is_detected_once_and_reboot_does_not_fake_completion(self):
        name=self.api.rows[0]['name']
        self.remote.accept_snapshot(self.snapshot('recording',name,2))
        self.remote.accept_snapshot(self.snapshot('stopping',name,2))
        self.remote.accept_snapshot(self.snapshot())
        self.assertEqual(self.remote.completion_target,name)
        self.assertTrue(self.remote.status()['completion_pending'])
        self.remote.completion_refresh_due=False
        self.remote.accept_snapshot(self.snapshot())
        self.assertFalse(self.remote.completion_refresh_due,'Repeated idle polls do not schedule more lists')
        self.remote.accept_snapshot(self.snapshot('recording',name,1))
        reboot=replace(self.snapshot(),boot=b'new-boot')
        self.remote.accept_snapshot(reboot)
        self.assertFalse(self.remote.completion_refresh_due)
        self.assertIsNone(self.remote.completed_recording)
    def test_completed_duration_from_list_expires_and_is_not_an_estimate(self):
        # Reuse the same bounded chunk path tested for normal metadata pages.
        helper=recording_tests.RecordingRadioTests('test_pages_and_large_topic_details_fit_frames_and_keep_counts')
        helper.setUp()
        try:
            name=helper.api.rows[0]['name']
            helper.remote.completion_target=name;helper.remote.completion_refresh_due=True
            helper.fetch()
            completed=helper.remote.status()['completed_recording']
            self.assertEqual(completed['duration_seconds'],10.5)
            self.assertEqual(completed['messages'],21)
            self.assertFalse(helper.remote.status()['completion_pending'])
            helper.remote.completed_at=time.monotonic()-11
            self.assertIsNone(helper.remote.status()['completed_recording'])
        finally:helper.doCleanups()
    def test_new_recording_cancels_old_completion_and_ignores_inflight_chunk(self):
        old,new=[row['name'] for row in self.api.rows[:2]]
        self.remote.accept_snapshot(self.snapshot('recording',old,1))
        self.remote.accept_snapshot(self.snapshot())
        transfer=JSONTransfer()
        self.remote.completion_refresh_due=False
        self.remote.data_transfer={'op':Op.RECORDINGS,'selector':bytes(2),'name':None,
                                   'transfer':transfer,'completion':True}
        first=self.agent.handle(Request(Op.RECORDINGS,10,data=transfer.request()+bytes(2)))
        self.remote.accept_snapshot(first);self.remote.accept_metadata(first)
        self.assertIsNotNone(self.remote.data_transfer,'Exercise a partially received catalog')
        self.snapshot('recording',new,1)
        delayed=self.agent.handle(Request(Op.RECORDINGS,11,data=transfer.request()+bytes(2)))
        # The worker accepts the live snapshot before consuming this old chunk.
        self.remote.accept_snapshot(delayed);self.remote.accept_metadata(delayed)
        self.assertFalse(self.remote.status()['completion_pending'])
        self.assertIsNone(self.remote.completion_target)
        self.assertIsNone(self.remote.completed_recording)
        self.assertIsNone(self.remote.data_transfer)
        self.assertFalse(self.remote.recordings_loaded,'Discard the canceled automatic catalog')
        self.remote.accept_snapshot(self.snapshot())
        self.assertEqual(self.remote.completion_target,new,'The next completion belongs to the new session')
        transfer=JSONTransfer()
        self.remote.completion_refresh_due=False
        self.remote.data_transfer={'op':Op.RECORDINGS,'selector':bytes(2),'name':None,
                                   'transfer':transfer,'completion':True}
        for number in range(12,1000):
            response=self.agent.handle(Request(Op.RECORDINGS,number,data=transfer.request()+bytes(2)))
            self.remote.accept_snapshot(response);self.remote.accept_metadata(response)
            if self.remote.data_transfer is None:break
        self.assertEqual(self.remote.status()['completed_recording']['name'],new)
        self.assertFalse(self.remote.status()['completion_pending'])
    def test_active_states_clear_saved_completion_but_preserve_manual_details(self):
        old,new=[row['name'] for row in self.api.rows[:2]]
        for state in ('starting','recording','stopping'):
            with self.subTest(state=state):
                self.remote.accept_snapshot(self.snapshot())
                self.remote.completed_recording={'name':old,'duration_seconds':10.5,'messages':21}
                self.remote.completed_at=time.monotonic()
                self.remote.completion_target=old;self.remote.completion_refresh_due=True
                manual={'op':Op.BAG_INFO,'selector':old.encode(),'name':old,'transfer':JSONTransfer()}
                self.remote.data_transfer=manual
                self.remote.accept_snapshot(self.snapshot(state,new,1))
                self.assertIs(self.remote.data_transfer,manual,'Keep explicit View topics requests')
                self.assertFalse(self.remote.status()['completion_pending'])
                self.assertIsNone(self.remote.status()['completed_recording'])
                self.assertIsNone(self.remote.completed_at)
    def test_reboot_discards_automatic_completion_transfer(self):
        old=self.api.rows[0]['name']
        self.remote.accept_snapshot(self.snapshot('recording',old,1))
        self.remote.accept_snapshot(self.snapshot())
        self.remote.data_transfer={'op':Op.RECORDINGS,'selector':bytes(2),'name':None,
                                   'transfer':JSONTransfer(),'completion':True}
        self.remote.accept_snapshot(replace(self.snapshot(),boot=b'new-boot'))
        self.assertIsNone(self.remote.data_transfer)
        self.assertFalse(self.remote.status()['completion_pending'])
    def test_lan_summary_and_temperature_reading(self):
        try:import app
        except ImportError:self.skipTest('Pi backend not in standalone remote repo')
        with patch.object(Path,'read_text',return_value='51200'):
            self.assertEqual(app.cpu_temperature(),51.2)
        with patch.object(Path,'read_text',return_value='NaN'):
            self.assertIsNone(app.cpu_temperature())
        with patch.object(Path,'read_text',side_effect=OSError):
            self.assertIsNone(app.cpu_temperature())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bag=root/'recording-test';bag.mkdir();(bag/'metadata.yaml').write_text('test');(bag/'bag_0.mcap').write_bytes(bytes(42))
            info={'started_at':'2026-10-29T12:00:00','duration_seconds':12.5,'total_messages':25}
            with patch.object(app,'RECORDINGS',root),patch.object(app,'recording_metadata',return_value=info) as metadata:
                self.assertEqual(app.recording_list()[0]['bytes'],42);metadata.assert_not_called()
                row=app.recording_list(include_metadata=True)[0]
                self.assertEqual(row['duration_seconds'],12.5);self.assertEqual(row['total_messages'],25)
