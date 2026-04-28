import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from services.cakto import CaktoService
from .database import get_db

gateway_bp = Blueprint("gateway", __name__, url_prefix="/pagamentos")
logger = logging.getLogger(__name__)

_svc = None


def get_service() -> CaktoService:
    global _svc
    if _svc is None:
        _svc = CaktoService()
    return _svc


def _bad(msg: str, code: int = 400):
    return jsonify({"success": False, "error": msg}), code


def _ok(data: dict, code: int = 200):
    return jsonify(data), code


def _get_service_or_error():
    try:
        return get_service(), None
    except Exception as exc:
        logger.error("Falha ao inicializar CaktoService: %s", exc)
        return None, _bad("Falha ao inicializar Cakto.", 500)


def _get_user_email(user_id: str) -> str | None:
    with get_db() as (cursor, conn):
        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
    if not user:
        return None
    email = user.get("email")
    return str(email).strip().lower() if isinstance(email, str) and email.strip() else None


@gateway_bp.route("/pix", methods=["POST"])
@jwt_required()
def criar_pix():
    service, error_response = _get_service_or_error()
    if error_response:
        return error_response

    user_id = str(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    user_email = _get_user_email(user_id)

    try:
        checkout_url = service.build_checkout_url(
            user_id=user_id,
            user_email=user_email,
            provided_url=body.get("checkout_url"),
        )
    except ValueError as exc:
        return _bad(str(exc), 400)

    return _ok(
        {
            "success": True,
            "message": "Use o checkout_url para concluir o pagamento na Cakto.",
            "data": {
                "checkout_url": checkout_url,
                "provider": "cakto",
            },
        },
        201,
    )


@gateway_bp.route("/payments/<payment_id>/reembolso", methods=["POST"])
@jwt_required()
def reembolsar(payment_id: str):
    return _bad(
        "Reembolso automatico nao disponivel nesta integracao. Faca pelo painel da Cakto.",
        410,
    )
