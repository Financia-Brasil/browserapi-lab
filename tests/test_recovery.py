import unittest
from unittest.mock import Mock
from browserapi_lab.browser import BrowserConfig, BrowserSession
from browserapi_lab.session import ProfileLock
from browserapi_lab.sender import evidence_of_send
import tempfile

class TestCleanup(unittest.TestCase):
    def test_stop_failure_still_releases_lock(self):
        with tempfile.TemporaryDirectory() as root:
            session = BrowserSession(BrowserConfig(profiles_root=root))
            session._lock.acquire()
            session._context = Mock()
            session._pw = Mock()
            session._pw.stop.side_effect = RuntimeError('driver failed')
            with self.assertRaises(RuntimeError):
                session.close()
            with ProfileLock(session.config.profile_dir):
                pass

    def test_mismatched_text_not_in_diagnostic(self):
        ok, detail = evidence_of_send({'count': 0}, {'count': 1, 'last': 'private-value'}, 'test')
        self.assertFalse(ok)
        self.assertNotIn('private-value', detail)
