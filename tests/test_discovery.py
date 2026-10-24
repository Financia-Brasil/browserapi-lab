"""Testes de pontuação/ranking (Marco 3) — puros, sem navegador.

Cobrem: ranking do composer, rejeição de classes dinâmicas,(contenteditable),
Shadow DOM/iframe, botão de envio, classificação de mensagens e detecção de drift.
"""

from __future__ import annotations

import unittest

from browserapi_lab.discovery import (
    ROLES,
    drift_report,
    rank_candidates,
    ranking_report,
    score_candidate,
)


def cand(**kwargs) -> dict:
    """Candidato sintético no formato devolvido pelo probe."""
    base = {
        "schema_version": "1.0",
        "tag": "div",
        "type": None,
        "role": None,
        "data_role": None,
        "accessible_name": "",
        "aria_label": None,
        "placeholder": None,
        "input_name": None,
        "id": None,
        "testid": None,
        "testid_value": None,
        "contenteditable": None,
        "disabled": False,
        "visible": True,
        "editable": False,
        "occurrences": 1,
        "selector": "div",
        "selector_kind": "tag",
        "uses_nth": False,
        "path_length": 1,
        "classes": [],
        "dynamic_class": False,
        "inside": "document",
        "frame_path": [],
        "shadow_path": [],
        "rect": {"w": 600, "h": 44, "x": 0, "y": 400},
        "text_length": 0,
        "has_code": False,
        "child_count": 0,
    }
    base.update(kwargs)
    return base


COMPOSER = cand(
    tag="textarea", id="composer", role="textbox", editable=True, visible=True,
    accessible_name="Mensagem para o chat", aria_label="Mensagem para o chat",
    placeholder="Digite sua mensagem", selector="#composer", selector_kind="id",
    classes=["composer-input"], text_length=0,
)
SEARCH = cand(
    tag="input", type="search", id="search", editable=True, visible=True,
    placeholder="Buscar nas conversas", accessible_name="Buscar nas conversas",
    selector="#search", selector_kind="id", rect={"w": 600, "h": 32, "x": 0, "y": 20},
)
CONTENTEDITABLE = cand(
    tag="div", contenteditable="true", role="textbox", editable=True, visible=True,
    aria_label="Mensagem para o chat", selector='div[aria-label="Mensagem para o chat"]',
    selector_kind="aria-label",
)
DYNAMIC = cand(
    tag="textarea", editable=True, visible=True, id=None,
    selector="div.ng-tns-c418 > textarea", selector_kind="path", path_length=2,
    classes=["ng-tns-c4187558392", "css-1x5jdmq"], dynamic_class=True,
)
NTH = cand(
    tag="textarea", editable=True, visible=True,
    selector="div > div:nth-of-type(2) > textarea", selector_kind="nth",
    uses_nth=True, path_length=3,
)
AMBIGUO = cand(
    tag="textarea", editable=True, visible=True, occurrences=4,
    selector="textarea", selector_kind="tag",
)
HIDDEN = cand(
    tag="textarea", editable=True, visible=False, selector="#oculto", selector_kind="id",
)
SHADOW = dict(COMPOSER, inside="open_shadow", shadow_path=["#composer-host"])
IFRAME = dict(COMPOSER, inside="iframe", frame_path=["#composer-frame"])


class TestComposer(unittest.TestCase):
    def test_textarea_vence_decoy_de_busca(self):
        ranking = rank_candidates([SEARCH, COMPOSER], "composer")
        self.assertEqual(ranking[0].selector, "#composer")
        self.assertEqual(ranking[1].selector, "#search")

    def test_contribuicoes_sao_explicaveis(self):
        scored = score_candidate(COMPOSER, "composer")
        for sinal in ("tag_textarea", "editable", "name_match", "kind_id", "visible"):
            self.assertIn(sinal, scored.signals, sinal)
        self.assertGreater(scored.score, 40)

    def test_contenteditable_e_forte(self):
        ranking = rank_candidates([SEARCH, CONTENTEDITABLE], "composer")
        self.assertEqual(ranking[0].selector, CONTENTEDITABLE["selector"])
        self.assertIn("tag_contenteditable", ranking[0].signals)

    def test_classe_dinamica_e_penalizada(self):
        limpo = score_candidate(COMPOSER, "composer")
        sujo = score_candidate(DYNAMIC, "composer")
        self.assertIn("dynamic_class", sujo.penalties)
        self.assertGreater(limpo.score, sujo.score)

    def test_nth_e_penalizado(self):
        simples = score_candidate(COMPOSER, "composer")
        com_nth = score_candidate(NTH, "composer")
        self.assertIn("uses_nth", com_nth.penalties)
        self.assertGreater(simples.score, com_nth.score)

    def test_ambiguidade_penalizada(self):
        unico = score_candidate(COMPOSER, "composer")
        multiplo = score_candidate(AMBIGUO, "composer")
        self.assertIn("ambiguous", multiplo.penalties)
        self.assertGreater(unico.score, multiplo.score)
        # penalidade é proporcional ao número de ocorrências extras
        self.assertLessEqual(multiplo.penalties["ambiguous"], -12.0)

    def test_invisivel_penalizado(self):
        visivel = score_candidate(COMPOSER, "composer")
        oculto = score_candidate(HIDDEN, "composer")
        self.assertIn("hidden", oculto.penalties)
        self.assertGreater(visivel.score, oculto.score)

    def test_shadow_e_iframe_chegam_ao_topo_com_pequena_penalidade(self):
        for candidato, chave in ((SHADOW, "inside_open_shadow"), (IFRAME, "inside_iframe")):
            ranking = rank_candidates([SEARCH, candidato], "composer")
            self.assertEqual(ranking[0].inside, candidato["inside"])
            self.assertIn(chave, ranking[0].penalties)
            self.assertGreater(ranking[0].score, ranking[1].score)

    def test_seletor_dependente_de_idioma_penalizado(self):
        por_id = score_candidate(COMPOSER, "composer")
        por_texto = score_candidate(CONTENTEDITABLE, "composer")
        self.assertIn("language_dependent_selector", por_texto.penalties)
        self.assertGreater(por_id.score, por_texto.score)


class TestSendButton(unittest.TestCase):
    def test_botao_enviar_vence_botao_generico(self):
        enviar = cand(
            tag="button", role="button", id="send", accessible_name="Enviar mensagem",
            aria_label="Enviar mensagem", selector="#send", selector_kind="id",
            rect={"w": 90, "h": 36, "x": 0, "y": 460},
        )
        generico = cand(
            tag="button", role="button", id="btn-1", accessible_name="Anexar arquivo",
            selector="#btn-1", selector_kind="id", rect={"w": 90, "h": 36, "x": 0, "y": 460},
        )
        ranking = rank_candidates([generico, enviar], "send_button")
        self.assertEqual(ranking[0].selector, "#send")
        self.assertIn("name_match", ranking[0].signals)

    def test_botao_desabilitado_penalizado(self):
        enviar = cand(tag="button", role="button", id="send", accessible_name="Enviar",
                      selector="#send", selector_kind="id")
        desabilitado = dict(enviar, id="send2", selector="#send2", disabled=True)
        ranking = rank_candidates([enviar, desabilitado], "send_button")
        self.assertEqual(ranking[0].selector, "#send")
        self.assertIn("disabled", ranking[1].penalties)

    def test_proximidade_do_composer_conta(self):
        perto = cand(tag="button", role="button", id="send", accessible_name="Enviar",
                     selector="#send", selector_kind="id", rect={"w": 80, "h": 36, "x": 20, "y": 410})
        longe = cand(tag="button", role="button", id="top", accessible_name="Enviar feedback",
                     selector="#top", selector_kind="id", rect={"w": 80, "h": 36, "x": 900, "y": 10})
        referencia = {"w": 600, "h": 44, "x": 0, "y": 400}
        ranking = rank_candidates([longe, perto], "send_button", reference_rect=referencia)
        self.assertEqual(ranking[0].selector, "#send")
        self.assertIn("near_composer", ranking[0].signals)


class TestMensagens(unittest.TestCase):
    def test_assistant_vs_user_por_data_role(self):
        assistente = cand(data_role="assistant", id="msg-2", selector="#msg-2",
                          selector_kind="id", text_length=320, has_code=True,
                          classes=["message"])
        usuario = cand(data_role="user", id="msg-1", selector="#msg-1",
                       selector_kind="id", text_length=18, classes=["message"])

        ranking_assistant = rank_candidates([usuario, assistente], "assistant_message")
        self.assertEqual(ranking_assistant[0].selector, "#msg-2")
        self.assertIn("data_role_yes", ranking_assistant[0].signals)
        self.assertIn("data_role_no", ranking_assistant[1].penalties)

        ranking_user = rank_candidates([usuario, assistente], "user_message")
        self.assertEqual(ranking_user[0].selector, "#msg-1")

    def test_ultima_mensagem_recebe_bonus(self):
        primeiro = cand(data_role="assistant", id="m1", selector="#m1", selector_kind="id",
                        text_length=10)
        ultimo = cand(data_role="assistant", id="m2", selector="#m2", selector_kind="id",
                      text_length=10)
        ranking = rank_candidates([primeiro, ultimo], "assistant_message")
        # empate em tudo, exceto o bônus de "última"
        self.assertEqual(ranking[0].selector, "#m2")
        self.assertIn("last_in_conversation", ranking[0].signals)

    def test_classe_indicativa_conta_sem_data_role(self):
        assistente = cand(classes=["assistant-turn"], id="a", selector="#a", selector_kind="id")
        usuario = cand(classes=["user-turn"], id="u", selector="#u", selector_kind="id")
        ranking = rank_candidates([usuario, assistente], "assistant_message")
        self.assertEqual(ranking[0].selector, "#a")
        self.assertIn("class_no", ranking[1].penalties)


class TestHintsEDrift(unittest.TestCase):
    def test_hint_conhecido_ajuda_mas_nao_decide(self):
        """Hipótese de site: bônus, nunca contrato (ADR-005)."""
        generico = cand(tag="textarea", editable=True, visible=True, id="unknown",
                        selector="#unknown", selector_kind="id")
        com_hint = cand(tag="textarea", editable=True, visible=True, id="prompt-textarea",
                        selector="#prompt-textarea", selector_kind="id")
        sem_hint = rank_candidates([generico, com_hint], "composer")
        com_hints = rank_candidates([generico, com_hint], "composer",
                                    known_hints=["prompt-textarea"])
        # o hint aumenta a distância, mas o vencedor já era o mesmo por estrutura
        self.assertEqual(sem_hint[0].selector, "#prompt-textarea")
        self.assertEqual(com_hints[0].selector, "#prompt-textarea")
        self.assertGreater(
            com_hints[0].score - com_hints[1].score,
            sem_hint[0].score - sem_hint[1].score,
        )

    def test_hint_nao_salva_candidato_ruim(self):
        otimo = COMPOSER
        ruim_com_hint = cand(tag="textarea", editable=True, visible=False, id="prompt-textarea",
                             selector="#prompt-textarea", selector_kind="id", occurrences=3)
        ranking = rank_candidates([otimo, ruim_com_hint], "composer",
                                  known_hints=["prompt-textarea"])
        self.assertEqual(ranking[0].selector, "#composer")

    def test_relatorio_de_ranking(self):
        relatorio = ranking_report({"url": "http://x", "visited_elements": 12,
                                    "candidates": [SEARCH, COMPOSER]}, "composer", top=1)
        self.assertEqual(relatorio["winner"]["selector"], "#composer")
        self.assertEqual(relatorio["candidate_count"], 1)
        self.assertEqual(relatorio["visited_elements"], 12)

    def test_ranking_vazio(self):
        relatorio = ranking_report({"candidates": []}, "composer")
        self.assertIsNone(relatorio["winner"])
        self.assertEqual(relatorio["candidates"], [])

    def test_drift_detecta_mudancas(self):
        antes = ranking_report({"candidates": [COMPOSER, SEARCH]}, "composer")
        depois = ranking_report({"candidates": [NTH, SEARCH]}, "composer")
        drift = drift_report(antes, depois)
        self.assertIn("#composer", drift["vanished"])
        self.assertIn("div > div:nth-of-type(2) > textarea", drift["appeared"])
        self.assertTrue(drift["winner_changed"])
        self.assertEqual(drift["winner_before"], "#composer")

    def test_drift_sem_mudanca(self):
        relatorio = ranking_report({"candidates": [COMPOSER]}, "composer")
        drift = drift_report(relatorio, relatorio)
        self.assertFalse(drift["winner_changed"])
        self.assertEqual(drift["vanished"], [])
        self.assertEqual(drift["appeared"], [])


class TestValidacoes(unittest.TestCase):
    def test_papel_invalido(self):
        with self.assertRaises(ValueError):
            score_candidate(COMPOSER, "nao_existe")

    def test_papeis_conhecidos(self):
        for papel in ROLES:
            score_candidate(cand(), papel)  # não deve estourar

    def test_ranking_numerado(self):
        ranking = rank_candidates([SEARCH, COMPOSER, NTH], "composer")
        self.assertEqual([item.rank for item in ranking], [1, 2, 3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
