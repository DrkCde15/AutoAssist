import sys
import unittest
from unittest.mock import patch, MagicMock, ANY, call
from pathlib import Path
from datetime import datetime, timedelta, timezone

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "backend"))

from backend.routes.database import (
    is_trial_expired,
    get_trial_days_remaining,
    is_valid_email_domain,
    get_mysql_history,
)


class TrialExpiryTest(unittest.TestCase):
    def test_trial_not_expired(self):
        user = {"created_at": datetime.now(timezone.utc) - timedelta(days=1)}
        self.assertFalse(is_trial_expired(user))

    def test_trial_expired(self):
        user = {"created_at": datetime.now(timezone.utc) - timedelta(days=35)}
        self.assertTrue(is_trial_expired(user))

    def test_trial_no_user(self):
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
        user = {"created_at": "invalid-date"}
        self.assertTrue(is_trial_expired(user))

    def test_trial_days_remaining_positive(self):
        user = {"created_at": datetime.now(timezone.utc) - timedelta(days=1)}
        self.assertGreater(get_trial_days_remaining(user), 0)

    def test_trial_days_remaining_zero(self):
        user = {"created_at": datetime.now(timezone.utc) - timedelta(days=35)}
        self.assertEqual(get_trial_days_remaining(user), 0)

    def test_trial_days_remaining_no_user(self):
        self.assertEqual(get_trial_days_remaining(None), 0)
        self.assertEqual(get_trial_days_remaining({}), 0)


class EmailValidationTest(unittest.TestCase):
    def test_valid_emails(self):
        self.assertTrue(is_valid_email_domain("user@example.com"))
        self.assertTrue(is_valid_email_domain("test@sub.domain.com.br"))
        self.assertTrue(is_valid_email_domain("user+tag@example.org"))

    def test_invalid_emails(self):
        self.assertFalse(is_valid_email_domain("notanemail"))
        self.assertFalse(is_valid_email_domain("user@"))
        self.assertFalse(is_valid_email_domain("@domain.com"))
        self.assertFalse(is_valid_email_domain(""))
        self.assertFalse(is_valid_email_domain(None))
        self.assertFalse(is_valid_email_domain(12345))


class MysqlHistoryTest(unittest.TestCase):
    def test_get_history_with_cursor(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"mensagem_usuario": "ola", "resposta_ia": "oi"},
            {"mensagem_usuario": "qual o oleo?", "resposta_ia": "use 5w30"},
        ]

        history = get_mysql_history(1, limit=5, cursor=mock_cursor)

        self.assertEqual(len(history), 4)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "qual o oleo?")
        self.assertEqual(history[1]["role"], "model")
        self.assertEqual(history[1]["content"], "use 5w30")
        self.assertEqual(history[2]["role"], "user")
        self.assertEqual(history[2]["content"], "ola")
        self.assertEqual(history[3]["role"], "model")
        self.assertEqual(history[3]["content"], "oi")

    def test_get_history_empty(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        history = get_mysql_history(1, limit=5, cursor=mock_cursor)
        self.assertEqual(history, [])

    def test_get_history_only_user(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"mensagem_usuario": "test", "resposta_ia": None},
        ]

        history = get_mysql_history(1, limit=5, cursor=mock_cursor)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["role"], "user")

    def test_get_history_only_model(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"mensagem_usuario": None, "resposta_ia": "answer"},
        ]

        history = get_mysql_history(1, limit=5, cursor=mock_cursor)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["role"], "model")

    def test_get_history_without_cursor(self):
        with patch("backend.routes.database.get_db") as mock_get_db:
            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_get_db.return_value.__enter__.return_value = (mock_cursor, mock_conn)
            mock_cursor.fetchall.return_value = [
                {"mensagem_usuario": "test", "resposta_ia": "answer"}
            ]

            history = get_mysql_history(1, limit=5)
            self.assertEqual(len(history), 2)

    def test_get_history_cursor_exception_returns_empty(self):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("DB error")

        history = get_mysql_history(1, limit=5, cursor=mock_cursor)
        self.assertEqual(history, [])


if __name__ == "__main__":
    unittest.main()
