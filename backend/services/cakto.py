import logging
import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class CaktoService:
    """Servicos utilitarios para integracao de checkout/webhook com a Cakto."""

    PAID_EVENTS = {
        "purchase_approved",
        "subscription_created",
        "subscription_renewed",
    }

    REVOKE_EVENTS = {
        "purchase_refused",
        "refund",
        "chargeback",
        "subscription_canceled",
        "subscription_renewal_refused",
    }

    def __init__(self):
        self.default_checkout_url = (os.getenv("CAKTO_CHECKOUT_URL") or "").strip()
        self.webhook_secret = (os.getenv("CAKTO_WEBHOOK_SECRET") or "").strip()
        self.accept_query_secret = (
            (os.getenv("CAKTO_ACCEPT_QUERY_SECRET") or "1").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self.auto_append_ref = (
            (os.getenv("CAKTO_APPEND_REF") or "1").strip().lower()
            not in {"0", "false", "no", "off"}
        )

    def build_checkout_url(
        self,
        *,
        user_id: str,
        user_email: str | None = None,
        provided_url: str | None = None,
    ) -> str:
        base_url = (provided_url or self.default_checkout_url or "").strip()
        if not base_url:
            raise ValueError(
                "URL de checkout da Cakto nao configurada. Defina CAKTO_CHECKOUT_URL."
            )

        if not self.auto_append_ref:
            return base_url

        parsed = urlparse(base_url)
        query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query_items.setdefault("src", "autoassist")
        query_items.setdefault("user_ref", str(user_id))
        if user_email:
            query_items.setdefault("email", user_email)

        new_query = urlencode(query_items)
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
        )

    @staticmethod
    def extract_event(payload: dict) -> str:
        event = payload.get("event")
        if event is None and isinstance(payload.get("data"), dict):
            event = payload["data"].get("event")
        return str(event or "").strip().lower()

    @staticmethod
    def extract_data(payload: dict) -> dict:
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def should_activate_premium(cls, event: str, status: str) -> bool:
        event = (event or "").strip().lower()
        status = (status or "").strip().lower()
        if event in cls.PAID_EVENTS:
            return True
        return status in {"paid", "approved"}

    @classmethod
    def should_deactivate_premium(cls, event: str, status: str) -> bool:
        event = (event or "").strip().lower()
        status = (status or "").strip().lower()
        if event in cls.REVOKE_EVENTS:
            return True
        return status in {"refunded", "chargedback", "canceled", "cancelled", "refused"}

    @staticmethod
    def extract_customer_email(payload: dict) -> str | None:
        data = CaktoService.extract_data(payload)

        customer = data.get("customer") if isinstance(data, dict) else None
        if isinstance(customer, dict):
            email = customer.get("email")
            if isinstance(email, str) and email.strip():
                return email.strip().lower()

        for key in ("email", "customer_email", "buyer_email"):
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip().lower()

        return None

    @staticmethod
    def extract_reference_user_id(payload: dict) -> str | None:
        data = CaktoService.extract_data(payload)
        candidates = (
            data.get("user_ref"),
            data.get("user_id"),
            data.get("external_reference"),
            payload.get("user_ref"),
            payload.get("user_id"),
            payload.get("external_reference"),
        )

        for candidate in candidates:
            if candidate is None:
                continue
            as_text = str(candidate).strip()
            if as_text.isdigit():
                return as_text
        return None

    def validate_secret(
        self,
        *,
        payload: dict,
        headers: dict,
        query_secret: str | None = None,
    ) -> tuple[bool, str]:
        if not self.webhook_secret:
            return False, "CAKTO_WEBHOOK_SECRET nao configurado no servidor."

        provided_candidates = [
            payload.get("secret") if isinstance(payload, dict) else None,
            headers.get("X-Cakto-Secret"),
            headers.get("X-Webhook-Secret"),
            headers.get("X-Api-Key"),
        ]
        auth_header = headers.get("Authorization")
        if isinstance(auth_header, str) and auth_header.lower().startswith("bearer "):
            provided_candidates.append(auth_header[7:].strip())

        if self.accept_query_secret and query_secret:
            provided_candidates.append(query_secret)

        normalized = [str(value).strip() for value in provided_candidates if value]
        if not normalized:
            return False, "Secret do webhook ausente."

        if self.webhook_secret in normalized:
            return True, "ok"
        return False, "Secret do webhook invalido."
