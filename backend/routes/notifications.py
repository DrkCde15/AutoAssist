import logging
import os
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from .database import get_db
from utils.cron_auth import require_cron_secret

notifications_bp = Blueprint("notifications", __name__)
logger = logging.getLogger(__name__)

@notifications_bp.route("/api/notifications", methods=["GET"])
@jwt_required()
def list_notifications():
    user_id = get_jwt_identity()
    limit = 50
    try:
        with get_db() as (cur, conn):
            cur.execute(
                """SELECT id, title, body, type, action_url, is_read, created_at
                   FROM notifications
                   WHERE user_id = %s
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (user_id, limit),
            )
            rows = cur.fetchall()
        return jsonify([{
            "id": r["id"],
            "title": r["title"],
            "body": r["body"],
            "type": r["type"],
            "action_url": r["action_url"],
            "is_read": bool(r["is_read"]),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        } for r in rows]), 200
    except Exception as e:
        logger.error("Erro ao listar notificações: %s", e)
        return jsonify([]), 200

@notifications_bp.route("/api/notifications/unread-count", methods=["GET"])
@jwt_required()
def unread_count():    
    user_id = get_jwt_identity()
    try:
        with get_db() as (cur, conn):
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM notifications WHERE user_id = %s AND is_read = 0",
                (user_id,),
            )
            row = cur.fetchone()
        return jsonify({"count": row["cnt"] if row else 0}), 200
    except Exception as e:
        logger.error("Erro ao contar notificações: %s", e)
        return jsonify({"count": 0}), 200

@notifications_bp.route("/api/notifications/<int:notif_id>/read", methods=["POST"])
@jwt_required()
def mark_read(notif_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cur, conn):
            cur.execute(
                "UPDATE notifications SET is_read = 1 WHERE id = %s AND user_id = %s",
                (notif_id, user_id),
            )
            conn.commit()
        return jsonify(success=True), 200
    except Exception as e:
        logger.error("Erro ao marcar notificação como lida: %s", e)
        return jsonify(success=False), 500

@notifications_bp.route("/api/notifications/read-all", methods=["POST"])
@jwt_required()
def mark_all_read():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cur, conn):
            cur.execute(
                "UPDATE notifications SET is_read = 1 WHERE user_id = %s AND is_read = 0",
                (user_id,),
            )
            conn.commit()
        return jsonify(success=True), 200
    except Exception as e:
        logger.error("Erro ao marcar todas notificações como lidas: %s", e)
        return jsonify(success=False), 500

@notifications_bp.route("/api/notifications/<int:notif_id>", methods=["DELETE"])
@jwt_required()
def delete_notification(notif_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cur, conn):
            cur.execute(
                "DELETE FROM notifications WHERE id = %s AND user_id = %s",
                (notif_id, user_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return jsonify(error="Notificação não encontrada"), 404
        return jsonify(success=True), 200
    except Exception as e:
        logger.error("Erro ao excluir notificação: %s", e)
        return jsonify(success=False), 500


def create_notification(user_id, title, body=None, type="info", action_url=None):
    try:
        with get_db() as (cur, conn):
            cur.execute(
                "INSERT INTO notifications (user_id, title, body, type, action_url) VALUES (%s, %s, %s, %s, %s)",
                (user_id, title, body, type, action_url),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.warning("Erro ao criar notificação: %s", e)
        return False


@notifications_bp.route("/api/cron/maintenance-emails", methods=["POST"])
@require_cron_secret()
def cron_dispatch_maintenance_emails():
    """Endpoint agendado (cron externo) para disparar e-mails de manutenção.

    Protegido por MAINTENANCE_EMAIL_CRON_SECRET via header X-Cron-Secret.
    O processamento real roda no worker RQ em background.
    """
    try:
        from tasks import dispatch_maintenance_emails
        try:
            from rq import Queue
            from redis import Redis
            redis_url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI")
            if redis_url and redis_url != "memory://":
                conn = Redis.from_url(redis_url)
                Queue("default", connection=conn).enqueue(
                    dispatch_maintenance_emails, timeout=600
                )
                return jsonify(scheduled=True, via="rq"), 202
        except Exception:
            pass
        # Fallback (sem Redis): executa em thread para nao bloquear o cron.
        import threading
        threading.Thread(target=dispatch_maintenance_emails, daemon=True).start()
        return jsonify(scheduled=True, via="thread"), 202
    except Exception as e:
        logger.error("Falha ao agendar dispatch de e-mails de manutenção: %s", e)
        return jsonify(error="Erro interno ao agendar envio."), 500
