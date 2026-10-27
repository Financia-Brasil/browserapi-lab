"""O experimento com o Chrome real não pode apodrecer em silêncio."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'native_open_probe.py'


def load():
    spec = importlib.util.spec_from_file_location('native_open_probe', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNativeOpenProbe(unittest.TestCase):
    def test_without_chrome_reports_skipped_never_pass(self):
        probe = load()
        with tempfile.TemporaryDirectory() as tmp, patch.object(probe, 'chrome_binary', return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            code = probe.main(['--output', str(Path(tmp) / 'probe')])
            result = json.loads((Path(tmp) / 'probe.json').read_text())
        self.assertEqual(code, 0)
        self.assertEqual(result['outcome'], 'SKIPPED')
        self.assertIn('google-chrome', result['error'])

    def test_failure_has_nonzero_exit_and_keeps_the_reason(self):
        probe = load()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            code = probe.finish({'outcome': 'FAIL', 'error': 'motivo'}, Path(tmp) / 'probe')
            self.assertEqual(json.loads((Path(tmp) / 'probe.json').read_text())['error'], 'motivo')
        self.assertEqual(code, 1)

    def test_wrapper_repeats_explicit_data_dir_and_drops_xdg(self):
        probe = load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'
            path = probe.write_wrapper(Path(tmp) / 'wrapper.sh', '/usr/bin/google-chrome', root)
            text = Path(path).read_text()
            executable = os.access(path, os.X_OK)
        self.assertTrue(executable)
        self.assertIn('unset XDG_CONFIG_HOME', text)
        self.assertIn('--user-data-dir="%s"' % root, text)
        self.assertTrue(text.rstrip().endswith('"$@"'))
