import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from services.cakto import CaktoService
from .database import get_db

gateway_bp = Blueprint("gateway", __name__, url_prefix="/pagamentos")
logger = logging.getLogger(__name__)

_svc = None

PAYMENT_METHOD_ALIASES = {
    "pix": "pix",
    "boleto": "boleto",
    "cartao_credito": "cartao_credito",
    "cartao-credito": "cartao_credito",
    "cartao": "cartao_credito",
    "credito": "cartao_credito",
    "picpay": "picpay",
    "apple_pay": "apple_pay",
    "apple-pay": "apple_pay",
    "google_pay": "google_pay",
    "google-pay": "google_pay",
}


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


def _normalize_payment_method(raw_method: str | None) -> str | None:
    if not raw_method:
        return None
    normalized = str(raw_method).strip().lower()
    return PAYMENT_METHOD_ALIASES.get(normalized)


def _create_checkout_for_method(method_hint: str | None):
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
            payment_method=method_hint,
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
                "payment_method": method_hint,
            },
        },
        201,
    )


@gateway_bp.route("/metodos", methods=["GET"])
@jwt_required()
def listar_metodos_pagamento():
    return _ok(
        {
            "success": True,
            "methods": [
                "pix",
                "boleto",
                "cartao_credito",
                "picpay",
                "apple_pay",
                "google_pay",
            ],
        }
    )


@gateway_bp.route("/checkout", methods=["POST"])
@jwt_required()
def criar_checkout_geral():
    body = request.get_json(silent=True) or {}
    raw_method = body.get("payment_method")
    method_hint = _normalize_payment_method(raw_method)
    if raw_method and not method_hint:
        return _bad("Metodo de pagamento invalido.", 400)
    return _create_checkout_for_method(method_hint)


@gateway_bp.route("/checkout/<method>", methods=["POST"])
@jwt_required()
def criar_checkout_por_metodo(method: str):
    method_hint = _normalize_payment_method(method)
    if not method_hint:
        return _bad("Metodo de pagamento invalido.", 400)
    return _create_checkout_for_method(method_hint)


@gateway_bp.route("/pix", methods=["POST"])
@jwt_required()
def criar_pix():
    return _create_checkout_for_method("pix")


@gateway_bp.route("/boleto", methods=["POST"])
@jwt_required()
def criar_boleto():
    return _create_checkout_for_method("boleto")


@gateway_bp.route("/cartao-credito", methods=["POST"])
@gateway_bp.route("/cartao_credito", methods=["POST"])
@jwt_required()
def criar_cartao_credito():
    return _create_checkout_for_method("cartao_credito")


@gateway_bp.route("/picpay", methods=["POST"])
@jwt_required()
def criar_picpay():
    return _create_checkout_for_method("picpay")


@gateway_bp.route("/apple-pay", methods=["POST"])
@gateway_bp.route("/apple_pay", methods=["POST"])
@jwt_required()
def criar_apple_pay():
    return _create_checkout_for_method("apple_pay")


@gateway_bp.route("/google-pay", methods=["POST"])
@gateway_bp.route("/google_pay", methods=["POST"])
@jwt_required()
def criar_google_pay():
    return _create_checkout_for_method("google_pay")


@gateway_bp.route("/payments/<payment_id>/reembolso", methods=["POST"])
@jwt_required()
def reembolsar(payment_id: str):
    return _bad(
        "Reembolso automatico nao disponivel nesta integracao. Faca pelo painel da Cakto.",
        410,
    )
