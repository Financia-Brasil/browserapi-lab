from pathlib import Path
import tempfile
import unittest
from browserapi_lab.history import History


class TestHistory(unittest.TestCase):
    def test_no_file_until_opt_in_write_scope_isolation_and_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            history=History(tmp)
            self.assertEqual(history.stats()['records'],0)
            self.assertFalse(history.path.exists())
            history.append('one','private question','private answer',['private document'])
            history.append('two','other question','other answer')
            self.assertEqual(history.path.stat().st_mode & 0o777,0o600)
            self.assertEqual(len(history.read('one')),3)
            self.assertNotIn('other question',str(history.read('one')))
            self.assertFalse(history.stats()['encrypted'])
            history.clear()
            self.assertEqual(history.stats()['records'],0)
            self.assertNotIn(b'private question',history.path.read_bytes())

    def test_capacity_evicts_oldest_not_unbounded_and_scope_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            history=History(tmp,limit=30)
            history.append('one','a'*10,'b'*10)
            history.append('one','c'*10,'d'*10)
            self.assertLessEqual(history.stats()['characters'],30)
            self.assertNotIn(('user','a'*10),history.read('one'))
            with self.assertRaises(ValueError):history.read('../other')
            with self.assertRaises(ValueError):history.append('one','x'*31,'')
