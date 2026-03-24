# routes/gateway.py

from flask import Blueprint, request, jsonify
import hmac, hashlib, os
from services.pagseguro_service import PagSeguroService

gateway_bp = Blueprint("gateway", __name__, url_prefix="/pagamentos")

_svc = None


def get_service() -> PagSeguroService:
    global _svc
    if _svc is None:
        _svc = PagSeguroService()
    return _svc


# ------------------------------------------------------------------ #
#  HELPERS                                                             #
# ------------------------------------------------------------------ #

def _bad(msg: str, code: int = 400):
    return jsonify({"success": False, "error": msg}), code


def _ok(data: dict, code: int = 200):
    return jsonify(data), code


# ------------------------------------------------------------------ #
#  PIX                                                                 #
# ------------------------------------------------------------------ #

@gateway_bp.route("/pix", methods=["POST"])
def criar_pix():
    """
    Cria uma cobrança via PIX.

    Body JSON:
    {
        "customer": { "name": "...", "email": "...", "tax_id": "..." },
        "items": [{ "name": "...", "quantity": 1, "unit_amount": 1000 }],
        "valor_centavos": 1000,
        "expiration_date": "2025-12-31T23:59:59-03:00",  // opcional
        "reference_id": "pedido-abc"                       // opcional
    }
    """
    body = request.get_json(silent=True) or {}

    for campo in ("customer", "items", "valor_centavos"):
        if campo not in body:
            return _bad(f"Campo obrigatório ausente: {campo}")

    result = get_service().criar_pix(
        customer=body["customer"],
        items=body["items"],
        valor_centavos=body["valor_centavos"],
        expiration_date=body.get("expiration_date"),
        reference_id=body.get("reference_id"),
    )
    code = result["status_code"] if not result["success"] else 201
    return _ok(result, code)


# ------------------------------------------------------------------ #
#  BOLETO                                                              #
# ------------------------------------------------------------------ #

@gateway_bp.route("/boleto", methods=["POST"])
def criar_boleto():
    """
    Cria uma cobrança via Boleto.

    Body JSON:
    {
        "customer": { ... },
        "items": [ ... ],
        "valor_centavos": 1000,
        "due_date": "2025-12-31",  // opcional
        "reference_id": "..."      // opcional
    }
    """
    body = request.get_json(silent=True) or {}

    for campo in ("customer", "items", "valor_centavos"):
        if campo not in body:
            return _bad(f"Campo obrigatório ausente: {campo}")

    result = get_service().criar_boleto(
        customer=body["customer"],
        items=body["items"],
        valor_centavos=body["valor_centavos"],
        due_date=body.get("due_date"),
        reference_id=body.get("reference_id"),
    )
    code = result["status_code"] if not result["success"] else 201
    return _ok(result, code)


# ------------------------------------------------------------------ #
#  CARTÃO DE CRÉDITO                                                   #
# ------------------------------------------------------------------ #

@gateway_bp.route("/cartao", methods=["POST"])
def criar_cobranca_cartao():
    """
    Cria uma cobrança via Cartão de Crédito.

    Body JSON:
    {
        "customer": { ... },
        "items": [ ... ],
        "valor_centavos": 1000,
        "encrypted_card": "<token PagSeguro.js>",
        "installments": 1,    // opcional, padrão 1
        "capture": true,      // opcional, padrão true
        "reference_id": "..." // opcional
    }
    """
    body = request.get_json(silent=True) or {}

    for campo in ("customer", "items", "valor_centavos", "encrypted_card"):
        if campo not in body:
            return _bad(f"Campo obrigatório ausente: {campo}")

    result = get_service().criar_cobranca_cartao(
        customer=body["customer"],
        items=body["items"],
        valor_centavos=body["valor_centavos"],
        encrypted_card=body["encrypted_card"],
        installments=body.get("installments", 1),
        capture=body.get("capture", True),
        reference_id=body.get("reference_id"),
    )
    code = result["status_code"] if not result["success"] else 201
    return _ok(result, code)


# ------------------------------------------------------------------ #
#  CONSULTAS                                                           #
# ------------------------------------------------------------------ #

@gateway_bp.route("/orders/<order_id>", methods=["GET"])
def consultar_order(order_id: str):
    """Retorna detalhes de uma order."""
    result = get_service().consultar_order(order_id)
    return _ok(result, result["status_code"] if not result["success"] else 200)


@gateway_bp.route("/charges/<charge_id>", methods=["GET"])
def consultar_charge(charge_id: str):
    """Retorna detalhes de uma charge."""
    result = get_service().consultar_charge(charge_id)
    return _ok(result, result["status_code"] if not result["success"] else 200)


# ------------------------------------------------------------------ #
#  REEMBOLSO                                                           #
# ------------------------------------------------------------------ #

@gateway_bp.route("/charges/<charge_id>/reembolso", methods=["POST"])
def reembolsar(charge_id: str):
    """
    Estorna uma charge (total ou parcial).

    Body JSON (opcional para estorno parcial):
    { "valor_centavos": 500 }
    """
    body = request.get_json(silent=True) or {}
    result = get_service().reembolsar_charge(charge_id, body.get("valor_centavos"))
    return _ok(result, result["status_code"] if not result["success"] else 200)


# ------------------------------------------------------------------ #
#  WEBHOOK                                                             #
# ------------------------------------------------------------------ #

WEBHOOK_SECRET = os.getenv("PAGSEGURO_WEBHOOK_SECRET", "")


def _verificar_assinatura(payload_bytes: bytes, signature_header: str) -> bool:
    """Valida HMAC-SHA256 enviado pelo PagSeguro (se o secret estiver configurado)."""
    if not WEBHOOK_SECRET:
        return True  # em desenvolvimento, sem secret configurado
    expected = hmac.new(
        WEBHOOK_SECRET.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


@gateway_bp.route("/webhook", methods=["POST"])
def webhook():
    """
    Recebe eventos do PagSeguro (charge.paid, charge.declined, etc.).
    Configure a URL https://seu-dominio.com/pagamentos/webhook no painel PagSeguro.
    """
    raw = request.get_data()
    sig = request.headers.get("X-PagSeguro-Signature", "")

    if not _verificar_assinatura(raw, sig):
        return _bad("Assinatura inválida", 401)

    evento = request.get_json(silent=True) or {}
    tipo = evento.get("type", "desconhecido")

    handlers = {
        "CHARGE_PAID":          _handle_charge_paid,
        "CHARGE_DECLINED":      _handle_charge_declined,
        "CHARGE_CANCELED":      _handle_charge_canceled,
        "CHARGE_CHARGEBACK":    _handle_charge_chargeback,
    }

    handler = handlers.get(tipo)
    if handler:
        handler(evento)
    else:
        print(f"[Webhook] Evento não tratado: {tipo} | payload: {evento}")

    return "", 200


# ------------------------------------------------------------------ #
#  HANDLERS DE EVENTOS (implemente a lógica do seu negócio aqui)      #
# ------------------------------------------------------------------ #

def _handle_charge_paid(evento: dict):
    charge = evento.get("data", {})
    print(f"[Webhook] ✅ Pagamento confirmado | charge_id={charge.get('id')} | "
          f"valor={charge.get('amount', {}).get('value')}")
    # TODO: atualizar pedido no banco de dados, enviar e-mail, etc.


def _handle_charge_declined(evento: dict):
    charge = evento.get("data", {})
    print(f"[Webhook] ❌ Pagamento recusado | charge_id={charge.get('id')}")
    # TODO: notificar cliente, liberar estoque reservado, etc.


def _handle_charge_canceled(evento: dict):
    charge = evento.get("data", {})
    print(f"[Webhook] 🚫 Pagamento cancelado | charge_id={charge.get('id')}")
    # TODO: lógica de cancelamento


def _handle_charge_chargeback(evento: dict):
    charge = evento.get("data", {})
    print(f"[Webhook] ⚠️  Chargeback | charge_id={charge.get('id')}")
    # TODO: abrir disputa, notificar equipe financeira, etc.