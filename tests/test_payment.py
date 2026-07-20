import sys
import unittest
from unittest.mock import patch, MagicMock, ANY, call
from pathlib import Path
import flask

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "backend"))

from backend.services.cakto import CaktoService
import backend.routes.payment as payment_module


class CaktoServiceTest(unittest.TestCase):
    # ─────────────── build_checkout_url ───────────────

    def test_build_checkout_url_basic(self):
        service = CaktoService()
        service.default_checkout_url = "https://pay.cakto.com.br/checkout"
        service.auto_append_ref = True

        url = service.build_checkout_url(user_id="1")

        self.assertIn("src=autoassist", url)
        self.assertIn("user_ref=1", url)
        self.assertIn("sck=1", url)

    def test_build_checkout_url_with_email(self):
        service = CaktoService()
        service.default_checkout_url = "https://pay.cakto.com.br/checkout"
        service.auto_append_ref = True

        url = service.build_checkout_url(user_id="1", user_email="user@email.com")

        self.assertIn("email=user%40email.com", url)

    def test_build_checkout_url_no_auto_append(self):
        service = CaktoService()
        service.default_checkout_url = "https://pay.cakto.com.br/checkout"
        service.auto_append_ref = False

        url = service.build_checkout_url(user_id="1")

        self.assertEqual(url, "https://pay.cakto.com.br/checkout")

    def test_build_checkout_url_with_internal_order(self):
        service = CaktoService()
        service.default_checkout_url = "https://pay.cakto.com.br/checkout"
        service.auto_append_ref = True

        url = service.build_checkout_url(user_id="1", internal_order_id="order-abc")

        self.assertIn("user_ref=order-abc", url)
        self.assertIn("sck=order-abc", url)

    def test_build_checkout_url_with_payment_method(self):
        service = CaktoService()
        service.default_checkout_url = "https://pay.cakto.com.br/checkout"
        service.auto_append_ref = True

        url = service.build_checkout_url(user_id="1", payment_method="pix")

        self.assertIn("payment_method=pix", url)

    def test_build_checkout_url_missing_url_raises(self):
        service = CaktoService()
        service.default_checkout_url = ""
        service.auto_append_ref = True

        with self.assertRaises(ValueError) as ctx:
            service.build_checkout_url(user_id="1")
        self.assertIn("CAKTO_CHECKOUT_URL", str(ctx.exception))

    def test_build_checkout_url_uses_provided_url(self):
        service = CaktoService()
        service.default_checkout_url = "https://default.url"
        service.auto_append_ref = True

        url = service.build_checkout_url(user_id="1", provided_url="https://custom.url/checkout")
        self.assertIn("https://custom.url/checkout", url)
        self.assertNotIn("https://default.url", url)

    def test_build_checkout_url_preserves_existing_query(self):
        service = CaktoService()
        service.default_checkout_url = "https://pay.cakto.com.br/checkout?existing=param"
        service.auto_append_ref = True

        url = service.build_checkout_url(user_id="1")

        self.assertIn("existing=param", url)
        self.assertIn("src=autoassist", url)

    # ─────────────── extract_event ───────────────

    def test_extract_event_from_root(self):
        payload = {"event": "purchase_approved", "data": {}}
        self.assertEqual(CaktoService.extract_event(payload), "purchase_approved")

    def test_extract_event_from_data(self):
        payload = {"data": {"event": "subscription_created"}}
        self.assertEqual(CaktoService.extract_event(payload), "subscription_created")

    def test_extract_event_empty(self):
        self.assertEqual(CaktoService.extract_event({}), "")
        self.assertEqual(CaktoService.extract_event({"data": {}}), "")

    # ─────────────── extract_data ───────────────

    def test_extract_data_from_data_key(self):
        payload = {"data": {"status": "paid"}}
        self.assertEqual(CaktoService.extract_data(payload), {"status": "paid"})

    def test_extract_data_fallback(self):
        payload = {"status": "paid"}
        self.assertEqual(CaktoService.extract_data(payload), {"status": "paid"})

    # ─────────────── should_activate_premium ───────────────

    def test_should_activate_premium_by_event(self):
        self.assertTrue(CaktoService.should_activate_premium("purchase_approved", ""))
        self.assertTrue(CaktoService.should_activate_premium("subscription_created", ""))
        self.assertTrue(CaktoService.should_activate_premium("subscription_renewed", ""))

    def test_should_activate_premium_by_status(self):
        self.assertTrue(CaktoService.should_activate_premium("", "paid"))
        self.assertTrue(CaktoService.should_activate_premium("", "approved"))

    def test_should_activate_premium_false(self):
        self.assertFalse(CaktoService.should_activate_premium("some_event", "some_status"))

    # ─────────────── should_deactivate_premium ───────────────

    def test_should_deactivate_premium_by_event(self):
        self.assertTrue(CaktoService.should_deactivate_premium("purchase_refused", ""))
        self.assertTrue(CaktoService.should_deactivate_premium("refund", ""))
        self.assertTrue(CaktoService.should_deactivate_premium("chargeback", ""))
        self.assertTrue(CaktoService.should_deactivate_premium("subscription_canceled", ""))
        self.assertTrue(CaktoService.should_deactivate_premium("subscription_renewal_refused", ""))

    def test_should_deactivate_premium_by_status(self):
        self.assertTrue(CaktoService.should_deactivate_premium("", "refunded"))
        self.assertTrue(CaktoService.should_deactivate_premium("", "chargedback"))
        self.assertTrue(CaktoService.should_deactivate_premium("", "canceled"))

    def test_should_deactivate_premium_false(self):
        self.assertFalse(CaktoService.should_deactivate_premium("some_event", "some_status"))

    # ─────────────── extract_customer_email ───────────────

    def test_extract_customer_email_from_customer_obj(self):
        payload = {"data": {"customer": {"email": "user@email.com"}}}
        self.assertEqual(CaktoService.extract_customer_email(payload), "user@email.com")

    def test_extract_customer_email_direct(self):
        payload = {"data": {"email": "user@email.com"}}
        self.assertEqual(CaktoService.extract_customer_email(payload), "user@email.com")

    def test_extract_customer_email_alternative_keys(self):
        payload = {"data": {"customer_email": "user@email.com"}}
        self.assertEqual(CaktoService.extract_customer_email(payload), "user@email.com")

    def test_extract_customer_email_none(self):
        self.assertIsNone(CaktoService.extract_customer_email({}))

    # ─────────────── extract_reference_user_id ───────────────

    def test_extract_reference_from_user_ref(self):
        payload = {"data": {"user_ref": "order-123"}}
        self.assertEqual(CaktoService.extract_reference_user_id(payload), "order-123")

    def test_extract_reference_from_sck(self):
        payload = {"data": {"sck": "sck-value"}}
        self.assertEqual(CaktoService.extract_reference_user_id(payload), "sck-value")

    def test_extract_reference_from_root(self):
        payload = {"user_ref": "root-ref"}
        self.assertEqual(CaktoService.extract_reference_user_id(payload), "root-ref")

    def test_extract_reference_from_refid(self):
        payload = {"data": {"refId": "order-refid"}}
        self.assertEqual(CaktoService.extract_reference_user_id(payload), "order-refid")

    def test_extract_reference_fallback_order(self):
        payload = {"data": {"user_id": "uid", "external_reference": "ext-ref"}}
        result = CaktoService.extract_reference_user_id(payload)
        self.assertIn(result, ("uid", "ext-ref"))

    # ─────────────── validate_secret ───────────────

    def test_validate_secret_missing_config(self):
        service = CaktoService()
        service.webhook_secret = ""  # not configured

        ok, reason = service.validate_secret(payload={}, headers={})
        self.assertFalse(ok)
        self.assertIn("nao configurado", reason)

    def test_validate_secret_match_from_payload(self):
        service = CaktoService()
        service.webhook_secret = "mysecret"

        ok, reason = service.validate_secret(payload={"secret": "mysecret"}, headers={})
        self.assertTrue(ok)

    def test_validate_secret_match_from_header(self):
        service = CaktoService()
        service.webhook_secret = "mysecret"

        ok, reason = service.validate_secret(payload={}, headers={"X-Cakto-Secret": "mysecret"})
        self.assertTrue(ok)

    def test_validate_secret_match_from_bearer(self):
        service = CaktoService()
        service.webhook_secret = "mysecret"

        ok, reason = service.validate_secret(
            payload={}, headers={"Authorization": "Bearer mysecret"}
        )
        self.assertTrue(ok)

    def test_validate_secret_match_from_query(self):
        service = CaktoService()
        service.webhook_secret = "mysecret"
        service.accept_query_secret = True

        ok, reason = service.validate_secret(payload={}, headers={}, query_secret="mysecret")
        self.assertTrue(ok)

    def test_validate_secret_query_disabled(self):
        service = CaktoService()
        service.webhook_secret = "mysecret"
        service.accept_query_secret = False

        ok, reason = service.validate_secret(payload={}, headers={}, query_secret="mysecret")
        self.assertFalse(ok)

    def test_validate_secret_no_match(self):
        service = CaktoService()
        service.webhook_secret = "mysecret"

        ok, reason = service.validate_secret(payload={"secret": "wrong"}, headers={})
        self.assertFalse(ok)

    def test_validate_secret_no_secret_present(self):
        service = CaktoService()
        service.webhook_secret = "mysecret"

        ok, reason = service.validate_secret(payload={}, headers={})
        self.assertFalse(ok)
        self.assertIn("ausente", reason)


class PaymentHelpersTest(unittest.TestCase):
    def setUp(self):
        self.mock_get_db = patch("backend.routes.payment.get_db").start()
        self.mock_cursor = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_get_db.return_value.__enter__.return_value = (
            self.mock_cursor,
            self.mock_conn,
        )

    def tearDown(self):
        patch.stopall()

    # ─────────────── _get_user_email ───────────────

    def test_get_user_email_found(self):
        from backend.routes.payment import _get_user_email
        self.mock_cursor.fetchone.return_value = {"email": "user@email.com"}
        email = _get_user_email("1")
        self.assertEqual(email, "user@email.com")

    def test_get_user_email_not_found(self):
        from backend.routes.payment import _get_user_email
        self.mock_cursor.fetchone.return_value = None
        email = _get_user_email("999")
        self.assertIsNone(email)

    def test_get_user_email_empty_string(self):
        from backend.routes.payment import _get_user_email
        self.mock_cursor.fetchone.return_value = {"email": ""}
        email = _get_user_email("1")
        self.assertIsNone(email)

    def test_get_user_email_whitespace(self):
        from backend.routes.payment import _get_user_email
        self.mock_cursor.fetchone.return_value = {"email": "  "}
        email = _get_user_email("1")
        self.assertIsNone(email)

    # ─────────────── _set_premium_by_user_id ───────────────

    def test_set_premium_by_user_id_update_ok(self):
        from backend.routes.payment import _set_premium_by_user_id
        self.mock_cursor.rowcount = 1
        result = _set_premium_by_user_id("1", True)
        self.assertEqual(result, 1)

    def test_set_premium_by_user_id_no_rows_affected_but_already_set(self):
        from backend.routes.payment import _set_premium_by_user_id
        self.mock_cursor.rowcount = 0
        self.mock_cursor.fetchone.return_value = {"id": 1}
        result = _set_premium_by_user_id("1", True)
        self.assertEqual(result, 1)

    def test_set_premium_by_user_id_not_found(self):
        from backend.routes.payment import _set_premium_by_user_id
        self.mock_cursor.rowcount = 0
        self.mock_cursor.fetchone.side_effect = [None, None]
        result = _set_premium_by_user_id("999", True)
        self.assertEqual(result, 0)

    # ─────────────── _set_premium_by_email ───────────────

    def test_set_premium_by_email_update_ok(self):
        from backend.routes.payment import _set_premium_by_email
        self.mock_cursor.rowcount = 1
        result = _set_premium_by_email("user@email.com", True)
        self.assertEqual(result, 1)

    def test_set_premium_by_email_no_rows_affected_but_already_set(self):
        from backend.routes.payment import _set_premium_by_email
        self.mock_cursor.rowcount = 0
        self.mock_cursor.fetchone.return_value = {"id": 1}
        result = _set_premium_by_email("user@email.com", True)
        self.assertEqual(result, 1)

    def test_set_premium_by_email_not_found(self):
        from backend.routes.payment import _set_premium_by_email
        self.mock_cursor.rowcount = 0
        self.mock_cursor.fetchone.side_effect = [None, None]
        result = _set_premium_by_email("unknown@email.com", True)
        self.assertEqual(result, 0)


class PaymentRoutesTest(unittest.TestCase):
    def setUp(self):
        self.mock_get_db = patch("backend.routes.payment.get_db").start()
        self.mock_cursor = MagicMock()
        self.mock_cursor.rowcount = 1
        self.mock_conn = MagicMock()
        self.mock_get_db.return_value.__enter__.return_value = (
            self.mock_cursor,
            self.mock_conn,
        )
        self.mock_service = MagicMock()
        self.mock_service.validate_secret.return_value = (True, "ok")
        self.mock_service.extract_event.return_value = "purchase_approved"
        self.mock_service.extract_data.return_value = {"id": "tx-1"}
        self.mock_service.extract_customer_email.return_value = None
        self.mock_service.extract_reference_user_id.return_value = "order-1"
        self.mock_service.should_activate_premium.return_value = True
        self.mock_service.should_deactivate_premium.return_value = False
        self.mock_service.verify_transaction_status.return_value = (True, 29.90)
        self.mock_service.build_checkout_url.return_value = (
            "https://pay.cakto.com.br/checkout?user_ref=order-1"
        )
        self.patcher_service = patch(
            "backend.routes.payment.get_service", return_value=self.mock_service
        )
        self.patcher_service.start()
        self.patcher_identity = patch(
            "backend.routes.payment.get_jwt_identity", return_value="1"
        )
        self.patcher_identity.start()
        self.patcher_push = patch("backend.routes.payment.send_push_notification").start()
        self.app = flask.Flask(__name__)
        self.app.config["JWT_SECRET_KEY"] = "test-secret"
        self.app.config["JWT_TOKEN_LOCATION"] = ["headers"]
        self.app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False
        from flask_jwt_extended import JWTManager
        JWTManager(self.app)

    def tearDown(self):
        patch.stopall()

    def _post(self, path, json_body=None, headers=None, args=None):
        from flask_jwt_extended import create_access_token
        with self.app.app_context():
            token = create_access_token(identity="1")
        req_headers = dict(headers or {})
        req_headers["Authorization"] = f"Bearer {token}"
        with self.app.test_request_context(
            path,
            method="POST",
            json=json_body or {},
            headers=req_headers,
            query_string=args or {},
        ):
            if path.endswith("/api/pay/preference"):
                return payment_module.create_preference()
            return payment_module.cakto_webhook()

    def test_create_preference_stores_plan_and_amount(self):
        from backend.routes.payment import create_preference as _unused  # noqa
        resp = self._post("/api/pay/preference", json_body={})
        self.assertEqual(resp[1], 201)
        self.assertTrue(resp[0].json["success"])
        # O pedido interno deve gravar plan/amount/currency esperados.
        insert_calls = [
            c for c in self.mock_cursor.execute.call_args_list
            if "INSERT INTO payments_orders" in (c.args[0] or "")
        ]
        self.assertEqual(len(insert_calls), 1)
        insert_params = insert_calls[0].args[1]
        # (id, user_id, plan, amount, currency, provider)
        self.assertEqual(insert_params[2], "completo")
        self.assertEqual(float(insert_params[3]), 29.90)
        self.assertEqual(insert_params[4], "BRL")

    def test_create_preference_rejects_unknown_plan(self):
        resp = self._post("/api/pay/preference", json_body={"plan": "inexistente"})
        self.assertEqual(resp[1], 400)
        self.assertFalse(resp[0].json["success"])

    def test_webhook_activates_premium_with_matching_amount(self):
        from backend.routes.payment import cakto_webhook as _unused  # noqa
        self.mock_cursor.fetchone.return_value = {
            "user_id": "1",
            "status": "pending",
            "plan": "completo",
            "amount": 29.90,
            "currency": "BRL",
        }
        resp = self._post("/api/pay/webhook/cakto", json_body={"id": "tx-1", "data": {}})
        self.assertEqual(resp[1], 200)
        self.assertTrue(resp[0].json["success"])
        self.assertTrue(resp[0].json["premium"])
        # Deve ter atualizado o usuario para premium (3o execute: SELECT order,
        # UPDATE payments_orders, UPDATE users).
        update_sql = self.mock_cursor.execute.call_args_list[2].args[0]
        self.assertIn("UPDATE users SET is_premium", update_sql)

    def test_webhook_rejects_amount_mismatch(self):
        self.mock_service.verify_transaction_status.return_value = (True, 9.90)
        self.mock_cursor.fetchone.return_value = {
            "user_id": "1",
            "status": "pending",
            "plan": "completo",
            "amount": 29.90,
            "currency": "BRL",
        }
        resp = self._post("/api/pay/webhook/cakto", json_body={"id": "tx-1", "data": {}})
        self.assertEqual(resp[1], 400)
        self.assertIn("Valor pago diverge", resp[0].json["error"])

    def test_webhook_rejects_unpaid_transaction(self):
        self.mock_service.verify_transaction_status.return_value = (False, None)
        self.mock_cursor.fetchone.return_value = {
            "user_id": "1",
            "status": "pending",
            "plan": "completo",
            "amount": 29.90,
            "currency": "BRL",
        }
        resp = self._post("/api/pay/webhook/cakto", json_body={"id": "tx-1", "data": {}})
        self.assertEqual(resp[1], 400)
        self.assertIn("nao confirmado", resp[0].json["error"])

    def test_webhook_missing_transaction_id(self):
        self.mock_service.extract_data.return_value = {}
        resp = self._post("/api/pay/webhook/cakto", json_body={"data": {}})
        self.assertEqual(resp[1], 400)
        self.assertIn("ID de transacao ausente", resp[0].json["error"])


if __name__ == "__main__":
    unittest.main()
