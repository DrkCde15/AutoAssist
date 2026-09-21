"""
Eventos API - Varredura de eventos automotivos
Fontes: NFeiras.com, Sindirepa Brasil, Diretriz, Shopping Interlagos, SerpApi (Google, via SERPAPI_KEY), Google (Sympla)
"""
import logging
import os
import threading
from flask import Blueprint, request, jsonify
from services.automotive_events import scan_automotive_events, filter_events
from utils.cache import cache_get_json, cache_set_json
from utils.cron_auth import require_cron_secret
from .database import get_db
from .notifications import create_notification
from .push import send_push_notification

events_bp = Blueprint('events', __name__)
logger = logging.getLogger(__name__)

# ─────────────────── notificações de novos eventos ───────────────────
NOTIFIED_EVENTS_CACHE_KEY = "automotive_events:notified_ids"
NOTIFIED_EVENTS_CACHE_TTL = 90 * 24 * 3600  # 90 dias (cron diário)
MAX_EVENT_NOTIFICATIONS_PER_RUN = 10
EVENTS_PAGE_URL = "/maps.html"


def _event_notification_key(ev):
    """Chave determinística por evento (id do scrape usa hash(), que varia
    entre processos - não pode ser usado para deduplicar notificações)."""
    titulo = (ev.get("titulo") or "").strip().lower()
    return f"{titulo}|{ev.get('data_inicio') or ev.get('url') or ''}"


def notify_new_automotive_events(max_per_run=MAX_EVENT_NOTIFICATIONS_PER_RUN, dry_run=False):
    """Varre os eventos automotivos e notifica os usuários sobre eventos novos.

    - Eventos já notificados (cache de 90 dias) são ignorados.
    - Cada usuário só recebe eventos da sua UF (definida pela localização
      enviada via /api/user/location). Eventos sem UF informada são genéricos
      e vão para todos. Usuários sem UF definida só recebem os genéricos.
    - Notifica in-app (todos os usuários) + push (quem tiver assinatura).
    - Com dry_run=True apenas calcula os novos eventos (não notifica).
    """
    payload = scan_automotive_events(force=True)
    events = payload.get("events", [])

    known = set(cache_get_json(NOTIFIED_EVENTS_CACHE_KEY) or [])
    new_events = [
        ev for ev in events
        if not ev.get("passado") and _event_notification_key(ev) not in known
    ]

    def _date_sort_key(ev):
        return (0, ev.get("data_inicio") or "9999") if ev.get("data_inicio") else (1, ev.get("titulo") or "")

    new_events.sort(key=_date_sort_key)

    if dry_run:
        return {"success": True, "new_count": len(new_events), "new_events": new_events}

    if not new_events:
        return {"success": True, "new_count": 0, "notified_rows": 0, "users_count": 0}

    with get_db() as (cur, conn):
        cur.execute("SELECT id, uf FROM users")
        users = [
            {"id": row["id"], "uf": (row.get("uf") or "").strip().upper()}
            for row in cur.fetchall()
        ]

    # Separa eventos regionais (com UF) dos genéricos (sem UF)
    regional = {}
    generic = []
    for ev in new_events:
        uf = (ev.get("uf") or "").strip().upper()
        if len(uf) == 2 and uf.isalpha():
            regional.setdefault(uf, []).append(ev)
        else:
            generic.append(ev)

    notified_rows = 0
    notified_users = 0
    notified_keys = set()
    for user in users:
        eligible = list(generic)
        uf = user["uf"]
        if len(uf) == 2 and uf.isalpha():
            eligible += regional.get(uf, [])
        if not eligible:
            continue
        eligible.sort(key=_date_sort_key)
        eligible = eligible[:max_per_run]
        notified_users += 1
        for ev in eligible:
            titulo = (ev.get("titulo") or "Evento automotivo").strip()
            cidade = (ev.get("cidade") or "").strip()
            uf_ev = (ev.get("uf") or "").strip()
            local = f"{cidade}{f' ({uf_ev})' if uf_ev else ''}".strip()
            body = ev.get("data_inicio") or "Data a confirmar"
            if local:
                body += f", {local}"
            try:
                if create_notification(
                    user_id=user["id"],
                    title=f"Novo evento: {titulo}",
                    body=body,
                    type="info",
                    action_url=EVENTS_PAGE_URL,
                ):
                    notified_rows += 1
            except Exception:
                pass
            try:
                send_push_notification(
                    user_id=user["id"],
                    title=f"🎉 Novo evento: {titulo}",
                    body=body or "Confira o mapa de eventos automotivos",
                    data={"url": EVENTS_PAGE_URL},
                )
            except Exception:
                pass
        notified_keys.update(_event_notification_key(ev) for ev in eligible)

    cache_set_json(NOTIFIED_EVENTS_CACHE_KEY, sorted(known | notified_keys), ttl=NOTIFIED_EVENTS_CACHE_TTL)
    logger.info(
        "[Events] %d evento(s) novo(s) notificado(s) para %d usuário(s) (%d inserções).",
        len(notified_keys), notified_users, notified_rows,
    )
    return {
        "success": True,
        "new_count": len(notified_keys),
        "candidates_count": len(new_events),
        "notified_rows": notified_rows,
        "users_count": notified_users,
        "events": [
            {"titulo": ev.get("titulo"), "data_inicio": ev.get("data_inicio"), "uf": ev.get("uf")}
            for ev in new_events
        ],
    }


@events_bp.route("/api/cron/events-notifications", methods=["POST"])
@require_cron_secret()
def cron_events_notifications():
    """Endpoint agendado (cron externo) para notificar usuários sobre novos eventos.

    Protegido por MAINTENANCE_EMAIL_CRON_SECRET via header X-Cron-Secret.
    O processamento real roda no worker RQ em background (fallback: thread).
    Query param opcional: ?dry_run=1 para simular sem notificar.
    """
    try:
        dry_run = request.args.get("dry_run", "").lower() in ("1", "true", "yes")
        if dry_run:
            result = notify_new_automotive_events(dry_run=True)
            return jsonify(result), 200

        from tasks import dispatch_events_notifications
        try:
            from rq import Queue
            from redis import Redis
            redis_url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI")
            if redis_url and redis_url != "memory://":
                conn = Redis.from_url(redis_url)
                Queue("default", connection=conn).enqueue(
                    dispatch_events_notifications, timeout=600
                )
                return jsonify(scheduled=True, via="rq"), 202
        except Exception:
            pass
        threading.Thread(target=dispatch_events_notifications, daemon=True).start()
        return jsonify(scheduled=True, via="thread"), 202
    except Exception as e:
        logger.error("Falha ao agendar notificações de eventos: %s", e)
        return jsonify(error="Erro interno ao agendar notificações de eventos."), 500


@events_bp.route('/api/events/automotive', methods=['GET'])
def automotive_events():
    """
    Retorna eventos automotivos coletados por web scraping / fontes especializadas.

    Query params:
      - force=1       : ignora o cache e refaz a varredura
      - uf=SP         : filtra por UF (BR)
      - q=auto        : filtra por termo no título/descrição/cidade/local
      - categoria=    : feira | encontro | competicao | exposicao | congresso | outros
      - periodo=      : "30" | "90" | "ano" | "todos" - janela a partir de hoje
      - lat=/lng=     : filtro geográfico "perto de mim"
      - radius=       : raio em km (padrão 50) usado com lat/lng
    """
    try:
        force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
        uf = (request.args.get('uf') or '').strip().upper()
        q = (request.args.get('q') or '').strip().lower()
        categoria = (request.args.get('categoria') or '').strip().lower()
        periodo = (request.args.get('periodo') or '').strip().lower()
        lat = request.args.get('lat') or None
        lng = request.args.get('lng') or None
        radius = request.args.get('radius') or None

        data = scan_automotive_events(force=force)

        events = filter_events(
            data.get('events', []),
            uf=uf or None,
            q=q or None,
            categoria=categoria or None,
            periodo=periodo or None,
            lat=lat,
            lng=lng,
            radius_km=radius,
        )

        data['count'] = len(events)
        data['events'] = events
        return jsonify(data), 200

    except Exception as e:
        logger.error(f"Erro na varredura de eventos: {e}")
        return jsonify({"success": False, "error": "Erro interno na varredura de eventos"}), 500


@events_bp.route('/api/events/<event_id>', methods=['GET'])
def get_event(event_id):
    """Retorna um evento específico (busca no cache da varredura + MySQL)."""
    try:
        event_id = event_id.strip()
        data = scan_automotive_events(force=False)
        for ev in data.get('events', []):
            if ev.get('id') == event_id:
                if (ev.get("country") or "BR").upper() != "BR" or (ev.get("uf") or "").upper() == "INT":
                    return jsonify({"success": False, "error": "Evento não encontrado"}), 404
                return jsonify({"success": True, "event": ev}), 200

        from routes.database import get_db
        with get_db() as (cursor, conn):
            cols = ", ".join([
                "id", "title", "original_title", "normalized_title", "description",
                "category", "categoria_label", "start_date", "end_date", "start_time",
                "end_time", "venue_name", "address", "city", "state", "country",
                "latitude", "longitude", "organizer", "organizer_url", "event_url",
                "image_url", "source", "source_url", "status", "confidence",
                "last_verified_at",
            ])
            cursor.execute(f"SELECT {cols} FROM events WHERE id=%s LIMIT 1", (event_id,))
            row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Evento não encontrado"}), 404
        keys = ["id", "titulo", "original_title", "normalized_title", "descricao",
                "categoria", "categoria_label", "data_inicio", "data_fim", "start_time",
                "end_time", "venue_name", "address", "cidade", "uf", "country",
                "latitude", "longitude", "organizer", "organizer_url", "event_url",
                "image_url", "fonte", "source_url", "status", "confidence",
                "last_verified_at"]
        ev = {k: v for k, v in zip(keys, row)}
        if (ev.get("country") or "BR").upper() != "BR" or (ev.get("uf") or "").upper() == "INT":
            return jsonify({"success": False, "error": "Evento não encontrado"}), 404
        return jsonify({"success": True, "event": ev}), 200

    except Exception as e:
        logger.error(f"Erro ao buscar evento {event_id}: {e}")
        return jsonify({"success": False, "error": "Erro interno ao buscar evento"}), 500