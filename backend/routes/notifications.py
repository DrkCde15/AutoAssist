import logging
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from .database import get_db

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
