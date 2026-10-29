"""Janelas do chat de navegador: blocos, delta, retomada, saída em blocos.

Testes sem navegador e sem rede: as contas são puras e o worker é exercitado
com ``exchange`` substituído por um chat simulado que **recusa** o que um chat
de verdade recusaria (texto maior que o campo, conversa maior que a janela).
"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from browserapi_lab import conversation as windows
from browserapi_lab.chat import ChatResult
from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.llm_api import Job, WarmBrowser
from browserapi_lab.setup import HYPOTHESES


def msg(role, text):
    return {'role': role, 'content': text}


class TestSplitting(unittest.TestCase):
    def test_short_text_is_one_send_without_header(self):
        sends = windows.chunk_sends('texto curto', windows.Limits())
        self.assertEqual(sends, ['texto curto'])

    def test_long_text_is_numbered_and_only_last_asks(self):
        text = '\n\n'.join('parágrafo ' + str(i) + ' ' + 'x' * 900 for i in range(40))
        sends = windows.chunk_sends(text, windows.Limits(message_chars=5_000))
        self.assertGreater(len(sends), 1)
        for index, send in enumerate(sends, start=1):
            self.assertLessEqual(len(send), 5_000, f'bloco {index} passou do teto')
            self.assertIn(f'[parte {index}/{len(sends)}', send)
        for send in sends[:-1]:
            self.assertIn('NÃO responda', send)
        self.assertIn('responda ao pedido final', sends[-1])
        # Nada foi perdido: o texto todo está nos blocos.
        joined = ''.join(sends)
        self.assertIn('parágrafo 39', joined)

    def test_paragraph_longer_than_limit_is_cut_not_dropped(self):
        sends = windows.chunk_sends('z' * 12_000, windows.Limits(message_chars=5_000))
        self.assertEqual(''.join(sends).count('z'), 12_000)
        for send in sends:
            self.assertLessEqual(len(send), 5_000)

    def test_overflow_raises_instead_of_dropping_text(self):
        with self.assertRaises(windows.WindowError):
            windows.chunk_sends('x' * 100_000, windows.Limits(message_chars=4_000, max_parts=4))


class TestRestore(unittest.TestCase):
    def test_recent_turns_stay_whole_and_old_ones_become_one_line(self):
        messages = [msg('system', 'instruções do sistema')]
        for index in range(20):
            messages.append(msg('user', f'pedido número {index} ' + 'detalhe ' * 50))
            messages.append(msg('assistant', f'resposta {index} ' + 'texto ' * 50))
        compact, info = windows.restore_messages(messages, windows.Limits())
        text = windows.render(compact)
        self.assertLess(len(text), len(windows.render(messages)))
        self.assertIn('instruções do sistema', text)
        self.assertIn('retomada de contexto', text)
        self.assertGreater(info['omitted'], 0)
        # O pedido atual nunca é cortado.
        self.assertIn('pedido número 19', text)
        self.assertIn('resposta 19', text)

    def test_tool_results_older_than_recent_are_trimmed_with_marker(self):
        messages = [msg('user', 'faça'), msg('assistant', '[resultado da ferramenta Read]\n' + 'y' * 9000)]
        for index in range(8):
            messages.append(msg('user', f'turno {index}'))
        reduced, report = windows.reduce_tool_results(messages, windows.Limits(tool_result_chars=2000))
        self.assertEqual(report['trimmed'], 1)
        self.assertGreater(report['characters'], 5000)
        self.assertIn('reduzido localmente', windows.render(reduced))


class TestPlanTurn(unittest.TestCase):
    def setUp(self):
        self.limits = windows.Limits(message_chars=5000, conversation_chars=12000)

    def test_first_turn_is_bootstrap_and_next_turn_is_delta(self):
        first = [msg('system', 'sistema'), msg('user', 'pedido A')]
        plan = windows.plan_turn(first, limits=self.limits, protocol='FERRAMENTAS…',
                                 reminder='[lembrete] X')
        self.assertEqual(plan.mode, 'bootstrap')
        self.assertIn('FERRAMENTAS', plan.sends[0])
        delivered = windows.Delivered(hashes=plan.hashes, characters=plan.characters, bootstrap=True)
        second = first + [msg('assistant', 'resposta A'), msg('user', 'pedido B')]
        delta = windows.plan_turn(second, delivered=delivered, limits=self.limits,
                                  protocol='FERRAMENTAS…', reminder='[lembrete] X')
        self.assertEqual(delta.mode, 'delta')
        self.assertEqual(len(delta.sends), 1)
        self.assertIn('pedido B', delta.sends[0])
        # O que já foi enviado NÃO vai de novo; o lembrete curto vai.
        self.assertNotIn('pedido A', delta.sends[0])
        self.assertIn('[lembrete]', delta.sends[0])

    def test_rewritten_history_restores_instead_of_delta(self):
        first = [msg('system', 'sistema'), msg('user', 'pedido A')]
        plan = windows.plan_turn(first, limits=self.limits)
        delivered = windows.Delivered(hashes=plan.hashes, characters=plan.characters, bootstrap=True)
        # O agente compactou o próprio histórico: o começo não confere mais.
        rewritten = [msg('system', 'sistema'), msg('system', 'resumo do que houve'),
                     msg('user', 'pedido B')]
        restore = windows.plan_turn(rewritten, delivered=delivered, limits=self.limits)
        self.assertEqual(restore.mode, 'restore')
        self.assertTrue(restore.rotate)
        self.assertIn('retomada', restore.sends[-1])

    def test_full_conversation_rotates_before_the_site_refuses(self):
        first = [msg('system', 'sistema'), msg('user', 'a' * 4000)]
        plan = windows.plan_turn(first, limits=self.limits)
        delivered = windows.Delivered(hashes=plan.hashes, characters=plan.characters, bootstrap=True)
        grown = first + [msg('assistant', 'resposta'), msg('user', 'b' * 4000)] * 2
        out = windows.plan_turn(grown, delivered=delivered, limits=self.limits)
        self.assertEqual(out.mode, 'restore')
        self.assertTrue(out.rotate)
        self.assertLessEqual(sum(len(send) for send in out.sends), self.limits.conversation_chars)

    def test_stateless_path_ignores_conversation_window(self):
        big = [msg('user', 'palavra ' * 3000)]
        plan = windows.plan_turn(big, limits=self.limits, stateless=True)
        self.assertEqual(plan.mode, 'bootstrap')
        self.assertGreater(len(plan.sends), 1)
        for send in plan.sends:
            self.assertLessEqual(len(send), self.limits.message_chars)
        # Acima do que os blocos comportam (max_parts × message_chars), recusa
        # em vez de cortar calado.
        with self.assertRaises(windows.WindowError):
            windows.plan_turn([msg('user', 'palavra ' * 20_000)], limits=self.limits,
                              stateless=True)
        small = windows.Limits(message_chars=5000, conversation_chars=12000, max_parts=2)
        with self.assertRaises(windows.WindowError):
            windows.plan_turn([msg('user', 'palavra ' * 3000)], limits=small, stateless=True)

    def test_unknown_contract_is_refused_with_the_client_vocabulary(self):
        anthropic = windows.dialect_error('anthropic', 300_000, windows.Limits())
        self.assertIn('prompt is too long', anthropic['error']['message'])
        self.assertTrue(anthropic['browserapi']['estimated'])
        openai = windows.dialect_error('openai-chat', 300_000, windows.Limits())
        self.assertEqual(openai['error']['code'], 'context_length_exceeded')


class TestOutputBlocks(unittest.TestCase):
    def test_open_fence_and_block_limit_ask_for_continuation(self):
        limits = windows.Limits(block_chars=2000)
        self.assertTrue(windows.needs_continuation('```python\ncodigo', 1, limits)[0])
        self.assertTrue(windows.needs_continuation('x' * 1900, 1, limits)[0])
        self.assertFalse(windows.needs_continuation('resposta curta', 1, limits)[0])
        self.assertFalse(windows.needs_continuation('x' * 1900, limits.max_blocks, limits)[0])

    def test_merge_removes_repeated_overlap_and_fim(self):
        self.assertEqual(windows.merge_blocks(['primeira parte', 'parte final']),
                         'primeira parte final')
        self.assertEqual(windows.merge_blocks(['abc def', 'def ghi']), 'abc def ghi')
        self.assertEqual(windows.merge_blocks(['texto completo', 'FIM']), 'texto completo')

    def test_estimate_is_labelled_and_never_zero_for_real_text(self):
        usage = windows.usage_block(4000, 400)
        self.assertEqual(usage['input_tokens'], 1000)
        self.assertEqual(usage['output_tokens'], 100)
        self.assertTrue(usage['browserapi']['estimated'])
        self.assertIn('estimativa', usage['browserapi']['note'].lower())


class SimulatedSite:
    """Chat de mentira com os limites de um chat de verdade (recusa, não finge)."""

    def __init__(self, limits, answer='resposta', not_ready=0, conversation=None,
                 truncate_after=None):
        self.limits = limits
        self.answer = answer
        self.not_ready = not_ready
        self.conversation = [] if conversation is None else conversation
        self.truncate_after = truncate_after
        self.calls = []
        self.refused = []

    def __call__(self, page, config, text, *, authorized=False, health_check=False, cancelled=None):
        self.calls.append(text)
        if self.not_ready > 0:
            self.not_ready -= 1
            return ChatResult('composer_missing', send_state='not_sent')
        if len(text) > self.limits.message_chars:
            self.refused.append(len(text))
            return ChatResult('send_unconfirmed', send_state='confirmed')
        if sum(len(item) for item in self.conversation) + len(text) > self.limits.conversation_chars * 2:
            self.refused.append(len(text))
            return ChatResult('send_unconfirmed', send_state='confirmed')
        self.conversation.append(text)
        answer = self.answer
        if self.truncate_after is not None and len(self.calls) == 1:
            answer = answer[:self.truncate_after]
        return ChatResult('success', True, answer=answer, send_state='confirmed')


class ReadyPage:
    """Página carregada: campo visível e editável."""

    def __init__(self, url='https://chat.example/t'):
        self.url = url
        # Identidade do documento: muda quando a página é recarregada.
        self.stamp = 1000.0

    def evaluate(self, script, *a):
        return self.stamp

    def is_closed(self):
        return False

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass

    def reload(self, *a, **kw):
        pass

    def goto(self, url, **kw):
        self.url = url

    def locator(self, selector):
        class _L:
            def count(self):
                return 1

            def is_visible(self):
                return True

            def is_editable(self):
                return True
        return _L()


class Session:
    def __init__(self, config):
        self.context = type('Ctx', (), {'pages': [ReadyPage()]})()
        self.context.new_page = lambda url=None: ReadyPage(url or 'https://chat.example/t')

    def start(self):
        pass

    def page(self, url=None):
        return self.context.pages[0]

    def new_page(self, url=None):
        return ReadyPage(url or 'https://chat.example/t')

    def close(self):
        pass


class TestWorkerWithSimulatedSite(unittest.TestCase):
    """O worker de verdade contra um site que recusa o que o de verdade recusaria."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))
        self.store.save(ChatConfig('saved', 'https://chat.example', **HYPOTHESES['fixture']))

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, sends, limits, **extra):
        job = Job(sends[-1], ['saved'], {'headless': False, 'lightweight': False, 'fallback': False},
                  {}, sends=list(sends), limits=limits, **extra)
        return job

    def test_bootstrap_parts_never_exceed_the_site_field(self):
        limits = windows.Limits(message_chars=5000, conversation_chars=60000)
        site = SimulatedSite(limits)
        plan = windows.plan_turn([msg('system', 's' * 3000), msg('user', 'x' * 9000)],
                                 limits=limits)
        job = self.job(plan.sends, limits)
        with patch('browserapi_lab.llm_api.exchange', side_effect=site):
            WarmBrowser(self.store, Session).run(job, lambda: False)
        self.assertEqual(job.result.status, 'success')
        self.assertEqual(site.refused, [])
        self.assertGreater(len(site.calls), 1)
        for call in site.calls:
            self.assertLessEqual(len(call), limits.message_chars)

    def test_page_not_ready_is_retried_and_the_cli_never_sees_an_error(self):
        limits = windows.Limits(message_chars=5000)
        site = SimulatedSite(limits, not_ready=2)
        job = self.job(['pergunta'], limits)
        with patch('browserapi_lab.llm_api.exchange', side_effect=site):
            WarmBrowser(self.store, Session).run(job, lambda: False)
        self.assertEqual(job.result.status, 'success')
        self.assertEqual(len(site.calls), 3)   # duas falhas antes de digitar + a boa
        self.assertEqual([a.get('retry') for a in job.attempts if a.get('retry')], [1, 2])

    def test_failure_that_may_have_been_sent_is_never_retried(self):
        limits = windows.Limits(message_chars=5000)
        calls = []

        def unclear(page, config, text, **kwargs):
            calls.append(text)
            return ChatResult('send_unconfirmed', send_state='unknown')

        job = self.job(['pergunta'], limits)
        with patch('browserapi_lab.llm_api.exchange', side_effect=unclear):
            WarmBrowser(self.store, Session).run(job, lambda: False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(job.result.status, 'send_unconfirmed')

    def test_truncated_answer_gets_one_continuation_and_is_merged(self):
        limits = windows.Limits(message_chars=5000, block_chars=1000)
        answers = ['a' * 1000, 'b' * 500]

        def exchange(page, config, text, **kwargs):
            return ChatResult('success', True, answer=answers.pop(0), send_state='confirmed')

        job = self.job(['pergunta'], limits)
        with patch('browserapi_lab.llm_api.exchange', side_effect=exchange):
            WarmBrowser(self.store, Session).run(job, lambda: False)
        self.assertEqual(job.result.status, 'success')
        self.assertEqual(job.result.answer, 'a' * 1000 + 'b' * 500)
        self.assertEqual(job.blocks, 2)
        # A continuação voltou com conteúdo e terminou naturalmente: o cliente
        # recebe end_turn, não um "cortado" que não houve.
        self.assertEqual(job.continuation_reason, 'natural')
        self.assertEqual(job.stop_reason, 'end_turn')

    def test_empty_page_after_reload_uses_the_self_contained_plan(self):
        limits = windows.Limits(message_chars=5000)
        plan = windows.plan_turn([msg('user', 'a'), msg('assistant', 'b'), msg('user', 'c')],
                                 limits=limits)
        job = self.job(plan.sends, limits)
        job.plan_report = {'mode': 'delta'}
        job.fallback_sends = ['[system]\ntudo de novo\n\n[user]\nc']
        # A aba foi reaberta: o chat pode estar vazio, então o envio é inteiro.
        job.page_reused = False
        site = SimulatedSite(limits)
        with patch('browserapi_lab.llm_api.exchange', side_effect=site):
            WarmBrowser(self.store, Session).run(job, lambda: False)
        self.assertEqual(job.result.status, 'success')
        self.assertEqual(site.calls, ['[system]\ntudo de novo\n\n[user]\nc'])
        self.assertTrue(job.conversation_shared)

    def two_turns(self, limits, reload=False, url_change=False):
        """Dois turnos na MESMA aba: o segundo é delta sobre a mesma conversa."""
        site = SimulatedSite(limits)
        browser = WarmBrowser(self.store, Session)
        with patch('browserapi_lab.llm_api.exchange', side_effect=site):
            first = self.job(['primeiro'], limits)
            browser.run(first, lambda: False)
            self.assertEqual(first.result.status, 'success')
            stamp = browser.page.stamp
            if reload:
                browser.page.stamp = stamp + 1   # documento novo, mesma URL
            if url_change:
                browser.page.url = 'https://chat.example/conversation-nova'
            plan = windows.plan_turn([msg('user', 'a'), msg('assistant', 'b'),
                                      msg('user', 'c')], limits=limits)
            job = self.job(plan.sends, limits)
            job.plan_report = {'mode': 'delta'}
            job.fallback_sends = ['[system]\ntudo de novo\n\n[user]\nc']
            job.previous_document = f'{stamp:.3f}'
            browser.run(job, lambda: False)
        return job, plan, site

    def test_reloaded_document_in_the_same_url_uses_the_self_contained_plan(self):
        # O caso que mais dói: o DOM parece vazio por carregamento preguiçoso e
        # a URL muda ao criar a conversa. Quem manda é o DOCUMENTO.
        limits = windows.Limits(message_chars=5000)
        job, plan, site = self.two_turns(limits, reload=True)
        self.assertEqual(job.result.status, 'success')
        self.assertEqual(site.calls[-1], '[system]\ntudo de novo\n\n[user]\nc')
        self.assertEqual(job.plan_report['fallback'], 'page_reloaded')
        self.assertEqual(job.characters, len(site.calls[-1]))
        self.assertTrue(job.conversation_shared)

    def test_same_document_and_new_url_still_sends_only_the_delta(self):
        # URL nova com o mesmo documento NÃO é conversa nova: mandar tudo de
        # novo entregava o contexto duas vezes ao site.
        limits = windows.Limits(message_chars=5000)
        job, plan, site = self.two_turns(limits, url_change=True)
        self.assertEqual(job.result.status, 'success')
        self.assertEqual(site.calls[-1], plan.sends[-1])
        self.assertNotIn('fallback', job.plan_report)

    def test_client_that_sends_only_the_new_message_gets_a_delta(self):
        # Regressão vista no CI com Chromium: o pedido 2 traz só "segunda
        # pergunta"; sem regra própria isso virava "histórico reescrito",
        # criava conversa nova e apagava a anterior.
        limits = windows.Limits(message_chars=5000)
        first = windows.plan_turn([msg('user', 'primeira')], limits=limits)
        self.assertEqual(first.mode, 'bootstrap')
        delivered = windows.Delivered(hashes=first.hashes, characters=first.characters,
                                      conversation='1000.000', bootstrap=True, turns=1)
        second = windows.plan_turn([msg('user', 'segunda')], delivered=delivered,
                                   limits=limits)
        self.assertEqual(second.mode, 'delta')
        self.assertFalse(second.rotate)
        self.assertEqual(second.report['reason'], 'history_omitted')
        self.assertEqual(second.sends, ['[user]\nsegunda'])
        # Já um histórico que não bate e tem mais de uma mensagem é reescrita.
        third = windows.plan_turn([msg('user', 'outra'), msg('assistant', 'x'),
                                   msg('user', 'mais')], delivered=delivered, limits=limits)
        self.assertEqual(third.mode, 'restore')
        self.assertTrue(third.rotate)

    def test_confirmed_send_that_times_out_is_waited_again_and_never_resent(self):
        # O relato: a mensagem aparece, o site demora, e o agente ouve "não está
        # funcionando" na primeira tentativa. Reenviar duplicaria a pergunta;
        # o certo é esperar de novo.
        limits = windows.Limits(message_chars=5000)
        calls = []

        def slow(page, config, text, **kwargs):
            calls.append(text)
            return ChatResult('timeout', send_state='confirmed')

        def later(page, config, **kwargs):
            return ChatResult('success', True, answer='resposta que chegou depois',
                              send_state='confirmed')

        job = self.job(['pergunta'], limits)
        with patch('browserapi_lab.llm_api.exchange', side_effect=slow), \
             patch('browserapi_lab.llm_api.harvest', side_effect=later):
            WarmBrowser(self.store, Session).run(job, lambda: False)
        self.assertEqual(calls, ['pergunta'])
        self.assertEqual(job.result.status, 'success')
        self.assertIn('resposta que chegou depois', job.result.answer)
        self.assertEqual(len(job.harvests), 1)
