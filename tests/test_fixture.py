"""Testes da fixture local (Marco 1) — exigem Chromium real.

A fixture é o "chão" do laboratório: se ela não se comportar de forma
determinística, nenhum experimento posterior vale nada.
"""

from __future__ import annotations

import unittest

from _harness import BrowserTestCase, REPO_ROOT


class FixtureTestCase(BrowserTestCase):
    def abre(self, query: str = "") -> None:
        self.page.goto(self.server.url("fake_chat.html", query), wait_until="load")
        self.page.wait_for_function("() => !!window.FakeChat")

    def estado(self) -> dict:
        return self.page.evaluate("() => window.FakeChat.state()")

    def configura(self, **kwargs) -> None:
        self.page.evaluate("(cfg) => window.FakeChat.config(cfg)", kwargs)

    def envia(self, texto: str = "Olá, fixture!") -> None:
        """Envia pela interface (não pela API): clica no botão Enviar."""
        root = self.page.evaluate(
            """() => {
              const host = document.getElementById('composer-host');
              if (host && host.shadowRoot) return 'shadow';
              if (document.getElementById('composer-frame')) return 'iframe';
              return 'document';
            }"""
        )
        alvo = self.page
        if root == "shadow":
            alvo = self.page.locator("#composer-host").locator("#composer")
        elif root == "iframe":
            alvo = self.page.frame_locator("#composer-frame").locator("#composer")
        else:
            alvo = self.page.locator("#composer")
        alvo.fill(texto)
        if root == "iframe":
            self.page.frame_locator("#composer-frame").locator("#send").click()
        elif root == "shadow":
            self.page.locator("#composer-host").locator("#send").click()
        else:
            self.page.locator("#send").click()


class TestComposer(FixtureTestCase):
    def test_textarea(self):
        self.abre("?composer=textarea")
        self.assertEqual(self.estado()["composer"], "textarea")
        self.assertEqual(self.page.locator("#composer").evaluate("el => el.tagName"), "TEXTAREA")

    def test_input(self):
        self.abre("?composer=input")
        self.assertEqual(self.page.locator("#composer").evaluate("el => el.tagName"), "INPUT")

    def test_contenteditable(self):
        self.abre("?composer=contenteditable")
        self.assertEqual(self.page.locator("#composer").evaluate("el => el.tagName"), "DIV")
        self.assertEqual(
            self.page.locator("#composer").get_attribute("contenteditable"), "true"
        )

    def test_open_shadow_dom(self):
        self.abre("?composer=textarea&shadow=1")
        self.assertTrue(self.page.evaluate("() => !!document.getElementById('composer-host').shadowRoot"))
        # alcançável pela automação
        self.page.locator("#composer-host").locator("#composer").fill("oi")
        self.assertEqual(
            self.page.evaluate("() => document.getElementById('composer-host').shadowRoot.getElementById('composer').value"),
            "oi",
        )

    def test_iframe_srcdoc(self):
        self.abre("?composer=textarea&iframe=1")
        self.assertTrue(self.page.locator("#composer-frame").count() == 1)
        self.page.frame_locator("#composer-frame").locator("#composer").fill("oi do iframe")
        self.assertEqual(
            self.page.evaluate(
                "() => document.getElementById('composer-frame').contentDocument.getElementById('composer').value"
            ),
            "oi do iframe",
        )

    def test_closed_shadow_dom_e_limitacao(self):
        self.abre("?composer=textarea&closed=1")
        # por design do navegador, não há como alcançar o conteúdo
        self.assertIsNone(self.page.evaluate("() => document.getElementById('composer-host').shadowRoot"))
        with self.assertRaises(Exception):
            self.page.locator("#composer").fill("x", timeout=1500)


class TestStreaming(FixtureTestCase):
    def test_fluxo_normal(self):
        self.abre("?composer=textarea&delay=2")
        self.envia("Mensagem de teste")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'done'", timeout=30_000)
        estado = self.estado()
        self.assertGreater(estado["chars"], 50)
        self.assertEqual(estado["user_messages"], 1)
        self.assertEqual(estado["pause_count"], 0)
        self.assertIsNotNone(estado["first_token_ms"])
        self.assertEqual(estado["aria_busy"], "false")
        self.assertEqual(self.page.evaluate("() => window.FakeChat.lastUserMessage()"), "Mensagem de teste")

    def test_resposta_contem_estrutura(self):
        self.abre("?composer=textarea&delay=1")
        self.envia("Estrutura")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'done'", timeout=30_000)
        html = self.page.evaluate("() => window.FakeChat.assistantHtml()")
        for trecho in ("<h3>", "<pre>", "<code", "<ol>", "<li>", "<a href", "<blockquote>", "<table>"):
            self.assertIn(trecho, html)

    def test_pausa_artificial_de_3s(self):
        """Base para E-OBS: a pausa precisa existir de fato na fixture."""
        self.abre("?composer=textarea&mode=pause&delay=1")
        self.envia("Pausa")
        self.page.wait_for_function("() => window.FakeChat.state().pause_count === 1", timeout=30_000)
        estado = self.estado()
        self.assertEqual(estado["pause_count"], 1)
        self.assertEqual(estado["status"], "paused")
        self.assertLess(estado["chars"], 1000)  # pausa acontece antes do fim
        self.page.wait_for_function("() => window.FakeChat.state().status === 'done'", timeout=30_000)

    def test_resposta_vazia(self):
        self.abre("?composer=textarea&mode=empty")
        self.envia("Vazia?")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'done'", timeout=30_000)
        estado = self.estado()
        self.assertEqual(estado["chars"], 0)
        self.assertEqual(self.page.evaluate("() => window.FakeChat.assistantHtml().trim()"), "")

    def test_erro_generico(self):
        self.abre("?composer=textarea&mode=error")
        self.envia("Erro")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'error'", timeout=30_000)
        self.assertEqual(self.estado()["error"], "error")
        self.assertGreater(self.page.locator(".error[role=alert]").count(), 0)

    def test_rate_limit(self):
        self.abre("?composer=textarea&mode=ratelimit")
        self.envia("Muitas")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'error'", timeout=30_000)
        self.assertIn("Limite", self.page.locator(".error[role=alert]").inner_text())

    def test_login_expirado(self):
        self.abre("?composer=textarea&mode=login")
        self.envia("Login")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'error'", timeout=30_000)
        self.assertEqual(self.estado()["error"], "login")
        self.assertIn("login", self.page.locator(".error[role=alert]").inner_text().lower())


class TestSinaisDeUi(FixtureTestCase):
    def test_stop_aparece_durante_streaming(self):
        self.abre("?composer=textarea&delay=40")
        self.envia("Stop")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'streaming'", timeout=30_000)
        self.assertTrue(self.estado()["stop_visible"])
        self.assertEqual(self.estado()["aria_busy"], "true")
        self.page.evaluate("() => window.FakeChat.stop()")
        self.page.wait_for_function("() => window.FakeChat.state().status !== 'streaming'", timeout=30_000)
        self.assertFalse(self.estado()["stop_visible"])

    def test_copy_aparece_no_fim(self):
        self.abre("?composer=textarea&delay=1&copy=1")
        self.envia("Copy")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'done'", timeout=30_000)
        self.assertTrue(self.estado()["has_copy_button"])

    def test_copy_antes_da_estabilidade(self):
        """Cenário que engana quem decide o fim só por sinais de UI."""
        self.abre("?composer=textarea&delay=60&copy=1&copyEarly=1")
        self.envia("Copy cedo")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'streaming'", timeout=30_000)
        self.assertTrue(self.estado()["has_copy_button"], "Copy deveria aparecer antes do fim")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'done'", timeout=30_000)

    def test_stop_e_copy_dentro_de_shadow(self):
        self.abre("?composer=textarea&delay=30&shadow=1")
        self.envia("Shadow")
        self.page.wait_for_function("() => window.FakeChat.state().status === 'streaming'", timeout=30_000)
        self.assertTrue(self.estado()["stop_visible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
