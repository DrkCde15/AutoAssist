import logging
import uuid

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
    target_state = bool(is_premium)
    with get_db() as (cursor, conn):
        cursor.execute(
            "UPDATE users SET is_premium = %s WHERE id = %s",
            (target_state, user_id),
        )
        if int(cursor.rowcount or 0) > 0:
            return 1

        cursor.execute(
            "SELECT id FROM users WHERE id = %s AND is_premium = %s",
            (user_id, target_state),
        )
        return 1 if cursor.fetchone() else 0


def _set_premium_by_email(email: str, is_premium: bool) -> int:
    target_state = bool(is_premium)
    with get_db() as (cursor, conn):
        cursor.execute(
            "UPDATE users SET is_premium = %s WHERE email = %s",
            (target_state, email),
        )
        if int(cursor.rowcount or 0) > 0:
            return 1

        cursor.execute(
            "SELECT id FROM users WHERE email = %s AND is_premium = %s",
            (email, target_state),
        )
        return 1 if cursor.fetchone() else 0


@payment_bp.route("/api/pay/preference", methods=["POST"])
@jwt_required()
def create_preference():
    user_id = str(get_jwt_identity())
    body = request.get_json(silent=True) or {}

    service, error_response = _get_service_or_error()
    if error_response:
        return error_response

    user_email = _get_user_email(user_id)
    order_id = str(uuid.uuid4())

    try:
        # Criar pedido pendente no banco antes de gerar o checkout
        with get_db() as (cursor, conn):
            cursor.execute(
                "INSERT INTO payments_orders (id, user_id, status, provider) VALUES (%s, %s, 'pending', 'cakto')",
                (order_id, user_id)
            )
            conn.commit()

        # Passar o order_id interno como referência para a Cakto
        checkout_url = service.build_checkout_url(
            user_id=user_id,
            user_email=user_email,
            provided_url=body.get("checkout_url"),
            internal_order_id=order_id
        )
    except Exception as exc:
        logger.error(f"Erro ao criar checkout: {exc}")
        return jsonify(success=False, error=str(exc)), 400

    return jsonify(
        success=True,
        message="Checkout Cakto gerado com sucesso.",
        checkout_url=checkout_url,
        data={"checkout_url": checkout_url, "order_id": order_id},
    ), 201


@payment_bp.route("/api/pay/confirm", methods=["POST"])
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
    internal_order_id = service.extract_reference_user_id(payload)
    email = service.extract_customer_email(payload)

    should_activate = service.should_activate_premium(event, status)
    should_deactivate = service.should_deactivate_premium(event, status)

    logger.info(
        "Webhook Cakto recebido | event=%s status=%s order_ref=%s email=%s activate=%s deactivate=%s",
        event or "-",
        status or "-",
        internal_order_id or "-",
        email or "-",
        should_activate,
        should_deactivate,
    )

    if not should_activate and not should_deactivate:
        return jsonify(success=True, message="Evento recebido sem acao de premium."), 200

    if should_activate:
        transaction_id = data.get("id")
        if not transaction_id:
            logger.warning("Hardening Cakto: Nenhum ID de transacao no webhook para validacao ativa.")
            return jsonify(success=False, error="ID de transacao ausente no payload."), 400
            
        try:
            is_really_paid = service.verify_transaction_status(transaction_id)
            if not is_really_paid:
                logger.warning("Hardening Cakto: Transacao %s divergente (nao paga na API).", transaction_id)
                return jsonify(success=False, error="Pagamento nao confirmado na consulta a API."), 400
        except ValueError as e:
            logger.error("Credenciais invalidas/ausentes na verificacao Cakto: %s", e)
            return jsonify(success=False, error="Erro de configuracao na API de pagamentos."), 500
        except Exception as e:
            logger.error("Erro inesperado na validacao ativa Cakto: %s", e)
            return jsonify(success=False, error="Falha ao consultar API da Cakto."), 500

    target_state = True if should_activate else False
    user_id = None
    
    if internal_order_id:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT user_id, status FROM payments_orders WHERE id = %s", (internal_order_id,))
            order = cursor.fetchone()
            
            if order:
                user_id = order["user_id"]
                # Atualizar status do pedido interno
                new_status = "approved" if should_activate else "revoked"
                cursor.execute(
                    "UPDATE payments_orders SET status = %s, provider_order_id = %s WHERE id = %s",
                    (new_status, data.get("id"), internal_order_id)
                )
                conn.commit()
            else:
                logger.warning(f"Webhook Cakto: Pedido interno {internal_order_id} nao encontrado.")

    updated = 0
    if user_id:
        updated = _set_premium_by_user_id(user_id, target_state)
    else:
        # Fallback por email se falhar o ID do pedido (mantido por retrocompatibilidade se necessario)
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
        "Webhook Cakto processado | event=%s status=%s premium=%s order=%s",
        event,
        status,
        target_state,
        internal_order_id,
    )
    return jsonify(success=True, premium=target_state, updated=updated), 200
