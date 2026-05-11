import logging
import os
import secrets
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
        self.client_id = (os.getenv("CLIENT_ID") or "").strip()
        self.client_secret = (os.getenv("CLIENT_SECRET") or "").strip()
        self.api_base_url = "https://api.cakto.com.br"
        self._access_token = None

    def build_checkout_url(
        self,
        *,
        user_id: str,
        user_email: str | None = None,
        provided_url: str | None = None,
        payment_method: str | None = None,
        internal_order_id: str | None = None,
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
        
        # Se tivermos um order_id interno, usamos ele como referência principal
        # para validar o webhook de forma estrita.
        if internal_order_id:
            query_items.setdefault("user_ref", str(internal_order_id))
        else:
            query_items.setdefault("user_ref", str(user_id))

        if user_email:
            query_items.setdefault("email", user_email)
        if payment_method:
            query_items.setdefault("payment_method", str(payment_method).strip().lower())

        new_query = urlencode(query_items)
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
        )

    def get_access_token(self) -> str:
        if self._access_token:
            return self._access_token

        if not self.client_id or not self.client_secret:
            logger.error("CLIENT_ID ou CLIENT_SECRET nao configurados.")
            raise ValueError("Credenciais da API da Cakto nao configuradas.")

        import requests
        url = f"{self.api_base_url}/public_api/token/"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials" # Padrao OAuth2 se exigido, mas enviaremos todos os campos necessarios
        }
        
        try:
            response = requests.post(url, data=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            self._access_token = data.get("access_token")
            return self._access_token
        except requests.RequestException as e:
            logger.error("Falha ao obter access token da Cakto: %s", e)
            raise ValueError("Erro ao autenticar na API da Cakto.")

    def verify_transaction_status(self, transaction_id: str) -> bool:
        """Faz a consulta ativa do pedido na Cakto para confirmar o status."""
        if not transaction_id:
            return False

        try:
            token = self.get_access_token()
            import requests
            url = f"{self.api_base_url}/public_api/orders/{transaction_id}/" # Assumindo endpoint padrao de pedido
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 404:
                logger.warning("Pedido %s nao encontrado na API Cakto.", transaction_id)
                return False
                
            response.raise_for_status()
            data = response.json()
            
            # Ajuste dependendo da estrutura real de retorno, tipicamente retorna o obj do pedido
            status = str(data.get("status") or "").strip().lower()
            return status in {"paid", "approved"}
            
        except Exception as e:
            logger.error("Erro ao validar transacao %s na Cakto: %s", transaction_id, e)
            return False

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
            if as_text:
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

        if any(secrets.compare_digest(self.webhook_secret, value) for value in normalized):
            return True, "ok"
        return False, "Secret do webhook invalido."
