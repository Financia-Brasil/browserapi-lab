import unittest
from browserapi_lab.context import plan, ContextError


class TestContext(unittest.TestCase):
    def test_single_message_is_not_rewritten(self):
        text,report=plan([{'role':'user','content':'Olá, preserve isto.'}])
        self.assertEqual(text,'Olá, preserve isto.')
        self.assertIsNone(report['token_count'])
        self.assertFalse(report['history_persisted'])

    def test_oversize_requires_explicit_retrieval(self):
        with self.assertRaises(ContextError):
            plan([{'role':'user','content':'pergunta'}],['documento '*5000])
        with self.assertRaises(ContextError):
            plan([{'role':'user','content':'instrução '*5000}],retrieve=True)

    def test_retrieval_preserves_instructions_and_current_question_with_provenance(self):
        messages=[{'role':'system','content':'NUNCA INVENTE NÚMEROS'},
                  {'role':'assistant','content':'história antiga '*3000},
                  {'role':'user','content':'Qual é o orçamento do projeto jabuticaba?'}]
        docs=['ruído '*20000,'Projeto jabuticaba: orçamento aprovado é 123 reais. '*100]
        text,report=plan(messages,docs,retrieve=True,budget=12000)
        self.assertLessEqual(len(text),12000)
        self.assertIn('NUNCA INVENTE NÚMEROS',text)
        self.assertIn(messages[-1]['content'],text)
        self.assertIn('documento 2; caracteres',text)
        self.assertIn('123 reais',text)
        self.assertTrue(report['reduced'])
        self.assertGreater(report['retrieved_chunks'],0)

    def test_malformed_tools_multimodal_and_huge_history_rejected(self):
        for data in (None,[],[{'role':'tool','content':'a'}],[{'role':'user','content':[]}],
                     [{'role':'assistant','content':'a'}],[{'role':'user','content':'','name':'x'}]):
            with self.subTest(data=data),self.assertRaises(ContextError):
                plan(data)
        with self.assertRaises(ContextError):
            plan([{'role':'user','content':'q'}],['x'*16_000_001],retrieve=True)
