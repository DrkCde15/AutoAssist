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
    raw = str(value)
    cleaned = bleach.clean(raw, tags=[], attributes={}, strip=True) if any(ch in raw for ch in "<>&") else raw
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
                "SELECT id, user_id, nome, estrelas, comentario, created_at FROM feedbacks ORDER BY created_at DESC LIMIT 50"
            )
            feedbacks = cursor.fetchall()
            for item in feedbacks:
                item["nome"] = _clean_text(item.get("nome"), 100)
                item["comentario"] = _clean_text(item.get("comentario"), 2000)
            return jsonify(feedbacks=feedbacks), 200
    except Exception as e:
        logger.error("Erro ao listar feedbacks: %s", e, exc_info=True)
        return jsonify(error="Erro interno ao listar feedbacks."), 500


@feedback_bp.route("/api/feedback/<int:feedback_id>", methods=["PUT"])
@jwt_required()
def update_feedback(feedback_id):
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    estrelas = data.get("estrelas")
    comentario = _clean_text(data.get("comentario"), 2000)

    if not comentario:
        return jsonify(error="O comentario e obrigatorio."), 400

    try:
        estrelas_int = int(estrelas)
    except (TypeError, ValueError):
        estrelas_int = 5
    estrelas_int = max(1, min(estrelas_int, 5))

    try:
        with get_db() as (cursor, conn):
            # Verificar se o feedback pertence ao usuário
            cursor.execute("SELECT user_id FROM feedbacks WHERE id = %s", (feedback_id,))
            feedback = cursor.fetchone()

            if not feedback:
                return jsonify(error="Feedback não encontrado."), 404

            if str(feedback["user_id"]) != str(user_id):
                return jsonify(error="Você não tem permissão para editar este feedback."), 403

            cursor.execute(
                "UPDATE feedbacks SET estrelas = %s, comentario = %s WHERE id = %s",
                (estrelas_int, comentario, feedback_id),
            )
        return jsonify(message="Feedback atualizado com sucesso!"), 200
    except Exception as e:
        logger.error("Erro ao atualizar feedback: %s", e, exc_info=True)
        return jsonify(error="Erro interno ao atualizar feedback."), 500


@feedback_bp.route("/api/feedback/<int:feedback_id>", methods=["DELETE"])
@jwt_required()
def delete_feedback(feedback_id):
    user_id = get_jwt_identity()

    try:
        with get_db() as (cursor, conn):
            # Verificar se o feedback pertence ao usuário
            cursor.execute("SELECT user_id FROM feedbacks WHERE id = %s", (feedback_id,))
            feedback = cursor.fetchone()

            if not feedback:
                return jsonify(error="Feedback não encontrado."), 404

            if str(feedback["user_id"]) != str(user_id):
                return jsonify(error="Você não tem permissão para excluir este feedback."), 403

            cursor.execute("DELETE FROM feedbacks WHERE id = %s", (feedback_id,))
        return jsonify(message="Feedback excluído com sucesso!"), 200
    except Exception as e:
        logger.error("Erro ao excluir feedback: %s", e, exc_info=True)
        return jsonify(error="Erro interno ao excluir feedback."), 500
