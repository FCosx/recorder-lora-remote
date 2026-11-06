"""Corrupt, wrong-platform or unexpected archives must preserve the old binary."""
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import bridge_packages as packages


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'bridge.tar.gz'
        self.binary = b'\x7fELF\x02\x01' + b'\0'*12 + struct.pack('<H',62) + b'corrected-test-binary'
        self.build = {'bridge_version':packages.VERSION,'patch_sha256':packages.PATCH_SHA256,
                      'source_sha256':packages.SOURCE_SHA256,'arch':'x86_64',
                      'binary_sha256':hashlib.sha256(self.binary).hexdigest()}
        self.package = dict(self.build,file=f'bridge-{packages.PACKAGE_ID}-x86_64.tar.gz',
                            min_glibc='2.35',ros_distros=['humble','jazzy'])
        self.write_archive()

    def write_archive(self, extra=None, metadata=None):
        files={'bridge/zenoh-bridge-ros2dds-fixed':self.binary,
               'bridge/BUILD.json':json.dumps(metadata or self.build).encode(),
               'bridge/LICENSE':b'license','bridge/NOTICE.md':b'notice'}
        with tarfile.open(self.archive,'w:gz') as archive:
            for name,data in files.items():
                member=tarfile.TarInfo(name);member.size=len(data)
                archive.addfile(member,io.BytesIO(data))
            if extra:
                member=tarfile.TarInfo(extra);member.size=0;archive.addfile(member,io.BytesIO())
        self.package['sha256']=packages.digest(self.archive)

    def manifest(self):
        return {'format':1,'bridge_version':packages.VERSION,'patch_sha256':packages.PATCH_SHA256,
                'source_sha256':packages.SOURCE_SHA256,'packages':[self.package]}

    def old_install(self):
        old=self.root/'install/bin/zenoh-bridge-ros2dds-fixed';old.parent.mkdir(parents=True)
        old.write_bytes(b'existing verified bridge');old.chmod(0o755)
        return old

    def test_architecture_distro_and_minimum_runtime_are_checked(self):
        self.assertEqual(packages.select(self.manifest(),'humble','amd64',('glibc','2.35'))['arch'],'x86_64')
        for args in [('jazzy','arm64',('glibc','2.39')),('jazzy','x86_64',('glibc','2.31')),
                     ('jazzy','armv7l',('glibc','2.35')),('jazzy','x86_64',('musl','1.2'))]:
            with self.subTest(args=args),self.assertRaises(ValueError):packages.select(self.manifest(),*args)

    def test_wrong_patch_or_traversal_filename_is_rejected(self):
        value=self.manifest();value['patch_sha256']='0'*64
        with self.assertRaises(ValueError):packages.select(value,'jazzy','x86_64',('glibc','2.39'))
        value=self.manifest();value['packages'][0]['file']='../../unrelated-file'
        with self.assertRaises(ValueError):packages.select(value,'jazzy','x86_64',('glibc','2.39'))

    def test_tampered_download_does_not_replace_the_existing_bridge(self):
        old=self.old_install();before=old.read_bytes()
        self.archive.write_bytes(self.archive.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):packages.install(self.archive,self.package,self.root/'install')
        self.assertEqual(old.read_bytes(),before)

    def test_extra_paths_and_symlinks_are_never_extracted(self):
        for name in ('../../outside','bridge/another-executable'):
            self.write_archive(extra=name)
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'members'):
                packages.install(self.archive,self.package,self.root/'install')
        self.assertFalse((self.root/'outside').exists())
        with tarfile.open(self.archive,'w:gz') as archive:
            for name in ('bridge/zenoh-bridge-ros2dds-fixed','bridge/BUILD.json','bridge/LICENSE','bridge/NOTICE.md'):
                member=tarfile.TarInfo(name)
                member.type=tarfile.SYMTYPE;member.linkname='/tmp/recorder-not-an-extract-target'
                archive.addfile(member)
        self.package['sha256']=packages.digest(self.archive)
        with self.assertRaisesRegex(ValueError,'members'):
            packages.install(self.archive,self.package,self.root/'install')

    def test_wrong_binary_architecture_and_version_are_rejected(self):
        binary=self.root/'binary';binary.write_bytes(self.binary);binary.chmod(0o755)
        with self.assertRaisesRegex(ValueError,'wrong CPU'):packages.validate_binary(binary,'aarch64')
        with patch.object(packages.subprocess,'run',return_value=type('Result',(),{'stdout':'v1.10.0','stderr':''})()):
            with self.assertRaisesRegex(ValueError,'version'):packages.validate_binary(binary,'x86_64')
        with patch.object(packages.subprocess,'run',return_value=type('Result',(),{'stdout':'zenoh-bridge-ros2dds v1.10.1\n','stderr':''})()):
            packages.validate_binary(binary,'x86_64')

    def test_failed_runtime_check_preserves_old_binary(self):
        old=self.old_install();before=old.read_bytes()
        with patch.object(packages,'validate_binary',side_effect=ValueError('not runnable')):
            with self.assertRaisesRegex(ValueError,'not runnable'):
                packages.install(self.archive,self.package,self.root/'install')
        self.assertEqual(old.read_bytes(),before)
        self.assertEqual(list(old.parent.glob('.bridge-*')),[])

    def test_verified_install_records_provenance_and_detects_later_tampering(self):
        old=self.old_install()
        with patch.object(packages,'validate_binary') as validate:
            packages.install(self.archive,self.package,self.root/'install')
        validate.assert_called_once()
        self.assertEqual(old.read_bytes(),self.binary)
        self.assertTrue(packages.installed(self.root/'install'))
        old.write_bytes(b'changed later')
        self.assertFalse(packages.installed(self.root/'install'))

    def test_archive_build_metadata_must_match_the_catalog(self):
        build=copy.deepcopy(self.build);build['patch_sha256']='0'*64
        self.write_archive(metadata=build)
        with self.assertRaisesRegex(ValueError,'provenance'):
            packages.install(self.archive,self.package,self.root/'install')


if __name__=='__main__':unittest.main()
