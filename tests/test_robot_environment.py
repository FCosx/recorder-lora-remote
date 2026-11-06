"""ROS selection must not silently reset settings or guess through conflicts."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from tools import robot_environment as ros


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'robot'
        self.ros = self.base / 'opt/ros'
        for name in ('humble', 'jazzy'):
            (self.ros / name).mkdir(parents=True)
            (self.ros / name / 'setup.bash').write_text('# ROS\n')

    def resolve(self, **kwargs):
        return ros.detect(self.root, ros_root=self.ros, environment=kwargs.pop('environment', {}),
                          evidence=kwargs.pop('evidence', []), **kwargs)

    def saved(self, domain=37, files=None):
        folder = self.root / 'zenoh'
        folder.mkdir(parents=True)
        (folder / 'robot-service.json').write_text(json.dumps({'ros_distro': 'jazzy', 'domain': domain,
            'setup_files': files or [str(self.ros/'jazzy/setup.bash')]}))
        (folder / 'robot.json5').write_text(json.dumps({'plugins': {'ros2dds': {'domain': domain}}}))

    def node(self, domain=42, distro='jazzy', environment=None):
        return {'domain': domain, 'distro': distro, 'environment': environment or {'ROS_DISTRO': distro}}

    def test_ros_domain_detected_without_loading_sourced_workspace(self):
        workspace = self.base / 'custom robot/install'
        workspace.mkdir(parents=True)
        (workspace/'setup.bash').write_text('# custom messages\n')
        value = self.resolve(environment={'ROS_DISTRO': 'jazzy', 'ROS_DOMAIN_ID': '42',
                                         'COLCON_PREFIX_PATH': str(workspace)})
        self.assertEqual((value['ros_distro'], value['domain']), ('jazzy', 42))
        self.assertEqual(value['setup_files'], [str(self.ros/'jazzy/setup.bash')])

    def test_unsourced_shell_can_detect_one_running_robot_domain(self):
        value = self.resolve(evidence=[self.node(89, 'humble')])
        self.assertEqual((value['ros_distro'], value['domain']), ('humble', 89))

    def test_conflicting_domain_evidence_defaults_to_zero(self):
        value = self.resolve(environment={'ROS_DOMAIN_ID': '0'}, evidence=[self.node(42)])
        self.assertEqual((value['ros_distro'], value['domain']), ('jazzy', 0))

    def test_multiple_running_domains_default_to_zero_but_allow_explicit_choice(self):
        self.assertEqual(self.resolve(evidence=[self.node(7), self.node(9)])['domain'], 0)
        self.assertEqual(self.resolve(domain=9, evidence=[self.node(7), self.node(9)])['domain'], 9)

    def test_two_installed_ros_versions_without_evidence_require_choice(self):
        with self.assertRaisesRegex(ValueError, 'Multiple ROS version'):
            self.resolve()
        self.assertEqual(self.resolve(distro='humble')['ros_distro'], 'humble')

    def test_explicit_distro_ignores_the_other_distro_domain(self):
        value=self.resolve(distro='jazzy',environment={'ROS_DISTRO':'humble','ROS_DOMAIN_ID':'42'},
                           evidence=[self.node(42,'humble'),self.node(9,'jazzy')])
        self.assertEqual(value['domain'],9)

    def test_repeat_setup_preserves_nonzero_domain_and_removes_saved_overlays(self):
        overlay=self.base/'saved install';overlay.mkdir();(overlay/'setup.bash').write_text('# saved\n')
        files=[str(self.ros/'jazzy/setup.bash'),str(overlay/'setup.bash')]
        self.saved(files=files)
        value=self.resolve(environment={'ROS_DOMAIN_ID':'0'})
        self.assertEqual(value['domain'],37)
        self.assertEqual(value['setup_files'],[files[0]])
        self.assertEqual(self.resolve(domain=12)['domain'],12)

    def test_missing_saved_workspace_does_not_block_standard_messages(self):
        self.saved(files=[str(self.ros/'jazzy/setup.bash'),str(self.base/'missing/setup.bash')])
        self.assertEqual(self.resolve()['setup_files'],[str(self.ros/'jazzy/setup.bash')])
        self.assertEqual(self.resolve(no_workspaces=True)['setup_files'],[str(self.ros/'jazzy/setup.bash')])

    def test_repeat_setup_does_not_add_an_unrelated_sourced_workspace(self):
        self.saved()
        overlay=self.base/'other robot/install';overlay.mkdir(parents=True)
        (overlay/'setup.bash').write_text('# other workspace\n')
        environment={'ROS_DISTRO':'jazzy','COLCON_PREFIX_PATH':str(overlay)}
        value=self.resolve(environment=environment)
        self.assertEqual(value['setup_files'],[str(self.ros/'jazzy/setup.bash')])
        with self.assertRaisesRegex(ValueError,'Workspace loading'):
            self.resolve(environment=environment,setups=[str(overlay/'setup.bash')])

    def test_isolated_colcon_packages_are_not_loaded(self):
        install=self.base/'ws/install';(install/'messages').mkdir(parents=True)
        (install/'setup.bash').write_text('# workspace\n');(install/'.colcon_install_layout').write_text('isolated')
        value=self.resolve(environment={'ROS_DISTRO':'jazzy','AMENT_PREFIX_PATH':
            str(install/'messages')+':'+str(self.ros/'jazzy')})
        self.assertEqual(value['setup_files'],[str(self.ros/'jazzy/setup.bash')])

    def test_ambiguous_node_workspaces_do_not_get_combined(self):
        nodes=[]
        for name in ('one','two'):
            path=self.base/name;path.mkdir();(path/'setup.bash').write_text('# setup\n')
            nodes.append(self.node(environment={'ROS_DISTRO':'jazzy','AMENT_PREFIX_PATH':str(path)}))
        self.assertEqual(self.resolve(evidence=nodes)['setup_files'],[str(self.ros/'jazzy/setup.bash')])

    def test_corrupt_or_disagreeing_saved_settings_are_preserved(self):
        self.saved()
        path=self.root/'zenoh/robot.json5'
        path.write_text('{"plugins":{"ros2dds":{"domain":99}}}')
        before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'disagree'):
            self.resolve()
        self.assertEqual(path.read_bytes(),before)

    def test_process_scan_excludes_bridge_helper_shell_and_daemon(self):
        proc=self.base/'proc';proc.mkdir()
        rows=[(10001,['python3','sensor.py'],True),(10002,['python3','robot_bandwidth.py'],True),
              (10003,['bash'],False),(10004,['_ros2_daemon'],True)]
        for number,argv,mapped in rows:
            item=proc/str(number);item.mkdir()
            (item/'cmdline').write_bytes(b'\0'.join(x.encode() for x in argv))
            (item/'maps').write_text('/opt/ros/jazzy/lib/librcl.so\n' if mapped else '/lib/libc.so\n')
            (item/'environ').write_bytes(b'ROS_DISTRO=jazzy\0ROS_DOMAIN_ID=74\0PASSWORD=not-retained\0')
        result=ros.process_evidence(proc,os.getuid())
        self.assertEqual([row['pid'] for row in result],[10001])
        self.assertEqual(result[0]['domain'],74)
        self.assertNotIn('PASSWORD',result[0]['environment'])

    def test_invalid_automatic_domain_hint_defaults_to_zero(self):
        for value in ('abc','233','-1','2;exit','1.0'):
            with self.subTest(value=value):
                self.assertEqual(self.resolve(distro='jazzy',environment={'ROS_DOMAIN_ID':value})['domain'],0)


if __name__=='__main__':unittest.main()
