"""Buffer setup preserves stronger/custom settings and rolls back persistence failures."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tools import dds_transport as dds


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.limit=self.root/'limit';self.limit.write_text('212992')
        self.config=self.root/'dds.conf';self.calls=[];self.fail_move=False

    def runner(self,args,**kwargs):
        self.calls.append(args)
        if args[0]=='sysctl':self.limit.write_text(args[-1].split('=')[1])
        elif args[0]=='install':shutil.copyfile(args[-2],args[-1])
        elif args[0]=='mv':
            if self.fail_move:raise subprocess.CalledProcessError(1,args)
            Path(args[-2]).replace(args[-1])
        elif args[0]=='rm':Path(args[-1]).unlink(missing_ok=True)
        return subprocess.CompletedProcess(args,0,'','')

    def configure(self):return dds.configure(self.limit,self.config,self.runner,sudo=[])

    def test_ceiling_persisted_atomically_and_repeat_is_noop(self):
        self.assertTrue(self.configure()['changed'])
        self.assertEqual(int(self.limit.read_text()),dds.KERNEL_CAP)
        self.assertTrue(self.config.read_text().startswith(dds.MARKER+'\n'))
        count=len(self.calls);self.assertFalse(self.configure()['changed'])
        self.assertEqual(len(self.calls),count)

    def test_higher_tuning_is_not_lowered(self):
        self.limit.write_text(str(32*1024**2));self.assertFalse(self.configure()['changed'])
        self.assertEqual(self.calls,[])

    def test_unmanaged_file_is_preserved(self):
        self.config.write_text('user tuning\n')
        with self.assertRaisesRegex(ValueError,'unmanaged'):self.configure()
        self.assertEqual(self.calls,[]);self.assertEqual(self.config.read_text(),'user tuning\n')

    def test_persist_failure_restores_original_limit(self):
        self.config.write_text(dds.MARKER+'\nold setting\n');self.fail_move=True
        with self.assertRaises(subprocess.CalledProcessError):self.configure()
        self.assertEqual(self.limit.read_text(),'212992')
        self.assertEqual(self.config.read_text(),dds.MARKER+'\nold setting\n')
        self.assertFalse(self.config.with_name('.dds.conf.new').exists())

    def test_profile_preserves_custom_domain_and_interface_choices(self):
        self.assertTrue(dds.write_source_profile(self.root))
        path=self.root/'zenoh/source-cyclonedds.xml';text=path.read_text()
        self.assertIn('Id="any"',text);self.assertIn('min="4MiB"',text)
        self.assertNotIn('NetworkInterface',text)
        path.write_text('<CycloneDDS>operator supplied</CycloneDDS>')
        self.assertFalse(dds.write_source_profile(self.root));self.assertIn('operator supplied',path.read_text())

    def test_authentication_has_no_operation_timeout_and_later_commands_never_prompt(self):
        calls=[]
        def runner(args,**kwargs):
            calls.append((args,kwargs))
            if args==['sudo','-v']:return subprocess.CompletedProcess(args,0,'','')
            self.assertEqual(args[:2],['sudo','-n'])
            return self.runner(args[2:],**kwargs)
        dds.configure(self.limit,self.config,runner,sudo=['sudo'])
        self.assertNotIn('timeout',calls[0][1])
        self.assertTrue(all(kw['timeout']==15 for _,kw in calls[1:]))


if __name__=='__main__':unittest.main()
