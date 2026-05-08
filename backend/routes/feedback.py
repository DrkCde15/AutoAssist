import logging

import bleach
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import limiter
from .database import get_db

feedback_bp = Blueprint("feedback_bp", __name__)
logger = logging.getLogger(__name__)


def _clean_text(value, max_length):
    if value is None:
        return ""
    cleaned = bleach.clean(str(value), tags=[], attributes={}, strip=True)
    cleaned = " ".join(cleaned.split())
    return cleaned[:max_length]


@feedback_bp.route("/api/feedback", methods=["POST"])
@limiter.limit("10 per minute")
@jwt_required()
def post_feedback():
    data = request.get_json(silent=True) or {}
    nome = _clean_text(data.get("nome"), 100)
    email = _clean_text(data.get("email"), 100)
    estrelas = data.get("estrelas", 5)
    comentario = _clean_text(data.get("comentario"), 2000)

    if not comentario:
        return jsonify(error="O comentario e obrigatorio."), 400

    try:
        estrelas_int = int(estrelas)
    except (TypeError, ValueError):
        estrelas_int = 5
    estrelas_int = max(1, min(estrelas_int, 5))

    user_id = get_jwt_identity()

    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """
                INSERT INTO feedbacks (user_id, nome, email, estrelas, comentario)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, nome, email, estrelas_int, comentario),
            )
        return jsonify(message="Feedback enviado com sucesso!"), 201
    except Exception as e:
        logger.error("Erro ao salvar feedback: %s", e, exc_info=True)
        return jsonify(error="Erro interno ao salvar feedback."), 500


@feedback_bp.route("/api/feedbacks", methods=["GET"])
@limiter.limit("30 per minute")
def get_feedbacks():
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "SELECT nome, estrelas, comentario, created_at FROM feedbacks ORDER BY created_at DESC LIMIT 20"
            )
            feedbacks = cursor.fetchall()
            for item in feedbacks:
                item["nome"] = _clean_text(item.get("nome"), 100)
                item["comentario"] = _clean_text(item.get("comentario"), 2000)
            return jsonify(feedbacks=feedbacks), 200
    except Exception as e:
        logger.error("Erro ao listar feedbacks: %s", e, exc_info=True)
        return jsonify(error="Erro interno ao listar feedbacks."), 500
