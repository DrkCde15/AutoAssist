import logging
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from .database import get_db

payment_bp = Blueprint('payment', __name__)
logger = logging.getLogger(__name__)

@payment_bp.route("/api/pay/mock", methods=["POST"])
@jwt_required()
def pay():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("UPDATE users SET is_premium = TRUE WHERE id = %s", (user_id,))
        return jsonify(success=True, message="Upgrade concluído!")
    except Exception as e:
        logger.error(f"❌ Erro no pagamento: {e}")
        return jsonify(error="Erro ao processar pagamento"), 500
