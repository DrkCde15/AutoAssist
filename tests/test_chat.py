import sys
import unittest
from unittest.mock import patch, MagicMock, ANY
from pathlib import Path
import json

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "backend"))

from backend.services.nogai import gerar_resposta, gerar_termos_busca


class ChatServiceTest(unittest.TestCase):
    def setUp(self):
        self.mock_groq = patch("backend.services.nogai.chat_completion").start()
        self.mock_build = patch("backend.services.nogai.build_chat_messages").start()
        self.mock_build.return_value = [{"role": "system", "content": "test"}]

    def tearDown(self):
        patch.stopall()

    # ─────────────── gerar_resposta ───────────────

    def test_gerar_resposta_success(self):
        self.mock_groq.return_value = "Resposta do NOG"
        response = gerar_resposta("qual o oleo ideal?", user_id=1)
        self.assertEqual(response, "Resposta do NOG")

    def test_gerar_resposta_empty_message(self):
        response = gerar_resposta("", user_id=1)
        self.assertIn("digite", response.lower())

    def test_gerar_resposta_blank_message(self):
        response = gerar_resposta("   ", user_id=1)
        self.assertIn("digite", response.lower())

    def test_gerar_resposta_with_premium_context(self):
        self.mock_groq.return_value = "Premium response"
        response = gerar_resposta(
            "mostre um video sobre troca de oleo",
            user_id=1,
            user_data={"is_premium": True, "lista_veiculos": []},
        )
        self.assertEqual(response, "Premium response")

    def test_gerar_resposta_with_vehicles(self):
        self.mock_groq.return_value = "Response with vehicle context"
        response = gerar_resposta(
            "qual a kilometragem ideal?",
            user_id=1,
            user_data={
                "lista_veiculos": [
                    {"tipo": "carro", "marca": "Fiat", "modelo": "Uno", "ano_fabricacao": 2020}
                ]
            },
        )
        self.assertEqual(response, "Response with vehicle context")

    @patch("backend.services.nogai.GROQ_QUOTA_MESSAGE", "Quota exceeded. Try again later.")
    def test_gerar_resposta_quota_error(self):
        from backend.services.groq_client import GroqHTTPError
        self.mock_groq.side_effect = GroqHTTPError(429, "Quota exceeded")
        response = gerar_resposta("qual o oleo?", user_id=1)
        self.assertIn("Quota", response)

    def test_gerar_resposta_generic_error(self):
        self.mock_groq.side_effect = Exception("Generic error")
        response = gerar_resposta("qual o oleo?", user_id=1)
        self.assertIn("Erro", response)

    def test_gerar_resposta_with_history(self):
        self.mock_groq.return_value = "Response with history"
        history = [
            {"role": "user", "content": "qual o oleo?"},
            {"role": "model", "content": "use 5w30"},
        ]
        response = gerar_resposta("e o filtro?", user_id=1, historico=history)
        self.assertEqual(response, "Response with history")

    # ─────────────── gerar_termos_busca ───────────────

    @patch("backend.services.nogai._generate_content_with_fallback")
    def test_gerar_termos_busca_success(self, mock_generate):
        mock_generate.return_value.text = json.dumps({
            "youtube": "troca de oleo",
            "loja": "oleo motor",
            "pecas": "filtro oleo",
        })
        result = gerar_termos_busca("preciso trocar o oleo")
        self.assertEqual(result["youtube"], "troca de oleo")
        self.assertEqual(result["loja"], "oleo motor")
        self.assertEqual(result["pecas"], "filtro oleo")

    @patch("backend.services.nogai._generate_content_with_fallback")
    def test_gerar_termos_busca_invalid_json(self, mock_generate):
        mock_generate.return_value.text = "invalid json"
        result = gerar_termos_busca("preciso trocar o oleo")
        self.assertIsNone(result["youtube"])
        self.assertIsNone(result["loja"])
        self.assertIsNone(result["pecas"])

    @patch("backend.services.nogai._generate_content_with_fallback")
    def test_gerar_termos_busca_exception(self, mock_generate):
        mock_generate.side_effect = Exception("API error")
        result = gerar_termos_busca("preciso trocar o oleo")
        self.assertIsNone(result["youtube"])
        self.assertIsNone(result["loja"])
        self.assertIsNone(result["pecas"])

    @patch("backend.services.nogai._generate_content_with_fallback")
    def test_gerar_termos_busca_with_history(self, mock_generate):
        mock_generate.return_value.text = json.dumps({
            "youtube": "troca de pastilha de freio",
            "loja": None,
            "pecas": "pastilha de freio",
        })
        history = [{"role": "user", "content": "freios barulhentos"}]
        result = gerar_termos_busca("preciso trocar as pastilhas", history)
        self.assertEqual(result["youtube"], "troca de pastilha de freio")
        self.assertEqual(result["pecas"], "pastilha de freio")


class ChatHelpersTest(unittest.TestCase):
    # ─────────────── is_generic_chat_message (from pages) ───────────────

    def test_generic_greetings(self):
        from backend.routes.pages import is_generic_chat_message
        self.assertTrue(is_generic_chat_message("oi"))
        self.assertTrue(is_generic_chat_message("bom dia"))
        self.assertTrue(is_generic_chat_message("Obrigado"))
        self.assertTrue(is_generic_chat_message("ola"))
        self.assertTrue(is_generic_chat_message("tudo bem"))

    def test_non_generic_messages(self):
        from backend.routes.pages import is_generic_chat_message
        self.assertFalse(is_generic_chat_message("qual o oleo ideal para meu carro?"))
        self.assertFalse(is_generic_chat_message("preciso de ajuda com o motor"))
        self.assertFalse(is_generic_chat_message("troca de pneus"))

    # ─────────────── parse_chat_attachment ───────────────

    def test_parse_chat_attachment_no_attachment(self):
        from backend.routes.pages import parse_chat_attachment
        result = parse_chat_attachment({})
        self.assertIsNone(result)

    def test_parse_chat_attachment_empty_name_defaults_to_anexo(self):
        import base64
        from backend.routes.pages import parse_chat_attachment
        encoded = base64.b64encode(b"test").decode()
        result = parse_chat_attachment({
            "attachment": {
                "name": "",
                "data": f"data:text/plain,{encoded}",
            }
        })
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "anexo")

    def test_parse_chat_attachment_disallowed_extension(self):
        from backend.routes.pages import parse_chat_attachment
        with self.assertRaises(ValueError) as ctx:
            parse_chat_attachment({
                "attachment": {
                    "name": "malware.exe",
                    "data": "data:application/octet-stream,dGVzdA==",
                }
            })
        self.assertIn("nao permitida", str(ctx.exception))

    def test_parse_chat_attachment_path_traversal(self):
        from backend.routes.pages import parse_chat_attachment
        with self.assertRaises(ValueError) as ctx:
            parse_chat_attachment({
                "attachment": {
                    "name": "../../etc/passwd.txt",
                    "data": "data:text/plain,dGVzdA==",
                }
            })
        self.assertIn("invalido", str(ctx.exception).lower())

    def test_parse_chat_attachment_invalid_data_url(self):
        from backend.routes.pages import parse_chat_attachment
        with self.assertRaises(ValueError):
            parse_chat_attachment({
                "attachment": {
                    "name": "test.txt",
                    "data": "not-a-data-url",
                }
            })

    @patch("PIL.Image")
    @patch("backend.routes.pages.io.BytesIO")
    def test_parse_chat_attachment_valid_image(self, mock_bytesio, mock_image):
        import base64
        from backend.routes.pages import parse_chat_attachment

        mock_img = MagicMock()
        mock_img.width = 100
        mock_img.height = 100
        mock_image.open.return_value = mock_img

        valid_data = base64.b64encode(b"fake_image_data").decode()
        result = parse_chat_attachment({
            "attachment": {
                "name": "foto.jpg",
                "data": f"data:image/jpeg,{valid_data}",
            }
        })
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "foto.jpg")
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["mime_type"], "image/jpeg")

    def test_parse_chat_attachment_oversized(self):
        import base64
        from backend.routes.pages import parse_chat_attachment

        oversized = "A" * (8 * 1024 * 1024 + 1)
        encoded = base64.b64encode(oversized.encode()).decode()
        with self.assertRaises(ValueError) as ctx:
            parse_chat_attachment({
                "attachment": {
                    "name": "large.txt",
                    "data": f"data:text/plain,{encoded}",
                }
            })
        self.assertIn("8 MB", str(ctx.exception))

    # ─────────────── normalize_guest_id ───────────────

    def test_normalize_guest_id_valid(self):
        from backend.routes.pages import normalize_guest_id
        result = normalize_guest_id("abc123XYZ_-" * 2)
        self.assertEqual(result, "abc123XYZ_-" * 2)

    def test_normalize_guest_id_too_short(self):
        from backend.routes.pages import normalize_guest_id
        result = normalize_guest_id("short")
        self.assertIsNone(result)

    def test_normalize_guest_id_invalid_chars(self):
        from backend.routes.pages import normalize_guest_id
        result = normalize_guest_id("<script>alert(1)</script>")
        self.assertIsNone(result)

    def test_normalize_guest_id_empty(self):
        from backend.routes.pages import normalize_guest_id
        result = normalize_guest_id("")
        self.assertIsNone(result)

    # ─────────────── hash_guest_id ───────────────

    def test_hash_guest_id_length(self):
        from backend.routes.pages import hash_guest_id
        hashed = hash_guest_id("test_guest_123")
        self.assertEqual(len(hashed), 64)

    def test_hash_guest_id_deterministic(self):
        from backend.routes.pages import hash_guest_id
        h1 = hash_guest_id("same_guest")
        h2 = hash_guest_id("same_guest")
        self.assertEqual(h1, h2)

    # ─────────────── reserve_guest_message ───────────────

    def test_reserve_guest_message_first(self):
        from backend.routes.pages import reserve_guest_message
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        remaining = reserve_guest_message(mock_cursor, "guest_id_123")
        self.assertIsNotNone(remaining)
        self.assertGreaterEqual(remaining, 0)

    def test_reserve_guest_message_limit_reached(self):
        from backend.routes.pages import reserve_guest_message
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"message_count": 5}

        remaining = reserve_guest_message(mock_cursor, "guest_id_123")
        self.assertIsNone(remaining)

    def test_reserve_guest_message_near_limit(self):
        from backend.routes.pages import reserve_guest_message
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"message_count": 3}

        remaining = reserve_guest_message(mock_cursor, "guest_id_123")
        self.assertEqual(remaining, 1)

    # ─────────────── parse_history_limit ───────────────

    def test_parse_history_limit_default(self):
        from backend.routes.pages import parse_history_limit
        self.assertEqual(parse_history_limit(None), 100)

    def test_parse_history_limit_custom(self):
        from backend.routes.pages import parse_history_limit
        self.assertEqual(parse_history_limit("50"), 50)

    def test_parse_history_limit_min(self):
        from backend.routes.pages import parse_history_limit
        self.assertEqual(parse_history_limit("0"), 1)

    def test_parse_history_limit_max(self):
        from backend.routes.pages import parse_history_limit
        self.assertEqual(parse_history_limit("500"), 200)

    # ─────────────── build_spending_summary ───────────────

    def test_build_spending_summary_empty(self):
        from backend.routes.pages import build_spending_summary
        result = build_spending_summary([])
        self.assertEqual(result["total_gastos"], 0.0)
        self.assertEqual(result["quantidade_registros"], 0)

    def test_build_spending_summary_with_data(self):
        from backend.routes.pages import build_spending_summary
        rows = [
            {"cost": 100.50, "maintenance_label": "Troca de Oleo"},
            {"cost": 250.00, "maintenance_label": "Troca de Oleo"},
            {"cost": 80.00, "maintenance_label": "Alinhamento"},
        ]
        result = build_spending_summary(rows)
        self.assertEqual(result["total_gastos"], 430.50)
        self.assertEqual(result["quantidade_registros"], 3)
        self.assertEqual(len(result["gastos_por_tipo"]), 2)

    def test_build_spending_summary_none_cost(self):
        from backend.routes.pages import build_spending_summary
        rows = [
            {"cost": None, "maintenance_label": "Troca de Oleo"},
            {"cost": 100.00, "maintenance_label": "Troca de Oleo"},
        ]
        result = build_spending_summary(rows)
        self.assertEqual(result["total_gastos"], 100.00)
        self.assertEqual(result["quantidade_registros"], 2)

    # ─────────────── normalize_chat_text ───────────────

    def test_normalize_chat_text_strips_accents(self):
        from backend.routes.pages import normalize_chat_text
        self.assertEqual(normalize_chat_text("Olá"), "ola")
        self.assertEqual(normalize_chat_text("Ação"), "acao")

    # ─────────────── format_chat_date ───────────────

    def test_format_chat_date_none(self):
        from backend.routes.pages import format_chat_date
        self.assertEqual(format_chat_date(None), "-")

    def test_format_chat_date_datetime(self):
        from datetime import datetime
        from backend.routes.pages import format_chat_date
        result = format_chat_date(datetime(2024, 6, 15))
        self.assertEqual(result, "15/06/2024")

    # ─────────────── format_chat_money ───────────────

    def test_format_chat_money_valid(self):
        from backend.routes.pages import format_chat_money
        result = format_chat_money(1234.56)
        self.assertIn("R$", result)

    def test_format_chat_money_none(self):
        from backend.routes.pages import format_chat_money
        self.assertEqual(format_chat_money(None), "R$ 0,00")

    def test_format_chat_money_invalid(self):
        from backend.routes.pages import format_chat_money
        self.assertEqual(format_chat_money("invalid"), "R$ 0,00")


if __name__ == "__main__":
    unittest.main()
