import unittest
from browserapi_lab.sender import evidence_of_send, control_kind

class TestEvidence(unittest.TestCase):
    def test_no_message_is_failure(self):
        self.assertFalse(evidence_of_send({'count': 1}, {'count': 1, 'last': 'oi'}, 'oi')[0])

    def test_wrong_text_is_failure(self):
        self.assertFalse(evidence_of_send({'count': 1}, {'count': 2, 'last': 'outro'}, 'oi')[0])

    def test_new_matching_message(self):
        self.assertTrue(evidence_of_send({'count': 1}, {'count': 2, 'last': 'oi'}, 'oi')[0])

    def test_kind(self):
        self.assertEqual(control_kind({'tag': 'textarea'}), 'textarea')
        self.assertEqual(control_kind({'tag': 'input'}), 'input')
        self.assertEqual(control_kind({'tag': 'div', 'contenteditable': 'true'}), 'contenteditable')
