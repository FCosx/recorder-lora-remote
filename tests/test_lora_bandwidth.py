"""Refresh-triggered radio estimates: bounded frames and one-shot capture isolation."""
import tempfile
import time
import unittest
from pathlib import Path
from dataclasses import replace
from lora.agent import Agent, Journal, RecorderAPI
from unittest.mock import patch
from lora.protocol import CATALOG_REQUEST, MAX_FRAME, Op, Request, Result, State, ZERO
from lora.remote import Remote

KEY=bytes(range(32))

class API:
    def __init__(self):self.state='idle';self.calls=[];self.measuring=False
    def status(self):return {'state':self.state,'name':None,'topics':[],'can_start':True}
    def topics(self):return [{'name':f'/camera_{i}'} for i in range(100)]
    def bandwidth(self,action):
        self.calls.append(action)
        if action=='sample':self.measuring=True
        return {'state':'measuring' if self.measuring else 'complete','measured_at':None if self.measuring else 1234.,
                'topics':{} if self.measuring else {f'/camera_{i}':{'bytes_per_second':None if i==0 else i*100003} for i in range(100)}}

class LoRaBandwidthTests(unittest.TestCase):
    def test_pi_agent_can_return_completed_sample_in_first_reply(self):
        clock=[0.0];calls=[]
        api=RecorderAPI()
        def request(path,body=None,timeout=3):
            calls.append(body)
            return {'state':'complete' if clock[0]>=1.2 else 'measuring'}
        def sleep(seconds):clock[0]+=seconds
        api.request=request
        with patch('lora.agent.time.monotonic',side_effect=lambda:clock[0]),patch('lora.agent.time.sleep',side_effect=sleep):
            self.assertEqual(api.bandwidth('sample')['state'],'complete')
        self.assertEqual(sum(body is not None for body in calls),1)
        self.assertLess(clock[0],1.5)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.api=API();self.journal=Journal(Path(self.tmp.name)/'pi.db');self.addCleanup(self.journal.close)
        self.agent=Agent(self.api,self.journal,clock=lambda:1000)
        self.remote=Remote(KEY,Path(self.tmp.name)/'remote.db','unused')
        self.remote.latest=self.agent.handle(Request(Op.STATUS,1));self.remote.received_at=time.monotonic()
        self.remote.synchronized=True;self.remote.needs_refresh=False;self.number=2

    def refresh(self):
        self.remote.refresh_topics()
        while self.remote.topic_transfer is not None:
            t=self.remote.topic_transfer;self.number+=1
            r=self.agent.handle(Request(Op.TOPICS,self.number,data=CATALOG_REQUEST.pack(t['revision'],len(t['data']))))
            self.remote.accept_snapshot(r);self.remote.accept_topics(r)

    def transfer(self):
        frames=0;self.remote.bandwidth_next=0
        while True:
            op,snapshot,data=self.remote.next_bandwidth_request();self.number+=1
            request=Request(op,self.number,tick=snapshot.tick,boot=snapshot.boot,data=data)
            response=self.agent.handle(request)
            self.assertLessEqual(len(response.encode(KEY)),MAX_FRAME)
            self.assertEqual(response.result,Result.OK)
            if frames==0:
                before=list(self.api.calls)
                self.agent.handle(request)  # Same radio request must not sample again.
                self.assertEqual(self.api.calls,before)
            self.remote.accept_snapshot(response);self.remote.accept_bandwidth(response);frames+=1
            if self.remote.bandwidth_transfer is None:return frames
            self.assertLess(frames,50)

    def test_refresh_starts_once_result_polls_never_resample_and_no_journal_writes(self):
        self.assertIsNone(self.remote.next_bandwidth_request());self.assertEqual(self.api.calls,[])
        self.refresh();self.assertTrue(self.remote.status()['bandwidth_loading'])
        self.transfer();self.assertEqual(self.api.calls,['sample'])
        self.transfer();self.assertEqual(self.api.calls,['sample','status'])
        self.api.measuring=False
        self.assertGreater(self.transfer(),1)
        self.assertFalse(self.remote.status()['bandwidth_loading'])
        self.assertIsNone(self.remote.bandwidth_rates['/camera_0'])
        self.assertEqual(self.remote.bandwidth_rates['/camera_99'],9900297)
        self.assertEqual(self.remote.bandwidth_measured_at,1234.)
        self.assertEqual(self.journal.highest(),0)
        self.remote.bandwidth_next=0
        self.assertIsNone(self.remote.next_bandwidth_request())
        self.assertEqual(self.api.calls.count('sample'),1)

    def test_expired_requests_and_changed_catalog_do_not_sample(self):
        self.refresh()
        for tick,revision,result in [(900,self.agent.catalog['revision'],Result.EXPIRED),(1000,b'outdated',Result.CATALOG_CHANGED)]:
            request=Request(Op.BANDWIDTH,99,tick=tick,boot=self.agent.boot,data=CATALOG_REQUEST.pack(ZERO,0)+b'\2'+revision)
            self.assertEqual(self.agent.handle(request).result,result)
        self.assertEqual(self.api.calls,[])

    def test_capture_cancels_pending_job_and_completion_cannot_restart_it(self):
        self.refresh();self.transfer()
        self.remote.submit(Op.START_SELECTED,[0],self.remote.catalog_revision.hex())
        self.assertFalse(self.remote.bandwidth_enabled);self.assertIsNone(self.remote.next_bandwidth_request())
        self.remote.accept_snapshot(replace(self.remote.latest,state=State.RECORDING))
        self.remote.accept_snapshot(replace(self.remote.latest,state=State.IDLE))
        self.assertIsNone(self.remote.next_bandwidth_request())

    def test_timeout_and_old_agent_leave_no_preview_work(self):
        self.refresh();self.remote.bandwidth_deadline=0
        self.assertIsNone(self.remote.next_bandwidth_request());self.assertFalse(self.remote.bandwidth_enabled)
        snapshot=self.agent.snapshot
        self.agent.snapshot=lambda *a,**kw:replace(snapshot(*a,**kw),flags=snapshot(*a,**kw).flags&127)
        self.refresh();self.assertFalse(self.remote.bandwidth_enabled)
        self.assertEqual(self.api.calls,[])

if __name__=='__main__':unittest.main()
