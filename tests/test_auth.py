import sys
import unittest
from unittest.mock import patch, MagicMock, ANY, call
from pathlib import Path
from datetime import datetime, timedelta, timezone

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "backend"))

from backend.routes.database import is_trial_expired, get_trial_days_remaining, is_valid_email_domain


class AuthHelpersTest(unittest.TestCase):
    # ─────────────── Password Reset Email HTML ───────────────

    def test_build_reset_password_email_html(self):
        from backend.routes.auth import _build_reset_password_email_html
        html = _build_reset_password_email_html("https://example.com/reset?token=abc")
        self.assertIn("Redefinição de Senha", html)
        self.assertIn("https://example.com/reset?token=abc", html)
        self.assertIn("15 minutos", html)

    def test_build_reset_password_email_html_contains_autoassist(self):
        from backend.routes.auth import _build_reset_password_email_html
        html = _build_reset_password_email_html("https://example.com/reset")
        self.assertIn("AutoAssist", html)

    # ─────────────── _get_frontend_base_url_for_email ───────────────

    @patch("backend.routes.auth.os.getenv")
    def test_get_frontend_base_url_production(self, mock_getenv):
        mock_getenv.side_effect = lambda key, default=None: {
            "FLASK_ENV": "production",
            "URL_PROD": "https://autoassist.app/",
        }.get(key, default or "")

        from backend.routes.auth import _get_frontend_base_url_for_email
        url = _get_frontend_base_url_for_email()
        self.assertEqual(url, "https://autoassist.app/")

    @patch("backend.routes.auth.os.getenv")
    def test_get_frontend_base_url_development(self, mock_getenv):
        mock_getenv.side_effect = lambda key, default=None: {
            "FLASK_ENV": "development",
            "URL_DEV": "http://localhost:3000/",
        }.get(key, default or "")

        from backend.routes.auth import _get_frontend_base_url_for_email
        url = _get_frontend_base_url_for_email()
        self.assertEqual(url, "http://localhost:3000/")

    @patch("backend.routes.auth.os.getenv")
    def test_get_frontend_base_url_fallback(self, mock_getenv):
        mock_getenv.side_effect = lambda key, default=None: {
            "FLASK_ENV": "development",
        }.get(key, default or "")

        from backend.routes.auth import _get_frontend_base_url_for_email
        url = _get_frontend_base_url_for_email()
        self.assertIn("autoassist", url)

    # ─────────────── get_google_oauth_hosts ───────────────

    @patch("backend.routes.auth.requests.get")
    def test_get_google_oauth_hosts_success(self, mock_get):
        import backend.routes.auth
        backend.routes.auth._google_hosts_cache = {"expires_at": 0.0, "hosts": None}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
        }

        from backend.routes.auth import get_google_oauth_hosts
        hosts = get_google_oauth_hosts()
        self.assertIsNotNone(hosts)
        self.assertEqual(hosts.authorization_endpoint, "https://accounts.google.com/o/oauth2/auth")
        self.assertEqual(hosts.token_endpoint, "https://oauth2.googleapis.com/token")
        self.assertEqual(hosts.userinfo_endpoint, "https://openidconnect.googleapis.com/v1/userinfo")

    @patch("backend.routes.auth.requests.get")
    def test_get_google_oauth_hosts_http_error(self, mock_get):
        import backend.routes.auth
        backend.routes.auth._google_hosts_cache = {"expires_at": 0.0, "hosts": None}
        mock_get.return_value.status_code = 500
        from backend.routes.auth import get_google_oauth_hosts
        hosts = get_google_oauth_hosts()
        self.assertIsNone(hosts)

    @patch("backend.routes.auth.requests.get")
    def test_get_google_oauth_hosts_exception(self, mock_get):
        import backend.routes.auth
        backend.routes.auth._google_hosts_cache = {"expires_at": 0.0, "hosts": None}
        mock_get.side_effect = Exception("Network error")
        from backend.routes.auth import get_google_oauth_hosts
        hosts = get_google_oauth_hosts()
        self.assertIsNone(hosts)

    @patch("backend.routes.auth.requests.get")
    def test_get_google_oauth_hosts_caching(self, mock_get):
        import backend.routes.auth
        backend.routes.auth._google_hosts_cache = {"expires_at": 0.0, "hosts": None}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
        }

        from backend.routes.auth import get_google_oauth_hosts
        get_google_oauth_hosts()
        get_google_oauth_hosts()
        self.assertEqual(mock_get.call_count, 1)

    # ─────────────── get_jwt_expires_delta ───────────────

    def test_get_jwt_expires_delta_free(self):
        from backend.routes.auth import get_jwt_expires_delta
        delta = get_jwt_expires_delta({"is_premium": False})
        self.assertEqual(delta, timedelta(days=30))

    def test_get_jwt_expires_delta_premium(self):
        from backend.routes.auth import get_jwt_expires_delta
        delta = get_jwt_expires_delta({"is_premium": True})
        self.assertIs(delta, False)

    # ─────────────── create_user_tokens ───────────────

    @patch("backend.routes.auth.create_access_token")
    @patch("backend.routes.auth.create_refresh_token")
    def test_create_user_tokens(self, mock_refresh, mock_access):
        mock_access.return_value = "access_token"
        mock_refresh.return_value = "refresh_token"
        from backend.routes.auth import create_user_tokens
        access, refr = create_user_tokens({"id": 1, "is_premium": False})
        self.assertEqual(access, "access_token")
        self.assertEqual(refr, "refresh_token")

    @patch("backend.routes.auth.create_access_token")
    @patch("backend.routes.auth.create_refresh_token")
    def test_create_user_tokens_premium(self, mock_refresh, mock_access):
        from backend.routes.auth import create_user_tokens
        create_user_tokens({"id": 1, "is_premium": True})
        mock_access.assert_called_once_with(identity="1", expires_delta=False)
        mock_refresh.assert_called_once_with(identity="1", expires_delta=False)

    # ─────────────── fetch_veiculos_user ───────────────

    def test_fetch_veiculos_user(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"id": 1, "tipo": "carro", "marca": "Fiat", "modelo": "Uno",
             "ano_fabricacao": 2020, "ano_compra": 2020, "quilometragem": 50000}
        ]
        from backend.routes.auth import fetch_veiculos_user
        veiculos = fetch_veiculos_user(mock_cursor, 1)
        self.assertEqual(len(veiculos), 1)
        self.assertEqual(veiculos[0]["marca"], "Fiat")

    def test_fetch_veiculos_user_empty(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        from backend.routes.auth import fetch_veiculos_user
        veiculos = fetch_veiculos_user(mock_cursor, 1)
        self.assertEqual(veiculos, [])

    # ─────────────── process_pending_password_reset_emails ───────────────

    @patch("backend.routes.auth.get_db")
    def test_process_pending_reset_emails_lock_busy(self, mock_get_db):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_get_db.return_value.__enter__.return_value = (mock_cursor, mock_conn)
        mock_cursor.fetchone.return_value = {"got_lock": 0}

        from backend.routes.auth import process_pending_password_reset_emails
        result = process_pending_password_reset_emails(batch_size=10)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["sent"], 0)

    @patch("backend.routes.auth.get_db")
    def test_process_pending_reset_emails_no_pending(self, mock_get_db):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_get_db.return_value.__enter__.return_value = (mock_cursor, mock_conn)
        mock_cursor.fetchone.return_value = {"got_lock": 1}
        mock_cursor.fetchall.return_value = []

        from backend.routes.auth import process_pending_password_reset_emails
        result = process_pending_password_reset_emails(batch_size=10)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["sent"], 0)

    @patch("backend.routes.auth._send_password_reset_email")
    @patch("backend.routes.auth.get_db")
    def test_process_pending_reset_emails_sends(self, mock_get_db, mock_send):
        mock_send.return_value = True
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_get_db.return_value.__enter__.return_value = (mock_cursor, mock_conn)
        mock_cursor.fetchone.return_value = {"got_lock": 1}
        mock_cursor.fetchall.return_value = [
            {"id": 1, "token": "token-1", "email": "user@email.com"},
        ]

        from backend.routes.auth import process_pending_password_reset_emails
        result = process_pending_password_reset_emails(batch_size=10)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["sent"], 1)

    @patch("backend.routes.auth._send_password_reset_email")
    @patch("backend.routes.auth.get_db")
    def test_process_pending_reset_emails_send_fails(self, mock_get_db, mock_send):
        mock_send.return_value = False
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_get_db.return_value.__enter__.return_value = (mock_cursor, mock_conn)
        mock_cursor.fetchone.return_value = {"got_lock": 1}
        mock_cursor.fetchall.return_value = [
            {"id": 1, "token": "token-1", "email": "user@email.com"},
        ]

        from backend.routes.auth import process_pending_password_reset_emails
        result = process_pending_password_reset_emails(batch_size=10)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["sent"], 0)

    # ─────────────── is_trial_expired ───────────────

    def test_trial_not_expired(self):
        user = {"created_at": datetime.now(timezone.utc) - timedelta(days=1)}
        self.assertFalse(is_trial_expired(user))

    def test_trial_expired(self):
        user = {"created_at": datetime.now(timezone.utc) - timedelta(days=35)}
        self.assertTrue(is_trial_expired(user))

    def test_trial_expired_no_user(self):
        self.assertTrue(is_trial_expired(None))
        self.assertTrue(is_trial_expired({}))

    def test_trial_string_date_recent(self):
        date_str = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        user = {"created_at": date_str}
        self.assertFalse(is_trial_expired(user))

    def test_trial_string_date_expired(self):
        date_str = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        user = {"created_at": date_str}
        self.assertTrue(is_trial_expired(user))

    def test_trial_invalid_string(self):
        user = {"created_at": "not-a-date"}
        self.assertTrue(is_trial_expired(user))

    # ─────────────── get_trial_days_remaining ───────────────

    def test_trial_days_remaining_positive(self):
        user = {"created_at": datetime.now(timezone.utc) - timedelta(days=1)}
        remaining = get_trial_days_remaining(user)
        self.assertGreater(remaining, 0)

    def test_trial_days_remaining_zero(self):
        user = {"created_at": datetime.now(timezone.utc) - timedelta(days=35)}
        self.assertEqual(get_trial_days_remaining(user), 0)

    def test_trial_days_remaining_no_user(self):
        self.assertEqual(get_trial_days_remaining(None), 0)
        self.assertEqual(get_trial_days_remaining({}), 0)

    # ─────────────── is_valid_email_domain ───────────────

    def test_valid_email(self):
        self.assertTrue(is_valid_email_domain("user@example.com"))
        self.assertTrue(is_valid_email_domain("test@sub.domain.com.br"))
        self.assertTrue(is_valid_email_domain("user+tag@example.org"))

    def test_invalid_email(self):
        self.assertFalse(is_valid_email_domain("notanemail"))
        self.assertFalse(is_valid_email_domain("user@"))
        self.assertFalse(is_valid_email_domain("@domain.com"))
        self.assertFalse(is_valid_email_domain(""))
        self.assertFalse(is_valid_email_domain(None))
        self.assertFalse(is_valid_email_domain(12345))


if __name__ == "__main__":
    unittest.main()
