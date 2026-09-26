import calendar
import logging
import os
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from services.cakto import CaktoService
from .database import get_db
from .push import send_push_notification
from .b2b import activate_b2b_client, set_b2b_client_state
from .analytics import record_analytics_event

payment_bp = Blueprint("payment", __name__)
logger = logging.getLogger(__name__)

# Planos esperados (fonte unica de verdade para valor/plano no backend).
# Evita fraudes de valor/plano: o upgrade so e confirmado se o pedido interno
# confere com o que foi efetivamente pago.
# Plano Premium = ASSINATURA MENSAL (R$ 19,99/mês), conforme produto na Cakto.
# O valor deve bater EXATAMENTE com o cobrado na Cakto, senão o webhook
# de ativação rejeita por divergência ("Valor pago diverge do pedido").
# Não incluir planos que não existem na Cakto (ex.: anual) - causaria falso positivo.
PREMIUM_PLANS = {
    "completo": {"amount": 19.90, "currency": "BRL", "interval": "month"},
}
DEFAULT_PLAN = "completo"

# Mapeamento produto/oferta Cakto -> plano interno.
# O mesmo webhook /api/pay/webhook/cakto recebe eventos de todos os produtos
# (Premium + planos B2B). Quando o pedido interno nao esta disponivel (evento
# orfao), usamos este mapa para identificar o plano a partir do ID do produto
# ou da oferta enviado pela Cakto. Preencha com os IDs reais obtidos na Cakto.
CAKTO_PRODUCT_TO_PLAN = {
    os.getenv("CAKTO_PRODUCT_PREMIUM_ID"): "completo",
    os.getenv("CAKTO_PRODUCT_B2B_1K_ID"): "b2b_pro_1k",
    os.getenv("CAKTO_PRODUCT_B2B_5K_ID"): "b2b_pro_5k",
    os.getenv("CAKTO_PRODUCT_B2B_20K_ID"): "b2b_pro_20k",
}
CAKTO_PRODUCT_TO_PLAN = {k: v for k, v in CAKTO_PRODUCT_TO_PLAN.items() if k}

_svc = None


def get_service() -> CaktoService:
    global _svc
    if _svc is None:
        _svc = CaktoService()
    return _svc


def _add_months(dt, months):
    """Soma meses com clamp de fim de mês (portável MySQL/PG)."""
    m = dt.month - 1 + months
    year, month = dt.year + m // 12, m % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _normalize_decimal(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


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


def _set_premium_by_user_id(user_id: str, is_premium: bool, plan: str | None = None) -> int:
    target_state = bool(is_premium)
    with get_db() as (cursor, conn):
        cursor.execute("SELECT is_premium FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        prior = bool((row or {}).get("is_premium"))

        if target_state:
            # P2-1: aplica crédito de indicação (meses grátis) ao ativar premium.
            cursor.execute(
                "SELECT referral_credit_months FROM users WHERE id = %s",
                (user_id,),
            )
            cred_row = cursor.fetchone()
            credit = int((cred_row or {}).get("referral_credit_months") or 0)
            if credit > 0:
                cursor.execute(
                    "SELECT premium_expires_at FROM users WHERE id = %s",
                    (user_id,),
                )
                exp_row = cursor.fetchone()
                base = (exp_row or {}).get("premium_expires_at") or datetime.now()
                if isinstance(base, str):
                    try:
                        base = datetime.fromisoformat(base)
                    except ValueError:
                        base = datetime.now()
                elif not isinstance(base, datetime):
                    base = datetime.now()
                cursor.execute(
                    """UPDATE users
                       SET is_premium = TRUE,
                           premium_expires_at = %s,
                           referral_credit_months = 0
                       WHERE id = %s""",
                    (_add_months(base, credit), user_id),
                )
                updated = 1
            else:
                cursor.execute(
                    "UPDATE users SET is_premium = %s WHERE id = %s",
                    (target_state, user_id),
                )
                updated = int(cursor.rowcount or 0)
        else:
            cursor.execute(
                "UPDATE users SET is_premium = FALSE WHERE id = %s",
                (user_id,),
            )
            updated = int(cursor.rowcount or 0)

        if updated > 0 and prior != target_state:
            _emit_premium_transition(user_id, plan or "completo", target_state, prior)
        return updated


def _set_premium_by_email(email: str, is_premium: bool, plan: str | None = None) -> int:
    target_state = bool(is_premium)
    with get_db() as (cursor, conn):
        cursor.execute("SELECT id, is_premium FROM users WHERE email = %s", (email,))
        row = cursor.fetchone()
        if not row:
            return 0
        user_id = row.get("id")
        prior = bool(row.get("is_premium"))
        cursor.execute(
            "UPDATE users SET is_premium = %s WHERE email = %s",
            (target_state, email),
        )
        updated = int(cursor.rowcount or 0)
        if updated > 0 and prior != target_state:
            _emit_premium_transition(user_id, plan or "completo", target_state, prior)
        return updated


def _emit_premium_transition(user_id, plan, became_premium, prior_premium):
    """P0.3: emite premium_upgrade/churn apenas em mudança real de estado."""
    if user_id is None or prior_premium is None:
        return
    if became_premium == prior_premium:
        return
    try:
        evt = "premium_upgrade" if became_premium else "premium_churn"
        record_analytics_event(
            evt,
            user_id=user_id,
            anonymous_id=None,
            path="/api/pay/webhook/cakto",
            metadata={"plan": plan, "via": "cakto_webhook"},
        )
    except Exception as exc:
        logger.warning("Falha ao emitir %s: %s", evt, exc)


@payment_bp.route("/api/pay/preference", methods=["POST"])
@jwt_required()
def create_preference():
    user_id = str(get_jwt_identity())
    body = request.get_json(silent=True) or {}

    service, error_response = _get_service_or_error()
    if error_response:
        return error_response

    # Plano/valor esperados: validados contra o catalogo interno (PREMIUM_PLANS).
    requested_plan = (body.get("plan") or DEFAULT_PLAN)
    plan_cfg = PREMIUM_PLANS.get(requested_plan)
    if not plan_cfg:
        return jsonify(success=False, error="Plano invalido."), 400

    user_email = _get_user_email(user_id)
    order_id = str(uuid.uuid4())

    try:
        # Criar pedido pendente no banco antes de gerar o checkout
        with get_db() as (cursor, conn):
            cursor.execute(
                """INSERT INTO payments_orders
                   (id, user_id, status, plan, amount, currency, provider)
                   VALUES (%s, %s, 'pending', %s, %s, %s, 'cakto')""",
                (order_id, user_id, requested_plan, plan_cfg["amount"], plan_cfg["currency"]),
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
        data={
            "checkout_url": checkout_url,
            "order_id": order_id,
            "plan": requested_plan,
            "amount": plan_cfg["amount"],
            "currency": plan_cfg["currency"],
        },
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

    # Carrega o pedido interno antes da validacao ativa para conferir valor/plano.
    order = None
    if internal_order_id:
        with get_db() as (cursor, conn):
            cursor.execute(
                "SELECT user_id, status, plan, amount, currency FROM payments_orders WHERE id = %s",
                (internal_order_id,),
            )
            order = cursor.fetchone()

    # Identifica o produto/plano do evento.
    # 1) Pedido interno tem prioridade (autoritativo e antifraude).
    # 2) Fallback: mapear produto/oferta Cakto -> plano interno quando o
    #    pedido interno nao esta disponivel (ex.: evento orfao).
    product_info = service.extract_product_info(payload)
    provider_product_id = product_info.get("product_id")
    provider_offer_id = product_info.get("offer_id")

    resolved_plan = (order.get("plan") if order else None) or None
    if not resolved_plan and (provider_product_id or provider_offer_id):
        resolved_plan = (
            CAKTO_PRODUCT_TO_PLAN.get(provider_product_id)
            or CAKTO_PRODUCT_TO_PLAN.get(provider_offer_id)
        )
    resolved_is_b2b = bool(resolved_plan) and str(resolved_plan).startswith("b2b_")

    if should_activate:
        transaction_id = data.get("id")
        if not transaction_id:
            logger.warning("Hardening Cakto: Nenhum ID de transacao no webhook para validacao ativa.")
            return jsonify(success=False, error="ID de transacao ausente no payload."), 400

        try:
            is_really_paid, paid_amount = service.verify_transaction_status(transaction_id)
            if not is_really_paid:
                logger.warning("Hardening Cakto: Transacao %s divergente (nao paga na API).", transaction_id)
                return jsonify(success=False, error="Pagamento nao confirmado na consulta a API."), 400

            # Confere o valor pago contra o pedido interno (defesa contra fraude de valor).
            expected_amount = _normalize_decimal(order.get("amount")) if order else None
            if expected_amount is not None and paid_amount is not None:
                if abs(round(float(paid_amount), 2) - expected_amount) > 0.01:
                    logger.warning(
                        "Hardening Cakto: valor divergente pedido=%s pago=%s",
                        expected_amount,
                        paid_amount,
                    )
                    return jsonify(success=False, error="Valor pago diverge do pedido."), 400
        except ValueError as e:
            logger.error("Credenciais invalidas/ausentes na verificacao Cakto: %s", e)
            return jsonify(success=False, error="Erro de configuracao na API de pagamentos."), 500
        except Exception as e:
            logger.error("Erro inesperado na validacao ativa Cakto: %s", e)
            return jsonify(success=False, error="Falha ao consultar API da Cakto."), 500

    target_state = True if should_activate else False
    user_id = None
    api_amount = _normalize_decimal(data.get("amount"))

    if order:
        user_id = order["user_id"]
        with get_db() as (cursor, conn):
            cursor.execute("SELECT is_premium FROM users WHERE id = %s", (user_id,))
        new_status = "approved" if should_activate else "revoked"
        with get_db() as (cursor, conn):
            if api_amount is not None and should_activate:
                cursor.execute(
                    """UPDATE payments_orders
                       SET status = %s, provider_order_id = %s, amount = %s
                       WHERE id = %s""",
                    (new_status, data.get("id"), api_amount, internal_order_id),
                )
            else:
                cursor.execute(
                    "UPDATE payments_orders SET status = %s, provider_order_id = %s WHERE id = %s",
                    (new_status, data.get("id"), internal_order_id),
                )
            conn.commit()
    elif internal_order_id:
        logger.warning(f"Webhook Cakto: Pedido interno {internal_order_id} nao encontrado.")

    updated = 0
    plan_name = resolved_plan or "completo"
    if user_id:
        if resolved_is_b2b:
            b2b_plan = str(resolved_plan).replace("b2b_", "", 1)
            updated = set_b2b_client_state(user_id, b2b_plan, target_state)
        else:
            updated = _set_premium_by_user_id(user_id, target_state, plan=plan_name)
    else:
        if not resolved_is_b2b:
            email = service.extract_customer_email(payload)
            if email:
                with get_db() as (cursor, conn):
                    cursor.execute("SELECT id, is_premium FROM users WHERE email = %s", (email,))
                    row = cursor.fetchone()
                if row:
                    user_id = row["id"]
                updated = _set_premium_by_email(email, target_state, plan=plan_name)
        else:
            # Evento B2B sem usuario e sem pedido interno: nao aplicamos Premium
            # por engano. Apenas registramos e encerramos com sucesso.
            logger.warning(
                "Webhook Cakto B2B ignorado (sem usuario/pedido): product=%s offer=%s",
                provider_product_id,
                provider_offer_id,
            )
            updated = 1

    if updated == 0:
        logger.warning(
            "Webhook Cakto sem usuario correspondente | event=%s status=%s",
            event,
            status,
        )
        return jsonify(success=False, error="Usuario nao encontrado para este evento."), 404

    # Envia push notification ao ativar
    if target_state and user_id:
        try:
            if resolved_is_b2b:
                send_push_notification(
                    user_id=user_id,
                    title="🔑 API B2B ativada!",
                    body="Sua chave de API AutoAssist esta ativa e pronta para usar.",
                    data={"url": "/b2b.html"},
                )
            else:
                send_push_notification(
                    user_id=user_id,
                    title="🌟 Bem-vindo ao AutoAssist Premium!",
                    body="Sua assinatura AutoAssist Premium foi ativada com sucesso.",
                    data={"url": "/dashboard.html"},
                )
        except Exception:
            logger.warning("Falha ao enviar push", exc_info=True)

    logger.info(
        "Webhook Cakto processado | event=%s status=%s premium=%s order=%s",
        event,
        status,
        target_state,
        internal_order_id,
    )
    return jsonify(success=True, premium=target_state, updated=updated), 200
