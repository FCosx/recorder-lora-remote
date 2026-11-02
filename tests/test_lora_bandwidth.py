"""Compact radio estimates: bounded frames, default off, leases and capture isolation."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from dataclasses import replace

from lora.agent import Agent, Journal
from lora.protocol import CATALOG_REQUEST, MAX_FRAME, Op, Request, Result, State, ZERO
from lora.remote import Remote

KEY=bytes(range(32))


class API:
    def __init__(self):
        self.state='idle';self.calls=[]
    def status(self):
        return {'state':self.state,'name':None,'topics':[],'can_start':True}
    def bandwidth(self,enabled,heartbeat=False):
        self.calls.append((enabled,heartbeat))
        return {'client_enabled':enabled,'measured_at':1234.,
                'topics':{f'/camera_{i}':{'bytes_per_second':None if i==0 else i*100003} for i in range(100)}}


class LoRaBandwidthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.api=API();self.journal=Journal(Path(self.tmp.name)/'pi.db');self.addCleanup(self.journal.close)
        self.agent=Agent(self.api,self.journal,clock=lambda:1000)
        self.agent.catalog={'revision':b'catalog1','topics':[f'/camera_{i}' for i in range(100)],'created':1000}
        self.remote=Remote(KEY,Path(self.tmp.name)/'remote.db','unused')
        self.remote.catalog=list(self.agent.catalog['topics']);self.remote.catalog_revision=b'catalog1'
        self.remote.latest=self.agent.handle(Request(Op.STATUS,1));self.remote.received_at=time.monotonic()
        self.remote.synchronized=True;self.remote.needs_refresh=False;self.number=2

    def transfer(self):
        frames=0
        while True:
            op,snapshot,data=self.remote.next_bandwidth_request()
            self.number+=1
            request=Request(op,self.number,tick=snapshot.tick,boot=snapshot.boot,data=data)
            response=self.agent.handle(request)
            self.assertLessEqual(len(response.encode(KEY)),MAX_FRAME)
            self.assertEqual(response.result,Result.OK)
            self.remote.accept_snapshot(response);self.remote.accept_bandwidth(response);frames+=1
            if self.remote.bandwidth_transfer is None:return frames
            self.assertLess(frames,50)

    def test_default_off_and_compact_all_topic_transfer_does_not_write_command_journal(self):
        self.assertFalse(self.remote.status()['bandwidth_enabled']);self.assertIsNone(self.remote.next_bandwidth_request())
        self.assertEqual(self.api.calls,[])
        self.remote.set_bandwidth(True)
        self.assertGreater(self.transfer(),1)
        self.assertIsNone(self.remote.bandwidth_rates['/camera_0'])
        self.assertEqual(self.remote.bandwidth_rates['/camera_99'],9900297)
        self.assertEqual(self.remote.bandwidth_measured_at,1234.)
        self.assertEqual(self.journal.highest(),0)
        self.assertIsNone(self.remote.next_bandwidth_request())
        self.remote.set_bandwidth(False);self.transfer()
        self.assertEqual(self.api.calls[-1],(False,False));self.assertFalse(self.remote.bandwidth_enabled)

    def test_expired_radio_requests_and_changed_catalog_do_not_start_sampling(self):
        for tick,revision,result in [(900,b'catalog1',Result.EXPIRED),(1000,b'outdated',Result.CATALOG_CHANGED)]:
            request=Request(Op.BANDWIDTH,10,tick=tick,boot=self.agent.boot,
                            data=CATALOG_REQUEST.pack(ZERO,0)+b'\1'+revision)
            self.assertEqual(self.agent.handle(request).result,result)
        self.assertEqual(self.api.calls,[])

    def test_browser_lease_expires_and_recording_turns_off_preview(self):
        self.remote.set_bandwidth(True);self.remote.bandwidth_browser_until=0
        request=self.remote.next_bandwidth_request();self.assertEqual(request[2][-9],0)
        self.assertFalse(self.remote.bandwidth_enabled)
        self.remote.set_bandwidth(True)
        recording=replace(self.remote.latest,state=State.RECORDING)
        self.remote.accept_snapshot(recording)
        self.assertFalse(self.remote.bandwidth_enabled);self.assertIsNone(self.remote.next_bandwidth_request())
        with self.assertRaises(ValueError):self.remote.set_bandwidth(True)

    def test_older_agent_disables_optional_feature(self):
        self.remote.latest=replace(self.remote.latest,flags=self.remote.latest.flags&127)
        self.assertFalse(self.remote.status()['bandwidth_supported'])
        with self.assertRaises(ValueError):self.remote.set_bandwidth(True)


if __name__=='__main__':unittest.main()
