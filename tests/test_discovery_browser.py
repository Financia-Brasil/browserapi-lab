"""Descoberta contra DOM real (Marco 3) — exige Chromium.

Valida o probe injetado (travessia de Shadow DOM/iframes, geração de seletores)
e a pontuação em Python contra a fixture, nos três cenários do briefing.
"""

from __future__ import annotations

import unittest

from browserapi_lab.discovery import (
    collect,
    discover,
    drift_report,
    load_probe_js,
    ranking_report,
)

from _harness import BrowserTestCase

CAMPOS_OBRIGATORIOS = (
    "tag", "role", "visible", "editable", "occurrences", "selector",
    "selector_kind", "path_length", "inside", "classes",
)


class DescobertaTestCase(BrowserTestCase):
    def abre(self, query: str = "") -> None:
        self.page.goto(self.server.url("fake_chat.html", query), wait_until="load")
        self.page.wait_for_function("() => !!document.getElementById('composer-host')")

    def coleta(self, role: str) -> dict:
        return collect(self.page, role)


class TestProbe(DescobertaTestCase):
    def test_probe_instala_e_expõe_api(self):
        self.abre()
        self.page.evaluate(load_probe_js())
        api = self.page.evaluate("() => Object.keys(window.__bal)")
        for nome in ("collectCandidates", "uiSignals", "installWatcher", "streamSummary"):
            self.assertIn(nome, api)

    def test_varre_elementos(self):
        self.abre()
        payload = self.coleta("composer")
        self.assertGreater(payload["visited_elements"], 30)
        self.assertEqual(payload["role"], "composer")

    def test_candidatos_tem_campos_obrigatorios(self):
        self.abre()
        payload = self.coleta("composer")
        self.assertTrue(payload["candidates"])
        for candidato in payload["candidates"]:
            for campo in CAMPOS_OBRIGATORIOS:
                self.assertIn(campo, candidato)


class TestComposerReal(DescobertaTestCase):
    def test_dom_comum(self):
        self.abre("?composer=textarea")
        relatorio = discover(self.page, "composer")
        vencedor = relatorio["winner"]
        self.assertEqual(vencedor["selector"], "#composer")
        self.assertEqual(vencedor["inside"], "document")
        self.assertGreater(vencedor["score"], 40)

    def test_input(self):
        self.abre("?composer=input")
        vencedor = discover(self.page, "composer")["winner"]
        self.assertEqual(vencedor["selector"], "#composer")

    def test_contenteditable(self):
        self.abre("?composer=contenteditable")
        vencedor = discover(self.page, "composer")["winner"]
        self.assertEqual(vencedor["selector"], "#composer")

    def test_open_shadow_dom(self):
        self.abre("?composer=textarea&shadow=1")
        relatorio = discover(self.page, "composer")
        vencedor = relatorio["winner"]
        self.assertEqual(vencedor["selector"], "#composer")
        self.assertEqual(vencedor["inside"], "open_shadow")
        self.assertTrue(vencedor["frame_path"] == [])

    def test_iframe(self):
        self.abre("?composer=textarea&iframe=1")
        relatorio = discover(self.page, "composer")
        vencedor = relatorio["winner"]
        self.assertEqual(vencedor["selector"], "#composer")
        self.assertEqual(vencedor["inside"], "iframe")
        self.assertTrue(vencedor["frame_path"])

    def test_closed_shadow_dom_e_limitacao(self):
        """Closed Shadow DOM é inacessível: o laboratório registra, não finge."""
        self.abre("?composer=textarea&closed=1")
        relatorio = discover(self.page, "composer")
        self.assertIsNone(relatorio["winner"])
        self.assertEqual(relatorio["candidate_count"], 0)

    def test_busca_nao_enganja_o_ranking(self):
        self.abre("?composer=textarea")
        relatorio = discover(self.page, "composer", top=3)
        seletores = [item["selector"] for item in relatorio["candidates"]]
        self.assertEqual(seletores[0], "#composer")
        # o campo de busca existe e aparece, mas abaixo
        self.assertIn("#search", seletores)


class TestBotaoDeEnvio(DescobertaTestCase):
    def test_envia_no_dom_comum(self):
        self.abre("?composer=textarea")
        vencedor = discover(self.page, "send_button")["winner"]
        self.assertEqual(vencedor["selector"], "#send")

    def test_envia_dentro_de_shadow(self):
        self.abre("?composer=textarea&shadow=1")
        vencedor = discover(self.page, "send_button")["winner"]
        self.assertEqual(vencedor["selector"], "#send")
        self.assertEqual(vencedor["inside"], "open_shadow")

    def test_envia_dentro_de_iframe(self):
        self.abre("?composer=textarea&iframe=1")
        vencedor = discover(self.page, "send_button")["winner"]
        self.assertEqual(vencedor["selector"], "#send")
        self.assertEqual(vencedor["inside"], "iframe")


class TestMensagens(DescobertaTestCase):
    def _conversa(self) -> None:
        self.abre("?composer=textarea&delay=1")
        self.page.locator("#composer").fill("Classifique isto")
        self.page.locator("#send").click()
        self.page.wait_for_function("() => window.FakeChat.state().status === 'done'", timeout=30_000)

    def _vencedor_e_bruto(self, role: str):
        payload = collect(self.page, role)
        relatorio = ranking_report(payload, role)
        vencedor = relatorio["winner"]
        self.assertIsNotNone(vencedor, f"nenhum candidato para {role}")
        brutos = [c for c in payload["candidates"] if c["selector"] == vencedor["selector"]]
        return vencedor, (brutos[0] if brutos else {})

    def test_assistant_message(self):
        self._conversa()
        vencedor, bruto = self._vencedor_e_bruto("assistant_message")
        self.assertEqual(bruto.get("data_role"), "assistant")
        self.assertIn("data_role_yes", vencedor["signals"])

    def test_user_message(self):
        self._conversa()
        vencedor, bruto = self._vencedor_e_bruto("user_message")
        self.assertEqual(bruto.get("data_role"), "user")
        self.assertIn("data_role_yes", vencedor["signals"])

    def test_papeis_nao_se_confundem(self):
        self._conversa()
        _, assistente = self._vencedor_e_bruto("assistant_message")
        _, usuario = self._vencedor_e_bruto("user_message")
        self.assertNotEqual(assistente.get("selector"), usuario.get("selector"))

    def test_conversation_container(self):
        self._conversa()
        vencedor = discover(self.page, "conversation")["winner"]
        self.assertEqual(vencedor["selector"], "#conversation")


class TestDrift(DescobertaTestCase):
    def test_drift_entre_cenarios(self):
        """Mudando o DOM (shadow ligado), o ranking precisa acusar a mudança."""
        self.abre("?composer=textarea")
        antes = discover(self.page, "composer")
        self.abre("?composer=textarea&shadow=1")
        depois = discover(self.page, "composer")
        drift = drift_report(antes, depois)
        self.assertEqual(drift["winner_before"], "#composer")
        self.assertEqual(drift["winner_after"], "#composer")
        # mudou o "inside", não o seletor: drift estrutural deve ser reportado
        self.assertTrue(drift["vanished"] or drift["appeared"] or drift["score_drops"]
                        or drift["winner_changed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
