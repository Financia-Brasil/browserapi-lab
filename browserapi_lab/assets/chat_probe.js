/* chat_probe.js — probe injetado automaticamente pelo Playwright (Marco 3 e 5).
 *
 * Regra do projeto (ADR-002): aqui fica SÓ o que exige estar dentro da página —
 * travessia de Shadow DOM/iframes, coleta de atributos e MutationObserver.
 * Pontuação, decisão de término e serialização ficam em Python.
 *
 * Nada de rede, nada de persistência, nada de dados privados: o probe devolve
 * apenas estrutura (tags, atributos, sinais de UI). Texto de mensagem volta
 * truncado e nunca é armazenado fora da página.
 */
(function () {
  "use strict";
  if (window.__bal) return;

  var SCHEMA_VERSION = "1.0";
  var MAX_ELEMENTS = 6000;      // teto de nós visitados por coleta
  var MAX_DEPTH = 6;            // profundidade de shadow/iframe
  var MAX_CANDIDATES = 60;
  var MAX_EVENTS = 400;         // eventos mantidos do stream

  var TESTID_ATTRS = ["data-testid", "data-test", "data-cy", "data-e2e", "data-qa", "data-id"];
  var ROLE_TAGS = { button: "button", a: "link", input: "input", textarea: "textbox" };

  /* --------------------------------- utils -------------------------------- */
  function now() { return performance.now(); }

  function truncate(value, limit) {
    var text = (value || "").replace(/\s+/g, " ").trim();
    return text.length > limit ? text.slice(0, limit) + "…" : text;
  }

  function accessibleName(el) {
    if (!el || !el.getAttribute) return "";
    var aria = el.getAttribute("aria-label");
    if (aria) return truncate(aria, 120);
    var labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      var ids = labelledBy.split(/\s+/);
      for (var i = 0; i < ids.length; i++) {
        var ref = document.getElementById(ids[i]);
        if (ref && ref.textContent) return truncate(ref.textContent, 120);
      }
    }
    if (el.id) {
      var label = document.querySelector('label[for="' + cssEscape(el.id) + '"]');
      if (label && label.textContent) return truncate(label.textContent, 120);
    }
    var title = el.getAttribute("title");
    if (title) return truncate(title, 120);
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
      var ph = el.getAttribute("placeholder");
      if (ph) return truncate(ph, 120);
    }
    return "";
  }

  function cssEscape(value) {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(value);
    return String(value).replace(/["\\]/g, "\\$&");
  }

  function isVisible(el) {
    if (!el) return false;
    var style = null;
    try { style = el.ownerDocument.defaultView.getComputedStyle(el); } catch (e) { return false; }
    if (!style) return false;
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
    if (el.hasAttribute("hidden")) return false;
    var rect = null;
    try { rect = el.getBoundingClientRect(); } catch (e) { rect = null; }
    if (rect && (rect.width > 0 || rect.height > 0)) return true;
    // sem layout (ex.: dentro de iframe oculto) — decisão conservadora
    return !!rect;
  }

  function isEditable(el) {
    if (!el) return false;
    if (el.disabled) return false;
    if (el.readOnly && el.tagName !== "DIV") return false;
    var ce = el.getAttribute && el.getAttribute("contenteditable");
    if (ce === "true" || ce === "") return true;
    var tag = el.tagName;
    if (tag === "TEXTAREA") return true;
    if (tag === "INPUT") {
      var type = (el.getAttribute("type") || "text").toLowerCase();
      return ["text", "search", "email", "url", "tel", "password"].indexOf(type) !== -1;
    }
    return false;
  }

  function classesOf(el) {
    var value = el.getAttribute && el.getAttribute("class");
    return value ? value.trim().split(/\s+/).filter(Boolean) : [];
  }

  // Classes geradas por frameworks/widgets: instáveis por construção.
  var DYNAMIC_CLASS = /(^|[-_])(ng-tns|ng-star|mat|mdc|css|sc-|svelte|emotion|jss|styled|tw-|makeStyles|Mui[A-Z])/i;
  var HASH_CLASS = /^[a-z]?[0-9a-f]{6,}$/i;

  function looksDynamic(name) {
    if (!name) return false;
    if (DYNAMIC_CLASS.test(name)) return true;
    if (HASH_CLASS.test(name)) return true;
    if (/[_:][a-z0-9]{6,}$/i.test(name)) return true;   // sufixo tipo css-1x5jdmq
    return false;
  }

  function testIdOf(el) {
    for (var i = 0; i < TESTID_ATTRS.length; i++) {
      var value = el.getAttribute(TESTID_ATTRS[i]);
      if (value) return { attr: TESTID_ATTRS[i], value: value };
    }
    return null;
  }

  /* --------------------------- geração de seletor -------------------------- */
  function uniqueIn(root, selector, el) {
    try {
      return root.querySelectorAll(selector).length === 1;
    } catch (e) {
      return false;
    }
  }

  function buildSelector(el, root) {
    // ordem de preferência: id estável > testid > aria-label > name/placeholder >
    // tag + atributos > caminho curto > nth (penalizado)
    var id = el.getAttribute && el.getAttribute("id");
    if (id && !looksDynamic(id) && uniqueIn(root, "#" + cssEscape(id), el)) {
      return { selector: "#" + cssEscape(id), kind: "id", usesNth: false };
    }
    var testid = testIdOf(el);
    if (testid) {
      var sel = "[" + testid.attr + '="' + cssEscape(testid.value) + '"]';
      if (uniqueIn(root, sel, el)) return { selector: sel, kind: "testid", usesNth: false };
    }
    var aria = el.getAttribute && el.getAttribute("aria-label");
    if (aria && aria.length <= 80) {
      var selAria = el.tagName.toLowerCase() + '[aria-label="' + cssEscape(aria) + '"]';
      if (uniqueIn(root, selAria, el)) return { selector: selAria, kind: "aria-label", usesNth: false };
    }
    var placeholder = el.getAttribute && el.getAttribute("placeholder");
    if (placeholder && placeholder.length <= 80) {
      var selPh = el.tagName.toLowerCase() + '[placeholder="' + cssEscape(placeholder) + '"]';
      if (uniqueIn(root, selPh, el)) return { selector: selPh, kind: "placeholder", usesNth: false };
    }
    var nameAttr = el.getAttribute && el.getAttribute("name");
    if (nameAttr) {
      var selName = el.tagName.toLowerCase() + '[name="' + cssEscape(nameAttr) + '"]';
      if (uniqueIn(root, selName, el)) return { selector: selName, kind: "name", usesNth: false };
    }
    var tag = el.tagName.toLowerCase();
    if (uniqueIn(root, tag, el)) return { selector: tag, kind: "tag", usesNth: false };

    var path = [], node = el, depth = 0;
    while (node && node.nodeType === 1 && depth < 4) {
      var parent = node.parentElement || (node.parentNode && node.parentNode.host) || null;
      var piece = node.tagName.toLowerCase();
      var nodeId = node.getAttribute && node.getAttribute("id");
      if (nodeId && !looksDynamic(nodeId)) { path.unshift(piece + "#" + cssEscape(nodeId)); break; }
      var nodeTestid = testIdOf(node);
      if (nodeTestid) { path.unshift(piece + "[" + nodeTestid.attr + '="' + cssEscape(nodeTestid.value) + '"]'); break; }
      var cls = classesOf(node).filter(function (c) { return !looksDynamic(c); })[0];
      if (cls) piece += "." + cssEscape(cls);
      path.unshift(piece);
      node = parent;
      depth += 1;
    }
    var cssPath = path.join(" > ");
    if (uniqueIn(root, cssPath, el)) {
      return { selector: cssPath, kind: "path", usesNth: false, pathLength: path.length };
    }
    // último recurso: nth-of-type (será penalizado pelo Python)
    var parent2 = el.parentElement;
    var index = 1;
    if (parent2) {
      var siblings = parent2.children;
      for (var i = 0; i < siblings.length; i++) {
        if (siblings[i] === el) { index = i + 1; break; }
      }
    }
    return {
      selector: cssPath + ":nth-of-type(" + index + ")",
      kind: "nth",
      usesNth: true,
      pathLength: path.length
    };
  }

  /* ------------------------------ travessia ------------------------------- */
  function walk(opts, visit) {
    var visited = 0;
    var notes = [];

    function recurse(root, inside, framePath, shadowPath, depth) {
      if (depth > MAX_DEPTH || visited > MAX_ELEMENTS) return;
      var nodes;
      try {
        nodes = root.querySelectorAll("*");
      } catch (e) {
        notes.push("falha ao varrer " + inside + ": " + e.message);
        return;
      }
      // Começar pela cauda mantém composer e mensagens novas acessíveis mesmo
      // quando o histórico ultrapassa o teto de nós visitados.
      for (var i = nodes.length - 1; i >= 0; i--) {
        if (visited >= MAX_ELEMENTS) return;
        var el = nodes[i];
        visited += 1;
        visit(el, root, inside, framePath, shadowPath, depth);

        // open shadow roots
        if (el.shadowRoot) {
          recurse(el.shadowRoot, "open_shadow", framePath, shadowPath.concat([buildSelector(el, root).selector]), depth + 1);
        } else if (el.tagName === "IFRAME") {
          var doc = null;
          try {
            doc = el.contentDocument;
          } catch (e) {
            notes.push("iframe de origem opaca ignorado: " + (el.id || el.src || "(srcdoc)"));
          }
          if (doc) {
            var frameSel = buildSelector(el, root).selector;
            recurse(doc, "iframe", framePath.concat([frameSel]), shadowPath, depth + 1);
          }
        }
      }
    }

    recurse(document, "document", [], [], 0);
    return { visited: visited, notes: notes };
  }

  /* ------------------------------ prefilhos ------------------------------- */
  var PREFILTER = {
    composer: function (el) {
      var tag = el.tagName;
      var ce = el.getAttribute && el.getAttribute("contenteditable");
      if (ce === "true" || ce === "") return true;
      if (tag === "TEXTAREA") return true;
      if (tag === "INPUT") {
        var type = (el.getAttribute("type") || "text").toLowerCase();
        return ["text", "search", "email", "url", "tel"].indexOf(type) !== -1;
      }
      if (el.getAttribute && (el.getAttribute("role") || "").toLowerCase() === "textbox") return true;
      return false;
    },
    send_button: function (el) {
      var tag = el.tagName;
      if (tag === "BUTTON") return true;
      if (tag === "INPUT" && (el.getAttribute("type") || "").toLowerCase() === "submit") return true;
      var role = (el.getAttribute && el.getAttribute("role")) || "";
      if (role.toLowerCase() === "button") return true;
      return false;
    },
    stop_button: function (el) {
      return PREFILTER.send_button(el);
    },
    copy_button: function (el) {
      return PREFILTER.send_button(el);
    },
    assistant_message: function (el) {
      return isMessageLike(el);
    },
    user_message: function (el) {
      return isMessageLike(el);
    },
    conversation: function (el) {
      var tag = el.tagName;
      var role = (el.getAttribute && el.getAttribute("role")) || "";
      if (role.toLowerCase() === "log" || role.toLowerCase() === "list") return true;
      if (el.hasAttribute && el.hasAttribute("aria-live")) return true;
      if (tag === "MAIN" || tag === "ARTICLE" || tag === "SECTION") return true;
      if (el.id && /convers|chat|thread|messages|history/i.test(el.id)) return true;
      if (classesOf(el).some(function (c) { return /convers|chat|thread|messages|history/i.test(c); })) return true;
      return false;
    }
  };

  function isMessageLike(el) {
    if (!el || el.nodeType !== 1) return false;
    var role = (el.getAttribute && el.getAttribute("data-role")) || "";
    if (role) return /user|assistant|model|human|ai|bot/i.test(role);
    var id = el.id || "";
    if (/^message|^msg|turn|response/i.test(id)) return true;
    var cls = classesOf(el).join(" ");
    if (/message|turn|response|bubble/i.test(cls)) return true;
    var testid = testIdOf(el);
    if (testid && /message|turn|response|conversation/i.test(testid.value)) return true;
    return false;
  }

  /* --------------------------- coleta de candidatos ----------------------- */
  function describe(el, root, inside, framePath, shadowPath) {
    var built = buildSelector(el, root);
    var cls = classesOf(el);
    var rect = null;
    try { rect = el.getBoundingClientRect(); } catch (e) { rect = null; }
    var testid = testIdOf(el);
    var textLen = (el.textContent || "").trim().length;

    return {
      schema_version: SCHEMA_VERSION,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute && el.getAttribute("type")) || null,
      role: (el.getAttribute && el.getAttribute("role")) || ROLE_TAGS[el.tagName.toLowerCase()] || null,
      data_role: (el.getAttribute && el.getAttribute("data-role")) || null,
      accessible_name: accessibleName(el),
      aria_label: (el.getAttribute && el.getAttribute("aria-label")) || null,
      placeholder: (el.getAttribute && el.getAttribute("placeholder")) || null,
      input_name: (el.getAttribute && el.getAttribute("name")) || null,
      id: (el.getAttribute && el.getAttribute("id")) || null,
      testid: testid ? testid.attr : null,
      testid_value: testid ? testid.value : null,
      contenteditable: (el.getAttribute && el.getAttribute("contenteditable")) || null,
      disabled: !!el.disabled,
      visible: isVisible(el),
      editable: isEditable(el),
      occurrences: countOccurrences(root, built.selector),
      selector: built.selector,
      selector_kind: built.kind,
      uses_nth: built.usesNth,
      path_length: built.pathLength || built.selector.split(" > ").length,
      classes: cls.slice(0, 8),
      dynamic_class: cls.some(looksDynamic),
      inside: inside,
      frame_path: framePath,
      shadow_path: shadowPath,
      rect: rect ? { w: Math.round(rect.width), h: Math.round(rect.height), x: Math.round(rect.width ? rect.left : 0), y: Math.round(rect.height ? rect.top : 0) } : null,
      text_length: textLen,
      has_code: !!el.querySelector("pre, code"),
      child_count: el.children ? el.children.length : 0
    };
  }

  function countOccurrences(root, selector) {
    try {
      return root.querySelectorAll(selector).length;
    } catch (e) {
      return -1;
    }
  }

  function collectCandidates(opts) {
    opts = opts || {};
    var role = opts.role || "composer";
    var prefilter = PREFILTER[role] || function () { return true; };
    var found = [];
    var result = walk(opts, function (el, root, inside, framePath, shadowPath) {
      if (!prefilter(el)) return;
      // A travessia já é newest-first; retenha os primeiros candidatos recentes.
      if (found.length >= MAX_CANDIDATES) return;
      found.push(describe(el, root, inside, framePath, shadowPath));
    });

    return {
      schema_version: SCHEMA_VERSION,
      role: role,
      url: location.href,
      visited_elements: result.visited,
      notes: result.notes,
      // Preserva ordem de documento esperada pelo ranking Python.
      candidates: found.reverse()
    };
  }

  /* --------------------------- sinais de UI -------------------------------- */
  var TEXT_PATTERNS = {
    captcha: /(captcha|verify you are (a )?human|are you a robot|confirme que você é humano|não sou um robô)/i,
    rate_limit: /(rate limit|too many requests|limite de requisi|muitas solicita)/i,
    login_required: /(sign in to continue|log in to continue|faça login|fazer login|entrar para continuar|sessão expirada)/i,
    error: /(something went wrong|algo deu errado|erro ao gerar|failed to generate)/i
  };

  function textFlags() {
    var text = "";
    // Não classificar opções, instruções nem o conteúdo da resposta como erros.
    var alerts = document.querySelectorAll('[role="alert"], [aria-live="assertive"], .error, .login-required');
    for (var i = 0; i < alerts.length; i++) {
      if (isVisible(alerts[i])) text += " " + (alerts[i].innerText || "");
    }
    if (text.length > 20000) text = text.slice(0, 20000);
    var flags = {};
    Object.keys(TEXT_PATTERNS).forEach(function (key) {
      flags[key] = TEXT_PATTERNS[key].test(text);
    });
    return flags;
  }

  function queryVisible(selectors) {
    for (var i = 0; i < selectors.length; i++) {
      try {
        var el = document.querySelector(selectors[i]);
        if (el && isVisible(el)) return { selector: selectors[i], found: true };
      } catch (e) { /* seletor inválido: ignora */ }
    }
    return { selector: null, found: false };
  }

  function uiSignals(opts) {
    opts = opts || {};
    var stopSel = opts.stopSelectors || [
      '[aria-label*="Stop" i]', '[aria-label*="Parar" i]', 'button:has-text("Stop")', '[data-testid*="stop" i]'
    ];
    var copySel = opts.copySelectors || [
      '[aria-label*="Copy" i]', '[aria-label*="Copiar" i]', '[data-testid*="copy" i]'
    ];
    var busy = null;
    var root = opts.rootSelector ? document.querySelector(opts.rootSelector) : document.body;
    if (root && root.getAttribute) {
      busy = root.getAttribute("aria-busy");
      if (busy === null && root.querySelector) {
        var busyEl = root.querySelector('[aria-busy="true"]');
        if (busyEl) busy = "true";
      }
    }
    // botões visíveis cujo nome sugere Stop/Copy (varredura leve)
    var buttons = [];
    try { buttons = Array.prototype.slice.call(document.querySelectorAll("button, [role=button]"), 0, 200); } catch (e) { buttons = []; }
    var stopVisible = false, copyVisible = false;
    buttons.forEach(function (btn) {
      var name = (btn.getAttribute("aria-label") || "") + " " + ((btn.textContent || "").trim());
      if (!isVisible(btn)) return;
      if (/(^|\W)(stop|parar|interromper)(\W|$)/i.test(name)) stopVisible = true;
      if (/(^|\W)(copy|copiar)(\W|$)/i.test(name)) copyVisible = true;
    });
    var foundStop = queryVisible(stopSel);
    var foundCopy = queryVisible(copySel);
    return {
      schema_version: SCHEMA_VERSION,
      aria_busy: busy,
      stop_visible: stopVisible || foundStop.found,
      stop_selector: foundStop.selector,
      copy_visible: copyVisible || foundCopy.found,
      copy_selector: foundCopy.selector,
      pending_indicators: countPendingIndicators(),
      text_flags: textFlags(),
      t_ms: now()
    };
  }

  function countPendingIndicators() {
    var count = 0;
    try {
      count += document.querySelectorAll('[aria-busy="true"]').length;
      count += document.querySelectorAll(".streaming, [data-status='streaming'], .animate-pulse, .typing, [data-testid*='loading' i]").length;
    } catch (e) { count = 0; }
    return count;
  }

  /* --------------------------- observação de stream ------------------------ */
  function installWatcher(opts) {
    // Reinstalação na aba quente não pode acumular MutationObservers.
    resetWatcher();
    opts = opts || {};
    var rootSelector = opts.rootSelector || "body";
    var root = document.querySelector(rootSelector) || document.body;
    var messageSelector = opts.messageSelector || null;
    var assistantSelector = opts.assistantSelector || null;

    var state = {
      schema_version: SCHEMA_VERSION,
      installed_at: now(),
      sent_at: null,
      mutation_count: 0,
      characterdata_count: 0,
      childlist_count: 0,
      attributes_count: 0,
      first_token_at: null,
      last_mutation_at: null,
      last_text_len: 0,
      last_text: "",
      events: [],
      observer: null
    };

    function textOf() {
      var target = null;
      if (assistantSelector) target = document.querySelector(assistantSelector);
      else if (messageSelector) {
        var nodes = document.querySelectorAll(messageSelector);
        if (typeof opts.messageCountBaseline === 'number' && nodes.length <= opts.messageCountBaseline) {
          return {text: "", len: 0};
        }
        target = nodes.length ? nodes[nodes.length - 1] : null;
      }
      if (!target) return { text: "", len: 0 };
      var text = (target.innerText !== undefined && target.innerText !== null)
        ? target.innerText
        : (target.textContent || "");
      return { text: text, len: text.length, target: target };
    }

    var observer = new MutationObserver(function (records) {
      var t = now();
      var added = 0, chardata = 0, attrs = 0;
      for (var i = 0; i < records.length; i++) {
        var rec = records[i];
        if (rec.type === "childList") added += rec.addedNodes.length;
        else if (rec.type === "characterData") chardata += 1;
        else if (rec.type === "attributes") attrs += 1;
      }
      state.mutation_count += records.length;
      state.childlist_count += added;
      state.characterdata_count += chardata;
      state.attributes_count += attrs;

      var snapshot = textOf();
      var grew = snapshot.len > state.last_text_len;
      state.last_text_len = snapshot.len;
      if (snapshot.text) state.last_text = snapshot.text;

      if (grew && state.first_token_at === null) state.first_token_at = t;
      // Relógios/sidebars fora da resposta não podem adiar o término.
      var responseMutation = snapshot.target && records.some(function (rec) {
        var node = rec.target.nodeType === 1 ? rec.target : rec.target.parentElement;
        if (node && (node === snapshot.target || snapshot.target.contains(node))) return true;
        return rec.type === 'childList' && Array.prototype.some.call(rec.addedNodes, function (added) {
          return added === snapshot.target || (added.nodeType === 1 && added.contains(snapshot.target));
        });
      });
      if (responseMutation || grew) state.last_mutation_at = t;

      if (state.events.length < MAX_EVENTS) {
        state.events.push({
          t: +(t - state.installed_at).toFixed(1),
          n: records.length,
          added: added,
          len: snapshot.len
        });
      }
    });

    observer.observe(root, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["aria-busy", "class", "data-status", "style", "disabled"]
    });

    state.observer = observer;
    window.__balStream = state;
    return { schema_version: SCHEMA_VERSION, installed: true, root: rootSelector };
  }

  function markSent() {
    if (window.__balStream) window.__balStream.sent_at = now();
    return true;
  }

  function streamSummary() {
    var s = window.__balStream;
    if (!s) return { schema_version: SCHEMA_VERSION, installed: false };
    var base = s.installed_at;
    function rel(value) { return value === null ? null : +(value - base).toFixed(1); }
    return {
      schema_version: SCHEMA_VERSION,
      installed: true,
      mutation_count: s.mutation_count,
      childlist_count: s.childlist_count,
      characterdata_count: s.characterdata_count,
      attributes_count: s.attributes_count,
      first_token_ms: rel(s.first_token_at),
      last_mutation_ms: rel(s.last_mutation_at),
      sent_ms: rel(s.sent_at),
      since_installed_ms: +(now() - base).toFixed(1),
      since_last_mutation_ms: s.last_mutation_at === null ? null : +(now() - s.last_mutation_at).toFixed(1),
      text_len: s.last_text_len,
      text_tail: s.last_text ? s.last_text.slice(-160) : "",
      events: s.events.slice(-40)
    };
  }

  function resetWatcher() {
    if (window.__balStream && window.__balStream.observer) {
      window.__balStream.observer.disconnect();
    }
    window.__balStream = null;
    return true;
  }

  /* --------------------------------- extras -------------------------------- */
  function snapshotHtml(selector) {
    var el = selector ? document.querySelector(selector) : document.body;
    if (!el) return null;
    // clone descartável: o DOM real nunca é tocado (ADR-003)
    return el.cloneNode(true).innerHTML;
  }

  function innerTextOf(selector) {
    var el = selector ? document.querySelector(selector) : document.body;
    if (!el) return null;
    return el.innerText !== undefined ? el.innerText : el.textContent;
  }

  function domFingerprint(selector) {
    var el = selector ? document.querySelector(selector) : document.body;
    if (!el) return null;
    var html = el.innerHTML || "";
    // FNV-1a: barato, suficiente para detectar alteração acidental do DOM
    var hash = 0x811c9dc5;
    for (var i = 0; i < html.length; i++) {
      hash ^= html.charCodeAt(i);
      hash = (hash + ((hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24))) >>> 0;
    }
    return { length: html.length, fnv1a: hash.toString(16) };
  }

  window.__bal = {
    schemaVersion: SCHEMA_VERSION,
    collectCandidates: collectCandidates,
    uiSignals: uiSignals,
    installWatcher: installWatcher,
    streamSummary: streamSummary,
    markSent: markSent,
    resetWatcher: resetWatcher,
    snapshotHtml: snapshotHtml,
    innerTextOf: innerTextOf,
    domFingerprint: domFingerprint,
    _internal: { looksDynamic: looksDynamic, isVisible: isVisible, isEditable: isEditable }
  };
})();
