import json
import logging
import os
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from .database import get_db

push_bp = Blueprint("push", __name__)
logger = logging.getLogger(__name__)


def get_vapid_claims():
    return {
        "sub": "mailto:autoassist45@gmail.com",
    }


def send_push_notification(user_id, title, body, icon=None, data=None):
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("pywebpush nao instalado — push notification ignorada")
        return False

    vapid_private_key = os.getenv("VAPID_PRIVATE_KEY")
    vapid_public_key = os.getenv("VAPID_PUBLIC_KEY")
    if not vapid_private_key or not vapid_public_key:
        logger.warning("VAPID keys nao configuradas — push ignorada")
        return False

    try:
        with get_db() as (cur, conn):
            cur.execute(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = %s",
                (user_id,),
            )
            rows = cur.fetchall()
    except Exception as e:
        logger.warning("Erro ao buscar subscriptions: %s", e)
        return False

    if not rows:
        return False

    payload = json.dumps({
        "title": title,
        "body": body,
        "icon": icon or "/static/logo2.png",
        "badge": "/static/logo2.png",
        "data": data or {},
        "requireInteraction": True,
    })

    sent = 0
    for row in rows:
        try:
            webpush(
                subscription_info={
                    "endpoint": row["endpoint"],
                    "keys": {
                        "p256dh": row["p256dh"],
                        "auth": row["auth"],
                    },
                },
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims=get_vapid_claims(),
            )
            sent += 1
        except WebPushException as e:
            if e.response and e.response.status_code in (410, 404):
                try:
                    with get_db() as (cur, conn):
                        cur.execute(
                            "DELETE FROM push_subscriptions WHERE endpoint = %s",
                            (row["endpoint"],),
                        )
                        conn.commit()
                except Exception:
                    pass
            logger.warning("Push falhou para %s: %s", row["endpoint"][:50], e)
        except Exception as e:
            logger.warning("Erro push inesperado: %s", e)

    return sent > 0


@push_bp.route("/api/push/vapid-public-key", methods=["GET"])
def vapid_public_key():
    key = os.getenv("VAPID_PUBLIC_KEY")
    if not key:
        return jsonify(error="VAPID nao configurado"), 500
    return jsonify({"publicKey": key}), 200


@push_bp.route("/api/push/subscribe", methods=["POST"])
@jwt_required()
def subscribe():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="Body invalido"), 400

    endpoint = data.get("endpoint")
    p256dh = data.get("keys", {}).get("p256dh")
    auth = data.get("keys", {}).get("auth")
    if not endpoint or not p256dh or not auth:
        return jsonify(error="Campos obrigatorios: endpoint, keys.p256dh, keys.auth"), 400

    try:
        with get_db() as (cur, conn):
            cur.execute(
                "SELECT id FROM push_subscriptions WHERE user_id = %s AND endpoint = %s",
                (user_id, endpoint),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    "UPDATE push_subscriptions SET p256dh = %s, auth = %s WHERE id = %s",
                    (p256dh, auth, existing["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (%s, %s, %s, %s)",
                    (user_id, endpoint, p256dh, auth),
                )
            conn.commit()
        return jsonify(success=True), 201
    except Exception as e:
        logger.error("Erro ao salvar subscription: %s", e, exc_info=True)
        return jsonify(error="Erro interno"), 500


@push_bp.route("/api/push/unsubscribe", methods=["POST"])
@jwt_required()
def unsubscribe():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True)
    endpoint = data.get("endpoint") if data else None

    try:
        with get_db() as (cur, conn):
            if endpoint:
                cur.execute(
                    "DELETE FROM push_subscriptions WHERE user_id = %s AND endpoint = %s",
                    (user_id, endpoint),
                )
            else:
                cur.execute(
                    "DELETE FROM push_subscriptions WHERE user_id = %s",
                    (user_id,),
                )
            conn.commit()
        return jsonify(success=True), 200
    except Exception as e:
        logger.error("Erro ao remover subscription: %s", e)
        return jsonify(error="Erro interno"), 500
