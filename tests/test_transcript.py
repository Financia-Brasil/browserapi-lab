"""Conversa do painel: memória, orçamento, descarte em pares e nenhum disco."""

import json
from pathlib import Path
import tempfile
import threading
import unittest

from browserapi_lab.transcript import MAX_TEXT, MARKER, Transcript


class TestTranscript(unittest.TestCase):
    def test_turno_completo_com_metadados_sem_escrita_em_disco(self):
        transcript = Transcript()
        transcript.add_exchange('meu-gemini', 'Pergunta', 'Resposta', at='2026-10-28T10:00:00Z',
                                total_ms=1234.56)
        view = transcript.snapshot('meu-gemini')
        self.assertEqual([item['role'] for item in view['messages']], ['user', 'assistant'])
        self.assertEqual(view['messages'][0]['text'], 'Pergunta')
        self.assertEqual(view['messages'][1]['text'], 'Resposta')
        self.assertEqual(view['messages'][1]['total_ms'], 1234.6)
        self.assertIsNone(view['messages'][0]['total_ms'])
        self.assertEqual(view['messages'][1]['at'], '2026-10-28T10:00:00Z')
        self.assertEqual(view['revision'], 1)
        self.assertIn('memória', view['scope'])
        self.assertEqual(transcript.summary('meu-gemini')['turns'], 1)
        self.assertNotIn('Pergunta', json.dumps(transcript.summary('meu-gemini')))

    def test_nada_e_gravado_nem_copiado_para_recibo_ou_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Transcript()
            transcript.add_exchange('chat', 'texto privado', 'resposta privada')
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertNotIn('texto privado', json.dumps(transcript.snapshot('chat')['limits']))

    def test_orcamento_descarta_em_pares_e_preserva_o_turno_novo(self):
        transcript = Transcript(max_entries=4, max_characters=1000)
        for index in range(4):
            transcript.add_exchange('chat', f'pergunta {index}', f'resposta {index}')
        view = transcript.snapshot('chat')
        self.assertEqual(len(view['messages']), 4)
        self.assertEqual([item['text'] for item in view['messages']],
                         ['pergunta 2', 'resposta 2', 'pergunta 3', 'resposta 3'])
        self.assertEqual(transcript.summary('chat')['dropped'], 4)
        self.assertEqual(transcript.summary('chat')['turns'], 2)

    def test_orcamento_de_caracteres_nunca_deixa_metade_do_turno(self):
        transcript = Transcript(max_entries=40, max_characters=1000)
        for index in range(5):
            transcript.add_exchange('chat', f'p{index}' + 'x' * 100, f'r{index}' + 'y' * 100)
        messages = transcript.snapshot('chat')['messages']
        self.assertEqual([item['role'] for item in messages], ['user', 'assistant'] * (len(messages) // 2))
        self.assertEqual(messages[-1]['role'], 'assistant')
        self.assertLessEqual(sum(len(item['text']) for item in messages), 1000)

    def test_turno_novo_e_preservado_mesmo_acima_do_orcamento(self):
        transcript = Transcript(max_entries=2, max_characters=1000)
        transcript.add_exchange('chat', 'a' * 3000, 'b' * 3000)
        view = transcript.snapshot('chat')
        self.assertEqual(len(view['messages']), 2)
        self.assertEqual(sum(len(item['text']) for item in view['messages']), 6000)

    def test_texto_gigante_e_cortado_com_aviso_visivel(self):
        transcript = Transcript()
        transcript.add_exchange('chat', 'pergunta', 'r' * (MAX_TEXT + 50))
        text = transcript.snapshot('chat')['messages'][1]['text']
        self.assertLessEqual(len(text), MAX_TEXT + len(MARKER))
        self.assertTrue(text.endswith(MARKER))

    def test_entradas_invalidas_sao_recusadas_sem_registrar(self):
        transcript = Transcript()
        for name, question, answer in (('../escape', 'q', 'a'), ('chat', '', 'a'), ('chat', 'q', '   '),
                                       ('chat', None, 'a'), ('Chat Inválido!', 'q', 'a')):
            with self.assertRaises(ValueError):
                transcript.add_exchange(name, question, answer)
        self.assertEqual(transcript.snapshot('chat')['messages'], [])
        with self.assertRaises(ValueError):
            Transcript(max_entries=1)
        with self.assertRaises(ValueError):
            Transcript(max_characters=10)

    def test_caracteres_de_controle_e_metadados_invalidos_nao_quebram(self):
        transcript = Transcript()
        transcript.add_exchange('chat', 'pergunta\x00com nulo', 'resposta', at='inventado', total_ms=-5)
        view = transcript.snapshot('chat')
        self.assertEqual(view['messages'][0]['text'], 'perguntacom nulo')
        self.assertNotIn('inventado', view['messages'][0]['at'])
        self.assertIsNone(view['messages'][1]['total_ms'])

    def test_limpar_remove_so_uma_conexao_e_mantem_concorrencia_segura(self):
        transcript = Transcript()
        transcript.add_exchange('um', 'q1', 'a1')
        transcript.add_exchange('dois', 'q2', 'a2')
        self.assertEqual(transcript.clear('um'), 2)
        self.assertEqual(transcript.snapshot('um')['messages'], [])
        self.assertEqual(transcript.summary('um')['revision'], 2)
        self.assertEqual(transcript.summary('dois')['turns'], 1)
        with self.assertRaises(ValueError):
            transcript.clear('../escape')

    def test_escritas_concorrentes_nao_intercalam_turnos(self):
        transcript = Transcript(max_entries=400, max_characters=2_000_000)
        def write(index):
            for _ in range(20):
                transcript.add_exchange('chat', f'q{index}', f'a{index}')
        threads = [threading.Thread(target=write, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        messages = transcript.snapshot('chat')['messages']
        self.assertEqual(len(messages), 160)
        for index in range(0, len(messages), 2):
            pair = messages[index:index + 2]
            self.assertEqual(pair[0]['role'], 'user')
            self.assertEqual(pair[1]['role'], 'assistant')
            self.assertEqual(pair[0]['text'], pair[1]['text'].replace('a', 'q'))


if __name__ == '__main__':
    unittest.main()
