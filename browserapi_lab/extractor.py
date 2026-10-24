"""Extração de texto limpo e Markdown mínimo (Marco 6).

Decisão (ADR-003): o extrator **nunca** toca o DOM real. Ele recebe uma string
HTML (capturada de um clone descartável pela página) e serializa em Python com
``html.parser``. Assim é impossível remover controles do DOM verdadeiro — o
extrator nem tem referência a ele.

Trata: parágrafos, títulos, listas (inclusive aninhadas), links, inline code,
blocos de código com linguagem, blockquote, tabelas simples, quebras de linha,
elementos ocultos e botões/controles de feedback (que são descartados).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence

# Ignorados por inteiro (inclusive o conteúdo).
SKIP_TAGS = {
    "script", "style", "noscript", "svg", "canvas", "head", "meta", "link",
    "button", "select", "textarea", "input", "form", "iframe", "video", "audio",
}

# Controles de feedback/UI que poluem a resposta (briefing pede removê-los).
SKIP_CLASS_PATTERNS = re.compile(r"(feedback|toolbar|actions|buttons|sr-only|visually-hidden)", re.I)

VOID_TAGS = {
    "br", "img", "hr", "input", "meta", "link", "source", "col", "area",
    "base", "wbr", "embed", "track", "param",
}

BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "aside", "figure", "figcaption",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "pre", "blockquote",
    "table", "thead", "tbody", "tfoot", "tr", "hr", "dl", "dt", "dd", "header",
    "footer", "nav", "details", "summary",
}

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


@dataclass
class _Node:
    tag: str
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List[Any] = field(default_factory=list)  # _Node | str


class _TreeBuilder(HTMLParser):
    """Constroi uma árvore mínima a partir do HTML (tolerante a HTML quebrado)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self._stack: List[_Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: Sequence[tuple]) -> None:
        node = _Node(tag.lower(), {str(k).lower(): (v if v is not None else "") for k, v in attrs})
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: Sequence[tuple]) -> None:
        node = _Node(tag.lower(), {str(k).lower(): (v if v is not None else "") for k, v in attrs})
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return
        # tag de fechamento órfã: ignorada (HTML real é assim)

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


def build_tree(html: str) -> _Node:
    parser = _TreeBuilder()
    parser.feed(html or "")
    parser.close()
    return parser.root


def is_hidden(node: _Node) -> bool:
    """Elemento oculto por atributo/estilo — não entra na extração."""
    attrs = node.attrs
    if "hidden" in attrs:
        return True
    if str(attrs.get("aria-hidden", "")).lower() == "true":
        return True
    style = str(attrs.get("style", "")).lower()
    if "display:none" in style.replace(" ", "") or "display: none" in style:
        return True
    if "visibility:hidden" in style.replace(" ", "") or "visibility: hidden" in style:
        return True
    return False


def _should_skip(node: _Node) -> bool:
    if node.tag in SKIP_TAGS:
        return True
    if is_hidden(node):
        return True
    classes = node.attrs.get("class", "")
    if classes and SKIP_CLASS_PATTERNS.search(classes):
        return True
    return False


def _text_of(node: _Node) -> str:
    """Texto puro de um nó (sem formatação), preservando espaços entre blocos."""
    parts: List[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        else:
            if _should_skip(child):
                continue
            if child.tag in BLOCK_TAGS:
                parts.append(" ")
            parts.append(_text_of(child))
            if child.tag in BLOCK_TAGS:
                parts.append(" ")
    return "".join(parts)


def _inline(node: _Node, depth: int = 0) -> str:
    """Renderiza conteúdo inline (parágrafos, células, itens de lista)."""
    parts: List[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
            continue
        if _should_skip(child):
            continue
        parts.append(_inline_node(child, depth))
    return normalize_inline("".join(parts))


def _inline_node(node: _Node, depth: int) -> str:
    tag = node.tag
    if tag == "br":
        return "\n"
    if tag == "a":
        text = _inline(node, depth)
        href = node.attrs.get("href", "").strip()
        if not href:
            return text
        return f"[{text}]({href})"
    if tag == "img":
        alt = node.attrs.get("alt", "")
        src = node.attrs.get("src", "")
        return f"![{alt}]({src})" if (alt or src) else ""
    if tag == "code":
        inner = _text_of(node)
        return f"`{inner.strip()}`" if inner.strip() else inner
    if tag in ("strong", "b"):
        inner = _inline(node, depth)
        return f"**{inner}**" if inner.strip() else inner
    if tag in ("em", "i"):
        inner = _inline(node, depth)
        return f"_{inner}_" if inner.strip() else inner
    if tag in ("ul", "ol"):
        # lista dentro de inline (raro): renderiza como bloco indentado
        bloco = _render_list(node, depth)
        return "\n" + bloco + "\n"
    if tag in BLOCK_TAGS:
        return "\n" + _block(node, depth) + "\n"
    return _inline(node, depth)


def _render_list(node: _Node, depth: int) -> str:
    ordered = node.tag == "ol"
    linhas: List[str] = []
    indice = 1
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                linhas.append(child.strip())
            continue
        if _should_skip(child):
            continue
        if child.tag != "li":
            # conteúdo solto dentro da lista: trata como item
            texto = _inline(child, depth)
            if texto.strip():
                linhas.append(("  " * depth) + texto)
            continue
        marcador = f"{indice}. " if ordered else "- "
        conteudo = _inline(child, depth + 1).strip()
        aninhadas = [c for c in child.children if not isinstance(c, str) and c.tag in ("ul", "ol")]
        linhas.append(("  " * depth) + marcador + conteudo.replace("\n", " "))
        for lista in aninhadas:
            linhas.append(_render_list(lista, depth + 1))
        indice += 1
    return "\n".join(linha for linha in linhas if linha.strip())


def _render_table(node: _Node) -> str:
    linhas: List[List[str]] = []
    cabecalho: List[str] = []

    def coletar(n: _Node) -> None:
        for child in n.children:
            if isinstance(child, str) or _should_skip(child):
                continue
            if child.tag == "tr":
                celulas = []
                for celula in child.children:
                    if isinstance(celula, str) or _should_skip(celula):
                        continue
                    if celula.tag in ("td", "th"):
                        celulas.append(_inline(celula).replace("|", "\\|").strip())
                if celulas:
                    linhas.append(celulas)
                    if any(c.tag == "th" for c in child.children if not isinstance(c, str)):
                        cabecalho.extend(celulas)
            elif child.tag in ("thead", "tbody", "tfoot"):
                coletar(child)

    coletar(node)
    if not linhas:
        return ""
    largura = max(len(linha) for linha in linhas)
    saida: List[str] = []
    primeira = linhas[0]
    saida.append("| " + " | ".join(primeira + [""] * (largura - len(primeira))) + " |")
    saida.append("| " + " | ".join(["---"] * largura) + " |")
    for linha in linhas[1:]:
        saida.append("| " + " | ".join(linha + [""] * (largura - len(linha))) + " |")
    return "\n".join(saida)


def _block(node: _Node, depth: int = 0) -> str:
    tag = node.tag
    if tag in HEADING_LEVELS:
        texto = _inline(node, depth).strip()
        return "#" * HEADING_LEVELS[tag] + " " + texto if texto else ""
    if tag == "pre":
        codigo = None
        for child in node.children:
            if not isinstance(child, str) and child.tag == "code":
                codigo = child
                break
        alvo = codigo if codigo is not None else node
        texto = _text_of(alvo).strip("\n")
        linguagem = ""
        if codigo is not None:
            classes = codigo.attrs.get("class", "")
            match = re.search(r"(?:language|lang)-([a-zA-Z0-9+#_-]+)", classes)
            if match:
                linguagem = match.group(1)
        return f"```{linguagem}\n{texto}\n```"
    if tag in ("ul", "ol"):
        return _render_list(node, depth)
    if tag == "li":
        return _inline(node, depth).strip()
    if tag == "blockquote":
        interno = _blocks(node, depth).strip()
        if not interno:
            return ""
        return "\n".join("> " + linha for linha in interno.splitlines())
    if tag == "table":
        return _render_table(node)
    if tag == "hr":
        return "---"
    if tag in ("thead", "tbody", "tfoot", "tr", "td", "th", "dl", "dt", "dd"):
        return _inline(node, depth).strip()
    # div/section/article/etc.: blocos internos se houver, senão inline
    return _blocks(node, depth).strip()


def _blocks(node: _Node, depth: int = 0) -> str:
    """Renderiza os filhos de um nó como sequência de blocos."""
    saida: List[str] = []
    buffer_inline: List[str] = []

    def fecha_inline() -> None:
        if buffer_inline:
            texto = normalize_inline("".join(buffer_inline))
            if texto.strip():
                saida.append(texto)
            buffer_inline.clear()

    for child in node.children:
        if isinstance(child, str):
            buffer_inline.append(child)
            continue
        if _should_skip(child):
            continue
        if child.tag in BLOCK_TAGS or any(
            not isinstance(neto, str) and neto.tag in BLOCK_TAGS for neto in child.children
        ):
            fecha_inline()
            bloco = _block(child, depth)
            if bloco.strip():
                saida.append(bloco)
        else:
            buffer_inline.append(_inline_node(child, depth))
    fecha_inline()
    return "\n\n".join(bloco for bloco in saida if bloco.strip())


def normalize_inline(text: str) -> str:
    """Colapsa espaços e tabulações, preservando quebras de linha significativas."""
    texto = text.replace("\t", " ")
    texto = re.sub(r"[ ]{2,}", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    return texto


def normalize_text(text: str) -> str:
    """Colapsa **toda** a whitespace: usado para comparar texto puro."""
    return re.sub(r"\s+", " ", text or "").strip()


def html_to_markdown(html: str) -> str:
    """Serializador DOM mínimo para Markdown (sobre string HTML, nunca o DOM vivo)."""
    raiz = build_tree(html)
    saida = _blocks(raiz)
    saida = re.sub(r"\n{3,}", "\n\n", saida).strip()
    return saida


def html_to_text(html: str) -> str:
    """Texto puro normalizado (baseline de comparação do Marco 6)."""
    return normalize_text(_text_of(build_tree(html)))


# --------------------------------------------------------------------------
# Integração com a página
# --------------------------------------------------------------------------

def ensure_probe(page: Any) -> None:
    """Instala o probe se ainda não estiver na página."""
    from .discovery import load_probe_js

    page.evaluate(
        """(js) => { if (!window.__bal) { eval(js); } }""",
        load_probe_js(),
    )


def extract(page: Any, selector: str, variants: Sequence[str] = ("markdown", "text_content", "inner_text")) -> Dict[str, Any]:
    """Extrai variantes de uma mensagem sem tocar no DOM real.

    * ``markdown``     — serializador Python sobre o HTML de um clone;
    * ``text_content`` — texto puro do mesmo clone (normalizado);
    * ``inner_text``   — ``innerText`` lido da página (depende de layout).
    """
    ensure_probe(page)
    html = page.evaluate("(sel) => window.__bal.snapshotHtml(sel)", selector)
    if html is None:
        raise ValueError(f"elemento não encontrado: {selector}")

    saida: Dict[str, Any] = {"selector": selector, "html_length": len(html)}
    if "markdown" in variants:
        saida["markdown"] = html_to_markdown(html)
    if "text_content" in variants:
        saida["text_content"] = html_to_text(html)
    if "inner_text" in variants:
        bruto = page.evaluate("(sel) => window.__bal.innerTextOf(sel)", selector)
        saida["inner_text"] = bruto if bruto is None else str(bruto).strip()
    return saida


def dom_fingerprint(page: Any, selector: str) -> Optional[Dict[str, Any]]:
    """Impressão digital do HTML — usada para provar que o DOM real não mudou."""
    ensure_probe(page)
    return page.evaluate("(sel) => window.__bal.domFingerprint(sel)", selector)
