"""Testes do esquema de resultados (Marco 0).

Cobre: envelope valido/invalido, run_id ordenavel, gravacao de JSON e CSV,
linhas longas/largas e celulas vazias para metricas ausentes.
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from browserapi_lab.report import (
    SCHEMA_VERSION,
    METRICS_COLUMNS,
    RUNS_COLUMNS,
    ResultWriter,
    Run,
    metrics_rows,
    new_run_id,
    run_row,
    unit_for,
    validate_envelope,
)


class TestEnvelope(unittest.TestCase):
    def test_run_valido(self):
        run = Run(experiment="E-DISC-1", target="fixture", milestone="M3", strategy="scoring")
        run.metric("discovery_ms", 12.5).metric("success", True)
        run.event(0.0, "discover", "composer")
        run.finish("success")
        self.assertEqual(validate_envelope(run.to_dict()), [])

    def test_campos_obrigatorios(self):
        run = Run(experiment="E-X", target="unit").to_dict()
        for key in ("schema_version", "run_id", "timestamp_utc", "env", "events"):
            del run[key]
        problems = validate_envelope(run)
        for key in ("schema_version", "run_id", "timestamp_utc", "env", "events"):
            self.assertIn(f"campo obrigatorio ausente: {key}", problems)

    def test_schema_version_errada(self):
        run = Run(experiment="E-X").to_dict()
        run["schema_version"] = "0.9"
        self.assertTrue(any("schema_version incompativel" in p for p in validate_envelope(run)))

    def test_status_invalido_rejeitado(self):
        with self.assertRaises(ValueError):
            Run(experiment="E-X").finish("quase-sucesso")

    def test_status_validos(self):
        for status in ("success", "failure", "timeout", "skipped"):
            self.assertEqual(Run(experiment="E-X").finish(status).status, status)

    def test_evento_sem_t_ms_e_invalido(self):
        run = Run(experiment="E-X")
        run.events.append({"type": "send"})
        self.assertTrue(any("evento 0 invalido" in p for p in validate_envelope(run.to_dict())))

    def test_run_id_ordenavel_e_unico(self):
        ids = {new_run_id(1_700_000_000 + i) for i in range(200)}
        self.assertEqual(len(ids), 200)
        primeiro = new_run_id(1_700_000_000)
        segundo = new_run_id(1_700_000_001)
        self.assertLess(primeiro[:15], segundo[:15])

    def test_schema_version_constante(self):
        self.assertEqual(SCHEMA_VERSION, "1.0")
        self.assertEqual(Run(experiment="E-X").to_dict()["schema_version"], "1.0")


class TestCsv(unittest.TestCase):
    def test_unidades_conhecidas(self):
        self.assertEqual(unit_for("ttft_ms"), "ms")
        self.assertEqual(unit_for("python_rss_kb"), "KB")
        self.assertEqual(unit_for("mutation_count"), "count")
        self.assertEqual(unit_for("alguma_coisa_nova"), "")

    def test_metricas_ausentes_viram_celula_vazia(self):
        run = Run(experiment="E-OBS-3", target="fixture", strategy="hybrid")
        run.metric("ttft_ms", 310.0)
        row = run_row(run.to_dict())
        self.assertEqual(row["ttft_ms"], "310")
        self.assertEqual(row["stream_ms"], "")
        self.assertEqual(row["error"], "")

    def test_booleano_vira_true_false(self):
        run = Run(experiment="E-X")
        run.metric("success", False)
        self.assertEqual(run_row(run.to_dict())["success"], "false")

    def test_metric_rows_ordenadas_por_nome(self):
        run = Run(experiment="E-X")
        run.metric("z_ms", 1).metric("a_ms", 2)
        nomes = [r["metric"] for r in metrics_rows(run.to_dict())]
        self.assertEqual(nomes, ["a_ms", "z_ms"])

    def test_colunas_fixas(self):
        run = Run(experiment="E-X")
        self.assertEqual(tuple(run_row(run.to_dict()).keys()), RUNS_COLUMNS)
        run.metric("total_ms", 1.0)
        self.assertEqual(tuple(metrics_rows(run.to_dict())[0].keys()), METRICS_COLUMNS)

    def test_execucao_sem_metricas_nao_gera_linha_de_metrica(self):
        self.assertEqual(metrics_rows(Run(experiment="E-X").to_dict()), [])


class TestResultWriter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.writer = ResultWriter(Path(self.tmp.name) / "results")

    def tearDown(self):
        self.tmp.cleanup()

    def test_grava_json_e_csvs(self):
        run = Run(experiment="E-SEND-1", target="fixture", milestone="M4", strategy="fill")
        run.metric("fill_ms", 10.0).metric("success", True)
        run.finish("success")
        path = self.writer.write(run)
        self.assertTrue(path.exists())

        with open(path, "r", encoding="utf-8") as handle:
            envelope = json.load(handle)
        self.assertEqual(envelope["run_id"], run.run_id)

        with open(self.writer.metrics_csv, newline="", encoding="utf-8") as handle:
            linhas = list(csv.DictReader(handle))
        self.assertEqual({linha["metric"] for linha in linhas}, {"fill_ms", "success"})

        with open(self.writer.runs_csv, newline="", encoding="utf-8") as handle:
            execucoes = list(csv.DictReader(handle))
        self.assertEqual(len(execucoes), 1)
        self.assertEqual(execucoes[0]["strategy"], "fill")

    def test_append_mantem_um_cabecalho(self):
        for i in range(3):
            run = Run(experiment="E-X", iteration=i + 1)
            run.metric("total_ms", float(i))
            self.writer.write(run)
        conteudo = self.writer.runs_csv.read_text(encoding="utf-8").splitlines()
        self.assertEqual(conteudo.count(conteudo[0]), 1, "cabecalho duplicado")
        self.assertEqual(len(conteudo), 4)  # cabecalho + 3 execucoes

    def test_envelope_invalido_nao_e_gravado(self):
        run = Run(experiment="E-X")
        run.events.append({"tipo_errado": 1})
        with self.assertRaises(ValueError):
            self.writer.write(run)

    def test_candidatos_auxiliares(self):
        run = Run(experiment="E-DISC-1", target="fixture")
        caminho = self.writer.write_candidates(run.run_id, {"role": "composer", "candidates": []})
        self.assertTrue(caminho.exists())
        self.assertTrue(caminho.name.endswith(".candidates.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
