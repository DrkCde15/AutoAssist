import hashlib
import hmac
import logging
import os

from flask import Blueprint, jsonify, request

from services.mercado_pago import MercadoPagoService

gateway_bp = Blueprint("gateway", __name__, url_prefix="/pagamentos")
logger = logging.getLogger(__name__)

_svc = None
WEBHOOK_SECRET = os.getenv("MERCADO_PAGO_WEBHOOK_SECRET", "")


def get_service() -> MercadoPagoService:
    global _svc
    if _svc is None:
        _svc = MercadoPagoService()
    return _svc


def _bad(msg: str, code: int = 400):
    return jsonify({"success": False, "error": msg}), code


def _ok(data: dict, code: int = 200):
    return jsonify(data), code


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_signature(signature_header: str) -> dict:
    parts = {}
    for part in (signature_header or "").split(","):
        key, _, value = part.partition("=")
        if key and value:
            parts[key.strip()] = value.strip()
    return parts


def _extract_notification_payment_id(evento: dict) -> str:
    payment_id = request.args.get("data.id") or request.args.get("id")
    if payment_id:
        return str(payment_id)
    return str((evento.get("data") or {}).get("id") or evento.get("id") or "")


def _verificar_assinatura(evento: dict) -> bool:
    if not WEBHOOK_SECRET:
        return True

    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")
    if not x_signature or not x_request_id:
        return False

    signature_parts = _parse_signature(x_signature)
    ts = signature_parts.get("ts")
    v1 = signature_parts.get("v1")
    if not ts or not v1:
        return False

    data_id = _extract_notification_payment_id(evento)
    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, v1)


@gateway_bp.route("/pix", methods=["POST"])
def criar_pix():
    body = request.get_json(silent=True) or {}

    for campo in ("customer", "items", "valor_centavos"):
        if campo not in body:
            return _bad(f"Campo obrigatorio ausente: {campo}")

    valor_centavos = _as_int(body.get("valor_centavos"))
    if not valor_centavos or valor_centavos <= 0:
        return _bad("valor_centavos deve ser um inteiro maior que zero.")

    result = get_service().criar_pix(
        customer=body["customer"],
        items=body["items"],
        valor_centavos=valor_centavos,
        expiration_date=body.get("expiration_date"),
        reference_id=body.get("reference_id"),
        notification_url=body.get("notification_url"),
        idempotency_key=body.get("idempotency_key"),
    )
    code = result["status_code"] if not result["success"] else 201
    return _ok(result, code)


@gateway_bp.route("/boleto", methods=["POST"])
def criar_boleto():
    body = request.get_json(silent=True) or {}

    for campo in ("customer", "items", "valor_centavos"):
        if campo not in body:
            return _bad(f"Campo obrigatorio ausente: {campo}")

    valor_centavos = _as_int(body.get("valor_centavos"))
    if not valor_centavos or valor_centavos <= 0:
        return _bad("valor_centavos deve ser um inteiro maior que zero.")

    result = get_service().criar_boleto(
        customer=body["customer"],
        items=body["items"],
        valor_centavos=valor_centavos,
        due_date=body.get("due_date"),
        reference_id=body.get("reference_id"),
        notification_url=body.get("notification_url"),
        payment_method_id=body.get("payment_method_id", "bolbradesco"),
        idempotency_key=body.get("idempotency_key"),
    )
    code = result["status_code"] if not result["success"] else 201
    return _ok(result, code)


@gateway_bp.route("/cartao", methods=["POST"])
def criar_cobranca_cartao():
    body = request.get_json(silent=True) or {}

    for campo in ("customer", "items", "valor_centavos", "payment_method_id"):
        if campo not in body:
            return _bad(f"Campo obrigatorio ausente: {campo}")

    token = body.get("token") or body.get("card_token") or body.get("encrypted_card")
    if not token:
        return _bad("Campo obrigatorio ausente: token (ou card_token/encrypted_card).")

    valor_centavos = _as_int(body.get("valor_centavos"))
    if not valor_centavos or valor_centavos <= 0:
        return _bad("valor_centavos deve ser um inteiro maior que zero.")

    installments = _as_int(body.get("installments", 1))
    if not installments or installments <= 0:
        return _bad("installments deve ser um inteiro maior que zero.")

    result = get_service().criar_cobranca_cartao(
        customer=body["customer"],
        items=body["items"],
        valor_centavos=valor_centavos,
        card_token=token,
        payment_method_id=body["payment_method_id"],
        installments=installments,
        capture=_as_bool(body.get("capture"), True),
        issuer_id=body.get("issuer_id"),
        reference_id=body.get("reference_id"),
        notification_url=body.get("notification_url"),
        idempotency_key=body.get("idempotency_key"),
    )
    code = result["status_code"] if not result["success"] else 201
    return _ok(result, code)


@gateway_bp.route("/payments/<payment_id>", methods=["GET"])
@gateway_bp.route("/orders/<payment_id>", methods=["GET"])
@gateway_bp.route("/charges/<payment_id>", methods=["GET"])
def consultar_pagamento(payment_id: str):
    result = get_service().consultar_pagamento(payment_id)
    code = result["status_code"] if not result["success"] else 200
    return _ok(result, code)


@gateway_bp.route("/payments/<payment_id>/reembolso", methods=["POST"])
@gateway_bp.route("/charges/<payment_id>/reembolso", methods=["POST"])
def reembolsar(payment_id: str):
    body = request.get_json(silent=True) or {}
    valor_centavos = body.get("valor_centavos")
    if valor_centavos is not None:
        valor_centavos = _as_int(valor_centavos)
        if not valor_centavos or valor_centavos <= 0:
            return _bad("valor_centavos deve ser um inteiro maior que zero.")

    result = get_service().reembolsar_pagamento(
        payment_id,
        valor_centavos=valor_centavos,
        idempotency_key=body.get("idempotency_key"),
    )
    code = result["status_code"] if not result["success"] else 200
    return _ok(result, code)


@gateway_bp.route("/webhook", methods=["POST"])
def webhook():
    evento = request.get_json(silent=True) or {}

    if not _verificar_assinatura(evento):
        return _bad("Assinatura invalida", 401)

    tipo = str(evento.get("type", "")).lower()
    if tipo and tipo != "payment":
        logger.info("Webhook ignorado (tipo=%s): %s", tipo, evento)
        return "", 200

    payment_id = _extract_notification_payment_id(evento)
    if not payment_id:
        logger.warning("Webhook sem payment_id: %s", evento)
        return "", 200

    consulta = get_service().consultar_pagamento(payment_id)
    if not consulta["success"]:
        logger.error(
            "Falha ao consultar payment_id=%s no Mercado Pago: %s",
            payment_id,
            consulta.get("error"),
        )
        return _bad("Falha ao processar webhook", 500)

    pagamento = consulta["data"]
    status = str(pagamento.get("status", "")).lower()

    handlers = {
        "approved": _handle_payment_approved,
        "rejected": _handle_payment_rejected,
        "cancelled": _handle_payment_cancelled,
        "refunded": _handle_payment_refunded,
        "charged_back": _handle_payment_charged_back,
    }
    handler = handlers.get(status)
    if handler:
        handler(pagamento, evento)
    else:
        logger.info(
            "Webhook recebido sem handler especifico (status=%s, payment_id=%s)",
            status,
            payment_id,
        )
    return "", 200


def _handle_payment_approved(pagamento: dict, evento: dict):
    logger.info(
        "Pagamento aprovado | payment_id=%s | external_reference=%s | action=%s",
        pagamento.get("id"),
        pagamento.get("external_reference"),
        evento.get("action"),
    )


def _handle_payment_rejected(pagamento: dict, evento: dict):
    logger.info(
        "Pagamento rejeitado | payment_id=%s | detail=%s | action=%s",
        pagamento.get("id"),
        pagamento.get("status_detail"),
        evento.get("action"),
    )


def _handle_payment_cancelled(pagamento: dict, evento: dict):
    logger.info(
        "Pagamento cancelado | payment_id=%s | action=%s",
        pagamento.get("id"),
        evento.get("action"),
    )


def _handle_payment_refunded(pagamento: dict, evento: dict):
    logger.info(
        "Pagamento reembolsado | payment_id=%s | action=%s",
        pagamento.get("id"),
        evento.get("action"),
    )


def _handle_payment_charged_back(pagamento: dict, evento: dict):
    logger.warning(
        "Chargeback recebido | payment_id=%s | action=%s",
        pagamento.get("id"),
        evento.get("action"),
    )
