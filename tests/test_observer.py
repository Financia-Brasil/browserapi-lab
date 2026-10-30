"""Testes da decisão de término (Marco 5) — puros, sem navegador.

Cada teste alimenta :func:`decide` com uma linha de tempo sintética (o mesmo que
o observador leria da página), o que permite provar comportamentos difíceis de
reproduzir de forma confiável: pausa artificial, resposta vazia, Copy antes da
estabilidade e timeout.
"""

from __future__ import annotations

import unittest

from browserapi_lab.observer import (
    POLICIES,
    Decision,
    StreamState,
    UiSignals,
    WatchConfig,
    decide,
)

JANELA = 1_200.0


def estado(instavel_há: float, texto: int = 120, decorrido: float = 5_000.0,
           mutacoes: int = 200, ultima: float = 4_000.0) -> StreamState:
    """Estado com 'silêncio' de ``instavel_há`` ms desde a última mutação."""
    return StreamState(
        mutation_count=mutacoes,
        first_token_ms=300.0,
        last_mutation_ms=ultima,
        since_last_mutation_ms=instavel_há,
        since_installed_ms=decorrido,
        text_len=texto,
        text_tail="...",
    )


def ui(stop: bool = False, copy: bool = False, busy: str | None = "false",
       pendentes: int = 0) -> UiSignals:
    return UiSignals(aria_busy=busy, stop_visible=stop, copy_visible=copy,
                     pending_indicators=pendentes)


class TestEstabilidade(unittest.TestCase):
    def test_nao_termina_durante_stream(self):
        for politica in POLICIES:
            with self.subTest(politica=politica):
                decisao = decide(estado(instavel_há=100), ui(stop=True, busy="true", pendentes=2),
                                 WatchConfig(policy=politica, stability_window_ms=JANELA))
                self.assertFalse(decisao.done, f"{politica} terminou durante o streaming")

    def test_stability_only_termina_apos_janela(self):
        decisao = decide(estado(instavel_há=JANELA + 50), ui(stop=False),
                         WatchConfig(policy="stability_only", stability_window_ms=JANELA))
        self.assertTrue(decisao.done)
        self.assertEqual(decisao.status, "success")
        self.assertIn("estável", decisao.reason)

    def test_stability_only_respeita_a_janela(self):
        decisao = decide(estado(instavel_há=JANELA - 50), ui(stop=False),
                         WatchConfig(policy="stability_only", stability_window_ms=JANELA))
        self.assertFalse(decisao.done)

    def test_pausa_artificial_nao_termina_prematuramente(self):
        """Cenário central do briefing: pausa de 3 s no meio do streaming."""
        config = WatchConfig(policy="hybrid", stability_window_ms=JANELA)
        for silencio in (0, 500, 1_000, 2_000, 2_900):
            with self.subTest(silencio=silencio):
                # durante a pausa o Stop continua visível e aria-busy segue true
                decisao = decide(estado(instavel_há=silencio), ui(stop=True, busy="true", pendentes=1), config)
                self.assertFalse(decisao.done, f"terminou com {silencio} ms de silêncio (pausa)")


class TestUiSignals(unittest.TestCase):
    def test_termina_quando_ui_confirma(self):
        decisao = decide(estado(instavel_há=200), ui(stop=False, copy=True, busy="false"),
                         WatchConfig(policy="ui_signals"))
        self.assertTrue(decisao.done)
        self.assertIn("sinais de UI", decisao.reason)

    def test_nao_termina_enquanto_stop_visivel(self):
        decisao = decide(estado(instavel_há=5_000), ui(stop=True, copy=True, busy="false"),
                         WatchConfig(policy="ui_signals"))
        self.assertFalse(decisao.done)

    def test_copy_antes_da_estabilidade_engana_ui_signals(self):
        """Documenta a falha conhecida: só sinais de UI aceitam Copy prematuro."""
        estado_cedo = estado(instavel_há=100)
        ui_cedo = ui(stop=False, copy=True, busy="false", pendentes=0)
        self.assertTrue(decide(estado_cedo, ui_cedo, WatchConfig(policy="ui_signals")).done)
        self.assertFalse(decide(estado_cedo, ui_cedo, WatchConfig(policy="hybrid")).done)
        self.assertFalse(decide(estado_cedo, ui_cedo,
                                WatchConfig(policy="stability_only", stability_window_ms=JANELA)).done)

    def test_sem_sinais_de_ui_disponiveis(self):
        decisao = decide(estado(instavel_há=9_000), None, WatchConfig(policy="ui_signals"))
        self.assertFalse(decisao.done)
        self.assertIn("sem sinais", decisao.reason)


class TestHibrido(unittest.TestCase):
    def test_exige_estabilidade_e_ausencia_de_stop(self):
        config = WatchConfig(policy="hybrid", stability_window_ms=JANELA)
        self.assertTrue(decide(estado(instavel_há=JANELA + 10), ui(stop=False, copy=False), config).done)
        self.assertFalse(decide(estado(instavel_há=JANELA + 10), ui(stop=True), config).done)

    def test_aceita_antecipado_com_ui_forte(self):
        config = WatchConfig(policy="hybrid", stability_window_ms=JANELA)
        curto = JANELA * 0.4
        decisao = decide(estado(instavel_há=curto), ui(stop=False, copy=True, busy="false"), config)
        self.assertTrue(decisao.done, "híbrido deveria aceitar com UI forte + estabilidade curta")
        self.assertIn("Copy", decisao.reason)

    def test_nao_aceita_antecipado_sem_copy(self):
        config = WatchConfig(policy="hybrid", stability_window_ms=JANELA)
        decisao = decide(estado(instavel_há=JANELA * 0.4), ui(stop=False, copy=False, busy="false"), config)
        self.assertFalse(decisao.done)

    def test_aria_busy_true_impede_antecipacao(self):
        config = WatchConfig(policy="hybrid", stability_window_ms=JANELA)
        decisao = decide(estado(instavel_há=JANELA * 0.9), ui(stop=False, copy=True, busy="true"), config)
        self.assertFalse(decisao.done)


class TestCasosLimite(unittest.TestCase):
    def test_resposta_vazia_nao_termina(self):
        for politica in POLICIES:
            with self.subTest(politica=politica):
                decisao = decide(estado(instavel_há=9_000, texto=0), ui(stop=False, copy=False),
                                 WatchConfig(policy=politica, stability_window_ms=JANELA))
                self.assertFalse(decisao.done, f"{politica} terminou sem conteúdo")

    def test_resposta_vazia_termina_por_timeout(self):
        decisao = decide(estado(instavel_há=61_000, texto=0, decorrido=61_000), None,
                         WatchConfig(policy="hybrid", timeout_ms=60_000))
        self.assertTrue(decisao.done)
        self.assertEqual(decisao.status, "timeout")

    def test_timeout_absoluto(self):
        decisao = decide(estado(instavel_há=100, decorrido=30_001), ui(stop=True),
                         WatchConfig(timeout_ms=30_000))
        self.assertTrue(decisao.done)
        self.assertEqual(decisao.status, "timeout")

    def test_min_text_len_configuravel(self):
        decisao = decide(estado(instavel_há=JANELA + 100, texto=5), ui(stop=False),
                         WatchConfig(policy="stability_only", stability_window_ms=JANELA, min_text_len=10))
        self.assertFalse(decisao.done)

    def test_bloqueios_tem_precedencia(self):
        for flag, esperado in (("captcha", "captcha"), ("login_required", "login_required"),
                               ("rate_limit", "rate_limit"), ("error", "error")):
            with self.subTest(flag=flag):
                sinais = UiSignals(**{flag: True})
                decisao = decide(estado(instavel_há=0, texto=10), sinais, WatchConfig())
                self.assertTrue(decisao.done)
                self.assertEqual(decisao.status, "blocked")
                self.assertIn(esperado, decisao.reason)

    def test_politica_invalida(self):
        with self.assertRaises(ValueError):
            decide(estado(instavel_há=0), None, WatchConfig(policy="inexistente"))


class TestUiSignalsModel(unittest.TestCase):
    def test_from_probe(self):
        sinais = UiSignals.from_probe({
            "aria_busy": "true",
            "stop_visible": True,
            "copy_visible": False,
            "pending_indicators": 2,
            "text_flags": {"captcha": False, "rate_limit": True, "login_required": False, "error": False},
        })
        self.assertTrue(sinais.stop_visible)
        self.assertEqual(sinais.aria_busy, "true")
        self.assertTrue(sinais.rate_limit)
        self.assertEqual(sinais.blocking, "rate_limit")

    def test_from_probe_vazio(self):
        sinais = UiSignals.from_probe({})
        self.assertIsNone(sinais.blocking)
        self.assertFalse(sinais.stop_visible)

    def test_decision_bool(self):
        self.assertTrue(bool(Decision(True)))
        self.assertFalse(bool(Decision(False)))


class TestStreamState(unittest.TestCase):
    def test_from_summary(self):
        estado = StreamState.from_summary({
            "mutation_count": 42,
            "first_token_ms": 310.5,
            "last_mutation_ms": 2400.0,
            "since_last_mutation_ms": 150.0,
            "since_installed_ms": 2550.0,
            "text_len": 880,
            "text_tail": "fim",
            "events": [{"t": 1, "n": 2, "len": 3}],
        })
        self.assertEqual(estado.mutation_count, 42)
        self.assertEqual(estado.first_token_ms, 310.5)
        self.assertEqual(estado.text_len, 880)
        self.assertEqual(len(estado.events), 1)

    def test_from_summary_vazio(self):
        estado = StreamState.from_summary({})
        self.assertEqual(estado.mutation_count, 0)
        self.assertIsNone(estado.first_token_ms)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestAmostrasEstaveis(unittest.TestCase):
    """Uma pausa do modelo não pode ser lida como fim da resposta.

    Dossiê 2026-10-28 (H3): o botão parar desaparece antes do texto terminar em
    vários chats, então o fim precisa de N leituras estáveis seguidas.
    """

    def test_tres_amostras_estaveis_antes_de_terminar(self):
        config = WatchConfig(policy='hybrid', stability_window_ms=JANELA, min_stable_samples=3)
        estaveis = estado(instavel_há=JANELA + 100)
        estaveis.stable_samples = 2
        self.assertFalse(decide(estaveis, ui(stop=False, busy='false'), config).done)
        estaveis.stable_samples = 3
        decisao = decide(estaveis, ui(stop=False, busy='false'), config)
        self.assertTrue(decisao.done)
        self.assertEqual(decisao.status, 'success')

    def test_mutacao_zera_as_amostras(self):
        config = WatchConfig(policy='stability_only', stability_window_ms=JANELA, min_stable_samples=3)
        instavel = estado(instavel_há=100)
        instavel.stable_samples = 0
        self.assertFalse(decide(instavel, ui(), config).done)
        # Voltar a silenciar depois de uma mutação recomeça a contagem do zero.
        instavel.since_last_mutation_ms = JANELA + 50
        instavel.stable_samples = 1
        decisao = decide(instavel, ui(), config)
        self.assertFalse(decisao.done)
        self.assertIn('aguardando', decisao.reason)

    def test_padrao_de_uma_amostra_preserva_o_comportamento_antigo(self):
        decisao = decide(estado(instavel_há=JANELA + 50), ui(stop=False),
                         WatchConfig(policy='stability_only', stability_window_ms=JANELA))
        self.assertTrue(decisao.done)


class TestJanelaDeConfirmacao(unittest.TestCase):
    """Uma pausa do modelo não pode virar "resposta terminou"."""

    def test_texto_que_volta_a_crescer_continua_a_espera(self):
        from unittest.mock import patch
        from browserapi_lab.observer import wait_for_completion

        # Três leituras estáveis, então o texto cresce uma vez, então estabiliza.
        roteiro = [100, 100, 100, 100, 150, 150, 150, 150, 150, 150, 150, 150]
        leituras = {'i': 0}

        def estado_falso(page):
            i = min(leituras['i'], len(roteiro) - 1)
            leituras['i'] += 1
            return StreamState(mutation_count=len(roteiro) + 10,
                               first_token_ms=10.0, last_mutation_ms=1000.0,
                               since_last_mutation_ms=JANELA + 100,
                               since_installed_ms=1000.0 + i * 100,
                               text_len=roteiro[i], text_tail='...')

        class Pagina:
            def wait_for_timeout(self, ms):
                pass

        with patch('browserapi_lab.observer.read_state', side_effect=estado_falso), \
             patch('browserapi_lab.observer.read_ui', return_value=ui(stop=False, copy=True)):
            observacao = wait_for_completion(
                Pagina(), WatchConfig(stability_window_ms=JANELA, timeout_ms=60_000,
                                      min_stable_samples=3, confirm_window_ms=1),
                '#conversa')
        self.assertEqual(observacao.status, 'success')
        # Terminou com o texto MAIOR: a pausa não cortou a resposta.
        self.assertEqual(observacao.text_len, 150)

    def test_sem_janela_de_confirmacao_o_comportamento_antigo_continua(self):
        self.assertEqual(WatchConfig().confirm_window_ms, 0.0)
