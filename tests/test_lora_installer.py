"""Install the paired zipapp with no network tools or system serial package."""

import json
import base64
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from lora.bundle import build_bundle
from lora.common import load_config, write_private
from lora.remote import Counter
from tools.lora_offline_bootstrap import decrypt_pairing, encrypt_pairing

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'remote.json'
        self.key = bytes(range(32)).hex()
        write_private(self.source, {'version': 1, 'role': 'remote', 'key': self.key,
                                   'state_file': 'remote-state.sqlite3'})
        self.bundle = build_bundle(ROOT, self.source, self.root / 'recorder-lora-remote.pyz')
        self.target = self.root / 'new laptop'
        self.config = self.root / 'new user config'
        self.empty_bin = self.root / 'empty-bin'
        self.empty_bin.mkdir()
        self.environment = dict(os.environ, PATH=str(self.empty_bin), PYTHONDONTWRITEBYTECODE='1')

    def install(self, bundle=None, pairing=None, passcode=None):
        command = [sys.executable, '-S', str(bundle or self.bundle), 'install',
                   '--directory', str(self.target), '--config-dir', str(self.config)]
        if pairing is not None:
            command += ['--pairing', str(pairing)]
        environment = dict(self.environment)
        if passcode is not None:
            environment['PATH'] = os.defpath
        return subprocess.run(command, input=None if passcode is None else passcode + '\n',
                              env=environment, capture_output=True, text=True, timeout=20)

    def encrypted_bundle(self):
        encrypted = self.root / 'pairing.enc.json'
        encrypted.write_bytes(encrypt_pairing(json.loads(self.source.read_text()), 'test-only-passphrase'))
        return encrypted, build_bundle(ROOT, None, self.root / 'encrypted.pyz', encrypted)

    def test_encrypted_first_install_then_update_without_passcode_or_openssl(self):
        encrypted, bundle = self.encrypted_bundle()
        self.assertNotIn(self.key.encode(), encrypted.read_bytes())
        self.assertNotIn(b'test-only-passphrase', encrypted.read_bytes())
        with zipfile.ZipFile(bundle) as archive:
            self.assertIn('pairing/remote.enc.json', archive.namelist())
            self.assertNotIn('pairing/remote.json', archive.namelist())
            for name in archive.namelist():
                self.assertNotIn(self.key.encode(), archive.read(name), name)
        result = self.install(bundle, passcode='test-only-passphrase')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('test-only-passphrase', result.stdout + result.stderr)
        _, key, state = load_config(self.config / 'remote.json', 'remote')
        self.assertEqual(key.hex(), self.key)
        counter = Counter(state)
        counter.ensure_at_least(500)
        counter.close()
        self.assertEqual((self.config / 'remote.json').stat().st_mode & 0o777, 0o600)
        result = self.install(bundle)  # Empty PATH, no passcode, no OpenSSL needed again.
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('passcode:', result.stderr)
        counter = Counter(state)
        self.assertEqual(counter.next(), 501)
        counter.close()

    def test_wrong_passcode_and_tampered_envelope_are_rejected(self):
        encrypted, bundle = self.encrypted_bundle()
        result = self.install(bundle, passcode='incorrect-test-passphrase')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Incorrect passcode or damaged', result.stderr)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.config.exists())
        original = json.loads(encrypted.read_bytes())
        for field in ('key_id', 'salt', 'ciphertext', 'mac'):
            changed = dict(original)
            if field in ('salt', 'ciphertext'):
                value = bytearray(base64.b64decode(changed[field]))
                value[-1] ^= 1
                changed[field] = base64.b64encode(value).decode()
            else:
                changed[field] = ('1' if changed[field][0] != '1' else '2') + changed[field][1:]
            with self.assertRaisesRegex(ValueError, 'Incorrect passcode or damaged'):
                decrypt_pairing(changed, 'test-only-passphrase')

    def test_encrypted_install_does_not_replace_other_pairing(self):
        _, bundle = self.encrypted_bundle()
        self.config.mkdir()
        previous = {'version': 1, 'role': 'remote', 'key': bytes(32).hex(),
                    'state_file': 'remote-state.sqlite3'}
        write_private(self.config / 'remote.json', previous)
        result = self.install(bundle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('different recorder', result.stderr)
        self.assertFalse(self.target.exists())
        self.assertEqual(json.loads((self.config / 'remote.json').read_text()), previous)

    def test_separate_encrypted_pairing_can_be_imported(self):
        encrypted, _ = self.encrypted_bundle()
        public = build_bundle(ROOT, None, self.root / 'public.pyz')
        result = self.install(public, encrypted, passcode='test-only-passphrase')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(load_config(self.config / 'remote.json', 'remote')[1].hex(), self.key)

    def test_offline_install_includes_serial_and_reinstall_preserves_pairing_and_counter(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Offline setup complete', result.stdout)
        self.assertIn('no Pi IP is needed', result.stdout)
        self.assertNotIn(self.key, result.stdout + result.stderr)
        _, key, state = load_config(self.config / 'remote.json', 'remote')
        self.assertEqual(key.hex(), self.key)
        self.assertEqual((self.config / 'remote.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.bundle.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.target / 'lora/remote.py').read_bytes(), (ROOT / 'lora/remote.py').read_bytes())
        self.assertTrue((self.target / 'vendor/pyserial-LICENSE.txt').is_file())
        # -S excludes the system pySerial. The installed launcher supplies its own.
        check = subprocess.run([sys.executable, '-S', '-c',
            'import runpy,sys; runpy.run_path(sys.argv[1],run_name="serial_probe"); import serial; print(serial.__file__); print(serial.__version__)',
            str(self.target / 'tools/lora_recorder.py')], env=self.environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn(str(self.target / 'vendor/serial'), check.stdout)
        counter = Counter(state)
        counter.ensure_at_least(200)
        counter.close()
        before = (self.config / 'remote.json').read_bytes()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.config / 'remote.json').read_bytes(), before)
        counter = Counter(state)
        self.assertEqual(counter.next(), 201)
        counter.close()

    def test_different_pairing_is_not_overwritten(self):
        self.config.mkdir()
        previous = {'version': 1, 'role': 'remote', 'key': bytes(reversed(range(32))).hex(),
                    'state_file': 'remote-state.sqlite3'}
        write_private(self.config / 'remote.json', previous)
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('different recorder', result.stderr)
        self.assertEqual(json.loads((self.config / 'remote.json').read_text()), previous)
        self.assertFalse(self.target.exists())

    def test_corrupt_installer_is_rejected_before_writing_files(self):
        damaged = self.root / 'damaged.pyz'
        with zipfile.ZipFile(self.bundle) as source, zipfile.ZipFile(damaged, 'w') as target:
            for name in source.namelist():
                data = source.read(name)
                if name == 'lora/remote.py':
                    data += b'\n# damaged transfer\n'
                target.writestr(name, data)
        result = self.install(damaged)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertFalse(self.target.exists())

    def test_public_installer_contains_no_pairing_and_can_import_private_authorization(self):
        public = build_bundle(ROOT, None, self.root / 'public.pyz')
        with zipfile.ZipFile(public) as archive:
            self.assertFalse(json.loads(archive.read('manifest.json'))['paired'])
            self.assertNotIn('pairing/remote.json', archive.namelist())
            for name in archive.namelist():
                self.assertNotIn(self.key.encode(), archive.read(name), name)
        result = self.install(public)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('authorization is still required', result.stdout)
        self.assertFalse((self.config / 'remote.json').exists())
        result = self.install(public, self.source)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        _, saved, state = load_config(self.config / 'remote.json', 'remote')
        self.assertEqual(saved.hex(), self.key)
        counter = Counter(state)
        counter.ensure_at_least(400)
        counter.close()
        result = self.install(public)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        counter = Counter(state)
        self.assertEqual(counter.next(), 401)
        counter.close()

    def test_public_install_rejects_a_different_supplied_pairing(self):
        self.assertEqual(self.install().returncode, 0)
        other = self.root / 'other.json'
        write_private(other, {'version': 1, 'role': 'remote', 'key': bytes(32).hex(),
                              'state_file': 'remote-state.sqlite3'})
        public = build_bundle(ROOT, None, self.root / 'public.pyz')
        result = self.install(public, other)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('different recorder', result.stderr)
        self.assertEqual(load_config(self.config / 'remote.json', 'remote')[1].hex(), self.key)


if __name__ == '__main__':
    unittest.main()
