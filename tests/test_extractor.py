"""Testes do extrator (Marco 6) — puros, sem navegador.

Cobrem o serializador Markdown mínimo e a remoção de ruído (ocultos, botões de
feedback), além da tolerância a HTML incompleto.
"""

from __future__ import annotations

import unittest

from browserapi_lab.extractor import (
    build_tree,
    html_to_markdown,
    html_to_text,
    is_hidden,
    normalize_text,
)

RESPOSTA = (
    '<p>Com certeza! Aqui está um <strong>resumo</strong> estruturado:</p>'
    '<h3>Passos</h3>'
    '<ol><li>Instale o <code>playwright</code></li><li>Rode o <code>doctor</code></li></ol>'
    '<h3>Exemplo</h3>'
    '<pre><code class="language-python">def hello():\n    print("olá")\n</code></pre>'
    '<p>Veja a <a href="https://example.com/doc">documentação</a>.</p>'
    '<blockquote>Atenção: concorrência 1.</blockquote>'
    '<table><thead><tr><th>Estratégia</th><th>Custo</th></tr></thead>'
    '<tbody><tr><td>fill</td><td>baixo</td></tr><tr><td>keyboard</td><td>médio</td></tr></tbody></table>'
    '<p style="display:none">texto oculto que não deve aparecer</p>'
    '<div class="feedback">'
    '<button aria-label="Boa resposta" type="button">👍</button>'
    '<button class="copy" aria-label="Copiar resposta" type="button">Copiar</button>'
    '</div>'
)


class TestMarkdown(unittest.TestCase):
    def test_paragrafos_e_titulos(self):
        md = html_to_markdown("<p>Olá</p><p>Tudo bem?</p><h3>Passos</h3>")
        self.assertIn("Olá", md)
        self.assertIn("Tudo bem?", md)
        self.assertIn("### Passos", md)

    def test_niveis_de_titulo(self):
        for nivel in range(1, 7):
            md = html_to_markdown(f"<h{nivel}>Título {nivel}</h{nivel}>")
            self.assertIn("#" * nivel + f" Título {nivel}", md)

    def test_lista_ordenada(self):
        md = html_to_markdown("<ol><li>um</li><li>dois</li></ol>")
        self.assertIn("1. um", md)
        self.assertIn("2. dois", md)

    def test_lista_nao_ordenada(self):
        md = html_to_markdown("<ul><li>a</li><li>b</li></ul>")
        self.assertIn("- a", md)
        self.assertIn("- b", md)

    def test_lista_aninhada(self):
        md = html_to_markdown("<ul><li>a<ul><li>a1</li></ul></li><li>b</li></ul>")
        self.assertIn("- a", md)
        self.assertIn("  - a1", md)

    def test_link(self):
        md = html_to_markdown('<p>Veja a <a href="https://x.com/doc">documentação</a>.</p>')
        self.assertIn("[documentação](https://x.com/doc)", md)

    def test_link_sem_href_vira_texto(self):
        md = html_to_markdown("<p><a>sem href</a></p>")
        self.assertIn("sem href", md)
        self.assertNotIn("[]", md)

    def test_inline_code(self):
        md = html_to_markdown("<p>use <code>fill()</code> aqui</p>")
        self.assertIn("`fill()`", md)

    def test_bloco_de_codigo_com_linguagem(self):
        md = html_to_markdown('<pre><code class="language-python">x = 1\ny = 2</code></pre>')
        self.assertIn("```python", md)
        self.assertIn("x = 1", md)
        self.assertTrue(md.rstrip().endswith("```"))

    def test_bloco_de_codigo_sem_linguagem(self):
        md = html_to_markdown("<pre><code>x = 1</code></pre>")
        self.assertIn("```\nx = 1", md)

    def test_blockquote(self):
        md = html_to_markdown("<blockquote>Atenção: concorrência 1.</blockquote>")
        self.assertIn("> Atenção: concorrência 1.", md)

    def test_tabela_simples(self):
        md = html_to_markdown(RESPOSTA)
        self.assertIn("| Estratégia | Custo |", md)
        self.assertIn("| --- | --- |", md)
        self.assertIn("| fill | baixo |", md)

    def test_negrito_e_italico(self):
        md = html_to_markdown("<p><strong>forte</strong> e <em>ênfase</em></p>")
        self.assertIn("**forte**", md)
        self.assertIn("_ênfase_", md)

    def test_hr(self):
        self.assertIn("---", html_to_markdown("<p>a</p><hr><p>b</p>"))

    def test_quebra_de_linha(self):
        md = html_to_markdown("<p>linha1<br>linha2</p>")
        self.assertIn("linha1\nlinha2", md)


class TestRuido(unittest.TestCase):
    def test_elemento_oculto_e_removido(self):
        md = html_to_markdown(RESPOSTA)
        self.assertNotIn("texto oculto", md)
        self.assertNotIn("não deve aparecer", md)

    def test_aria_hidden_removido(self):
        md = html_to_markdown('<p>visível</p><p aria-hidden="true">segredo de layout</p>')
        self.assertIn("visível", md)
        self.assertNotIn("segredo de layout", md)

    def test_atributo_hidden_removido(self):
        md = html_to_markdown("<p>ok</p><p hidden>escondido</p>")
        self.assertNotIn("escondido", md)

    def test_botoes_e_feedback_removidos(self):
        md = html_to_markdown(RESPOSTA)
        self.assertNotIn("Copiar", md)
        self.assertNotIn("👍", md)
        self.assertNotIn("Boa resposta", md)

    def test_script_e_style_removidos(self):
        md = html_to_markdown("<p>texto</p><script>var segredo=1;</script><style>p{}</style>")
        self.assertIn("texto", md)
        self.assertNotIn("segredo", md)

    def test_svg_removido(self):
        md = html_to_markdown("<p>ok</p><svg><text>ícone</text></svg>")
        self.assertNotIn("ícone", md)


class TestTextoPuro(unittest.TestCase):
    def test_normalizacao(self):
        self.assertEqual(normalize_text("a\n\n  b\t c "), "a b c")

    def test_texto_puro_sem_marcacao(self):
        texto = html_to_text(RESPOSTA)
        self.assertNotIn("#", texto)
        self.assertNotIn("|", texto)
        self.assertIn("def hello():", texto)
        self.assertNotIn("Copiar", texto)

    def test_is_hidden(self):
        arvore = build_tree('<p style="display:none">x</p><p>y</p>')
        oculto, visivel = arvore.children[0], arvore.children[1]
        self.assertTrue(is_hidden(oculto))
        self.assertFalse(is_hidden(visivel))


class TestRobustez(unittest.TestCase):
    def test_html_vazio(self):
        self.assertEqual(html_to_markdown(""), "")
        self.assertEqual(html_to_text(""), "")

    def test_html_sem_tags(self):
        self.assertEqual(html_to_markdown("texto puro"), "texto puro")

    def test_tag_nao_fechada(self):
        md = html_to_markdown("<p>aberta<div>depois</div>")
        self.assertIn("aberta", md)
        self.assertIn("depois", md)

    def test_tag_de_fechamento_orfa(self):
        md = html_to_markdown("<p>texto</span></p>")
        self.assertIn("texto", md)

    def test_entidades_html(self):
        md = html_to_markdown("<p>a &amp; b &mdash; c</p>")
        self.assertIn("a & b", md)
        self.assertIn("c", md)

    def test_espacos_excessivos(self):
        md = html_to_markdown("<p>a</p>\n\n\n<p>b</p>")
        self.assertNotIn("\n\n\n", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
