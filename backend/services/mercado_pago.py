import os
import uuid
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()


class MercadoPagoService:
    BASE_URL = "https://api.mercadopago.com"

    def __init__(self):
        self.token = (
            os.getenv("MERCADO_PAGO_ACCESS_TOKEN")
            or os.getenv("MP_ACCESS_TOKEN")
            or os.getenv("ACCESS_TOKEN")
        )
        if not self.token:
            raise ValueError(
                "Token do Mercado Pago nao encontrado. "
                "Configure MERCADO_PAGO_ACCESS_TOKEN (ou MP_ACCESS_TOKEN/ACCESS_TOKEN)."
            )
        self.default_notification_url = os.getenv("MERCADO_PAGO_NOTIFICATION_URL")
        self.timeout = int(os.getenv("MERCADO_PAGO_TIMEOUT", "15"))

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

        return self._post(
            "/v1/payments",
            payload,
            idempotency_key=idempotency_key,
            require_idempotency=True,
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

        return self._post(
            "/v1/payments",
            payload,
            idempotency_key=idempotency_key,
            require_idempotency=True,
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

        return self._post(
            "/v1/payments",
            payload,
            idempotency_key=idempotency_key,
            require_idempotency=True,
        )

    def consultar_pagamento(self, payment_id: str) -> dict:
        return self._get(f"/v1/payments/{payment_id}")

    def reembolsar_pagamento(
        self,
        payment_id: str,
        valor_centavos: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        payload = {}
        if valor_centavos is not None:
            payload["amount"] = self._centavos_para_reais(valor_centavos)
        return self._post(
            f"/v1/payments/{payment_id}/refunds",
            payload,
            idempotency_key=idempotency_key,
            require_idempotency=True,
        )

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

    def _build_headers(
        self,
        idempotency_key: str | None = None,
        require_idempotency: bool = False,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if require_idempotency or idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
        return headers

    @staticmethod
    def _parse_response_data(resp: requests.Response) -> Any:
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    def _post(
        self,
        path: str,
        payload: dict,
        idempotency_key: str | None = None,
        require_idempotency: bool = False,
    ) -> dict:
        try:
            resp = requests.post(
                f"{self.BASE_URL}{path}",
                headers=self._build_headers(
                    idempotency_key=idempotency_key,
                    require_idempotency=require_idempotency,
                ),
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return {
                "success": True,
                "status_code": resp.status_code,
                "data": self._parse_response_data(resp),
            }
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 500
            error_data = (
                self._parse_response_data(exc.response)
                if exc.response is not None
                else str(exc)
            )
            return {"success": False, "status_code": status_code, "error": error_data}
        except requests.exceptions.RequestException as exc:
            return {"success": False, "status_code": 503, "error": str(exc)}

    def _get(self, path: str) -> dict:
        try:
            resp = requests.get(
                f"{self.BASE_URL}{path}",
                headers=self._build_headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return {
                "success": True,
                "status_code": resp.status_code,
                "data": self._parse_response_data(resp),
            }
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 500
            error_data = (
                self._parse_response_data(exc.response)
                if exc.response is not None
                else str(exc)
            )
            return {"success": False, "status_code": status_code, "error": error_data}
        except requests.exceptions.RequestException as exc:
            return {"success": False, "status_code": 503, "error": str(exc)}
