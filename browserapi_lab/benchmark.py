"""Verificação reproduzível somente contra fixture local; nunca sites reais."""
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import math
import os
import resource
import statistics
import tempfile
import threading
import time

from .browser import BrowserConfig, BrowserSession, browser_tree_rss_kb, rss_kb
from .discovery import collect, rank_candidates
from .extractor import extract, dom_fingerprint
from .observer import WatchConfig, install, mark_sent, wait_for_completion
from .report import Run, ResultWriter, env_facts
from .sender import send_message

ASSETS = Path(__file__).resolve().parent / 'assets'


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def fixture_server():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ASSETS)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/fake_chat.html'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def percentile(values, fraction=.95):
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def one_trial(page, url, config, scenario='normal', iteration=1, writer=None, env=None):
    """Retorna apenas métricas/sinais sintéticos, sem conteúdo de mensagens."""
    run = Run('E-BENCH-1', target='fixture', milestone='M7', strategy=config.policy,
              iteration=iteration, env=env or {})
    started = time.perf_counter()
    cpu_start = time.process_time()
    try:
        page.goto(url + '?delay=1', wait_until='load')
        patch = {'mode': 'normal', 'composer': 'textarea'}
        if scenario in ('pause', 'empty', 'error', 'ratelimit', 'login'):
            patch['mode'] = scenario
        elif scenario in ('input', 'contenteditable'):
            patch['composer'] = scenario
        elif scenario in ('shadow', 'iframe'):
            patch[scenario] = True
        elif scenario == 'no_copy':
            patch['copy'] = False
        elif scenario == 'copy_early':
            patch['copyEarly'] = True
        page.evaluate('patch => FakeChat.config(patch)', patch)
        if scenario == 'iframe':
            page.frame_locator('#composer-frame').locator('#composer').wait_for()
        t = time.perf_counter()
        composers = rank_candidates(collect(page, 'composer')['candidates'], 'composer')
        buttons = rank_candidates(collect(page, 'send_button')['candidates'], 'send_button')
        if not composers or not buttons:
            raise ValueError('descoberta sem candidato')
        run.metric('discovery_ms', (time.perf_counter() - t) * 1000)
        install(page, message_selector='[data-role="assistant"] .body')
        mark_sent(page)
        sent = send_message(page, composers[0], buttons[0], 'Teste sintético público',
                            verify_timeout_ms=1000)
        if not sent.success:
            raise ValueError('envio não confirmado')
        run.metric('fill_ms', sent.fill_ms).metric('send_ms', sent.send_ms)
        run.metric('composer_confirmed', sent.attempts[-1].composer_confirmed)
        observed = wait_for_completion(page, config)
        truth = page.evaluate('FakeChat.state()')
        expected = 'blocked' if scenario in ('error', 'ratelimit', 'login') else (
            'timeout' if scenario == 'empty' else 'success')
        if observed.status != expected:
            raise ValueError(f'estado {observed.status}; esperado {expected}')
        if expected == 'success' and truth['status'] != 'done':
            raise ValueError('término prematuro')
        if expected == 'success':
            selector = '[data-role="assistant"]:last-child .body'
            before = dom_fingerprint(page, selector)
            t = time.perf_counter()
            result = extract(page, selector)
            run.metric('extract_ms', (time.perf_counter() - t) * 1000)
            if before != dom_fingerprint(page, selector):
                raise ValueError('DOM alterado')
            if not all(token in result['markdown'] for token in ('```python', '### Passos', '| Estratégia | Custo |')):
                raise ValueError('estrutura perdida')
            # TTFT relativo ao envio, e overhead relativo ao ground truth da fixture.
            timing = page.evaluate('''() => ({sent:window.__balStream.sent_at,
                now:performance.now(), truth:FakeChat.state()})''')
            run.metric('ttft_ms', max(0, timing['truth']['first_token_ms'] - timing['sent']))
            run.metric('settle_overhead_ms', max(0, timing['now'] - timing['truth']['last_mutation_ms']))
        run.metric('mutation_count', observed.mutation_count)
        run.metric('poll_count', observed.polls)
        run.metric('success', True)
        run.event(0, 'scenario', scenario)
    except Exception as exc:
        # Não serializar exceções Playwright com snapshots ou texto de página.
        run.finish('failure', type(exc).__name__)
        run.metric('success', False)
    finally:
        run.metric('total_ms', (time.perf_counter() - started) * 1000)
        run.metric('python_cpu_ms', (time.process_time() - cpu_start) * 1000)
        run.metric('python_rss_kb', rss_kb(os.getpid()))
        if writer:
            writer.write(run)
    return run


def verify(iterations=10, results='results/verify', channel=None, headed=False):
    if not 1 <= iterations <= 1000:
        raise ValueError('iterations deve estar entre 1 e 1000')
    writer = ResultWriter(results)
    runs = []
    env = env_facts()
    env['browser_channel'] = channel or 'chromium'
    env['headed'] = headed
    # Perfil temporário só para fixture. Nenhuma sessão autenticada é acessada.
    with tempfile.TemporaryDirectory(prefix='browserapi-verify-') as root, fixture_server() as url:
        with BrowserSession(BrowserConfig(profiles_root=root, headless=not headed, channel=channel)) as session:
            page = session.page()
            env['browser_version'] = session.context.browser.version
            startup_ms = session.cold_start_ms
            for i in range(iterations):
                run = one_trial(page, url, WatchConfig(stability_window_ms=600, timeout_ms=15000),
                                iteration=i + 1, writer=writer, env=env)
                run.metrics['browser_rss_kb'] = browser_tree_rss_kb(session)
                runs.append(run)
            for scenario in ('pause', 'input', 'contenteditable', 'shadow', 'iframe', 'no_copy',
                             'copy_early', 'empty', 'error', 'ratelimit', 'login'):
                timeout = 1000 if scenario == 'empty' else 15000
                runs.append(one_trial(page, url, WatchConfig(stability_window_ms=600, timeout_ms=timeout),
                                      scenario=scenario, writer=writer, env=env))
            # comparar políticas com o mesmo cenário e recursos
            for policy in ('stability_only', 'ui_signals'):
                runs.append(one_trial(page, url, WatchConfig(policy=policy, stability_window_ms=600,
                                                            timeout_ms=15000), writer=writer, env=env))
            warm_page = session.page()
            warm_reused = warm_page is page and len(session.context.pages) == 1
            browser_rss = browser_tree_rss_kb(session)
        # Reabrir o perfil: startup de perfil quente, sem confundir com reúso de aba.
        with BrowserSession(BrowserConfig(profiles_root=root, headless=not headed, channel=channel)) as reopened:
            restart_ms = reopened.cold_start_ms
    baseline = runs[:iterations]
    overheads = [r.metrics['settle_overhead_ms'] for r in baseline if 'settle_overhead_ms' in r.metrics]
    summary = {
        'schema_version': '1.0', 'env': env, 'iterations': iterations,
        'trials': len(runs), 'failures': sum(r.status != 'success' for r in runs),
        'cold_start_ms': startup_ms, 'profile_restart_ms': restart_ms,
        'one_hot_page_reused': warm_reused, 'browser_tree_rss_kb_approx': browser_rss,
        'total_p50_ms': statistics.median([r.metrics['total_ms'] for r in baseline]),
        'total_p95_ms': percentile([r.metrics['total_ms'] for r in baseline]),
        'settle_overhead_p95_ms': percentile(overheads),
        'python_peak_rss_kb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'performance_budget_ms': 2500,
        'performance_pass': len(overheads) == iterations and percentile(overheads) < 2500,
        'limits': ['fixture sintética; não demonstra uso 24/7 ou sites reais',
                   'RSS inclui driver e memória compartilhada; não é pico do navegador',
                   'CPU medida somente do Python; sem CPU da árvore Chromium'],
    }
    summary['passed'] = (summary['failures'] == 0 and warm_reused and summary['performance_pass'])
    import json
    Path(results, 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    return summary
