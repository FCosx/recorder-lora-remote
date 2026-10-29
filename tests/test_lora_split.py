"""Split limits must survive browser -> radio -> Pi API without extra Start actions."""
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from lora.agent import Agent, Journal, RecorderAPI
from lora.remote import Remote
from lora.protocol import (CATALOG_REQUEST, MAX_FRAME, MAX_SPLIT_DURATION_SECONDS,
    MAX_SPLIT_SIZE_MIB, Op, Request, Result, SPLIT_LIMITS, ZERO, split_limits)

KEY=bytes(range(32))

class SplitAPI:
    def __init__(self):
        self.value={'state':'idle','name':None,'topics':[],'can_start':True}
        self.calls=[]
    def status(self):return dict(self.value)
    def topics(self):return [{'name':'/camera'},{'name':'/imu'}]
    def start(self,topics,size=0,duration=0):
        self.calls.append((topics,size,duration))
        self.value.update(state='recording',name='recording-test',topics=topics)

class SplitRadioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.api=SplitAPI()
        self.journal=Journal(self.root/'pi.db');self.addCleanup(self.journal.close)
        self.agent=Agent(self.api,self.journal,lambda:1000)
        self.agent.handle(Request(Op.TOPICS,1,data=CATALOG_REQUEST.pack(ZERO,0)))
    def remote(self):
        r=Remote(KEY,self.root/'remote.db','unused')
        r.latest=self.agent.handle(Request(Op.STATUS,2));r.received_at=time.monotonic()
        r.synchronized=True;r.needs_refresh=False
        r.catalog=['/camera','/imu'];r.catalog_revision=self.agent.catalog['revision']
        return r
    def test_off_size_time_and_combined_limits_roundtrip_and_retry_once(self):
        for index,(size,duration) in enumerate([(None,None),(100,None),(None,10),(100,10),(MAX_SPLIT_SIZE_MIB,MAX_SPLIT_DURATION_SECONDS)],10):
            with self.subTest(size=size,duration=duration):
                self.api.value.update(state='idle',name=None,topics=[])
                r=self.remote();r.submit(Op.START_SELECTED,[1],r.catalog_revision.hex(),size,duration)
                op,snapshot,data=r.queue.get_nowait()
                request=Request(op,index,tick=snapshot.tick,boot=snapshot.boot,recording=snapshot.recording,data=data)
                frame=request.encode(KEY);self.assertLessEqual(len(frame),MAX_FRAME)
                decoded=Request.decode(frame,KEY)
                self.assertEqual(len(decoded.data),21 if not(size or duration) else 29)
                self.assertEqual(self.agent.handle(decoded).result,Result.ACCEPTED)
                before=len(self.api.calls)
                self.assertEqual(self.agent.handle(decoded).result,Result.ACCEPTED)
                self.assertEqual(len(self.api.calls),before)
                self.assertEqual(self.api.calls[-1],(['/imu'],size or 0,duration or 0))
    def test_invalid_limits_rejected_before_queueing_and_on_pi(self):
        for size,duration in [(-1,0),(1.5,0),(True,0),('10',0),(MAX_SPLIT_SIZE_MIB+1,0),(0,MAX_SPLIT_DURATION_SECONDS+1),(0,False)]:
            with self.subTest(size=size,duration=duration):
                r=self.remote()
                with self.assertRaises(ValueError):r.submit(Op.START_SELECTED,[0],r.catalog_revision.hex(),size,duration)
                self.assertTrue(r.queue.empty());self.assertIsNone(r.pending)
        prefix=self.agent.catalog['revision']+(1).to_bytes(13,'big')
        for index,data in enumerate([prefix+b'x',prefix+SPLIT_LIMITS.pack(MAX_SPLIT_SIZE_MIB+1,0),prefix+SPLIT_LIMITS.pack(0,MAX_SPLIT_DURATION_SECONDS+1)],100):
            request=Request(Op.START_SELECTED,index,tick=1000,boot=self.agent.boot,data=data)
            self.assertEqual(self.agent.handle(request).result,Result.INVALID_SPLIT)
        self.assertFalse(self.api.calls)
    def test_old_agent_capability_refuses_splitting_but_accepts_off(self):
        r=self.remote();r.latest=replace(r.latest,flags=r.latest.flags & ~32)
        with self.assertRaisesRegex(ValueError,'Update the Pi'):r.submit(Op.START_SELECTED,[0],r.catalog_revision.hex(),5,0)
        self.assertIsNone(r.pending)
        r.submit(Op.START_SELECTED,[0],r.catalog_revision.hex())
        self.assertEqual(len(r.queue.get_nowait()[2]),21)
    def test_changed_limits_on_same_command_id_are_not_reexecuted(self):
        prefix=self.agent.catalog['revision']+(1).to_bytes(13,'big')
        request=Request(Op.START_SELECTED,100,tick=1000,boot=self.agent.boot,data=prefix+SPLIT_LIMITS.pack(10,5))
        self.assertEqual(self.agent.handle(request).result,Result.ACCEPTED)
        self.assertEqual(self.agent.handle(replace(request,data=prefix+SPLIT_LIMITS.pack(20,5))).result,Result.ID_CONFLICT)
        self.assertEqual(len(self.api.calls),1)
    def test_api_client_passes_both_split_fields_to_existing_pi_endpoint(self):
        api=RecorderAPI();api.request=Mock(return_value={'state':'recording'})
        api.start(['/camera'],100,10)
        api.request.assert_called_once_with('/api/start',{'topics':['/camera'],'max_bag_size_mib':100,'max_bag_duration_seconds':10},timeout=5)

class RecorderSplitBackendTests(unittest.TestCase):
    def test_same_limits_produce_rosbag_size_bytes_and_duration_seconds(self):
        try:import app
        except ImportError:self.skipTest('Pi backend not included in standalone remote repo')
        self.assertEqual(MAX_SPLIT_SIZE_MIB,app.MAX_SPLIT_SIZE_MIB)
        self.assertEqual(MAX_SPLIT_DURATION_SECONDS,app.MAX_SPLIT_DURATION_SECONDS)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for size,duration in [(0,0),(5,0),(0,10),(5,10)]:
                recorder=app.Recorder();recorder.status=Mock(return_value={'state':'recording'})
                stat=Mock(f_bavail=100000000,f_frsize=4096)
                with patch.object(app,'RECORDINGS',root),patch.object(app,'LOGS',root/'logs'),patch.object(app.os,'statvfs',return_value=stat),patch.object(app.subprocess,'Popen') as start,patch.object(app.threading.Thread,'start'):
                    try:
                        recorder.start(['/camera'],size,duration)
                        command=start.call_args.args[0]
                        if size:self.assertEqual(command[command.index('--max-bag-size')+1],str(size*1024**2))
                        else:self.assertNotIn('--max-bag-size',command)
                        if duration:self.assertEqual(command[command.index('--max-bag-duration')+1],str(duration))
                        else:self.assertNotIn('--max-bag-duration',command)
                    finally:
                        if recorder.log_file:recorder.log_file.close()
