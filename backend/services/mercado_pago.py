import os
import uuid
import logging
from typing import Any, TYPE_CHECKING
from dotenv import load_dotenv

try:
    import mercadopago
    from mercadopago.config import RequestOptions as MercadoPagoRequestOptions
except ImportError:  # pragma: no cover - depende do ambiente
    mercadopago = None
    MercadoPagoRequestOptions = None

if TYPE_CHECKING:
    from mercadopago.config import RequestOptions

load_dotenv()
logger = logging.getLogger(__name__)

class MercadoPagoService:
    def __init__(self):
        token_source = None
        raw_token = os.getenv("MERCADO_PAGO_ACCESS_TOKEN")
        if raw_token:
            token_source = "MERCADO_PAGO_ACCESS_TOKEN"
        elif os.getenv("MP_ACCESS_TOKEN"):
            raw_token = os.getenv("MP_ACCESS_TOKEN")
            token_source = "MP_ACCESS_TOKEN"
        elif os.getenv("ACCESS_TOKEN"):
            raw_token = os.getenv("ACCESS_TOKEN")
            token_source = "ACCESS_TOKEN"

        self.token = raw_token.strip() if isinstance(raw_token, str) else None
        if not self.token:
            raise ValueError(
                "Token do Mercado Pago nao encontrado. "
                "Configure MERCADO_PAGO_ACCESS_TOKEN (ou MP_ACCESS_TOKEN/ACCESS_TOKEN)."
            )

        token_format = (
            "APP_USR"
            if self.token.startswith("APP_USR-")
            else "TEST"
            if self.token.startswith("TEST-")
            else "UNKNOWN"
        )
        env_hint = (os.getenv("MERCADO_PAGO_ENV") or "").strip().lower() or "not_set"
        logger.info(
            "Mercado Pago token carregado | source=%s | format=%s | env_hint=%s",
            token_source or "unknown",
            token_format,
            env_hint,
        )
        if token_source != "MERCADO_PAGO_ACCESS_TOKEN":
            logger.warning(
                "Usando fallback de token (%s). Recomenda-se usar apenas MERCADO_PAGO_ACCESS_TOKEN no .env.",
                token_source or "unknown",
            )

        if mercadopago is None:
            raise ImportError(
                "Pacote 'mercadopago' nao encontrado. "
                "Instale com: pip install mercadopago"
            )
        self.sdk = mercadopago.SDK(self.token)
        self.default_notification_url = os.getenv("MERCADO_PAGO_NOTIFICATION_URL")
        self.timeout = int(os.getenv("MERCADO_PAGO_TIMEOUT", "15"))
        self.env_mode = (os.getenv("MERCADO_PAGO_ENV") or "").strip().lower()
        self.test_scope = (os.getenv("MERCADO_PAGO_TEST_SCOPE") or "").strip()
        self.test_pix_auto_approve = (
            (os.getenv("MERCADO_PAGO_TEST_PIX_AUTO_APPROVE") or "1").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        if not self.test_scope and self.env_mode == "test":
            self.test_scope = "sandbox"

        if self.test_scope:
            logger.info("Mercado Pago test scope habilitado | x-test-scope=%s", self.test_scope)

    def criar_pix(
        self,
        customer: dict,
        items: list,
        valor_centavos: int,
        expiration_date: str | None = None,
        reference_id: str | None = None,
        notification_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        if self.env_mode == "test":
            result = self._create_pix_order_test(
                customer=customer,
                valor_centavos=valor_centavos,
                reference_id=reference_id,
                notification_url=notification_url,
                idempotency_key=idempotency_key,
            )
            if result.get("success"):
                result["data"] = self._adapt_pix_result(result.get("data"))
            return result

        payload = {
            "transaction_amount": self._centavos_para_reais(valor_centavos),
            "description": self._montar_descricao(items),
            "payment_method_id": "pix",
            "external_reference": reference_id or f"pedido-{uuid.uuid4().hex[:8]}",
            "payer": self._montar_payer(customer),
        }
        if expiration_date:
            payload["date_of_expiration"] = expiration_date
        final_notification_url = notification_url or self.default_notification_url
        if final_notification_url:
            payload["notification_url"] = final_notification_url

        return self._create_payment(
            payload,
            idempotency_key=idempotency_key,
        )

    def criar_boleto(
        self,
        customer: dict,
        items: list,
        valor_centavos: int,
        due_date: str | None = None,
        reference_id: str | None = None,
        notification_url: str | None = None,
        payment_method_id: str = "bolbradesco",
        idempotency_key: str | None = None,
    ) -> dict:
        payload = {
            "transaction_amount": self._centavos_para_reais(valor_centavos),
            "description": self._montar_descricao(items),
            "payment_method_id": payment_method_id,
            "external_reference": reference_id or f"pedido-{uuid.uuid4().hex[:8]}",
            "payer": self._montar_payer(customer),
        }
        if due_date:
            payload["date_of_expiration"] = due_date
        final_notification_url = notification_url or self.default_notification_url
        if final_notification_url:
            payload["notification_url"] = final_notification_url

        return self._create_payment(
            payload,
            idempotency_key=idempotency_key,
        )

    def criar_cobranca_cartao(
        self,
        customer: dict,
        items: list,
        valor_centavos: int,
        card_token: str,
        payment_method_id: str,
        installments: int = 1,
        capture: bool = True,
        issuer_id: str | None = None,
        reference_id: str | None = None,
        notification_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        payload = {
            "transaction_amount": self._centavos_para_reais(valor_centavos),
            "description": self._montar_descricao(items),
            "token": card_token,
            "installments": installments,
            "payment_method_id": payment_method_id,
            "capture": capture,
            "external_reference": reference_id or f"pedido-{uuid.uuid4().hex[:8]}",
            "payer": self._montar_payer(customer),
        }
        if issuer_id:
            payload["issuer_id"] = issuer_id
        final_notification_url = notification_url or self.default_notification_url
        if final_notification_url:
            payload["notification_url"] = final_notification_url

        return self._create_payment(
            payload,
            idempotency_key=idempotency_key,
        )

    def consultar_pagamento(self, payment_id: str) -> dict:
        try:
            result = self.sdk.payment().get(
                payment_id,
                self._build_request_options(),
            )
            return self._normalize_sdk_result(result)
        except Exception as exc:
            return {"success": False, "status_code": 503, "error": str(exc)}

    def consultar_order(self, order_id: str) -> dict:
        try:
            result = self.sdk.order().get(
                order_id,
                self._build_request_options(),
            )
            return self._normalize_sdk_result(result)
        except Exception as exc:
            return {"success": False, "status_code": 503, "error": str(exc)}

    def criar_preferencia(
        self,
        preference_data: dict,
        idempotency_key: str | None = None,
    ) -> dict:
        if not isinstance(preference_data, dict):
            return {
                "success": False,
                "status_code": 400,
                "error": "preference_data deve ser um objeto JSON.",
            }
        try:
            result = self.sdk.preference().create(
                preference_data,
                self._build_request_options(
                    idempotency_key=idempotency_key,
                    with_idempotency=True,
                ),
            )
            return self._normalize_sdk_result(result)
        except Exception as exc:
            return {"success": False, "status_code": 503, "error": str(exc)}

    def reembolsar_pagamento(
        self,
        payment_id: str,
        valor_centavos: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        refund_payload = None
        if valor_centavos is not None:
            refund_payload = {"amount": self._centavos_para_reais(valor_centavos)}
        try:
            result = self.sdk.refund().create(
                payment_id,
                refund_payload,
                self._build_request_options(
                    idempotency_key=idempotency_key,
                    with_idempotency=True,
                ),
            )
            return self._normalize_sdk_result(result)
        except Exception as exc:
            return {"success": False, "status_code": 503, "error": str(exc)}

    def _montar_payer(self, customer: dict) -> dict:
        customer = customer or {}
        payer: dict[str, Any] = {}

        email = customer.get("email")
        if email:
            payer["email"] = email

        first_name = customer.get("first_name")
        last_name = customer.get("last_name")
        name = customer.get("name")

        if name and not (first_name or last_name):
            partes = str(name).strip().split(" ", 1)
            first_name = partes[0]
            last_name = partes[1] if len(partes) > 1 else "Cliente"

        if first_name:
            payer["first_name"] = first_name
        if last_name:
            payer["last_name"] = last_name

        tax_id_raw = customer.get("tax_id") or customer.get("document")
        if tax_id_raw:
            tax_id = "".join(ch for ch in str(tax_id_raw) if ch.isdigit())
            if tax_id:
                id_type = customer.get("identification_type")
                if not id_type:
                    id_type = "CPF" if len(tax_id) == 11 else "CNPJ"
                payer["identification"] = {"type": id_type, "number": tax_id}

        return payer

    @staticmethod
    def _montar_descricao(items: list) -> str:
        if not items:
            return "Pagamento"
        nomes = [str(item.get("name", "")).strip() for item in items if item.get("name")]
        if not nomes:
            return "Pagamento"
        return " / ".join(nomes[:3])

    @staticmethod
    def _centavos_para_reais(valor_centavos: int) -> float:
        if valor_centavos is None:
            raise ValueError("valor_centavos e obrigatorio.")
        return round(float(valor_centavos) / 100.0, 2)

    def _build_request_options(
        self,
        idempotency_key: str | None = None,
        with_idempotency: bool = False,
    ) -> "RequestOptions":
        if MercadoPagoRequestOptions is None:
            raise ImportError(
                "Pacote 'mercadopago' nao encontrado. "
                "Instale com: pip install mercadopago"
            )
        headers = {}
        if self.test_scope:
            headers["x-test-scope"] = self.test_scope
        if with_idempotency or idempotency_key:
            headers["x-idempotency-key"] = idempotency_key or str(uuid.uuid4())
        return MercadoPagoRequestOptions(
            access_token=self.token,
            connection_timeout=float(self.timeout),
            custom_headers=headers or None,
        )

    def _create_payment(self, payload: dict, idempotency_key: str | None = None) -> dict:
        try:
            result = self.sdk.payment().create(
                payload,
                self._build_request_options(
                    idempotency_key=idempotency_key,
                    with_idempotency=True,
                ),
            )
            return self._normalize_sdk_result(result)
        except Exception as exc:
            return {"success": False, "status_code": 503, "error": str(exc)}

    def _create_pix_order_test(
        self,
        customer: dict,
        valor_centavos: int,
        reference_id: str | None = None,
        notification_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        amount_str = f"{self._centavos_para_reais(valor_centavos):.2f}"
        payer = self._montar_payer(customer)
        payer_email = payer.get("email") or "test@testuser.com"
        first_name = payer.get("first_name")
        if self.test_pix_auto_approve:
            first_name = "APRO"

        order_payload: dict[str, Any] = {
            "type": "online",
            "processing_mode": "automatic",
            "external_reference": reference_id or f"pedido-{uuid.uuid4().hex[:8]}",
            "total_amount": amount_str,
            "payer": {"email": payer_email},
            "transactions": {
                "payments": [
                    {
                        "amount": amount_str,
                        "payment_method": {
                            "id": "pix",
                            "type": "bank_transfer",
                        },
                    }
                ]
            },
        }
        if first_name:
            order_payload["payer"]["first_name"] = first_name

        final_notification_url = notification_url or self.default_notification_url
        if final_notification_url:
            order_payload["notification_url"] = final_notification_url

        try:
            result = self.sdk.order().create(
                order_payload,
                self._build_request_options(
                    idempotency_key=idempotency_key,
                    with_idempotency=True,
                ),
            )
            return self._normalize_sdk_result(result)
        except Exception as exc:
            return {"success": False, "status_code": 503, "error": str(exc)}

    @staticmethod
    def _adapt_pix_result(payload: Any) -> Any:
        if not isinstance(payload, dict):
            return payload

        if (
            isinstance(payload.get("point_of_interaction"), dict)
            and isinstance(payload.get("id"), (str, int))
        ):
            return payload

        payments = (
            (payload.get("transactions") or {}).get("payments")
            if isinstance(payload.get("transactions"), dict)
            else None
        )
        if not isinstance(payments, list) or not payments:
            return payload

        first_payment = payments[0] if isinstance(payments[0], dict) else {}
        payment_method = first_payment.get("payment_method") or {}

        return {
            "id": first_payment.get("id") or payload.get("id"),
            "order_id": payload.get("id"),
            "status": first_payment.get("status") or payload.get("status"),
            "status_detail": first_payment.get("status_detail") or payload.get("status_detail"),
            "external_reference": payload.get("external_reference"),
            "point_of_interaction": {
                "transaction_data": {
                    "qr_code": payment_method.get("qr_code"),
                    "qr_code_base64": payment_method.get("qr_code_base64"),
                    "ticket_url": payment_method.get("ticket_url"),
                }
            },
            "raw_order": payload,
        }

    @staticmethod
    def _normalize_sdk_result(result: Any) -> dict:
        if not isinstance(result, dict):
            return {"success": False, "status_code": 500, "error": result}

        try:
            status_code = int(result.get("status") or 500)
        except (TypeError, ValueError):
            status_code = 500
        payload = result.get("response", {})
        if 200 <= status_code < 300:
            return {"success": True, "status_code": status_code, "data": payload}
        return {"success": False, "status_code": status_code, "error": payload}
