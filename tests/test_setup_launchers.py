"""Desktop launchers preserve ownership and reuse one authenticated controller."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lora import launcher
from tools import desktop_shortcuts


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.key=bytes(range(32))

    def test_shortcut_does_not_launch_anything_and_preserves_unmanaged_files(self):
        data=self.root/'data';desktop=self.root/'Desktop';desktop.mkdir()
        with patch.object(desktop_shortcuts.subprocess,'run') as run:
            paths=desktop_shortcuts.install('test.desktop','Recorder',['/path with spaces/tool','100%','$value'],
                                            'Open recorder',data,desktop)
        run.assert_not_called();self.assertEqual(len(paths),2)
        text=Path(paths[0]).read_text()
        self.assertIn('"/path with spaces/tool"',text);self.assertIn('100%%',text)
        self.assertIn('\\$value',text)
        Path(paths[0]).write_text('unmanaged\n')
        desktop_shortcuts.install('test.desktop','New',['new'],'Open recorder',data,desktop)
        self.assertEqual(Path(paths[0]).read_text(),'unmanaged\n')

    def test_lock_blocks_same_pairing_even_with_another_port_and_releases(self):
        with launcher.controller_lock(self.key,self.root):
            with self.assertRaisesRegex(ValueError,'already has'):
                with launcher.controller_lock(self.key,self.root):pass
            with launcher.controller_lock(bytes(32),self.root):pass
        with launcher.controller_lock(self.key,self.root):pass

    def test_existing_matching_controller_is_reused_without_service_or_radio_changes(self):
        value={'application':'robot-recorder-lora','pairing':launcher.fingerprint(self.key)}
        with patch.object(launcher,'info',return_value=value),patch.object(launcher.subprocess,'run') as run:
            self.assertEqual(launcher.open_remote(self.root,self.root/'remote.json',self.key,browser=False),value)
        run.assert_not_called()

    def test_other_pairing_is_rejected(self):
        with patch.object(launcher,'info',return_value={'pairing':'other'}),patch.object(launcher.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'different recorder'):
                launcher.open_remote(self.root,self.root/'remote.json',self.key,browser=False)
        run.assert_not_called()

    def test_service_starts_only_on_request_and_is_not_enabled_at_boot(self):
        value={'application':'robot-recorder-lora','pairing':launcher.fingerprint(self.key)}
        unit=self.root/'user/controller.service'
        with patch.object(launcher,'unit_path',return_value=unit), \
             patch.dict('os.environ',{'XDG_RUNTIME_DIR':str(self.root)}), \
             patch.object(launcher,'info',side_effect=[None,value]), \
             patch.object(launcher.subprocess,'run',return_value=subprocess.CompletedProcess([],3)) as run:
            launcher.open_remote(self.root,self.root/'config space.json',self.key,browser=False)
        commands=[call.args[0] for call in run.call_args_list]
        self.assertIn(['systemctl','--user','start',launcher.UNIT],commands)
        self.assertFalse(any('enable' in command or 'restart' in command for command in commands))
        self.assertIn('"'+str(self.root/'config space.json')+'"',unit.read_text())
        self.assertIn('KillMode=control-group',unit.read_text())

    def test_stop_does_not_kill_an_unmanaged_controller(self):
        unit=self.root/'unit';unit.write_text('unmanaged')
        with patch.object(launcher,'unit_path',return_value=unit),patch.object(launcher.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'No managed controller'):launcher.stop_remote()
        run.assert_not_called()


if __name__=='__main__':unittest.main()
