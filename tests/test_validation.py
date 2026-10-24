import unittest
from browserapi_lab.validation import composer_evidence, select_output, validate_response


class TestComposerEvidence(unittest.TestCase):
    def test_combined_confirmation(self):
        self.assertTrue(composer_evidence('oi', 'oi', '', True).confirmed)

    def test_cleared_alone_is_not_confirmation(self):
        self.assertFalse(composer_evidence('oi', 'oi', '', False).confirmed)

    def test_missing_control_is_not_empty(self):
        self.assertFalse(composer_evidence('oi', 'oi', None, True).confirmed)

    def test_changed_or_wrong_value(self):
        self.assertFalse(composer_evidence('oi', 'outro', '', True).confirmed)
        self.assertFalse(composer_evidence('oi', 'oi', 'oi', True).confirmed)


class TestOutputContract(unittest.TestCase):
    valid = '{"request_id":"test-1","answer":"Olá"}'

    def test_current_response(self):
        self.assertTrue(validate_response(self.valid, 'test-1'))

    def test_previous_response(self):
        self.assertFalse(validate_response(self.valid, 'previous'))

    def test_rejects_invalid_shapes(self):
        for text in ('texto', '[]', '```json\n' + self.valid + '\n```',
                     '{"request_id":"test-1","answer":3}',
                     '{"request_id":"test-1","answer":"a","extra":1}',
                     '{"request_id":"test-1","answer":"a","answer":"b"}',
                     self.valid + ' texto', '{"request_id":"test-1"'):
            with self.subTest(text=text):
                self.assertFalse(validate_response(text, 'test-1'))

    def test_selects_only_valid_candidate(self):
        result = select_output(['Copiar', 'resposta antiga', self.valid], 'test-1')
        self.assertEqual((result.status, result.index), ('selected', 2))

    def test_ambiguous_is_not_silently_selected(self):
        result = select_output([self.valid, self.valid], 'test-1')
        self.assertEqual(result.status, 'ambiguous')
        self.assertIsNone(result.index)

    def test_no_match(self):
        self.assertEqual(select_output(['incompleto'], 'test-1').status, 'no_match')
