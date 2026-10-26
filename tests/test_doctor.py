"""Testes da auditoria de ambiente (Marco 0).

Nao exigem navegador: validam a logica de deteccao contra o proprio ambiente e contra
valores sinteticos.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from browserapi_lab.doctor import (
    CHROMIUM_LIBS,
    EnvReport,
    build_report,
    check_libraries,
    detect_environment_kind,
    disk_free_gb,
    find_library,
    render_text,
)


class TestDeteccao(unittest.TestCase):
    def test_ambiente_conhecido(self):
        self.assertIn(detect_environment_kind(), {"local-linux", "codespaces", "ci", "unknown"})

    def test_find_library_retorna_status(self):
        status = find_library("libz.so.1")
        self.assertIsInstance(status.found, bool)
        if status.found:
            self.assertIsInstance(status.path, str)

    def test_biblioteca_inexistente(self):
        self.assertFalse(find_library("libnao_existe_xyz.so.9").found)

    def test_check_libraries_cobre_todas(self):
        status = check_libraries(("libz.so.1",))
        self.assertEqual(len(status), 1)
        self.assertEqual(status[0].name, "libz.so.1")

    def test_lista_de_libs_tem_itens_criticos(self):
        for critica in ("libnss3.so", "libatk-1.0.so.0", "libgbm.so.1", "libasound.so.2"):
            self.assertIn(critica, CHROMIUM_LIBS)

    def test_disco_livre(self):
        valor = disk_free_gb(tempfile.gettempdir())
        self.assertIsInstance(valor, float)
        self.assertGreaterEqual(valor, 0.0)


class TestRelatorio(unittest.TestCase):
    def setUp(self):
        self.report = build_report(results_path=tempfile.gettempdir())

    def test_relatorio_e_serializavel(self):
        dados = self.report.to_dict()
        json.dumps(dados, ensure_ascii=False)  # levante se nao serializar
        for campo in (
            "environment_kind",
            "os_name",
            "python_version",
            "cpu_count",
            "ram_total_mb",
            "missing_required_libs",
            "browser_ready",
            "can_headed",
        ):
            self.assertIn(campo, dados)

    def test_browser_ready_implica_sem_libs_faltando(self):
        if self.report.browser_ready:
            self.assertEqual(self.report.missing_required_libs, [])
            self.assertTrue(self.report.playwright_installed)

    def test_can_headed_implica_browser_ready(self):
        if self.report.can_headed:
            self.assertTrue(self.report.browser_ready)

    def test_coerencia_das_listas_de_libs(self):
        self.assertEqual(
            len(self.report.missing_required_libs) + len(self.report.present_required_libs),
            len(CHROMIUM_LIBS),
        )

    def test_sugestoes_nao_sao_vazias_quando_falta_algo(self):
        if not self.report.browser_ready:
            self.assertTrue(self.report.recommendations)

    def test_render_text_contem_cabecalho_e_veredito(self):
        texto = render_text(self.report)
        self.assertIn("browserapi-lab :: doctor", texto)
        self.assertIn("pode rodar navegador", texto)

    def test_relatorio_json_gravavel(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "doctor.json"
            caminho.write_text(json.dumps(self.report.to_dict()), encoding="utf-8")
            with open(caminho, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["environment_kind"], self.report.environment_kind)


class TestEnvReportDataclass(unittest.TestCase):
    def test_padrao_nao_pronto(self):
        vazio = EnvReport()
        self.assertFalse(vazio.browser_ready)
        self.assertEqual(vazio.system_browsers, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
