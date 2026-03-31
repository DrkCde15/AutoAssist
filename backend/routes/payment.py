import logging
import os

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from services.mercado_pago import MercadoPagoService
from .database import get_db

payment_bp = Blueprint("payment", __name__)
logger = logging.getLogger(__name__)

_svc = None


def get_service() -> MercadoPagoService:
    global _svc
    if _svc is None:
        _svc = MercadoPagoService()
    return _svc


def _upgrade_user_to_premium(user_id: int) -> None:
    with get_db() as (cursor, conn):
        cursor.execute("UPDATE users SET is_premium = TRUE WHERE id = %s", (user_id,))


def _get_service_or_error():
    try:
        return get_service(), None
    except Exception as exc:
        logger.error("Falha ao inicializar Mercado PagoService: %s", exc)
        return None, (
            jsonify(
                success=False,
                error="Falha ao inicializar Mercado Pago. Verifique token e dependencia SDK.",
            ),
            500,
        )


def _validar_items_preferencia(items) -> str | None:
    if not isinstance(items, list) or not items:
        return "Campo obrigatorio: items (lista nao vazia)."

    required_fields = ("id", "title", "quantity", "currency_id", "unit_price")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            return f"items[{index}] deve ser um objeto."
        faltantes = [campo for campo in required_fields if campo not in item]
        if faltantes:
            campos = ", ".join(faltantes)
            return f"items[{index}] sem campos obrigatorios: {campos}."
    return None


def _normalizar_preference_payload(payload: dict) -> dict:
    normalized = dict(payload)

    back_urls = normalized.get("back_urls")
    if not isinstance(back_urls, dict):
        back_urls = {}

    default_back_url = (
        os.getenv("MERCADO_PAGO_BACK_URL_SUCCESS")
        or os.getenv("FRONTEND_URL")
        or ""
    ).strip()

    if not back_urls.get("success") and default_back_url:
        back_urls["success"] = default_back_url
    if not back_urls.get("pending") and back_urls.get("success"):
        back_urls["pending"] = back_urls["success"]
    if not back_urls.get("failure") and back_urls.get("success"):
        back_urls["failure"] = back_urls["success"]

    if back_urls:
        normalized["back_urls"] = back_urls

    auto_return = normalized.get("auto_return")
    success_url = str(back_urls.get("success") or "")
    if auto_return and (not success_url or not success_url.startswith("https://")):
        normalized.pop("auto_return", None)

    return normalized


@payment_bp.route("/api/pay/preference", methods=["POST"])
@jwt_required()
def create_preference():
    user_id = get_jwt_identity()
    body = request.get_json(silent=True) or {}

    erro_items = _validar_items_preferencia(body.get("items"))
    if erro_items:
        return jsonify(success=False, error=erro_items), 400

    service, error_response = _get_service_or_error()
    if error_response:
        return error_response

    preference_payload = _normalizar_preference_payload(body)
    idempotency_key = preference_payload.pop("idempotency_key", None)
    preference_payload.setdefault("external_reference", str(user_id))
    if service.default_notification_url and not preference_payload.get("notification_url"):
        preference_payload["notification_url"] = service.default_notification_url

    result = service.criar_preferencia(
        preference_data=preference_payload,
        idempotency_key=idempotency_key,
    )
    if not result["success"]:
        status_code = result.get("status_code", 500)
        logger.error(
            "Falha ao criar preferencia no Mercado Pago | status=%s | details=%s",
            status_code,
            result.get("error"),
        )
        if status_code == 401:
            return jsonify(
                success=False,
                error="Falha ao criar preferencia no Mercado Pago: token invalido ou sem permissao.",
                details=result.get("error"),
            ), 401
        return jsonify(
            success=False,
            error="Falha ao criar preferencia no Mercado Pago.",
            details=result.get("error"),
        ), status_code

    preference = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
    return jsonify(
        success=True,
        message="Preferencia criada com sucesso.",
        preference_id=preference.get("id"),
        init_point=preference.get("init_point"),
        sandbox_init_point=preference.get("sandbox_init_point"),
        data=preference,
    ), 201


@payment_bp.route("/api/pay/confirm", methods=["POST"])
@payment_bp.route("/api/pay/mock", methods=["POST"])  # rota legada
@jwt_required()
def confirm_payment():
    user_id = get_jwt_identity()
    body = request.get_json(silent=True) or {}
    payment_id = body.get("payment_id")

    if not payment_id:
        return jsonify(
            success=False,
            error="Informe payment_id para confirmar pagamento no Mercado Pago.",
        ), 400

    service, error_response = _get_service_or_error()
    if error_response:
        return error_response

    consulta = service.consultar_pagamento(str(payment_id))
    if not consulta["success"]:
        status_code = int(consulta.get("status_code") or 500)
        if status_code == 404:
            return jsonify(
                success=False,
                error="Pagamento ainda em processamento.",
                payment_id=payment_id,
            ), 409
        return jsonify(
            success=False,
            error="Falha ao consultar pagamento no Mercado Pago.",
            details=consulta.get("error"),
        ), status_code

    pagamento = consulta["data"]
    status = str(pagamento.get("status", "")).lower()
    if status != "approved":
        return jsonify(
            success=False,
            error="Pagamento ainda nao aprovado.",
            payment_id=payment_id,
            payment_status=status,
            status_detail=pagamento.get("status_detail"),
        ), 409

    external_reference = str(pagamento.get("external_reference") or "")
    if external_reference and external_reference != str(user_id):
        logger.warning(
            "Tentativa de confirmacao com external_reference divergente. "
            "user_id=%s payment_id=%s external_reference=%s",
            user_id,
            payment_id,
            external_reference,
        )
        return jsonify(
            success=False,
            error="Pagamento nao pertence ao usuario autenticado.",
        ), 403

    try:
        _upgrade_user_to_premium(user_id)
        return jsonify(
            success=True,
            message="Upgrade concluido com pagamento aprovado.",
            payment_id=payment_id,
            payment_status=status,
        )
    except Exception as exc:
        logger.error("Erro ao concluir upgrade premium: %s", exc)
        return jsonify(
            success=False,
            error="Erro ao atualizar status premium do usuario.",
        ), 500
