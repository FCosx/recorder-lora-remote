"""On-demand setup checks must never start sensor subscriptions or alter services."""
import subprocess
import tempfile
from pathlib import Path
import unittest

from tools import check_robot_setup as check


class SetupCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.status={'state':'idle','robot_link':'connected','free_bytes':30*1024**3,'can_start':True}
        self.topics=[{'name':'/camera','type':'sensor_msgs/msg/Image'}]
        self.calls=[]

    def fetch(self,url):
        self.calls.append(url)
        return {'topics':self.topics} if url.endswith('/api/topics') else self.status

    def run_check(self,bridges=None,helpers=None,route='eth0',active=True,connected=True):
        return check.checks(self.root,'http://192.168.1.182:8080',wait=0,fetch=self.fetch,
            route=lambda host:route,
            inspect=lambda:([{'pid':1,'executable':str(self.root/'bin/zenoh-bridge-ros2dds-fixed')}] if bridges is None else bridges,
                            [{'pid':2}] if helpers is None else helpers),
            runner=lambda *a,**kw:subprocess.CompletedProcess(a,0 if active else 3,'active' if active else 'inactive',''),
            connected=lambda host,pid:connected,buffers=lambda:8*1024**2)

    def test_success_uses_only_existing_readonly_metadata_apis(self):
        value=self.run_check()
        self.assertTrue(value['ok'])
        self.assertEqual(self.calls,['http://192.168.1.182:8080/api/topics','http://192.168.1.182:8080/api/status'])
        self.assertFalse(list(self.root.iterdir()))

    def test_no_sensor_publishers_is_warning_not_false_failure(self):
        self.topics=[{'name':'/rosout'},{'name':'/parameter_events'}]
        value=self.run_check()
        self.assertTrue(value['ok'])
        self.assertEqual(value['checks'][-1]['state'],'warn')

    def test_discovery_is_warmed_before_reading_heartbeat_on_older_recorders(self):
        self.status['robot_link']='unknown'
        previous=self.fetch
        def fetch(url):
            if url.endswith('/api/topics'):self.status['robot_link']='connected'
            return previous(url)
        self.fetch=fetch
        self.assertTrue(self.run_check()['ok'])

    def test_checks_are_safe_during_recording(self):
        self.status['state']='recording'
        self.assertTrue(self.run_check()['ok'])

    def test_cached_connected_heartbeat_does_not_hide_missing_current_tcp(self):
        value=self.run_check(connected=False)
        self.assertFalse(value['ok'])
        self.assertEqual(next(row for row in value['checks'] if row['name']=='Bridge TCP')['state'],'fail')

    def test_tcp_inspection_matches_both_endpoint_and_owned_bridge_pid(self):
        text='0 0 192.168.1.129:12345 192.168.1.182:7447 users:(("zenoh-bridge-ro",pid=42,fd=9))\n'
        runner=lambda *a,**kw:subprocess.CompletedProcess(a,0,text,'')
        self.assertTrue(check.tcp_connection('192.168.1.182',42,runner))
        self.assertFalse(check.tcp_connection('192.168.1.182',43,runner))
        self.assertFalse(check.tcp_connection('192.168.1.18',42,runner))

    def test_missing_wired_route_and_duplicate_bridge_fail_with_next_steps(self):
        value=self.run_check(bridges=[{'pid':1,'executable':'/usr/bin/zenoh-bridge-ros2dds'},{'pid':2,'executable':'/other'}],route=None)
        self.assertFalse(value['ok'])
        failures=[row for row in value['checks'] if row['state']=='fail']
        self.assertEqual([row['name'] for row in failures],['Ethernet','Bridge instance'])
        self.assertTrue(all(row.get('next') for row in failures))

    def test_missing_helper_and_disconnected_pi_are_not_success(self):
        self.status['robot_link']='lost'
        value=self.run_check(helpers=[],active=False)
        self.assertFalse(value['ok'])
        self.assertIn('Rate helper',[row['name'] for row in value['checks'] if row['state']=='fail'])

    def test_unreachable_pi_reports_one_actionable_error(self):
        def fetch(url):raise OSError('timed out')
        self.fetch=fetch
        value=self.run_check()
        self.assertFalse(value['ok'])
        self.assertIn('SSD',value['checks'][-1]['next'])


if __name__=='__main__':unittest.main()
