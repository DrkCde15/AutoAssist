from flask import Blueprint, jsonify, request

from .database import get_db

feedback_bp = Blueprint("feedback_bp", __name__)


@feedback_bp.route("/api/feedback", methods=["POST"])
def post_feedback():
    data = request.get_json(silent=True) or {}
    nome = data.get("nome")
    email = data.get("email")
    estrelas = data.get("estrelas", 5)
    comentario = data.get("comentario")

    if not comentario:
        return jsonify(error="O comentario e obrigatorio."), 400

    try:
        estrelas_int = int(estrelas)
    except (TypeError, ValueError):
        estrelas_int = 5
    estrelas_int = max(1, min(estrelas_int, 5))

    user_id = None
    from flask_jwt_extended import decode_token

    auth_header = request.headers.get("Authorization")
    if auth_header and "Bearer " in auth_header:
        try:
            token = auth_header.split(" ")[1]
            decoded = decode_token(token)
            user_id = decoded.get("sub")
        except Exception:
            pass

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
        print(f"Erro ao salvar feedback: {e}")
        return jsonify(error="Erro interno ao salvar feedback."), 500


@feedback_bp.route("/api/feedbacks", methods=["GET"])
def get_feedbacks():
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "SELECT nome, estrelas, comentario, created_at FROM feedbacks ORDER BY created_at DESC LIMIT 20"
            )
            feedbacks = cursor.fetchall()
            return jsonify(feedbacks=feedbacks), 200
    except Exception as e:
        return jsonify(error=str(e)), 500
