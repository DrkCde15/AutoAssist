import json
import logging
import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from extensions import limiter
from .database import get_db

analytics_bp = Blueprint("analytics", __name__)
logger = logging.getLogger(__name__)
_analytics_table_ready = False

ANALYTICS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS analytics_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    anonymous_id VARCHAR(80) NULL,
    event_type VARCHAR(80) NOT NULL,
    path VARCHAR(500) NULL,
    metadata JSON NULL,
    user_agent VARCHAR(500) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_analytics_created (created_at),
    INDEX idx_analytics_event_created (event_type, created_at),
    INDEX idx_analytics_user_created (user_id, created_at),
    INDEX idx_analytics_anonymous_created (anonymous_id, created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
)
"""

EVENT_NAME_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")
MAX_PATH_LENGTH = 500
MAX_ANONYMOUS_ID_LENGTH = 80
MAX_METADATA_BYTES = 2048
BLOCKED_METADATA_KEYS = {
    "authorization",
    "cookie",
    "password",
    "senha",
    "token",
    "refresh_token",
    "access_token",
    "jwt",
    "secret",
    "email",
    "telefone",
    "phone",
    "cpf",
    "cnpj",
    "placa",
    "license_plate",
    "message",
    "mensagem",
    "prompt",
    "content",
    "imagem",
    "image",
    "photo",
    "foto",
    "audio",
    "voice",
}


def _ensure_analytics_table(cursor):
    global _analytics_table_ready
    if _analytics_table_ready:
        return
    cursor.execute(ANALYTICS_TABLE_SQL)
    _analytics_table_ready = True


def _clean_text(value, max_length):
    if value is None:
        return ""
    return " ".join(str(value).strip().split())[:max_length]


def _clean_event_type(value):
    event_type = _clean_text(value, 80)
    if not EVENT_NAME_RE.match(event_type):
        return ""
    return event_type


def _safe_metadata(value):
    if not isinstance(value, dict):
        return {}

    cleaned = {}
    for raw_key, raw_value in value.items():
        key = _clean_text(raw_key, 80)
        if not key or key.lower() in BLOCKED_METADATA_KEYS:
            continue

        if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            cleaned[key] = raw_value if not isinstance(raw_value, str) else _clean_text(raw_value, 240)
        elif isinstance(raw_value, list):
            cleaned[key] = [
                _clean_text(item, 120) if isinstance(item, str) else item
                for item in raw_value[:10]
                if isinstance(item, (str, int, float, bool)) or item is None
            ]

    encoded = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    while len(encoded.encode("utf-8")) > MAX_METADATA_BYTES and cleaned:
        cleaned.pop(next(reversed(cleaned)))
        encoded = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))

    return cleaned


def _get_optional_user_id():
    try:
        verify_jwt_in_request(optional=True)
        return get_jwt_identity()
    except Exception:
        return None


@analytics_bp.route("/api/analytics/events", methods=["POST"])
@limiter.limit("120 per minute")
def record_analytics_event():
    data = request.get_json(silent=True) or {}
    event_type = _clean_event_type(data.get("event_type") or data.get("type"))
    path = _clean_text(data.get("path") or request.referrer or "", MAX_PATH_LENGTH)
    anonymous_id = _clean_text(data.get("anonymous_id"), MAX_ANONYMOUS_ID_LENGTH)
    metadata = _safe_metadata(data.get("metadata"))

    if not event_type:
        return jsonify(error="Tipo de evento invalido."), 400

    user_id = _get_optional_user_id()
    user_agent = _clean_text(request.headers.get("User-Agent"), 500)

    try:
        with get_db() as (cursor, conn):
            _ensure_analytics_table(cursor)
            cursor.execute(
                """
                INSERT INTO analytics_events
                    (user_id, anonymous_id, event_type, path, metadata, user_agent)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    anonymous_id or None,
                    event_type,
                    path,
                    json.dumps(metadata, ensure_ascii=False) if metadata else None,
                    user_agent or None,
                ),
            )
        return jsonify(ok=True), 201
    except Exception as exc:
        logger.error("Erro ao registrar evento de analytics: %s", exc, exc_info=True)
        return jsonify(error="Erro interno ao registrar analytics."), 500
