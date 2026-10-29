"""Bounded telemetry and one-shot completion metadata; no real recording actions."""
import tempfile,time,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from lora.agent import Agent,Journal
from lora.remote import Remote
from lora.protocol import MAX_FRAME,Op,Request,Response,State,STATUS_SEGMENTS,recording_token
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
    def test_segment_count_is_two_bytes_and_survives_interleaved_metadata(self):
        name=self.api.rows[0]['name']
        status=self.snapshot('recording',name,7)
        self.assertEqual(len(status.data),2)
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
