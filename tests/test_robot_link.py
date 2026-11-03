"""Metadata-only robot link monitoring; no sensor traffic or real bag actions."""
import io,json,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from tools.robot_bandwidth import Coordinator,LINK_TIMEOUT_SECONDS
from lora.agent import Agent,Journal
from lora.remote import Remote
from lora.protocol import Op,Request,Response,MAX_FRAME,STATUS_SEGMENTS,STATUS_TELEMETRY
from test_lora_recordings import SavedAPI
try:
 import app
 from bandwidth import BandwidthEstimator
except ImportError:
 app=None

class LinkMetadataTests(unittest.TestCase):
 def test_existing_presence_detects_loss_recovery_without_extra_ros_requests(self):
  now=[0.];wire=[];reports=[];c=Coordinator(wire.append,reports.append,lambda:now[0])
  c.step();self.assertEqual(reports[-1],{'robot_link':'unknown'})
  presence={'op':'presence','source':'a'*32,'epoch':'b'*32};c.receive(presence)
  now[0]=1.;c.step();self.assertEqual(reports[-1],{'robot_link':'connected'})
  now[0]=LINK_TIMEOUT_SECONDS+.1;c.step();self.assertEqual(reports[-1],{'robot_link':'lost'})
  c.receive(presence);now[0]+=1.;c.step();self.assertEqual(reports[-1],{'robot_link':'connected'})
  self.assertEqual(wire,[{'op':'discover'},{'op':'discover'}],'Monitoring adds no ROS requests')
  self.assertFalse(c.pending);self.assertFalse(c.used_sources)
 def test_local_reports_are_at_most_once_per_second_not_per_executor_tick(self):
  now=[0.];reports=[];c=Coordinator(lambda _:None,reports.append,lambda:now[0])
  for i in range(1000):now[0]=i*.005;c.step()
  self.assertLessEqual(len(reports),5)

@unittest.skipIf(app is None,'Pi backend not in standalone remote repository')
class CachedLinkTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.est=BandwidthEstimator(self.root);self.addCleanup(self.est.close)
 def test_unknown_is_not_a_connection_failure_and_cached_reads_have_no_io(self):
  with patch('bandwidth.subprocess.Popen',side_effect=AssertionError('spawn')),patch.object(Path,'open',side_effect=AssertionError('read')):
   for _ in range(1000):self.assertEqual(self.est.connection_status(),{'state':'unknown','disconnects':0})
 def test_outage_is_latched_once_and_recovery_preserves_counter(self):
  with patch('bandwidth.time.monotonic',return_value=100):self.est._set_connection('connected')
  with patch('bandwidth.time.monotonic',return_value=106):
   for _ in range(10):self.assertEqual(self.est.connection_status(),{'state':'lost','disconnects':1})
   self.est._set_connection('unknown');self.assertEqual(self.est.connection_status()['state'],'lost')
   self.est._set_connection('connected');self.assertEqual(self.est.connection_status(),{'state':'connected','disconnects':1})
  self.est.close();self.assertEqual(self.est.connection_status()['state'],'unknown')
 def test_pipe_eof_marks_a_known_link_lost(self):
  process=SimpleNamespace(stdout=io.StringIO('{"robot_link":"connected"}\n'))
  self.est.process=process
  try:self.est._read(process);self.assertEqual(self.est.connection_status(),{'state':'lost','disconnects':1})
  finally:self.est.process=None
 def test_outage_between_ui_polls_persists_in_finished_bag_without_claiming_loss_count(self):
  recorder=app.Recorder();recorder.bandwidth=self.est
  self.est._set_connection('connected');recorder.link_start=self.est.connection_status()
  for _ in range(2):self.est._set_connection('lost');self.est._set_connection('connected')
  bag=self.root/'recording-test';bag.mkdir();(bag/'metadata.yaml').write_text('placeholder')
  recorder.process=Mock();recorder.process.poll.return_value=None;recorder.name=bag.name;recorder.topics=['/camera']
  meta=SimpleNamespace(topics_with_message_count=[SimpleNamespace(topic_metadata=SimpleNamespace(name='/camera'),message_count=10)],message_count=10,duration=SimpleNamespace(nanoseconds=1_000_000_000))
  with patch.object(app,'RECORDINGS',self.root),patch.dict('sys.modules',{'rosbag2_py':SimpleNamespace(MetadataIo=lambda:SimpleNamespace(read_metadata=lambda _:meta))}),patch.object(app,'recording_loss',return_value=None) as read_loss:
   live=recorder.status();self.assertEqual(live['robot_link'],'connected');self.assertEqual(live['robot_link_interruptions'],2);read_loss.assert_not_called()
   recorder.process.poll.return_value=0;recorder.process.returncode=0;recorder.status()
  result=app.recording_health(bag);self.assertEqual(result['state'],'warning');self.assertEqual(result['robot_link_interruptions'],2);self.assertNotIn('data_loss',result)
  self.assertEqual(app.recording_notice(result)['brief'],'Warning: Robot link interrupted')
  self.assertEqual(app.recording_notice(result,detail=True)['message'],'Robot link interrupted (2). Message loss not measured.')
  self.assertIsNone(recorder.link_start)
 def test_session_starting_during_known_outage_warns_but_old_outage_does_not_leak(self):
  r=app.Recorder();r.bandwidth=self.est;self.est._set_connection('lost');r.link_start=self.est.connection_status()
  self.assertEqual(r._link_interruptions(self.est.connection_status()),1)
  self.est._set_connection('connected');r.link_start=self.est.connection_status();self.assertEqual(r._link_interruptions(self.est.connection_status()),0)

class LinkRadioTests(unittest.TestCase):
 def test_one_byte_extension_fits_frames_and_survives_metadata_and_legacy_status(self):
  with tempfile.TemporaryDirectory() as directory:
   api=SavedAPI();api.value.update(state='recording',name='recording-current',segment_count=7,elapsed_seconds=1,robot_link='lost',robot_link_interruptions=1)
   journal=Journal(Path(directory)/'pi.db')
   try:
    agent=Agent(api,journal);status=agent.handle(Request(Op.STATUS,1));self.assertEqual(len(status.data),3);self.assertLessEqual(len(status.encode(bytes(32))),MAX_FRAME)
    decoded=Response.decode(status.encode(bytes(32)),bytes(32));self.assertEqual(decoded.as_dict()['robot_link'],'lost');self.assertTrue(decoded.as_dict()['robot_link_interrupted'])
    remote=Remote(bytes(32),Path(directory)/'remote.db','unused');remote.accept_snapshot(decoded);remote.accept_snapshot(replace(decoded,op=Op.BAG_INFO,data=b'chunk'))
    self.assertEqual(remote.status()['status']['robot_link'],'lost');self.assertTrue(remote.status()['status']['robot_link_interrupted']);self.assertEqual(remote.status()['status']['segment_count'],7)
    old=replace(decoded,data=STATUS_SEGMENTS.pack(7));self.assertEqual(old.as_dict()['segment_count'],7);self.assertEqual(old.as_dict()['robot_link'],'unknown');self.assertFalse(old.as_dict()['robot_link_interrupted'])
    bad=replace(decoded,data=STATUS_TELEMETRY.pack(7,255));self.assertEqual(bad.as_dict()['robot_link'],'unknown');self.assertFalse(bad.as_dict()['robot_link_interrupted'])
   finally:journal.close()
