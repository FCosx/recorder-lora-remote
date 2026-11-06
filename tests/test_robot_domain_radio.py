"""Source-domain controls remain bounded, retry-safe and compatible with old radios."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock
from lora.agent import Agent,Journal
from lora.remote import Remote
from lora.protocol import (Op,State,Result,Request,Response,ZERO,MAX_FRAME,
                           DOMAIN_COMMAND,DOMAIN_STATUS_REQUEST,JSONTransfer)
from tools.robot_control_client import set_domain


class RobotDomainRadioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.api=Mock()
        self.api.status.return_value={'state':'idle','can_start':True,'name':'r'*48,
           'robot_domain':{'domain':37,'pending':None,'revision':123,'connected':True,'registered':True,'bridge_running':True},
           'cloud':{'configured':True,'mode':'manual','reachable':'reachable','state':'idle'}}
        journal=Journal(self.root/'journal.sqlite');self.addCleanup(journal.close)
        self.agent=Agent(self.api,journal)

    def test_opt_in_status_retains_legacy_cloud_and_fits_radio(self):
        legacy=self.agent.handle(Request(Op.STATUS,1)).as_dict()
        self.assertIsNone(legacy['robot_domain'])
        self.assertTrue(legacy['cloud']['configured'])
        response=self.agent.handle(Request(Op.STATUS,2,data=DOMAIN_STATUS_REQUEST))
        frame=response.encode(bytes(32));self.assertLessEqual(len(frame),MAX_FRAME)
        state=Response.decode(frame,bytes(32)).as_dict()
        self.assertEqual(state['robot_domain']['domain'],37)
        self.assertTrue(state['cloud']['configured'])

    def test_domain_retries_execute_once_and_recording_rejects_change(self):
        request=Request(Op.ROBOT_DOMAIN,3,int(self.agent.clock()),self.agent.boot,ZERO,DOMAIN_COMMAND.pack(7,123))
        self.assertEqual(self.agent.handle(request).result,Result.ACCEPTED)
        self.assertEqual(self.agent.handle(request).result,Result.ACCEPTED)
        self.api.robot_domain.assert_called_once_with(7,123)
        self.api.status.return_value['state']='recording'
        second=Request(Op.ROBOT_DOMAIN,4,int(self.agent.clock()),self.agent.boot,ZERO,DOMAIN_COMMAND.pack(0,123))
        self.assertEqual(self.agent.handle(second).result,Result.BUSY)
        self.api.robot_domain.assert_called_once()

    def test_domain_command_has_priority_and_requires_managed_robot(self):
        remote=Remote(bytes(32),self.root/'remote.sqlite','unused')
        remote.latest=self.agent.handle(Request(Op.STATUS,5,data=DOMAIN_STATUS_REQUEST))
        remote.received_at=time.monotonic();remote.synchronized=True;remote.needs_refresh=False
        remote.robot_domain=remote.latest.as_dict()['robot_domain']
        remote.data_transfer={'name':None,'transfer':JSONTransfer()}
        remote.set_robot_domain(42,123)
        op,snapshot,data=remote.queue.get_nowait()
        self.assertEqual(op,Op.ROBOT_DOMAIN)
        self.assertEqual(DOMAIN_COMMAND.unpack(data),(42,123))
        remote.pending=None;remote.robot_domain=None
        with self.assertRaisesRegex(ValueError,'fresh robot status'):
            remote.set_robot_domain(42,123)

    def test_saved_source_domain_repairs_config_on_next_start(self):
        config=self.root/'robot.json5';config.write_text('{"plugins":{"ros2dds":{"domain":0,"namespace":"/"}}}')
        settings=self.root/'robot-service.json'
        set_domain(settings,{'config':str(config),'domain':0},42)
        saved=json.loads(settings.read_text());self.assertEqual(saved['domain'],42)
        config.write_text('{"plugins":{"ros2dds":{"domain":0}}}')
        set_domain(settings,saved,saved['domain'])
        self.assertEqual(json.loads(config.read_text())['plugins']['ros2dds']['domain'],42)
        self.assertEqual(settings.stat().st_mode&0o777,0o600)


if __name__=='__main__':unittest.main()
