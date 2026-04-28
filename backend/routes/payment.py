import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from services.cakto import CaktoService
from .database import get_db

payment_bp = Blueprint("payment", __name__)
logger = logging.getLogger(__name__)

_svc = None


def get_service() -> CaktoService:
    global _svc
    if _svc is None:
        _svc = CaktoService()
    return _svc


def _get_service_or_error():
    try:
        return get_service(), None
    except Exception as exc:
        logger.error("Falha ao inicializar CaktoService: %s", exc)
        return None, (
            jsonify(
                success=False,
                error="Falha ao inicializar integracao Cakto.",
            ),
            500,
        )


def _get_user_email(user_id: str) -> str | None:
    with get_db() as (cursor, conn):
        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return None
        email = user.get("email")
        return str(email).strip().lower() if isinstance(email, str) and email.strip() else None


def _set_premium_by_user_id(user_id: str, is_premium: bool) -> int:
    with get_db() as (cursor, conn):
        cursor.execute(
            "UPDATE users SET is_premium = %s WHERE id = %s",
            (bool(is_premium), user_id),
        )
        return int(cursor.rowcount or 0)


def _set_premium_by_email(email: str, is_premium: bool) -> int:
    with get_db() as (cursor, conn):
        cursor.execute(
            "UPDATE users SET is_premium = %s WHERE email = %s",
            (bool(is_premium), email),
        )
        return int(cursor.rowcount or 0)


@payment_bp.route("/api/pay/preference", methods=["POST"])
@jwt_required()
def create_preference():
    user_id = str(get_jwt_identity())
    body = request.get_json(silent=True) or {}

    service, error_response = _get_service_or_error()
    if error_response:
        return error_response

    user_email = _get_user_email(user_id)

    try:
        checkout_url = service.build_checkout_url(
            user_id=user_id,
            user_email=user_email,
            provided_url=body.get("checkout_url"),
        )
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400

    return jsonify(
        success=True,
        message="Checkout Cakto gerado com sucesso.",
        checkout_url=checkout_url,
        data={"checkout_url": checkout_url},
    ), 201


@payment_bp.route("/api/pay/confirm", methods=["POST"])
@payment_bp.route("/api/pay/mock", methods=["POST"])
@jwt_required()
def confirm_payment():
    user_id = str(get_jwt_identity())
    with get_db() as (cursor, conn):
        cursor.execute("SELECT is_premium FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

    if not user:
        return jsonify(success=False, error="Usuario nao encontrado."), 404

    is_premium = bool(user.get("is_premium"))
    if not is_premium:
        return jsonify(
            success=False,
            error="Pagamento ainda nao confirmado. Aguarde o webhook da Cakto.",
            is_premium=False,
        ), 409

    return jsonify(
        success=True,
        message="Assinatura premium ativa.",
        is_premium=True,
    ), 200


@payment_bp.route("/api/pay/webhook/cakto", methods=["POST"])
def cakto_webhook():
    payload = request.get_json(silent=True) or {}

    service, error_response = _get_service_or_error()
    if error_response:
        return error_response

    secret_ok, reason = service.validate_secret(
        payload=payload,
        headers=request.headers,
        query_secret=request.args.get("secret"),
    )
    if not secret_ok:
        logger.warning("Webhook Cakto rejeitado: %s", reason)
        return jsonify(success=False, error="Nao autorizado."), 401

    event = service.extract_event(payload)
    data = service.extract_data(payload)
    status = str(data.get("status") or payload.get("status") or "").strip().lower()

    should_activate = service.should_activate_premium(event, status)
    should_deactivate = service.should_deactivate_premium(event, status)

    if not should_activate and not should_deactivate:
        return jsonify(success=True, message="Evento recebido sem acao de premium."), 200

    target_state = True if should_activate else False
    user_id = service.extract_reference_user_id(payload)
    updated = 0

    if user_id:
        updated = _set_premium_by_user_id(user_id, target_state)

    if updated == 0:
        email = service.extract_customer_email(payload)
        if email:
            updated = _set_premium_by_email(email, target_state)

    if updated == 0:
        logger.warning(
            "Webhook Cakto sem usuario correspondente | event=%s status=%s",
            event,
            status,
        )
        return jsonify(success=False, error="Usuario nao encontrado para este evento."), 404

    logger.info(
        "Webhook Cakto processado | event=%s status=%s premium=%s registros=%s",
        event,
        status,
        target_state,
        updated,
    )
    return jsonify(success=True, premium=target_state, updated=updated), 200
