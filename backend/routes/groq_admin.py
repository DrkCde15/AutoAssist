"""Admin: métricas Groq por endpoint (P2)."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import limiter

groq_admin_bp = Blueprint("groq_admin", __name__)
logger = logging.getLogger(__name__)


def _is_admin(user_id) -> bool:
    try:
        from routes.database import get_db

        with get_db() as (cursor, _conn):
            cursor.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
            return bool(row and row.get("is_admin"))
    except Exception:
        return False


@groq_admin_bp.route("/api/admin/groq-metrics", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def groq_metrics():
    user_id = get_jwt_identity()
    if not _is_admin(user_id):
        return jsonify(error="Acesso restrito."), 403
    try:
        from services.groq_metrics import snapshot

        return jsonify(snapshot()), 200
    except Exception as exc:
        logger.error("Falha ao ler métricas Groq: %s", exc)
        return jsonify(error="Erro ao ler métricas"), 500
