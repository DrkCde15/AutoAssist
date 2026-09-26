import json
import logging
import re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request, jwt_required

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
    from .database import exec_ddl
    exec_ddl(cursor, ANALYTICS_TABLE_SQL)
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


def record_analytics_event(
    event_type,
    *,
    user_id=None,
    anonymous_id=None,
    path=None,
    metadata=None,
    user_agent=None,
):
    """Persiste um evento de analytics na tabela ``analytics_events``.

    Função compartilhada entre o endpoint público (/api/analytics/events)
    e os hooks de negócio (signup, nog_use, raio_x_use, etc.), mantendo
    um único pipeline de armazenamento. Não lança exceção: retorna False
    em caso de falha para não quebrar o fluxo que originou o evento.
    """
    event_type = _clean_event_type(event_type)
    if not event_type:
        return False

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
                    _clean_text(anonymous_id, MAX_ANONYMOUS_ID_LENGTH) or None,
                    event_type,
                    _clean_text(path, MAX_PATH_LENGTH) or None,
                    json.dumps(_safe_metadata(metadata), ensure_ascii=False) if metadata else None,
                    _clean_text(user_agent, 500) or None,
                ),
            )
        return True
    except Exception as exc:
        logger.error("Erro ao registrar evento de analytics: %s", exc, exc_info=True)
        return False


def has_prior_event(event_type, *, user_id=None, anonymous_id=None):
    """Indica se já existe evento do tipo para a identidade informada.

    Identidade: ``user_id`` quando autenticado, caso contrário
    ``anonymous_id``. Usado para decidir a emissão de eventos ``first_*``
    com base em dados persistidos (e não em estado de memória).
    """
    event_type = _clean_event_type(event_type)
    if not event_type:
        return False

    conditions = []
    params = [event_type]
    if user_id:
        conditions.append("user_id = %s")
        params.append(user_id)
    if anonymous_id:
        conditions.append("(user_id IS NULL AND anonymous_id = %s)")
        params.append(_clean_text(anonymous_id, MAX_ANONYMOUS_ID_LENGTH))

    if not conditions:
        return False

    sql = "SELECT 1 FROM analytics_events WHERE event_type = %s AND ({}) LIMIT 1".format(
        " OR ".join(conditions)
    )
    try:
        with get_db() as (cursor, conn):
            cursor.execute(sql, params)
            return cursor.fetchone() is not None
    except Exception as exc:
        logger.error("Erro ao verificar evento previo: %s", exc, exc_info=True)
        return False


# Estágios do funil de negócio. Todos instrumentados a partir de P0.2/P0.3.
FUNNEL_STAGES = [
    ("visitor", "page_view", "instrumented"),
    ("signup", "signup", "instrumented"),
    ("first_nog_use", "first_nog_use", "instrumented"),
    ("first_raio_x", "first_raio_x", "instrumented"),
    ("free_limit_reached", "free_limit_reached", "instrumented"),
    ("premium_upgrade", "premium_upgrade", "instrumented"),
    ("premium_churn", "premium_churn", "instrumented"),
]

# Mapa event_type -> nome do conjunto de estágio (usado no breakdown de aquisição).
STAGE_SETS = {
    "page_view": "visitor",
    "signup": "signup",
    "first_nog_use": "first_nog_use",
    "first_raio_x": "first_raio_x",
    "free_limit_reached": "free_limit_reached",
    "premium_upgrade": "premium_upgrade",
    "premium_churn": "premium_churn",
}


def _coerce_json(val):
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return {}


def _canonical_identity(event, users_map):
    """Identidade única por evento (mesma regra do SQL do funil): user_id
    tem precedência sobre anonymous_id, com prefixo para evitar colisão."""
    uid = event.get("user_id")
    if uid is not None:
        return "u:" + str(uid)
    anon = event.get("anonymous_id")
    if anon:
        return "a:" + str(anon)
    return None


def _event_attribution(event, meta, users_map):
    """Atribuição de primeiro toque (first-touch).

    Prioriza UTM presente no próprio evento; senão, cai no UTM do usuário
    (users.utm_*) quando houver user_id. Dados ausentes viram 'unknown'
    (nunca transformados em origem real).
    """
    def _clean(x):
        return (x or "").strip()

    s = _clean(meta.get("utm_source"))
    m = _clean(meta.get("utm_medium"))
    c = _clean(meta.get("utm_campaign"))
    if s or m or c:
        return (s or "unknown", m or "unknown", c or "unknown")

    uid = event.get("user_id")
    if uid is not None and uid in users_map:
        u = users_map[uid]
        s2 = _clean(u.get("utm_source"))
        m2 = _clean(u.get("utm_medium"))
        c2 = _clean(u.get("utm_campaign"))
        if s2 or m2 or c2:
            return (s2 or "unknown", m2 or "unknown", c2 or "unknown")
    return ("unknown", "unknown", "unknown")


def _build_acquisition(cursor):
    """Calcula o breakdown de aquisição por (source, medium, campaign).

    Identidade unificada por evento; atribuição first-touch; dados ausentes
    agrupados em 'unknown'. Retorna (funnel_summary, breakdown, by_source, by_campaign).
    """
    event_types = list(STAGE_SETS.keys())
    placeholders = ",".join(["%s"] * len(event_types))
    cursor.execute(
        "SELECT event_type, user_id, anonymous_id, metadata FROM analytics_events "
        "WHERE event_type IN ({})".format(placeholders),
        event_types,
    )
    rows = cursor.fetchall()
    cursor.execute("SELECT id, anonymous_id, utm_source, utm_medium, utm_campaign FROM users")
    users_map = {r["id"]: r for r in cursor.fetchall()}

    buckets = {}
    funnel_counts = {name: set() for name in STAGE_SETS.values()}

    for ev in rows:
        meta = _coerce_json(ev.get("metadata"))
        ident = _canonical_identity(ev, users_map)
        if ident is None:
            continue
        src, med, cmp = _event_attribution(ev, meta, users_map)
        key = (src, med, cmp)
        b = buckets.setdefault(key, {n: set() for n in STAGE_SETS.values()})
        set_name = STAGE_SETS.get(ev["event_type"])
        if set_name:
            b[set_name].add(ident)
            funnel_counts[set_name].add(ident)

    def _row(src, med, cmp, sets):
        v = len(sets["visitor"])
        sg = len(sets["signup"])
        ng = len(sets["first_nog_use"])
        rx = len(sets["first_raio_x"])
        return {
            "utm_source": src,
            "utm_medium": med,
            "utm_campaign": cmp,
            "visitors": v,
            "signups": sg,
            "first_nog_use": ng,
            "first_raio_x": rx,
            "signup_rate": round(sg / v, 4) if v else None,
            "first_nog_rate": round(ng / sg, 4) if sg else None,
            "first_raio_x_rate": round(rx / sg, 4) if sg else None,
        }

    breakdown = sorted(
        (_row(s, m, c, b) for (s, m, c), b in buckets.items()),
        key=lambda r: r["visitors"],
        reverse=True,
    )

    by_source_map = {}
    for (s, m, c), b in buckets.items():
        agg = by_source_map.setdefault(s, {n: set() for n in STAGE_SETS.values()})
        for n in STAGE_SETS.values():
            agg[n] |= b[n]
    by_source = sorted(
        (_row(s, None, None, agg) for s, agg in by_source_map.items()),
        key=lambda r: r["visitors"],
        reverse=True,
    )

    by_campaign_map = {}
    for (s, m, c), b in buckets.items():
        agg = by_campaign_map.setdefault(c, {n: set() for n in STAGE_SETS.values()})
        for n in STAGE_SETS.values():
            agg[n] |= b[n]
    by_campaign = sorted(
        (_row(None, None, c, agg) for c, agg in by_campaign_map.items()),
        key=lambda r: r["visitors"],
        reverse=True,
    )

    funnel_summary = {name: len(s) for name, s in funnel_counts.items()}
    return funnel_summary, breakdown, by_source, by_campaign


def get_funnel_report():
    """Relatório inicial do funil a partir de ``analytics_events``.

    Estágios não instrumentados retornam status ``not_instrumented`` com
    ``total``/``unique_persons`` nulos (nunca zero), para não confundir
    ausência de instrumentação com zero de conversão.

    Identidade unificada: ``user_id`` quando presente, senão
    ``anonymous_id`` (via prefixo para evitar colisão de tipos).
    """
    try:
        with get_db() as (cursor, conn):
            stage_data = {}
            for key, event_type, status in FUNNEL_STAGES:
                if status != "instrumented":
                    stage_data[key] = {"total": None, "unique_persons": None}
                    continue
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COUNT(DISTINCT CASE
                            WHEN user_id IS NOT NULL THEN CONCAT('u', user_id)
                            ELSE CONCAT('a', anonymous_id)
                        END) AS unique_persons
                    FROM analytics_events
                    WHERE event_type = %s
                    """,
                    (event_type,),
                )
                row = cursor.fetchone() or {"total": 0, "unique_persons": 0}
                stage_data[key] = {
                    "total": int(row["total"]),
                    "unique_persons": int(row["unique_persons"]),
                }

            steps = []
            prev_unique = None
            for key, _, status in FUNNEL_STAGES:
                if status != "instrumented":
                    continue
                unique = stage_data[key]["unique_persons"]
                conv = round(unique / prev_unique, 4) if prev_unique else None
                drop = round(1 - conv, 4) if conv is not None else None
                steps.append(
                    {
                        "stage": key,
                        "unique_persons": unique,
                        "conversion_from_previous": conv,
                        "drop_from_previous": drop,
                    }
                )
                prev_unique = unique

            funnel_summary, breakdown, by_source, by_campaign = _build_acquisition(cursor)

            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "funnel": funnel_summary,
                "stages": [
                    {
                        "stage": key,
                        "event_type": et,
                        "status": st,
                        "total": stage_data[key]["total"],
                        "unique_persons": stage_data[key]["unique_persons"],
                    }
                    for key, et, st in FUNNEL_STAGES
                ],
                "conversion_steps": steps,
                "acquisition_breakdown": breakdown,
                "acquisition_by_source": by_source,
                "acquisition_by_campaign": by_campaign,
            }
    except Exception as exc:
        logger.error("Erro ao gerar relatorio de funil: %s", exc, exc_info=True)
        return {"error": str(exc)}


@analytics_bp.route("/api/analytics/events", methods=["POST"])
@limiter.limit("120 per minute")
def record_analytics_event_route():
    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type") or data.get("type")
    if not _clean_event_type(event_type or ""):
        return jsonify(error="Tipo de evento invalido."), 400

    anonymous_id = data.get("anonymous_id")
    metadata = data.get("metadata")
    path = data.get("path") or request.referrer
    user_id = _get_optional_user_id()
    user_agent = request.headers.get("User-Agent")

    from utils.abuse_monitor import monitor_public_ingest
    monitor_public_ingest("analytics_events", limit=500)

    record_analytics_event(
        event_type,
        user_id=user_id,
        anonymous_id=anonymous_id,
        path=path,
        metadata=metadata,
        user_agent=user_agent,
    )
    return jsonify(ok=True), 201


@analytics_bp.route("/api/analytics/funnel", methods=["GET"])
@jwt_required()
def analytics_funnel_route():
    admin_id = get_jwt_identity()
    with get_db() as (cursor, conn):
        cursor.execute("SELECT is_admin FROM users WHERE id = %s", (admin_id,))
        row = cursor.fetchone()
    if not row or not row.get("is_admin"):
        return jsonify(error="Acesso restrito."), 403
    return jsonify(get_funnel_report())
