import logging
import os
import threading

from flask import Blueprint, jsonify, request

from .database import get_db
from utils.email import enviar_email

feedback_bp = Blueprint("feedback_bp", __name__)
logger = logging.getLogger(__name__)


def _send_feedback_email_async(admin_email: str, assunto: str, mensagem: str) -> None:
    try:
        ok = enviar_email(admin_email, assunto, mensagem)
        if not ok:
            logger.warning("Falha ao enviar e-mail de feedback para admin.")
    except Exception as exc:
        logger.warning(f"Falha no envio assíncrono de e-mail de feedback: {exc}")


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
    # Tenta identificar o usuario se houver token.
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

        # Enviar e-mail de alerta para o administrador sem bloquear request.
        admin_email = os.getenv("EMAIL_REMETENTE")
        if admin_email:
            assunto = f"Novo Feedback Recebido - {estrelas_int} Estrelas"
            stars_visual = " * " * estrelas_int
            mensagem = f"""
            <div style='font-family: sans-serif; color: #374151;'>
                <h2 style='color: #2563eb;'>Novo Feedback do Usuario</h2>
                <p><strong>Nome:</strong> {nome or 'Anonimo'}</p>
                <p><strong>Email:</strong> {email or 'Nao informado'}</p>
                <p><strong>Avaliacao:</strong> {stars_visual} ({estrelas_int}/5)</p>
                <p><strong>Comentario:</strong></p>
                <div style='background: #f3f4f6; padding: 15px; border-radius: 8px; border-left: 4px solid #2563eb;'>
                    {comentario}
                </div>
                <p style='font-size: 12px; color: #9ca3af; margin-top: 20px;'>
                    Este feedback foi registrado automaticamente pelo sistema AutoAssist.
                </p>
            </div>
            """
            threading.Thread(
                target=_send_feedback_email_async,
                args=(admin_email, assunto, mensagem),
                daemon=True,
            ).start()

        return jsonify(message="Feedback enviado com sucesso!"), 201
    except Exception as e:
        logger.error(f"Erro ao salvar feedback: {e}")
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
