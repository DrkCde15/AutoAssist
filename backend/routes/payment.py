import logging

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

    consulta = get_service().consultar_pagamento(str(payment_id))
    if not consulta["success"]:
        return jsonify(
            success=False,
            error="Falha ao consultar pagamento no Mercado Pago.",
            details=consulta.get("error"),
        ), consulta.get("status_code", 500)

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
            message="Upgrade concluido com pagamento aprovado no Mercado Pago.",
            payment_id=payment_id,
            payment_status=status,
        )
    except Exception as exc:
        logger.error("Erro ao concluir upgrade premium: %s", exc)
        return jsonify(
            success=False,
            error="Erro ao atualizar status premium do usuario.",
        ), 500
