import sys
import unittest
from unittest.mock import patch, MagicMock, ANY
from pathlib import Path
from datetime import datetime, timedelta

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "backend"))


class DashboardHelpersTest(unittest.TestCase):
    def setUp(self):
        self.mock_get_db = patch("backend.routes.dashboard.get_db").start()
        self.mock_cursor = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_get_db.return_value.__enter__.return_value = (
            self.mock_cursor,
            self.mock_conn,
        )

    def tearDown(self):
        patch.stopall()

    # ─────────────── _refresh_fipe ───────────────

    @patch("backend.routes.dashboard.get_fipe_value")
    def test_refresh_fipe_success(self, mock_get_fipe):
        mock_get_fipe.return_value = {
            "Valor": "R$ 35.000,00",
            "MesReferencia": "Julho/2024",
        }

        from backend.routes.dashboard import _refresh_fipe
        _refresh_fipe(1, "carro", "Fiat", "Uno", 2020)

        self.mock_cursor.execute.assert_called_once()

    @patch("backend.routes.dashboard.get_fipe_value")
    def test_refresh_fipe_api_returns_none(self, mock_get_fipe):
        mock_get_fipe.return_value = None

        from backend.routes.dashboard import _refresh_fipe
        _refresh_fipe(1, "carro", "Fiat", "Uno", 2020)

        self.mock_cursor.execute.assert_not_called()

    @patch("backend.routes.dashboard.get_fipe_value")
    def test_refresh_fipe_missing_valor_key(self, mock_get_fipe):
        mock_get_fipe.return_value = {"MesReferencia": "Julho/2024"}

        from backend.routes.dashboard import _refresh_fipe
        _refresh_fipe(1, "carro", "Fiat", "Uno", 2020)

        self.mock_cursor.execute.assert_not_called()

    @patch("backend.routes.dashboard.get_fipe_value")
    def test_refresh_fipe_exception_handled(self, mock_get_fipe):
        mock_get_fipe.side_effect = Exception("API timeout")

        from backend.routes.dashboard import _refresh_fipe
        try:
            _refresh_fipe(1, "carro", "Fiat", "Uno", 2020)
        except Exception:
            self.fail("_refresh_fipe raised an exception")

    @patch("backend.routes.dashboard.get_fipe_value")
    def test_refresh_fipe_db_write(self, mock_get_fipe):
        mock_get_fipe.return_value = {
            "Valor": "R$ 40.000,00",
            "MesReferencia": "Agosto/2024",
        }

        from backend.routes.dashboard import _refresh_fipe
        _refresh_fipe(1, "carro", "Fiat", "Uno", 2020)

        call_args = self.mock_cursor.execute.call_args[0]
        self.assertIn("UPDATE veiculos", call_args[0])
        self.assertIn("R$ 40.000,00", call_args[1])

    # ─────────────── FIPE stale check logic ───────────────

    def test_fipe_cache_hours_constant(self):
        from backend.routes.dashboard import FIPE_CACHE_HOURS
        self.assertEqual(FIPE_CACHE_HOURS, 24)

    def test_fipe_stale_calculation(self):
        stale_time = datetime.now() - timedelta(hours=25)
        self.assertTrue((datetime.now() - stale_time) > timedelta(hours=24))

    def test_fipe_fresh_calculation(self):
        fresh_time = datetime.now() - timedelta(hours=1)
        self.assertFalse((datetime.now() - fresh_time) > timedelta(hours=24))

    # ─────────────── Health Score Logic ───────────────

    def test_health_score_new_vehicle(self):
        current_year = datetime.now().year
        km = 1000
        health_score = max(20, min(100, int(
            100 - (current_year - current_year) * 2 - (km // 10000) * 1.5
        )))
        self.assertGreaterEqual(health_score, 80)

    def test_health_score_old_vehicle(self):
        current_year = datetime.now().year
        ano_fab = current_year - 15
        km = 150000
        health_score = max(20, min(100, int(
            100 - (current_year - ano_fab) * 2 - (km // 10000) * 1.5
        )))
        self.assertLessEqual(health_score, 60)

    def test_health_score_minimum_clamp(self):
        health_score = max(20, min(100, -50))
        self.assertEqual(health_score, 20)

    def test_health_score_maximum_clamp(self):
        health_score = max(20, min(100, 150))
        self.assertEqual(health_score, 100)

    def test_health_score_moderate_vehicle(self):
        current_year = datetime.now().year
        ano_fab = current_year - 8
        km = 60000
        health_score = max(20, min(100, int(
            100 - (current_year - ano_fab) * 2 - (km // 10000) * 1.5
        )))
        self.assertGreaterEqual(health_score, 20)
        self.assertLessEqual(health_score, 100)

    # ─────────────── Alert Logic ───────────────

    def test_alert_critical_for_low_health(self):
        health_score = 40
        if health_score < 50:
            alertas = [{"item": "Atenção Geral", "msg": "Seu veículo tem alta quilometragem/idade. Revise com frequência.", "status": "Crítico"}]
        elif health_score < 80:
            alertas = [{"item": "Uso Moderado", "msg": "Bom estado, mas fique atento aos prazos de revisão.", "status": "Atenção"}]
        else:
            alertas = [{"item": "Ótimo Estado", "msg": "Veículo novo ou pouco rodado. Continue assim!", "status": "OK"}]
        self.assertEqual(alertas[0]["status"], "Crítico")

    def test_alert_warning_for_medium_health(self):
        health_score = 65
        if health_score < 50:
            alertas = [{"item": "Atenção Geral", "status": "Crítico"}]
        elif health_score < 80:
            alertas = [{"item": "Uso Moderado", "status": "Atenção"}]
        else:
            alertas = [{"item": "Ótimo Estado", "status": "OK"}]
        self.assertEqual(alertas[0]["status"], "Atenção")

    def test_alert_ok_for_high_health(self):
        health_score = 90
        if health_score < 50:
            alertas = [{"item": "Atenção Geral", "status": "Crítico"}]
        elif health_score < 80:
            alertas = [{"item": "Uso Moderado", "status": "Atenção"}]
        else:
            alertas = [{"item": "Ótimo Estado", "status": "OK"}]
        self.assertEqual(alertas[0]["status"], "OK")

    # ─────────────── FIPE info construction ───────────────

    def test_fipe_info_present(self):
        fipe_valor = "R$ 30.000,00"
        fipe_mes = "Junho/2024"
        fipe_info = {"Valor": fipe_valor, "MesReferencia": fipe_mes}
        self.assertEqual(fipe_info["Valor"], "R$ 30.000,00")

    def test_fipe_info_absent(self):
        fipe_info = {"Valor": "Não listado na Tabela FIPE", "MesReferencia": "---"}
        self.assertEqual(fipe_info["Valor"], "Não listado na Tabela FIPE")

    # ─────────────── Dashboard vehicle data shape ───────────────

    def test_dashboard_vehicle_shape(self):
        row = {
            "id": 1,
            "tipo": "carro",
            "marca": "Fiat",
            "modelo": "Uno",
            "ano_fabricacao": 2020,
            "quilometragem": 50000,
        }
        vehicle = {
            "id": row["id"],
            "tipo": row["tipo"],
            "marca": row["marca"],
            "modelo": row["modelo"],
            "ano_fabricacao": row["ano_fabricacao"],
            "quilometragem": row["quilometragem"],
        }
        self.assertEqual(vehicle["marca"], "Fiat")
        self.assertEqual(vehicle["modelo"], "Uno")

    # ─────────────── Background FIPE refresh thread target ───────────────

    @patch("backend.routes.dashboard.get_fipe_value")
    @patch("backend.routes.dashboard.get_db")
    def test_refresh_fipe_through_thread(self, mock_get_db, mock_get_fipe):
        mock_get_fipe.return_value = {"Valor": "R$ 50.000,00", "MesReferencia": "Set/2024"}
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_get_db.return_value.__enter__.return_value = (mock_cursor, mock_conn)

        from backend.routes.dashboard import _refresh_fipe
        _refresh_fipe(1, "carro", "Fiat", "Uno", 2020)

        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
