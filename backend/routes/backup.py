"""Backup do banco (cron) + listagem de backups (admin)."""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import limiter
from utils.cron_auth import require_cron_secret

backup_bp = Blueprint("backup", __name__)
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


@backup_bp.route("/api/cron/db-backup", methods=["POST"])
@limiter.limit("2 per hour")
@require_cron_secret()
def cron_db_backup():
    """Dispara o backup MySQL → S3/R2. Agende 1x/dia via cron externo:

        curl -X POST https://<dominio>/api/cron/db-backup \\
          -H "X-Cron-Secret: $MAINTENANCE_EMAIL_CRON_SECRET"
    """
    try:
        from tasks import run_db_backup
        try:
            from rq import Queue
            from redis import Redis
            redis_url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI")
            if redis_url and redis_url != "memory://":
                conn = Redis.from_url(redis_url)
                Queue("default", connection=conn).enqueue(run_db_backup, timeout=1800)
                return jsonify(scheduled=True, via="rq"), 202
        except Exception:
            pass
        import threading
        threading.Thread(target=run_db_backup, daemon=True).start()
        return jsonify(scheduled=True, via="thread"), 202
    except Exception as exc:
        logger.error("Falha ao agendar backup: %s", exc)
        return jsonify(error="Erro interno ao agendar backup."), 500


@backup_bp.route("/api/admin/backups", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def list_backups():
    user_id = get_jwt_identity()
    if not _is_admin(user_id):
        return jsonify(error="Acesso restrito."), 403
    try:
        from services.db_backup import list_backups as _list, _bucket, _prefix, _retention_days
        return jsonify(
            bucket=_bucket(),
            prefix=_prefix(),
            retention_days=_retention_days(),
            backups=_list(),
        ), 200
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 500
    except Exception as exc:
        logger.error("Falha ao listar backups: %s", exc)
        return jsonify(error="Erro ao listar backups."), 500
