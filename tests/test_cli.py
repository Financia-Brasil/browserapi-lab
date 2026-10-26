import contextlib
import io
import unittest
from unittest.mock import patch
from browserapi_lab.cli import main
from browserapi_lab.benchmark import percentile

class TestCLI(unittest.TestCase):
    def test_help(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exc:
                main(['--help'])
        self.assertEqual(exc.exception.code, 0)
        self.assertIn('verify', output.getvalue())

    def test_bad_iterations(self):
        for n in ('0', '-1', '1001'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                main(['verify', '--iterations', n])
            self.assertEqual(exc.exception.code, 2)

    def test_success_and_failure_exit_codes(self):
        for passed, code in ((True, 0), (False, 1)):
            with patch('browserapi_lab.benchmark.verify', return_value={'passed': passed}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['verify']), code)

    def test_missing_browser_is_not_success(self):
        with patch('browserapi_lab.benchmark.verify', side_effect=RuntimeError('private')), contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main(['verify']), 2)
        self.assertNotIn('private', output.getvalue())

    def test_percentile(self):
        self.assertEqual(percentile(list(range(1, 21))), 19)
        self.assertIsNone(percentile([]))
