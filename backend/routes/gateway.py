import logging
import os

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from services.mercado_pago import MercadoPagoService

gateway_bp = Blueprint("gateway", __name__, url_prefix="/pagamentos")
logger = logging.getLogger(__name__)

_svc = None


def get_service() -> MercadoPagoService:
    global _svc
    if _svc is None:
        _svc = MercadoPagoService()
    return _svc


def _bad(msg: str, code: int = 400):
    return jsonify({"success": False, "error": msg}), code


def _ok(data: dict, code: int = 200):
    return jsonify(data), code


def _get_service_or_error():
    try:
        return get_service(), None
    except Exception as exc:
        logger.error("Falha ao inicializar MercadoPagoService: %s", exc)
        return None, _bad(
            "Falha ao inicializar Mercado Pago. Verifique token e dependencia SDK.",
            500,
        )


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_mp_error_message(error_payload) -> str:
    if not error_payload:
        return ""
    if isinstance(error_payload, str):
        return error_payload
    if isinstance(error_payload, dict):
        cause = error_payload.get("cause")
        if isinstance(cause, list) and cause:
            first = cause[0]
            if isinstance(first, dict):
                return str(
                    first.get("description")
                    or first.get("code")
                    or error_payload.get("message")
                    or error_payload.get("error")
                    or ""
                )
        return str(error_payload.get("message") or error_payload.get("error") or "")
    return str(error_payload)


def _is_test_user_email(email: str | None) -> bool:
    if not isinstance(email, str):
        return False
    return "@testuser.com" in email.strip().lower()


@gateway_bp.route("/pix", methods=["POST"])
@jwt_required()
def criar_pix():
    service, error_response = _get_service_or_error()
    if error_response:
        return error_response

    user_id = str(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    for campo in ("customer", "items", "valor_centavos"):
        if campo not in body:
            return _bad(f"Campo obrigatorio ausente: {campo}")

    valor_centavos = _as_int(body.get("valor_centavos"))
    if not valor_centavos or valor_centavos <= 0:
        return _bad("valor_centavos deve ser um inteiro maior que zero.")

    if (
        (os.getenv("MERCADO_PAGO_ENV") or "").strip().lower() == "test"
        and isinstance(body.get("customer"), dict)
    ):
        customer = dict(body["customer"])
        forced_test_email = (os.getenv("MERCADO_PAGO_TEST_PAYER_EMAIL") or "").strip()
        if forced_test_email:
            customer["email"] = forced_test_email

        if not _is_test_user_email(customer.get("email")):
            return _bad(
                "No modo teste, o pagador precisa ter email @testuser.com. "
                "Configure MERCADO_PAGO_TEST_PAYER_EMAIL com o email do Buyer Test User.",
                400,
            )

        body["customer"] = customer

    result = service.criar_pix(
        customer=body["customer"],
        items=body["items"],
        valor_centavos=valor_centavos,
        expiration_date=body.get("expiration_date"),
        reference_id=user_id,
        notification_url=body.get("notification_url"),
        idempotency_key=body.get("idempotency_key"),
    )
    if not result["success"]:
        status_code = int(result.get("status_code") or 500)
        mp_error = result.get("error")
        mp_message = _extract_mp_error_message(mp_error)

        logger.error(
            "Falha ao criar Pix no Mercado Pago | status=%s | details=%s",
            status_code,
            mp_error,
        )

        if "invalid_email_for_sandbox" in str(mp_error):
            return (
                jsonify(
                    success=False,
                    error=(
                        "Email invalido para sandbox. "
                        "Use email @testuser.com no pagador (Buyer Test User)."
                    ),
                    details=mp_error,
                ),
                400,
            )

        if status_code == 401:
            unauthorized_message = (
                "Falha de autorizacao no Mercado Pago. "
                "No modo teste, use as credenciais de teste da aplicacao do Seller e comprador de teste (@testuser.com). "
                "No modo producao, use credenciais de producao e comprador real."
            )
            return (
                jsonify(
                    success=False,
                    error=unauthorized_message,
                    details=mp_message or mp_error,
                ),
                401,
            )

        return (
            jsonify(
                success=False,
                error=mp_message or "Falha ao criar pagamento Pix no Mercado Pago.",
                details=mp_error,
            ),
            status_code,
        )

    return _ok(result, 201)


@gateway_bp.route("/payments/<payment_id>/reembolso", methods=["POST"])
def reembolsar(payment_id: str):
    service, error_response = _get_service_or_error()
    if error_response:
        return error_response

    body = request.get_json(silent=True) or {}
    valor_centavos = body.get("valor_centavos")
    if valor_centavos is not None:
        valor_centavos = _as_int(valor_centavos)
        if not valor_centavos or valor_centavos <= 0:
            return _bad("valor_centavos deve ser um inteiro maior que zero.")

    result = service.reembolsar_pagamento(
        payment_id,
        valor_centavos=valor_centavos,
        idempotency_key=body.get("idempotency_key"),
    )
    code = result["status_code"] if not result["success"] else 200
    return _ok(result, code)
