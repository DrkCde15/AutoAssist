# services/gateway.py

import requests
import os
import uuid
from dotenv import load_dotenv

load_dotenv()


class PagSeguroService:
    BASE_URL = "https://api.pagseguro.com"

    def __init__(self):
        self.token = os.getenv("PAGSEGURO_TOKEN")
        if not self.token:
            raise ValueError("PAGSEGURO_TOKEN não encontrado nas variáveis de ambiente.")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    #  ORDERS                                                              #
    # ------------------------------------------------------------------ #

    def criar_order(self, customer: dict, items: list, charges: list, reference_id: str = None) -> dict:
        """
        Cria uma order genérica no PagSeguro.

        Args:
            customer: dict com name, email, tax_id
            items: lista de dicts com name, quantity, unit_amount (centavos)
            charges: lista de dicts com amount (value + currency) e payment_method
            reference_id: identificador externo (gerado automaticamente se omitido)
        """
        payload = {
            "reference_id": reference_id or f"pedido-{uuid.uuid4().hex[:8]}",
            "customer": customer,
            "items": items,
            "charges": charges,
        }
        return self._post("/orders", payload)

    # ------------------------------------------------------------------ #
    #  PIX                                                                 #
    # ------------------------------------------------------------------ #

    def criar_pix(self, customer: dict, items: list, valor_centavos: int,
                  expiration_date: str = None, reference_id: str = None) -> dict:
        """
        Gera uma cobrança via PIX.

        Args:
            customer: dict com name, email, tax_id
            items: lista de produtos
            valor_centavos: valor total em centavos (ex: R$10,00 → 1000)
            expiration_date: data de expiração ISO-8601 (opcional)
            reference_id: identificador externo
        """
        pix_method: dict = {"type": "PIX"}
        if expiration_date:
            pix_method["expiration_date"] = expiration_date

        charges = [
            {
                "amount": {"value": valor_centavos, "currency": "BRL"},
                "payment_method": pix_method,
            }
        ]
        return self.criar_order(customer, items, charges, reference_id)

    # ------------------------------------------------------------------ #
    #  BOLETO                                                              #
    # ------------------------------------------------------------------ #

    def criar_boleto(self, customer: dict, items: list, valor_centavos: int,
                     due_date: str = None, reference_id: str = None) -> dict:
        """
        Gera uma cobrança via Boleto Bancário.

        Args:
            due_date: vencimento no formato YYYY-MM-DD (opcional)
        """
        boleto_method: dict = {"type": "BOLETO"}
        if due_date:
            boleto_method["boleto"] = {"due_date": due_date}

        charges = [
            {
                "amount": {"value": valor_centavos, "currency": "BRL"},
                "payment_method": boleto_method,
            }
        ]
        return self.criar_order(customer, items, charges, reference_id)

    # ------------------------------------------------------------------ #
    #  CARTÃO DE CRÉDITO                                                   #
    # ------------------------------------------------------------------ #

    def criar_cobranca_cartao(self, customer: dict, items: list, valor_centavos: int,
                               encrypted_card: str, installments: int = 1,
                               capture: bool = True, reference_id: str = None) -> dict:
        """
        Gera uma cobrança via Cartão de Crédito.

        Args:
            encrypted_card: cartão tokenizado pelo PagSeguro.js
            installments: número de parcelas (padrão 1)
            capture: True para captura imediata, False para pré-autorização
        """
        charges = [
            {
                "amount": {"value": valor_centavos, "currency": "BRL"},
                "payment_method": {
                    "type": "CREDIT_CARD",
                    "installments": installments,
                    "capture": capture,
                    "card": {"encrypted": encrypted_card},
                },
            }
        ]
        return self.criar_order(customer, items, charges, reference_id)

    # ------------------------------------------------------------------ #
    #  CONSULTAS                                                           #
    # ------------------------------------------------------------------ #

    def consultar_order(self, order_id: str) -> dict:
        """Retorna os detalhes de uma order pelo ID."""
        return self._get(f"/orders/{order_id}")

    def consultar_charge(self, charge_id: str) -> dict:
        """Retorna os detalhes de uma charge pelo ID."""
        return self._get(f"/charges/{charge_id}")

    # ------------------------------------------------------------------ #
    #  REEMBOLSO                                                           #
    # ------------------------------------------------------------------ #

    def reembolsar_charge(self, charge_id: str, valor_centavos: int = None) -> dict:
        """
        Realiza estorno total ou parcial de uma charge.

        Args:
            charge_id: ID da cobrança
            valor_centavos: valor para estorno parcial; None para estorno total
        """
        payload = {}
        if valor_centavos:
            payload["amount"] = {"value": valor_centavos}
        return self._post(f"/charges/{charge_id}/cancel", payload)

    # ------------------------------------------------------------------ #
    #  HELPERS HTTP                                                        #
    # ------------------------------------------------------------------ #

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = requests.post(
                f"{self.BASE_URL}{path}",
                headers=self.headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            return {"success": True, "status_code": resp.status_code, "data": resp.json()}
        except requests.exceptions.HTTPError as e:
            return {
                "success": False,
                "status_code": e.response.status_code,
                "error": e.response.json() if e.response.content else str(e),
            }
        except requests.exceptions.RequestException as e:
            return {"success": False, "status_code": 503, "error": str(e)}

    def _get(self, path: str) -> dict:
        try:
            resp = requests.get(
                f"{self.BASE_URL}{path}",
                headers=self.headers,
                timeout=15,
            )
            resp.raise_for_status()
            return {"success": True, "status_code": resp.status_code, "data": resp.json()}
        except requests.exceptions.HTTPError as e:
            return {
                "success": False,
                "status_code": e.response.status_code,
                "error": e.response.json() if e.response.content else str(e),
            }
        except requests.exceptions.RequestException as e:
            return {"success": False, "status_code": 503, "error": str(e)}