"""Bridge startup conditions and service ownership without altering the host."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import robot_bridge_service as service


class BridgeServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'eth-test/device').mkdir(parents=True)
        (self.root / 'eth-test/operstate').write_text('up')
        (self.root / 'wifi-test/device').mkdir(parents=True)
        (self.root / 'wifi-test/wireless').mkdir()
        (self.root / 'wifi-test/operstate').write_text('up')

    def route(self, dev='eth-test', **extra):
        row = {'dev': dev, 'prefsrc': '192.168.1.129', **extra}
        return lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps([row]))

    def test_only_a_direct_wired_route_is_ready(self):
        self.assertEqual(service.wired_route('192.168.1.182', self.route(), self.root), 'eth-test')
        self.assertIsNone(service.wired_route('192.168.1.182', self.route('wifi-test'), self.root))
        self.assertIsNone(service.wired_route('192.168.1.182', self.route(gateway='192.168.3.1'), self.root))
        self.assertIsNone(service.wired_route('192.168.1.182', self.route(prefsrc=None), self.root))
        self.assertIsNone(service.wired_route('192.168.1.182', self.route('docker0'), self.root))
        (self.root / 'eth-test/operstate').write_text('down')
        self.assertIsNone(service.wired_route('192.168.1.182', self.route(), self.root))

    def test_vlan_and_ethernet_bridge_resolve_to_their_physical_member(self):
        (self.root / 'vlan-test').mkdir()
        (self.root / 'vlan-test/lower_eth-test').symlink_to(self.root / 'eth-test')
        self.assertTrue(service.physical_wired('vlan-test', self.root))
        (self.root / 'br-test/brif').mkdir(parents=True)
        (self.root / 'br-test/brif/eth-test').symlink_to(self.root / 'eth-test')
        self.assertTrue(service.physical_wired('br-test', self.root))
        (self.root / 'wifi-bridge/brif').mkdir(parents=True)
        (self.root / 'wifi-bridge/brif/wifi-test').symlink_to(self.root / 'wifi-test')
        self.assertFalse(service.physical_wired('wifi-bridge', self.root))

    def test_missing_routes_and_unreadable_counters_are_not_ready(self):
        for stdout in ('[]', '{}', 'not JSON'):
            self.assertIsNone(service.wired_route('192.168.1.182',
                lambda *a, **kw: SimpleNamespace(stdout=stdout), self.root))

    def test_unit_has_persistent_lifecycle_and_stops_the_whole_process_group(self):
        text = service.service_text(self.root / 'robot space%test', self.root / 'settings.json')
        self.assertIn('KillMode=control-group', text)
        self.assertIn('Restart=always', text)
        self.assertIn('WantedBy=default.target', text)
        self.assertIn('space%%test', text)
        self.assertNotIn('network-online.target', text)
        self.assertIn('ExecStart=:', text)

    def test_user_ros_overlay_is_preserved_for_the_correct_distribution(self):
        overlay = self.root / 'workspace/install'
        overlay.mkdir(parents=True)
        (overlay / 'setup.bash').write_text('# workspace\n')
        env = {'ROS_DISTRO': 'jazzy', 'COLCON_PREFIX_PATH': str(overlay)}
        self.assertEqual(service.setup_files('jazzy', env), ['/opt/ros/jazzy/setup.bash', str(overlay/'setup.bash')])
        self.assertEqual(service.setup_files('humble', env), ['/opt/ros/humble/setup.bash'])

    def test_service_waits_until_wired_ready_and_then_executes_the_existing_launcher(self):
        settings = self.root / 'settings.json'
        settings.write_text(json.dumps({'root': str(self.root), 'config': str(self.root/'robot.json5'),
            'pi_url': 'http://192.168.1.182:8080', 'ros_distro': 'jazzy', 'domain': 42,
            'setup_files': ['/opt/ros/jazzy/setup.bash']}))
        with patch.object(service, 'wired_route', side_effect=[None, None, 'eth-test']), \
                patch.object(service.time, 'sleep') as sleep, patch.object(service.os, 'execve') as execute:
            service.run(settings)
        self.assertEqual(sleep.call_count, 2)
        executable, arguments, environment = execute.call_args.args
        self.assertEqual(executable, '/bin/bash')
        self.assertIn('start_zenoh_bridge.sh', arguments[-1])
        self.assertEqual(environment['ROS_DOMAIN_ID'], '42')
        self.assertNotIn('ROS_LOCALHOST_ONLY', environment)

    def test_only_exact_owned_launchers_are_identified(self):
        proc = self.root / 'proc'
        for number, command in [(10001, ['bash', 'tools/start_zenoh_bridge.sh']),
                                (10002, ['python3', '-c', 'tools/start_zenoh_bridge.sh']),
                                (10003, ['bash', '/different/robot/tools/start_zenoh_bridge.sh'])]:
            directory = proc / str(number)
            directory.mkdir(parents=True)
            (directory/'cmdline').write_bytes(('\0'.join(command)+'\0').encode())
            (directory/'cwd').symlink_to(self.root)
        self.assertEqual(service.manual_launchers(self.root, proc), [10001])

    def test_recording_blocks_restart_even_when_status_returns_successfully(self):
        with patch.object(service, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(b'{"state":"recording"}')
            with self.assertRaisesRegex(ValueError, 'Stop recording'):
                service.assert_idle('http://192.168.1.182:8080')


if __name__ == '__main__':
    unittest.main()
