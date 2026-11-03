"""Cloud actions are tiny authenticated commands, not bag data over LoRa."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from lora.agent import Agent, Journal
from lora.protocol import (CLOUD_PHASES, CLOUD_REACH, CLOUD_TELEMETRY, MAX_FRAME, Op, Request,
                           Response, Result, ZERO, recording_token)
from lora.remote import Remote

KEY=bytes(range(32))

class API:
    def __init__(self):
        self.value={'state':'idle','can_start':True,'name':None,'topics':[],
                    'cloud':{'configured':True,'mode':'manual','reachable':'reachable','state':'idle','progress':0,'name':None}}
        self.calls=[]
        self.rows=[{'name':'recording-test','bytes':42,'started_at':None,'duration_seconds':2,'total_messages':20,
                    'upload':{'state':'uploaded','progress':100}}]
    def status(self):return self.value.copy()
    def recordings(self,offset):return {'recordings':self.rows,'total':1,'next_offset':None}
    def cloud(self):return self.value['cloud']
    def upload(self,name):self.calls.append(('upload',name))
    def upload_mode(self,mode):self.calls.append(('mode',mode))

class RadioCloudTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.api=API();self.journal=Journal(Path(self.temp.name)/'commands.sqlite');self.addCleanup(self.journal.close)
        self.agent=Agent(self.api,self.journal,lambda:1000)
        self.remote=Remote(KEY,Path(self.temp.name)/'remote.sqlite','unused')
        self.remote.accept_snapshot(self.agent.handle(Request(Op.STATUS,1)))
        self.remote.synchronized=True;self.remote.needs_refresh=False
    def test_status_maximum_name_and_cloud_fields_fit_packet(self):
        self.api.value.update(name='recording-'+'1'*38,state='recording',elapsed_seconds=5)
        self.api.value['cloud'].update(name='recording-test',state='paused',progress=75)
        response=self.agent.handle(Request(Op.STATUS,2));frame=response.encode(KEY)
        self.assertLessEqual(len(frame),MAX_FRAME)
        decoded=Response.decode(frame,KEY).as_dict()
        self.assertEqual(decoded['cloud']['mode'],'manual');self.assertEqual(decoded['cloud']['state'],'paused')
        self.assertEqual(decoded['cloud']['progress'],75)
    def test_upload_and_mode_are_fresh_idempotent_actions(self):
        self.agent.recording_transfers[Op.RECORDINGS]={'revision':b'list-rev','created':1000,
                                                     'value':{'r':[['recording-test',42,None,2,20]]}}
        upload=Request(Op.UPLOAD,10,tick=1000,boot=self.agent.boot,data=b'list-rev'+recording_token('recording-test'))
        self.assertEqual(self.agent.handle(upload).result,Result.ACCEPTED)
        self.assertEqual(self.agent.handle(upload).result,Result.ACCEPTED)
        self.assertEqual(self.api.calls,[('upload','recording-test')])
        mode=Request(Op.UPLOAD_MODE,11,tick=1000,boot=self.agent.boot,data=b'\x01')
        self.assertEqual(self.agent.handle(mode).result,Result.ACCEPTED)
        self.assertEqual(self.agent.handle(mode).result,Result.ACCEPTED)
        self.assertEqual(self.api.calls[-1],('mode','automatic'))
        expired=Request(Op.UPLOAD_MODE,12,tick=900,boot=self.agent.boot,data=b'\x00')
        self.assertEqual(self.agent.handle(expired).result,Result.EXPIRED)
    def test_radio_updates_uploaded_badge_without_catalog_reload(self):
        self.remote.recordings=[['recording-test',42,None,2,20]]
        self.api.value['cloud'].update(state='uploaded',name='recording-test',progress=100)
        self.remote.accept_snapshot(self.agent.handle(Request(Op.STATUS,2)))
        self.assertEqual(self.remote.status()['recordings_upload']['recording-test']['state'],'uploaded')
        self.remote.received_at-=100
        self.assertIsNone(self.remote.status()['cloud'])
    def test_completed_jobs_sync_even_if_terminal_status_poll_was_missed(self):
        from lora.protocol import JSONTransfer
        revision=b'list-rev'
        rows=[['recording-test',42,None,2,20],['recording-second',42,None,2,20]]
        self.agent.recording_transfers[Op.RECORDINGS]={'revision':revision,'created':1000,'value':{'r':rows}}
        self.remote.recordings=rows;self.remote.recordings_revision=revision;self.remote.recordings_loaded=True
        self.api.value['cloud'].update(revision=7,state='uploading',name='recording-second',
                                      uploads={'recording-test':{'state':'uploaded'},'recording-second':{'state':'uploading'}})
        self.remote.accept_snapshot(self.agent.handle(Request(Op.STATUS,5)))
        for number in range(20,30):
            op,_,data=self.remote.next_cloud_request()
            response=self.agent.handle(Request(op,number,data=data))
            self.assertLessEqual(len(response.encode(KEY)),MAX_FRAME)
            self.remote.accept_cloud(response)
            if self.remote.cloud_transfer is None:break
        self.assertEqual(self.remote.recordings_upload['recording-test']['state'],'uploaded')
        self.assertEqual(self.remote.upload_revision,7)
        self.assertIsNone(self.remote.next_cloud_request())

    def test_mutation_rejected_without_fresh_loaded_selection(self):
        self.remote.recordings=[['recording-test',42,None,2,20]]
        self.remote.recordings_revision=b'list-rev'
        with self.assertRaises(ValueError):self.remote.upload_recording('wrong','bad')
        self.remote.upload_recording('recording-test',b'list-rev'.hex())
        op,_,data=self.remote.queue.get_nowait();self.assertEqual(op,Op.UPLOAD)
        self.assertEqual(len(data),16)
