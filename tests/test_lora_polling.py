"""Keep the accepted one-second default and exercise the two-second fallback."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lora.common import write_private
from lora.remote import run_remote
from tools.lora_recorder import main


class PollingTests(unittest.TestCase):
    def test_cli_default_and_explicit_intervals(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'remote.json'
            write_private(config, {'version': 1, 'role': 'remote',
                                  'key': bytes(32).hex(), 'state_file': 'state.sqlite3'})
            for options, expected in (([], 1), (['--poll-seconds', '1'], 1),
                                      (['--poll-seconds', '2'], 2)):
                with self.subTest(options=options), \
                     patch('sys.argv', ['lora_recorder.py', 'remote', '--config', str(config)] + options), \
                     patch('tools.lora_recorder.select_port', return_value='/fake-radio'), \
                     patch('lora.remote.run_remote') as start:
                    main()
                    self.assertEqual(start.call_args.kwargs, {'poll_seconds': expected})
            for value in ('0', '-1', 'nan', '1.5', '3'):
                with self.subTest(invalid=value), \
                     patch('sys.argv', ['lora_recorder.py', 'remote', '--poll-seconds', value]), \
                     contextlib.redirect_stderr(io.StringIO()), \
                     self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)

    def test_server_forwards_interval_and_always_closes_remote(self):
        for interval in (1, 2):
            with self.subTest(interval=interval), \
                 patch('lora.remote.Remote') as factory, \
                 patch('lora.remote.make_handler'), \
                 patch('lora.remote.ThreadingHTTPServer') as server, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                server.return_value.serve_forever.side_effect = KeyboardInterrupt
                with self.assertRaises(KeyboardInterrupt):
                    run_remote({}, bytes(32), Path('/unused'), '/fake-radio', 8081,
                               poll_seconds=interval)
                factory.assert_called_once_with(bytes(32), Path('/unused'), '/fake-radio',
                                                poll_seconds=interval)
                factory.return_value.start.assert_called_once()
                factory.return_value.close.assert_called_once()
                server.return_value.server_close.assert_called_once()
                self.assertIn(f'wait {interval} second(s)', output.getvalue())


if __name__ == '__main__':
    unittest.main()
