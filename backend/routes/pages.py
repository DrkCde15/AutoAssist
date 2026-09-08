import os
import io
import base64
import hashlib
import html
import logging
import mimetypes
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from time import monotonic
from services.web_scraping import WebScraper
from flask import Blueprint, request, jsonify, current_app, send_from_directory, has_request_context, redirect, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
import uuid
from services.maintenance_service import _status_from_remaining, apply_manual_overrides, parse_maintenance_entry, serialize_maintenance_row
from services.nogai import prever_intervalo_manutencao, _invalidate_maintenance_context, _invalidate_user_ai_cache
from utils.async_task import _predictor, train_in_background
from utils.turnstile import turnstile_or_auth
import json
from decimal import Decimal
from .database import get_db, is_trial_expired, get_trial_days_remaining, get_mysql_history
from .analytics import record_analytics_event, has_prior_event
from utils.email import enviar_email


def _emit_usage_events(*, user_id, anonymous_id, is_raio):
    """Emite eventos de uso do funil (NOG / Raio-X) de forma idempotente.

    ``first_*`` é decidido por dados persistidos (has_prior_event), nunca
    por estado de memória. Não lança exceção para não impactar a resposta
    de chat/voz já gerada com sucesso.
    """
    identity_uid = user_id
    identity_aid = anonymous_id if not user_id else None
    if not identity_uid and not identity_aid:
        return
    try:
        # "primeiro" é decidido ANTES de emitir o evento de uso, para não
        # contar o próprio evento recém-inserido como prévio.
        is_first_nog = not has_prior_event("nog_use", user_id=identity_uid, anonymous_id=identity_aid)
        record_analytics_event(
            "nog_use",
            user_id=identity_uid,
            anonymous_id=identity_aid,
            path="/api/chat",
            metadata={"mode": "image" if is_raio else "text"},
        )
        if is_first_nog:
            record_analytics_event(
                "first_nog_use",
                user_id=identity_uid,
                anonymous_id=identity_aid,
                path="/api/chat",
                metadata={},
            )
        if is_raio:
            is_first_raio = not has_prior_event("raio_x_use", user_id=identity_uid, anonymous_id=identity_aid)
            record_analytics_event(
                "raio_x_use",
                user_id=identity_uid,
                anonymous_id=identity_aid,
                path="/api/chat",
                metadata={"mode": "image"},
            )
            if is_first_raio:
                record_analytics_event(
                    "first_raio_x",
                    user_id=identity_uid,
                    anonymous_id=identity_aid,
                    path="/api/chat",
                    metadata={},
                )
    except Exception as exc:
        logger.warning("Falha ao emitir eventos de uso (nog/raio): %s", exc)
from .notifications import create_notification
from .push import send_push_notification
from pydub import AudioSegment
import speech_recognition as sr

@lru_cache(maxsize=1)
def _load_maintenance_helpers():
    from services.maintenance_service import (
        parse_maintenance_entry,
        apply_manual_overrides,
        serialize_maintenance_row,
        consolidate_active_maintenance_records,
        build_maintenance_alerts,
        _status_from_remaining,
    )
    return (
        parse_maintenance_entry,
        apply_manual_overrides,
        serialize_maintenance_row,
        consolidate_active_maintenance_records,
        build_maintenance_alerts,
        _status_from_remaining,
    )

pages_bp = Blueprint('pages', __name__)
logger = logging.getLogger(__name__)

PREMIUM_ONLY_ERROR = "Recurso exclusivo para Premium"
INVALID_SESSION_ERROR = "Sessao invalida. Faca login novamente."
CRITICAL_MAINTENANCE_STATUSES = ("overdue",)
ACTIONABLE_MAINTENANCE_STATUSES = ("overdue", "due_soon")
MAINTENANCE_DISPATCH_LOCK_NAME = "autoassist_maintenance_email_dispatcher"
_maintenance_dispatch_thread_lock = threading.Lock()
_maintenance_dispatch_last_started_at = 0.0

GENERIC_CHAT_TOKENS = {
    "ai",
    "bem",
    "boa",
    "bom",
    "dia",
    "e",
    "noite",
    "obrigada",
    "obrigado",
    "oi",
    "ola",
    "opa",
    "salve",
    "tarde",
    "tudo",
    "valeu",
}

GUEST_CHAT_LIMIT = 5
# P0-1: free registrado ganha quota mensal de interações no chat.
# Premium é ilimitado. Evita burn infinito de IA em contas gratuitas.
FREE_MONTHLY_CHAT_LIMIT = int(os.getenv("FREE_MONTHLY_CHAT_LIMIT", "30"))
# P1-1: free pode registrar até N manutenções; premium é ilimitado.
FREE_MAINTENANCE_LIMIT = int(os.getenv("FREE_MAINTENANCE_LIMIT", "3"))
MAX_CHAT_HISTORY_LIMIT = 200
DEFAULT_CHAT_HISTORY_LIMIT = 100
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
TEXT_ATTACHMENT_LIMIT = 12000
IMAGE_ATTACHMENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
BINARY_ATTACHMENT_TYPES = {"application/pdf"}
TEXT_ATTACHMENT_TYPES = {
    "application/json",
    "application/xml",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/xml",
}
ALLOWED_ATTACHMENT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "pdf", "txt", "md", "csv", "json"}
MAX_IMAGE_DIMENSIONS = (5000, 5000)
MAX_FILENAME_LENGTH = 120
ATTACHMENT_RATE_LIMIT_SECONDS = 5

def get_dashboard_url() -> str:
    # Return URL to the legacy HTML dashboard page
    base = request.host_url.rstrip('/')
    return f"{base}/dashboard.html"

def get_user_by_id(cursor, user_id):
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    return cursor.fetchone()

def invalid_session_response():
    return jsonify(error=INVALID_SESSION_ERROR), 401

def ensure_premium_user(user):
    if not user:
        return invalid_session_response()
    if bool(user.get("is_premium")):
        return None
    return jsonify(error=PREMIUM_ONLY_ERROR), 403


def ensure_maintenance_access(user, cursor):
    """P1-1: free pode registrar até FREE_MAINTENANCE_LIMIT manutenções; premium ilimitado.
    Listagem é liberada para todos (free vê seus próprios registros)."""
    if not user:
        return invalid_session_response()
    if bool(user.get("is_premium")):
        return None
    user_id = user.get("id")
    cursor.execute("SELECT COUNT(*) AS cnt FROM maintenance_history WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    count = int((row or {}).get("cnt") or 0)
    if count >= FREE_MAINTENANCE_LIMIT:
        return jsonify(
            error=f"O plano gratuito permite ate {FREE_MAINTENANCE_LIMIT} registros de manutencao. Assine o Premium para historico ilimitado.",
            code="free_maintenance_limit_reached",
            limit=FREE_MAINTENANCE_LIMIT,
            used=count,
        ), 403
    return None

def _get_fx_rates():
    """Taxas de câmbio para normalização de custos em BRL (configurável via env)."""
    return {
        "BRL": 1.0,
        "USD": float(os.getenv("USD_BRL_RATE", "5.0")),
        "EUR": float(os.getenv("EUR_BRL_RATE", "5.5")),
    }


def _normalize_cost_to_brl(cost, currency):
    if cost is None:
        return 0.0
    try:
        value = float(cost)
    except (TypeError, ValueError):
        return 0.0
    rate = _get_fx_rates().get((currency or "BRL").upper(), 1.0)
    return value * rate


def build_spending_summary(history_rows):
    total_cost = 0.0
    by_type = {}

    for row in history_rows:
        cost_brl = _normalize_cost_to_brl(row.get("cost"), row.get("currency"))
        if cost_brl <= 0:
            continue

        total_cost += cost_brl
        label = row.get("maintenance_label") or "Manutencao geral"
        by_type[label] = by_type.get(label, 0.0) + cost_brl

    gastos_por_tipo = [
        {"tipo": label, "valor": round(amount, 2)}
        for label, amount in sorted(by_type.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "total_gastos": round(total_cost, 2),
        "quantidade_registros": len(history_rows),
        "gastos_por_tipo": gastos_por_tipo,
        "moeda": "BRL",
    }


def normalize_chat_text(value):
    normalized = unicodedata.normalize("NFD", (value or "").lower())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def is_generic_chat_message(message):
    normalized = normalize_chat_text(message)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return bool(tokens) and len(tokens) <= 5 and all(token in GENERIC_CHAT_TOKENS for token in tokens)


def get_optional_user_id():
    try:
        verify_jwt_in_request(optional=True)
        return get_jwt_identity()
    except Exception as exc:
        logger.info("Sessao opcional ignorada no chat publico: %s", exc)
        return None


def normalize_guest_id(raw_guest_id):
    guest_id = (raw_guest_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{16,128}", guest_id):
        return guest_id
    return None


def hash_guest_id(guest_id):
    return hashlib.sha256(guest_id.encode("utf-8")).hexdigest()


def ensure_guest_chat_usage_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guest_chat_usage (
            guest_id_hash CHAR(64) PRIMARY KEY,
            message_count INT NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    """)


def reserve_guest_message(cursor, guest_id):
    ensure_guest_chat_usage_table(cursor)
    guest_id_hash = hash_guest_id(guest_id)
    cursor.execute(
        "SELECT message_count FROM guest_chat_usage WHERE guest_id_hash = %s",
        (guest_id_hash,)
    )
    row = cursor.fetchone()
    current_count = int((row or {}).get("message_count") or 0)
    if current_count >= GUEST_CHAT_LIMIT:
        return None

    cursor.execute(
        """
        INSERT INTO guest_chat_usage (guest_id_hash, message_count)
        VALUES (%s, 1)
        ON DUPLICATE KEY UPDATE message_count = message_count + 1
        """,
        (guest_id_hash,)
    )
    return max(0, GUEST_CHAT_LIMIT - current_count - 1)


def parse_json_list(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def parse_history_limit(raw_limit):
    try:
        limit = int(raw_limit or DEFAULT_CHAT_HISTORY_LIMIT)
    except (TypeError, ValueError):
        return DEFAULT_CHAT_HISTORY_LIMIT
    return max(1, min(limit, MAX_CHAT_HISTORY_LIMIT))


def parse_after_id(raw_after_id):
    try:
        after_id = int(raw_after_id or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, after_id)


def decode_attachment_data(data_url):
    if not isinstance(data_url, str) or "," not in data_url:
        raise ValueError("Arquivo anexado inválido.")

    header, encoded = data_url.split(",", 1)
    mime_type = ""
    if header.startswith("data:"):
        mime_type = header[5:].split(";", 1)[0].strip().lower()

    try:
        return mime_type, base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("Não foi possível ler o arquivo anexado.") from exc


def infer_attachment_mime_type(filename, provided_type, data_url_type):
    guessed_type = mimetypes.guess_type(filename or "")[0]
    mime_type = (provided_type or data_url_type or guessed_type or "").strip().lower()
    if mime_type == "text/x-markdown":
        return "text/markdown"
    if mime_type in ("application/x-json", "text/json"):
        return "application/json"
    return mime_type


def is_supported_attachment_type(mime_type):
    return (
        mime_type in IMAGE_ATTACHMENT_TYPES
        or mime_type in BINARY_ATTACHMENT_TYPES
        or mime_type in TEXT_ATTACHMENT_TYPES
    )


def parse_chat_attachment(data):
    raw_attachment = data.get("attachment")
    if raw_attachment is None and isinstance(data.get("attachments"), list) and data["attachments"]:
        raw_attachment = data["attachments"][0]
    if not isinstance(raw_attachment, dict):
        return None

    raw_filename = (raw_attachment.get("name") or "anexo").replace("\\", "/").strip()
    if not raw_filename:
        raise ValueError("Nome do arquivo vazio.")
    filename = os.path.basename(raw_filename)[:MAX_FILENAME_LENGTH] or "anexo"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Validacao de extensao
    if ext and ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValueError(f"Extensao .{ext} nao permitida. Use: {', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))}")

    # Protecao contra path traversal
    if ".." in raw_filename or raw_filename.startswith("/") or raw_filename.startswith("\\"):
        raise ValueError("Nome de arquivo invalido.")

    data_url_type, file_data = decode_attachment_data(raw_attachment.get("data") or "")
    mime_type = infer_attachment_mime_type(filename, raw_attachment.get("type"), data_url_type)

    # Validacao MIME contra extensao (um MIME pode ter varias extensoes validas)
    mime_to_exts = {
        "image/jpeg": {"jpg", "jpeg"},
        "image/png": {"png"},
        "image/webp": {"webp"},
        "image/gif": {"gif"},
        "application/pdf": {"pdf"},
        "text/plain": {"txt"},
        "text/csv": {"csv"},
        "text/markdown": {"md", "markdown"},
        "application/json": {"json"},
    }
    expected_exts = mime_to_exts.get(mime_type)
    if expected_exts and ext and ext not in expected_exts:
        logger.warning(f"MIME mismatch: {mime_type} vs extensao .{ext}")

    if len(file_data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"O arquivo anexado deve ter no maximo {MAX_ATTACHMENT_BYTES // (1024*1024)} MB.")
    if len(file_data) == 0:
        raise ValueError("O arquivo anexado esta vazio.")
    if not is_supported_attachment_type(mime_type):
        raise ValueError("Formato nao suportado. Envie imagem PNG/JPG/WebP/GIF, PDF, TXT, CSV, Markdown ou JSON.")

    # Validacao extra para imagens (dimensoes)
    if mime_type in IMAGE_ATTACHMENT_TYPES:
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(file_data))
            if img.width > MAX_IMAGE_DIMENSIONS[0] or img.height > MAX_IMAGE_DIMENSIONS[1]:
                raise ValueError(f"Dimensoes da imagem excedem o limite de {MAX_IMAGE_DIMENSIONS[0]}x{MAX_IMAGE_DIMENSIONS[1]}px.")
            img.verify()
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"Falha ao validar imagem: {e}")

    kind = "text" if mime_type in TEXT_ATTACHMENT_TYPES else "binary"
    if mime_type in IMAGE_ATTACHMENT_TYPES:
        kind = "image"

    return {
        "name": filename,
        "mime_type": mime_type,
        "size": len(file_data),
        "data": file_data,
        "kind": kind,
    }


def attachment_metadata(attachment):
    if not attachment:
        return []
    return [{
        "name": attachment["name"],
        "type": attachment["mime_type"],
        "size": attachment["size"],
    }]


def build_text_attachment_message(message, attachment):
    text = attachment["data"].decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("O arquivo de texto anexado está vazio.")

    clipped_text = text[:TEXT_ATTACHMENT_LIMIT]
    omitted_notice = "\n\n[Conteúdo cortado para análise.]" if len(text) > TEXT_ATTACHMENT_LIMIT else ""
    question = (message or "").strip() or "Analise o arquivo anexado e destaque os pontos automotivos relevantes."
    return (
        f"{question}\n\n"
        f"Arquivo anexado: {attachment['name']} ({attachment['mime_type']}).\n"
        f"Conteúdo do arquivo:\n{clipped_text}{omitted_notice}"
    )


def normalize_client_history(raw_history):
    if not isinstance(raw_history, list):
        return []

    history = []
    for item in raw_history[-8:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role not in ("user", "model") or not content:
            continue

        history.append({"role": role, "content": content[:4000]})

    return history


def build_recommendations(message, historico_recente, default_topic="Consultoria Geral"):
    if not (message or "").strip():
        return [], [], default_topic
    if is_generic_chat_message(message):
        return [], [], default_topic

    _MECH_KEYWORDS = ["mecanic", "oficina", "borracheiro", "funileiro",
                      "reparo", "consertar", "arrumar", "trocar oleo",
                      "alinhamento", "balanceamento", "revisao"]
    if any(kw in message.lower() for kw in _MECH_KEYWORDS):
        return [], [], "Busca de Mecânicos"

    from services.nogai import gerar_termos_busca
    from services.youtube_service import buscar_videos_youtube

    termos = gerar_termos_busca(message, historico=historico_recente)
    termo_yt = termos.get("youtube")
    termo_loja = termos.get("loja")
    termo_pecas = termos.get("pecas")

    videos = []
    links = []

    if termo_yt:
        try:
            videos = buscar_videos_youtube(termo_yt)
        except Exception as e:
            logger.warning(f"Erro ao buscar videos: {e}")

    if termo_loja:
        try:
            scraper = WebScraper()
            lojas = scraper.search_car_stores(termo_loja)
            for loja in lojas:
                loja.setdefault("tipo", "veiculo")
                loja.setdefault("icon", "fas fa-car")
            links.extend(lojas)
        except Exception as e:
            logger.warning(f"Erro ao buscar links de loja: {e}")

    if termo_pecas:
        try:
            scraper = WebScraper()
            pecas = scraper.search_car_parts(termo_pecas)
            for peca in pecas:
                peca.setdefault("tipo", "peca")
                peca.setdefault("icon", "fas fa-tools")
            links.extend(pecas)
        except Exception as e:
            logger.warning(f"Erro ao buscar links de peças: {e}")

    topic = termo_yt or termo_loja or termo_pecas or default_topic
    return videos, links, topic


def generate_assistant_payload(
    message,
    user_id,
    user,
    historico_recente,
    image_b64=None,
    attachment=None,
    default_topic="Consultoria Geral",
    reference_images=None,
):
    prompt_message = message
    if attachment and attachment["kind"] == "text":
        prompt_message = build_text_attachment_message(message, attachment)

    if attachment and attachment["kind"] in ("image", "binary"):
        from services.attachment_ai import analisar_arquivo
        resposta = analisar_arquivo(
            attachment["data"],
            attachment["mime_type"],
            attachment["name"],
            message,
        )
        videos, links, topic = [], [], default_topic
        return resposta, videos, links, topic

    if image_b64:
        from services.vision_ai import analisar_imagem
        resposta = analisar_imagem(image_b64, message, reference_images=reference_images)
        videos, links, topic = [], [], default_topic
        return resposta, videos, links, topic

    from services.nogai import gerar_resposta
    resposta = gerar_resposta(
        prompt_message,
        user_id,
        user_data=user,
        historico=historico_recente,
    )
    videos, links, topic = build_recommendations(message, historico_recente, default_topic)

    return resposta, videos, links, topic or default_topic


def get_vehicle_reference_images(cursor, user_id, vehicle_id):
    """Fotos de referência do veículo para diagnóstico visual assistido (memória visual)."""
    try:
        vid = int(vehicle_id)
    except (TypeError, ValueError):
        return []
    if vid <= 0:
        return []
    try:
        cursor.execute(
            "SELECT foto_base64 FROM veiculos WHERE id=%s AND user_id=%s",
            (vid, user_id),
        )
        row = cursor.fetchone()
    except Exception as exc:
        logger.warning("Falha ao buscar foto de referência do veículo: %s", exc)
        return []
    if not row:
        return []
    foto = row.get("foto_base64")
    if foto and str(foto).strip():
        return [foto]
    return []


def seed_vehicle_photo_if_missing(cursor, conn, user_id, vehicle_id, image_b64):
    """Se o veículo ainda não tem foto, usa a imagem do diagnóstico como baseline de memória."""
    try:
        vid = int(vehicle_id)
    except (TypeError, ValueError):
        return
    if vid <= 0 or not image_b64:
        return
    try:
        cursor.execute(
            "UPDATE veiculos SET foto_base64=%s WHERE id=%s AND user_id=%s AND foto_base64 IS NULL",
            (image_b64, vid, user_id),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Falha ao semear foto do veículo: %s", exc)


def resolve_recommendations(recommendations_future, default_topic):
    if recommendations_future is None:
        return [], [], default_topic

    try:
        return recommendations_future.result()
    except Exception as exc:
        logger.warning("Recomendações indisponíveis: %s", exc)
        return [], [], default_topic

def serialize_datetime_field(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def normalize_chat_session_id(raw_session_id):
    session_id = (raw_session_id or "").strip()
    if not session_id:
        return None
    return session_id[:50]


def parse_client_created_at(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = (value or "").strip()
        if not text:
            return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def serialize_chat_row(row):
    videos = parse_json_list(row.get("videos"))
    links = parse_json_list(row.get("links"))
    attachments = parse_json_list(row.get("attachments"))

    if is_generic_chat_message(row["mensagem_usuario"]):
        videos = []
        links = []

    return {
        "id": row["id"],
        "session_id": row.get("session_id") or "",
        "mensagem_usuario": row["mensagem_usuario"],
        "resposta_ia": row["resposta_ia"],
        "created_at": serialize_datetime_field(row["created_at"]),
        "videos": videos,
        "links": links,
        "topic": row.get("topic") or "",
        "attachments": attachments,
    }


def format_chat_date(value):
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def format_chat_money(value):
    if value is None:
        return "R$ 0,00"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "R$ 0,00"
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_vehicle_for_chat(vehicle):
    label = " ".join(
        str(vehicle.get(field) or "").strip()
        for field in ("tipo", "marca", "modelo")
        if str(vehicle.get(field) or "").strip()
    ) or f"Veiculo #{vehicle.get('id')}"
    details = []
    if vehicle.get("ano_fabricacao"):
        details.append(f"ano {vehicle.get('ano_fabricacao')}")
    if vehicle.get("quilometragem") is not None:
        details.append(f"{vehicle.get('quilometragem')} km")
    return f"{label} ({', '.join(details)})" if details else label


def build_user_chat_data_context(cursor, user_id, veiculos):
    lines = []
    if veiculos:
        lines.append("Dashboard - veiculos cadastrados: " + "; ".join(format_vehicle_for_chat(v) for v in veiculos[:5]))
    else:
        lines.append("Dashboard - nenhum veiculo cadastrado para este usuario.")

    cursor.execute(
        """
        SELECT COUNT(*) AS quantidade_registros,
               COALESCE(SUM(cost), 0) AS total_gastos,
               MAX(service_date) AS ultima_manutencao
        FROM maintenance_history
        WHERE user_id = %s
        """,
        (user_id,)
    )
    summary = cursor.fetchone() or {}
    lines.append(
        "Dashboard - anotacoes de manutencao: "
        f"{int(summary.get('quantidade_registros') or 0)} registro(s), "
        f"total gasto {format_chat_money(summary.get('total_gastos'))}, "
        f"ultima manutencao {format_chat_date(summary.get('ultima_manutencao'))}."
    )

    try:
        alerts = fetch_user_maintenance_alerts(cursor, user_id, only_actionable=True)[:4]
    except Exception as exc:
        logger.warning("Contexto de alertas indisponivel para o chat: %s", exc)
        alerts = []
    if alerts:
        lines.append(
            "Alertas ativos das anotacoes: "
            + " | ".join(f"{a.get('item')}: {a.get('msg')}" for a in alerts)
        )

    cursor.execute(
        """
        SELECT mh.description, mh.maintenance_label, mh.service_date, mh.service_km,
               mh.cost, v.marca AS vehicle_marca, v.modelo AS vehicle_modelo
        FROM maintenance_history mh
        LEFT JOIN veiculos v ON v.id = mh.vehicle_id
        WHERE mh.user_id = %s
        ORDER BY mh.service_date DESC, mh.created_at DESC
        LIMIT 5
        """,
        (user_id,)
    )
    notes = cursor.fetchall()
    if notes:
        note_parts = []
        for note in notes:
            vehicle_label = " ".join(
                str(note.get(field) or "").strip()
                for field in ("vehicle_marca", "vehicle_modelo")
                if str(note.get(field) or "").strip()
            )
            note_parts.append(
                f"{format_chat_date(note.get('service_date'))}: "
                f"{note.get('maintenance_label') or 'Manutencao'}"
                f"{f' em {vehicle_label}' if vehicle_label else ''}"
                f" - {note.get('description')}"
            )
        lines.append("Anotacoes recentes do usuario: " + " | ".join(note_parts))

    predictions = []
    for vehicle in veiculos[:3]:
        try:
            prediction = _predictor().predict_next(
                vehicle_id=vehicle["id"],
                maintenance_type="troca_oleo",
                kilometers_actual=vehicle.get("quilometragem"),
            )
        except Exception as exc:
            logger.warning("Predicao ML indisponivel para veiculo %s: %s", vehicle.get("id"), exc)
            prediction = None

        if prediction:
            predictions.append(
                f"{format_vehicle_for_chat(vehicle)}: proxima referencia em "
                f"{prediction.get('predicted_next_km')} km ou {prediction.get('predicted_next_date')} "
                f"(confianca {prediction.get('confidence')}, modelo {prediction.get('maintenance_type_used', 'treinado')})"
            )

    if predictions:
        lines.append("ML preditivo de manutencao: " + " | ".join(predictions))
    else:
        lines.append("ML preditivo de manutencao: sem previsao confiavel disponivel; nao invente prazos.")

    lines.append(
        "Regra de resposta: use estes dados como fonte quando forem relevantes; "
        "quando faltar dado cadastrado, diga isso claramente em vez de supor."
    )
    return "\n".join(lines)


def load_user_chat_context(cursor, user_id):
    user = get_user_by_id(cursor, user_id)
    if not user:
        return None

    cursor.execute(
        "SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s",
        (user_id,)
    )
    veiculos = cursor.fetchall()
    if veiculos:
        user["lista_veiculos"] = veiculos
    try:
        user["chat_context"] = build_user_chat_data_context(cursor, user_id, veiculos)
    except Exception as exc:
        logger.warning("Nao foi possivel montar contexto do usuario para o chat: %s", exc)
    return user


def select_recent_chat_history(cursor, user_id, message, client_history, ignore_global_history):
    if is_generic_chat_message(message):
        return []
    if ignore_global_history or not user_id:
        return client_history
    return get_mysql_history(user_id, limit=3, cursor=cursor)


def build_chat_response(chat_id, session_id, message, resposta, videos, links, topic, attachments):
    return {
        "id": chat_id,
        "session_id": session_id or "",
        "mensagem_usuario": message,
        "resposta_ia": resposta,
        "created_at": datetime.now().isoformat(),
        "videos": videos,
        "links": links,
        "topic": topic or "",
        "attachments": attachments,
    }

def fetch_user_maintenance_alerts(cursor, user_id, vehicle_id=None, only_actionable=False):
    vehicle_filter = ""
    vehicle_params = [user_id]
    history_params = [user_id]
    if vehicle_id is not None:
        vehicle_filter = " AND id = %s"
        vehicle_params.append(vehicle_id)
        history_params.append(vehicle_id)

    cursor.execute(
        f"SELECT id, quilometragem FROM veiculos WHERE user_id = %s{vehicle_filter}",
        tuple(vehicle_params)
    )
    vehicles = cursor.fetchall()
    vehicle_km_map = {item["id"]: item.get("quilometragem") for item in vehicles}

    cursor.execute(
        f"""
        SELECT *
        FROM maintenance_history
        WHERE user_id = %s {'AND vehicle_id = %s' if vehicle_id is not None else ''}
        ORDER BY service_date DESC, created_at DESC
        """,
        tuple(history_params)
    )
    history_rows = cursor.fetchall()
    (
        _,
        _,
        _,
        consolidate_active_maintenance_records,
        build_maintenance_alerts,
        _,
    ) = _load_maintenance_helpers()
    active_records = consolidate_active_maintenance_records(history_rows)
    alerts = build_maintenance_alerts(active_records, vehicle_km_map=vehicle_km_map)

    if only_actionable:
        alerts = [a for a in alerts if a.get("status_code") in ACTIONABLE_MAINTENANCE_STATUSES]
    return alerts

def filter_alerts_for_email(cursor, user_id, status_codes=None, transition_only=False):
    alerts = fetch_user_maintenance_alerts(
        cursor,
        user_id=user_id,
        only_actionable=True
    )
    if status_codes:
        allowed_statuses = set(status_codes)
        alerts = [a for a in alerts if a.get("status_code") in allowed_statuses]

    if not transition_only or not alerts:
        return alerts

    maintenance_ids = [
        int(alert["maintenance_id"])
        for alert in alerts
        if alert.get("maintenance_id") is not None
    ]
    if not maintenance_ids:
        return []

    placeholders = ", ".join(["%s"] * len(maintenance_ids))
    cursor.execute(
        f"""
        SELECT id, alert_last_status_code
        FROM maintenance_history
        WHERE user_id = %s AND id IN ({placeholders})
        """,
        tuple([user_id, *maintenance_ids])
    )
    previous_status = {
        int(row["id"]): row.get("alert_last_status_code")
        for row in (cursor.fetchall() or [])
    }
    return [
        alert for alert in alerts
        if previous_status.get(int(alert["maintenance_id"])) != alert.get("status_code")
    ]

def mark_maintenance_alerts_sent(cursor, user_id, alerts):
    for alert in alerts:
        maintenance_id = alert.get("maintenance_id")
        status_code = alert.get("status_code")
        if maintenance_id is None or not status_code:
            continue
        cursor.execute(
            """
            UPDATE maintenance_history
            SET alert_last_status_code = %s,
                alert_last_sent_at = NOW()
            WHERE id = %s AND user_id = %s
            """,
            (status_code, maintenance_id, user_id)
        )

def should_send_maintenance_email(user_row, force=False):
    if force:
        return True
    if not user_row.get("maintenance_email_enabled", True):
        return False

    last_sent = user_row.get("maintenance_email_last_sent")
    if not last_sent:
        return True

    if isinstance(last_sent, datetime):
        last_date = last_sent.date()
    elif isinstance(last_sent, str):
        try:
            last_date = datetime.fromisoformat(last_sent).date()
        except ValueError:
            return True
    else:
        return True
    return last_date < datetime.now().date()

def render_maintenance_email_html(user_name, alerts):
    safe_name = html.escape(user_name or "usuário")
    rows = []
    for alert in alerts:
        item = html.escape(str(alert.get("item") or "Manutenção"))
        msg = html.escape(str(alert.get("msg") or ""))
        status_code = alert.get("status_code")

        if status_code == "overdue":
            color = "#dc2626"  # Vermelho forte
            bg = "#fee2e2"
            status_text = "⚠️ ATENÇÃO"
        elif status_code == "due_soon":
            color = "#d97706"  # Laranja/Ambar
            bg = "#fef3c7"
            status_text = "📅 EM BREVE"
        else:
            color = "#059669"  # Verde
            bg = "#d1fae5"
            status_text = "✅ OK"

        rows.append(
            f"""
            <div style="margin-bottom: 15px; padding: 15px; border: 1px solid #e5e7eb; border-radius: 12px; background-color: #ffffff;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-weight: bold; font-size: 16px; color: #111827;">{item}</span>
                    <span style="padding: 4px 10px; border-radius: 6px; background-color: {bg}; color: {color}; font-size: 11px; font-weight: 800; text-transform: uppercase;">{status_text}</span>
                </div>
                <p style="margin: 0; font-size: 14px; color: #4b5563;">{msg}</p>
            </div>
            """
        )

    rows_html = "".join(rows) if rows else "<p>Nenhum alerta crítico identificado para seus veículos.</p>"

    return f"""
        <h2 style="margin-top: 0; color: #111827; font-size: 20px;">Olá, {safe_name}!</h2>
        <p style="color: #4b5563; font-size: 16px; margin-bottom: 25px;">
            Identificamos alguns itens de manutenção que precisam da sua atenção para garantir a segurança e o bom funcionamento do seu veículo.
        </p>

        <div style="margin-top: 20px;">
            {rows_html}
        </div>

        <div style="margin-top: 30px; padding: 20px; background-color: #f0f9ff; border-radius: 12px; border: 1px solid #bae6fd;">
            <p style="margin: 0; font-size: 14px; color: #0369a1;">
                <strong>Dica AutoAssist:</strong> Manter a manutenção em dia economiza até 30% em reparos futuros e valoriza seu veículo na hora da revenda.
            </p>
        </div>

        <div style="text-align: center; margin-top: 35px;">
            <a href="{html.escape(get_dashboard_url())}" style="display: inline-block; padding: 14px 28px; background-color: #2563eb; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">Ver Painel Completo</a>
            <p style="margin: 18px 0 0; font-size: 15px; color: #374151;">Quer saber o que fazer e quanto vai custar?</p>
            <a href="chat.html" style="display: inline-block; padding: 14px 28px; background-color: #059669; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">Pergunte à NOG o que fazer</a>
        </div>
    """

def send_maintenance_alert_email_for_user(
    cursor,
    user_row,
    force=False,
    status_codes=None,
    transition_only=False,
):
    if not user_row.get("email"):
        return {"sent": False, "reason": "missing_email", "alerts_count": 0}
    if not user_row.get("maintenance_email_enabled", True) and not force:
        return {"sent": False, "reason": "disabled", "alerts_count": 0}
    if not transition_only and not should_send_maintenance_email(user_row, force=force):
        return {"sent": False, "reason": "already_sent_today", "alerts_count": 0}

    # Se chamado de uma thread sem cursor, abre nova conexão
    if cursor is None:
        with get_db() as (new_cursor, conn):
            return _send_maintenance_alert_logic(
                new_cursor,
                user_row,
                force,
                status_codes=status_codes,
                transition_only=transition_only,
            )
    else:
        return _send_maintenance_alert_logic(
            cursor,
            user_row,
            force,
            status_codes=status_codes,
            transition_only=transition_only,
        )

def _send_maintenance_alert_logic(
    cursor,
    user_row,
    force,
    status_codes=None,
    transition_only=False,
):
    alerts = filter_alerts_for_email(
        cursor,
        user_id=user_row["id"],
        status_codes=status_codes,
        transition_only=transition_only,
    )
    if not alerts:
        reason = "no_new_critical_alerts" if status_codes == CRITICAL_MAINTENANCE_STATUSES else "no_actionable_alerts"
        return {"sent": False, "reason": reason, "alerts_count": 0}

    subject = f"AutoAssist: {len(alerts)} alerta(s) de manutencao para revisar"
    html_body = render_maintenance_email_html(user_row.get("nome"), alerts)
    sent_ok = enviar_email(user_row["email"], subject, html_body)

    # Cria notificação in-app + push para cada alerta
    user_id = user_row["id"]
    for alert in alerts[:5]:
        try:
            create_notification(
                user_id=user_id,
                title=alert.get("item", "Alerta de manutenção"),
                body=alert.get("msg", ""),
                type="warning",
                action_url="/dashboard.html",
            )
        except Exception:
            pass

    # Envia push notification com resumo dos alertas
    if alerts:
        try:
            send_push_notification(
                user_id=user_id,
                title=f"🔧 {len(alerts)} alerta(s) de manutenção",
                body=alerts[0].get("msg", ""),
                data={"url": "/dashboard.html"},
            )
        except Exception:
            logger.warning("Falha ao enviar push notification", exc_info=True)

    if not sent_ok:
        return {"sent": False, "reason": "send_failed", "alerts_count": len(alerts)}

    mark_maintenance_alerts_sent(cursor, user_id, alerts)
    cursor.execute(
        "UPDATE users SET maintenance_email_last_sent = NOW() WHERE id = %s",
        (user_id,)
    )
    return {"sent": True, "reason": "sent", "alerts_count": len(alerts)}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def run_maintenance_email_dispatch(
    *,
    force: bool = False,
    transition_only: bool = True,
    include_due_soon: bool = False,
    limit: int | None = None,
) -> dict:
    status_codes = (
        ACTIONABLE_MAINTENANCE_STATUSES
        if include_due_soon
        else CRITICAL_MAINTENANCE_STATUSES
    )
    scan_limit = limit if limit is not None else int(os.getenv("MAINTENANCE_EMAIL_DISPATCH_LIMIT", "500"))
    scan_limit = max(1, min(int(scan_limit), 2000))
    summary = {
        "processed": 0,
        "sent": 0,
        "no_new_critical_alerts": 0,
        "no_actionable_alerts": 0,
        "already_sent_today": 0,
        "failed": 0,
        "lock_busy": 0,
    }

    with get_db() as (cursor, conn):
        cursor.execute("SELECT GET_LOCK(%s, 0) AS got_lock", (MAINTENANCE_DISPATCH_LOCK_NAME,))
        lock_row = cursor.fetchone() or {}
        got_lock = int(lock_row.get("got_lock") or 0)
        if got_lock != 1:
            summary["lock_busy"] = 1
            return {
                "success": True,
                "force": force,
                "transition_only": transition_only,
                "include_due_soon": include_due_soon,
                "status_codes": list(status_codes),
                "resumo": summary,
            }

        try:
            cursor.execute(
                """
                SELECT id, nome, email, maintenance_email_enabled, maintenance_email_last_sent
                FROM users
                WHERE email IS NOT NULL
                  AND email <> ''
                  AND maintenance_email_enabled = TRUE
                ORDER BY id ASC
                LIMIT %s
                """,
                (scan_limit,),
            )
            users = cursor.fetchall() or []
            for user in users:
                summary["processed"] += 1
                result = send_maintenance_alert_email_for_user(
                    cursor,
                    user,
                    force=force,
                    status_codes=status_codes,
                    transition_only=transition_only,
                )
                if result["sent"]:
                    summary["sent"] += 1
                elif result["reason"] == "no_new_critical_alerts":
                    summary["no_new_critical_alerts"] += 1
                elif result["reason"] == "no_actionable_alerts":
                    summary["no_actionable_alerts"] += 1
                elif result["reason"] == "already_sent_today":
                    summary["already_sent_today"] += 1
                else:
                    summary["failed"] += 1
        finally:
            cursor.execute("SELECT RELEASE_LOCK(%s)", (MAINTENANCE_DISPATCH_LOCK_NAME,))

    return {
        "success": True,
        "force": force,
        "transition_only": transition_only,
        "include_due_soon": include_due_soon,
        "status_codes": list(status_codes),
        "resumo": summary,
    }


def _enqueue_alert_email(user_row):
    try:
        from redis import Redis
        from rq import Queue
        redis_url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI", "redis://localhost:6379/0")
        if redis_url != "memory://":
            q = Queue("default", connection=Redis.from_url(redis_url))
            q.enqueue("tasks.send_maintenance_alert_email", user_row, False, CRITICAL_MAINTENANCE_STATUSES, True)
        else:
            import threading
            threading.Thread(
                target=send_maintenance_alert_email_for_user,
                args=(None, user_row),
                kwargs={"force": False, "status_codes": CRITICAL_MAINTENANCE_STATUSES, "transition_only": True},
                daemon=True,
            ).start()
    except Exception:
        import threading
        threading.Thread(
            target=send_maintenance_alert_email_for_user,
            args=(None, user_row),
            kwargs={"force": False, "status_codes": CRITICAL_MAINTENANCE_STATUSES, "transition_only": True},
            daemon=True,
        ).start()

def _dispatch_maintenance_emails_background() -> None:
    try:
        result = run_maintenance_email_dispatch(
            force=False,
            transition_only=True,
            include_due_soon=_env_bool("MAINTENANCE_EMAIL_INCLUDE_DUE_SOON", False),
        )
        logger.info("Dispatch interno de manutencao finalizado: %s", result.get("resumo"))
    except Exception as exc:
        logger.warning("Erro no dispatch interno de manutencao: %s", exc)


@pages_bp.before_app_request
def maybe_dispatch_maintenance_emails_from_backend():
    if not _env_bool("MAINTENANCE_EMAIL_AUTODISPATCH_ENABLED", True):
        return None
    if request.path.startswith("/static/") or request.path.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico", ".woff", ".woff2")):
        return None

    interval = max(60, int(os.getenv("MAINTENANCE_EMAIL_AUTODISPATCH_INTERVAL_SECONDS", "1800")))
    now = monotonic()

    global _maintenance_dispatch_last_started_at
    with _maintenance_dispatch_thread_lock:
        if now - _maintenance_dispatch_last_started_at < interval:
            return None
        _maintenance_dispatch_last_started_at = now

    try:
        from redis import Redis
        from rq import Queue
        redis_url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI", "redis://localhost:6379/0")
        if redis_url != "memory://":
            q = Queue("default", connection=Redis.from_url(redis_url))
            q.enqueue("tasks.dispatch_maintenance_emails")
        else:
            import threading
            threading.Thread(target=_dispatch_maintenance_emails_background, daemon=True).start()
    except Exception:
        import threading
        threading.Thread(target=_dispatch_maintenance_emails_background, daemon=True).start()
    return None


@pages_bp.route("/api/user", methods=["GET"])
@jwt_required()
def get_user():
    user_id = get_jwt_identity()
    with get_db() as (cursor, conn):
        cursor.execute("""
            SELECT id, nome, email, is_premium, created_at, possui_veiculo,
                   veiculo_marca, veiculo_modelo, veiculo_ano_fabricacao,
                   veiculo_ano_compra, veiculo_tipo, veiculo_quilometragem, is_two_factor_enabled,
                   maintenance_email_enabled, maintenance_email_last_sent, uf
            FROM users WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()
        if not user:
            return invalid_session_response()
        user["maintenance_email_last_sent"] = serialize_datetime_field(user.get("maintenance_email_last_sent"))

        cursor.execute("SELECT COUNT(DISTINCT session_id) AS total FROM chats WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()

        cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem, fipe_valor, fipe_mes_referencia FROM veiculos WHERE user_id = %s", (user_id,))
        veiculos = cursor.fetchall()

        for v in veiculos:
            if isinstance(v.get("fipe_valor"), Decimal):
                v["fipe_valor"] = float(v["fipe_valor"])

        return jsonify({
            **user,
            "trial_expired": is_trial_expired(user),
            "trial_days_remaining": get_trial_days_remaining(user),
            "is_premium": bool(user.get("is_premium")),
            "possui_veiculo": len(veiculos) > 0,
            "veiculos": veiculos,
            "total_consultas": int(total["total"])
        }), 200

@pages_bp.route("/api/user", methods=["PUT"])
@jwt_required()
def update_user():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    nome = (data.get("nome") or "").strip()
    email = (data.get("email") or "").strip().lower()

    if not nome or not email:
        return jsonify(error="Dados inválidos"), 400

    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT id FROM users WHERE email = %s AND id <> %s", (email, user_id))
            if cursor.fetchone():
                return jsonify(error="Email já está em uso"), 409

            cursor.execute("""
                UPDATE users SET
                    nome = %s, email = %s
                WHERE id = %s
            """, (nome, email, user_id))
            conn.commit()

            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                return invalid_session_response()

            cursor.execute("SELECT COUNT(DISTINCT session_id) AS total FROM chats WHERE user_id = %s", (user_id,))
            total = cursor.fetchone()

            return jsonify({
                **user,
                "trial_expired": is_trial_expired(user),
                "trial_days_remaining": get_trial_days_remaining(user),
                "is_premium": bool(user.get("is_premium")),
                "total_consultas": int(total["total"]),
                "success": True
            }), 200
    except Exception as e:
        logger.error(f"❌ Erro ao atualizar perfil: {e}")
        return jsonify(error="Erro ao atualizar perfil"), 500

@pages_bp.route("/api/user/location", methods=["POST"])
@jwt_required()
def update_user_location():
    """Salva a localização (UF) do usuário para notificações regionais de eventos.

    Recebe {lat, lng} (geolocalização do navegador) - a UF é inferida por
    reverse geocoding (Nominatim) e cacheadas por ~1km. Também aceita {uf}
    diretamente e {uf: ""} para limpar a localização.
    """
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    uf = (data.get("uf") or "").strip().upper()

    if not uf and data.get("lat") is not None and data.get("lng") is not None:
        try:
            from utils.geocode import reverse_geocode_uf
            uf = reverse_geocode_uf(data["lat"], data["lng"]) or ""
        except Exception as e:
            logger.warning("Falha ao inferir UF pela localização: %s", e)
            uf = ""

    if uf and (len(uf) != 2 or not uf.isalpha()):
        return jsonify(error="UF inválida"), 400

    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "UPDATE users SET uf = %s WHERE id = %s",
                (uf or None, user_id),
            )
            conn.commit()
        return jsonify(success=True, uf=uf or None), 200
    except Exception as e:
        logger.error(f"❌ Erro ao salvar localização do usuário: {e}")
        return jsonify(error="Erro ao salvar localização"), 500

import re
import json
from datetime import datetime


_MOD_FIPE_PCT = {
    # Pesos CONSERVADORES de valor RETIDO em revenda para itens documentados,
    # baseados no comportamento tipico do mercado brasileiro: a maioria dos
    # mods NAO repassa o custo (audio/estetica raramente agregam; performance
    # pode ajudar comprador entusiasta mas penaliza o comprador geral). Sao
    # estimativas de mercado, NAO refletem a Tabela FIPE (que e de fabrica).
    # Calibrar conforme dados reais de transacao.
    "motor": 0.04, "turbo": 0.05, "suspensao": 0.02, "freios": 0.02,
    "rodas": 0.015, "pneus": 0.01, "escapamento": 0.015, "eletronica": 0.02,
    "som": 0.005, "estetica": 0.005, "interna": 0.01, "outros": 0.01,
}
# Teto de valorizacao total para evitar inflacao irrealista do valor.
_MOD_FIPE_PCT_MAX = 0.12

# Aviso exibido junto ao valor estimado: deixa claro que NAO e avaliacao oficial.
FIPE_AJUSTADA_DISCLAIMER = (
    "Valor estimado de mercado com base na Tabela FIPE e/ou precos de anuncios "
    "reais, ajustado por itens documentados. Nao e avaliacao oficial e nao "
    "substitui pericia para venda, seguro ou financiamento."
)


def _parse_fipe_valor(valor):
    """Extrai valor numerico (float) de uma string FIPE ('R$ 45.000,00')."""
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    nums = re.findall(r"\d+[\.,]?\d*", str(valor).replace(".", "").replace(",", "."))
    for n in nums:
        try:
            return float(n)
        except ValueError:
            continue
    return 0.0


def _calcular_detalhe(base_valor, modificacoes, mercado=None):
    """Calcula o valor estimado de mercado de forma transparente e fundamentada.

    - A base e a Tabela FIPE (referencia oficial de mercado) OU a mediana de
      anuncios reais quando disponivel e coerente (ratio 0.4x-2.5x da FIPE).
    - O ajuste por modificacoes e uma estimativa conservadora e exposta
      (cada categoria contribui com seu peso, ate o teto).

    Retorna dict com valor, base usada, fonte, pct, extra e o detalhe por mod.
    """
    fipe_base = _parse_fipe_valor(base_valor)
    base = fipe_base
    fonte = "Tabela FIPE (referencia oficial de mercado)"
    if mercado and isinstance(mercado, (int, float)) and mercado > 0:
        if fipe_base > 0:
            ratio = mercado / fipe_base
            if 0.4 <= ratio <= 2.5:
                base = float(mercado)
                fonte = "Preco medio de anuncios reais (Mercado Livre)"
        else:
            base = float(mercado)
            fonte = "Preco medio de anuncios reais (Mercado Livre)"

    pct_total = 0.0
    extra_abs = 0.0
    detalhe = []
    for m in (modificacoes or []):
        cat = (m.get("categoria") or "outros").lower()
        p = _MOD_FIPE_PCT.get(cat, _MOD_FIPE_PCT["outros"])
        pct_total += p
        contrib_abs = 0.0
        v = m.get("valor")
        if v:
            try:
                contrib_abs = float(v)
                extra_abs += contrib_abs
            except (TypeError, ValueError):
                pass
        detalhe.append({"categoria": cat, "pct": p, "valor_informado": contrib_abs})

    pct_total = min(pct_total, _MOD_FIPE_PCT_MAX)
    ajustado = base * (1 + pct_total) + extra_abs
    valor_str = "R$ {:,.2f}".format(ajustado).replace(",", "X").replace(".", ",").replace("X", ".")
    return {
        "valor": valor_str,
        "base": base,
        "base_fonte": fonte,
        "pct": round(pct_total, 4),
        "extra_abs": round(extra_abs, 2),
        "detalhe": detalhe,
    }


def calcular_fipe_ajustada(base_valor, modificacoes, mercado=None):
    """Calcula o valor estimado de mercado por modificacoes (Mod Passport).

    Mantem a assinatura (valor_str, pct, extra) para retrocompatibilidade.
    'mercado' opcional = mediana de anuncios reais para fundamentar a base.
    """
    d = _calcular_detalhe(base_valor, modificacoes, mercado=mercado)
    return (d["valor"], d["pct"], d["extra_abs"])


def _salvar_mod_passport_version(cursor, veiculo_id, user_id, modificacoes, fipe_valor, fipe_ajustada):
    """Persiste um snapshot do Mod Passport para dar continuidade/historico (lock-in de dados)."""
    try:
        cursor.execute(
            """INSERT INTO mod_passport_versions
               (veiculo_id, user_id, snapshot, fipe_valor, fipe_ajustada, valor_estimado, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
            (veiculo_id, user_id, json.dumps(modificacoes or [], ensure_ascii=False),
             fipe_valor, fipe_ajustada, fipe_ajustada),
        )
    except Exception as e:
        logger.warning("Falha ao versionar Mod Passport: %s", e)


def _l1(value):
    return str(value).encode("latin-1", "ignore").decode("latin-1")


def _build_modpassport_pdf(veiculo, snapshot, valor_estimado):
    """PDF do Mod Passport (ficha tecnica viva do veiculo)."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(59, 130, 246)
    pdf.cell(0, 10, _l1("AutoAssist IA - Mod Passport"), 0, 1, "C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, _l1("Veiculo:"), 0, 1)
    pdf.set_font("Arial", "", 11)
    nome = "{} {} ({})".format(
        veiculo.get("marca") or "", veiculo.get("modelo") or "", veiculo.get("ano_fabricacao") or ""
    )
    pdf.cell(0, 7, _l1(nome), 0, 1)
    pdf.cell(0, 7, _l1("Valor FIPE: {}".format(veiculo.get("fipe_valor") or "n/a")), 0, 1)
    pdf.cell(0, 7, _l1("Valor estimado (c/ mods): {}".format(valor_estimado or "n/a")), 0, 1)
    pdf.ln(3)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, _l1("Modificacoes registradas:"), 0, 1)
    pdf.set_font("Arial", "", 10)
    mods = snapshot or []
    if not mods:
        pdf.cell(0, 6, _l1("(nenhuma)"), 0, 1)
    for m in mods:
        cat = m.get("categoria") or "outros"
        desc = m.get("descricao") or m.get("desc") or ""
        val = m.get("valor")
        linha = "- {}".format(cat)
        if desc:
            linha += ": {}".format(desc)
        if val:
            linha += " (R$ {})".format(val)
        pdf.multi_cell(0, 6, _l1(linha))
    pdf.ln(8)
    pdf.set_font("Arial", "I", 9)
    pdf.set_text_color(200, 50, 50)
    pdf.multi_cell(0, 5, _l1("AVISO: Mod Passport e uma estimativa gerada por IA. Nao substitui vistoria ou avaliacao profissional."))
    return pdf.output(dest="S").encode("latin-1")


def _require_mod_passport(cursor, user_id):
    """Exige premium ativo para o recurso Mod Passport."""
    cursor.execute("SELECT is_premium, premium_expires_at FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    if not row or not row.get("is_premium"):
        return False, (jsonify(error="Recurso exclusivo Premium."), 403)
    expira = row.get("premium_expires_at")
    if expira is not None:
        try:
            if isinstance(expira, str):
                expira = datetime.fromisoformat(expira.replace("Z", "+00:00"))
            if expira < datetime.now():
                return False, (jsonify(error="Premium expirado. Renove para usar o Mod Passport."), 403)
        except Exception:
            pass
    return True, None


@pages_bp.route("/api/veiculos", methods=["POST"])
@jwt_required()
def add_veiculo():
    user_id = get_jwt_identity()
    data = request.get_json()
    try:
        with get_db() as (cursor, conn):
            ano_fab = data.get("ano_fabricacao")
            ano_compra = data.get("ano_compra")
            ano_fab = int(ano_fab) if ano_fab else None
            ano_compra = int(ano_compra) if ano_compra else None

            cursor.execute("""
                INSERT INTO veiculos (user_id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, data.get("tipo"), data.get("marca"), data.get("modelo"), ano_fab, ano_compra, data.get("quilometragem")))
            v_id = cursor.lastrowid
            cursor.execute("UPDATE users SET possui_veiculo = TRUE WHERE id = %s", (user_id,))

            # Popula o valor FIPE na criacao (assincrono via RQ, com fallback sincrono).
            # Garante que o Patrimonio e o card de FIPE tenham base numerica.
            try:
                from routes.dashboard import _refresh_fipe
                _refresh_fipe(v_id, data.get("tipo"), data.get("marca"),
                             data.get("modelo"), ano_fab)
            except Exception as fipe_err:
                logger.warning(f"Falha ao agendar refresh FIPE na criacao: {fipe_err}")

            # Gatilho imediato de e-mail se houver algo crítico
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    send_maintenance_alert_email_for_user(
                        cursor,
                        user_row,
                        force=False,
                        status_codes=CRITICAL_MAINTENANCE_STATUSES,
                        transition_only=True,
                    )
            except Exception as email_err:
                logger.warning(f"Falha no gatilho imediato de email: {email_err}")

            _invalidate_dashboard_cache_for_user(user_id)
            try:
                from routes.notifications import create_notification
                from routes.push import send_push_notification
                create_notification(
                    user_id,
                    "Veiculo adicionado!",
                    "Crie o Mod Passport para acompanhar o valor estimado e o historico do seu carro pela IA.",
                    type="ativo",
                    action_url="dashboard.html",
                )
                send_push_notification(
                    user_id,
                    "Bem-vindo ao AutoAssist!",
                    "Toque para criar o Mod Passport do seu veiculo.",
                    data={"url": "dashboard.html"},
                )
            except Exception as act_err:
                logger.warning("Falha na notificacao de ativacao: %s", act_err)
            return jsonify(success=True, id=v_id), 201
    except Exception as e:
        logger.error(f"Erro ao adicionar veiculo: {e}")
        return jsonify(error="Erro interno ao adicionar veículo"), 500

@pages_bp.route("/api/veiculos", methods=["GET"])
@jwt_required()
def list_veiculos():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """
                SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem,
                       fipe_valor, fipe_mes_referencia, modificacoes, fipe_ajustada, foto_base64
                FROM veiculos
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,)
            )
            veiculos = cursor.fetchall()
            for v in veiculos:
                if isinstance(v.get("fipe_valor"), Decimal):
                    v["fipe_valor"] = float(v["fipe_valor"])
                if v.get("fipe_ajustada") is not None and isinstance(v.get("fipe_ajustada"), Decimal):
                    v["fipe_ajustada"] = float(v["fipe_ajustada"])
                # Fundamenta o valor estimado com precos de mercado reais (best-effort).
                mods = v.get("modificacoes")
                if isinstance(mods, str):
                    try:
                        mods = json.loads(mods)
                    except (ValueError, TypeError):
                        mods = []
                if v.get("fipe_valor") or mods:
                    mercado = None
                    if mods:
                        try:
                            from services import web_scraping as _ws
                            mkt = _ws.get_market_price_estimate(
                                v.get("marca"), v.get("modelo"), v.get("ano_fabricacao")
                            )
                            if mkt:
                                mercado = mkt[0]
                        except Exception as mkt_err:
                            logger.debug("enriquecimento de mercado falhou: %s", mkt_err)
                    det = _calcular_detalhe(v.get("fipe_valor"), mods, mercado=mercado)
                    v["fipe_ajustada"] = det["valor"]
                    v["fipe_ajustada_fonte"] = det["base_fonte"]
                    v["fipe_ajustada_metodo"] = det["detalhe"]
                    v["fipe_ajustada_aviso"] = (
                        FIPE_AJUSTADA_DISCLAIMER if (mods or mercado) else None
                    )
            return jsonify(veiculos=veiculos), 200
    except Exception as e:
        logger.error(f"Erro ao listar veiculos: {e}")
        return jsonify(error="Erro ao listar veiculos"), 500

@pages_bp.route("/api/veiculos/<int:v_id>/foto", methods=["POST"])
@jwt_required()
def upload_veiculo_foto(v_id):
    """Salva (ou remove) a foto do veículo. Recebe base64 em ``foto``.

    Enviar ``foto`` vazio/nulo limpa a foto atual.
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    foto = data.get("foto")
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT id FROM veiculos WHERE id = %s AND user_id = %s", (v_id, user_id))
            if not cursor.fetchone():
                return jsonify(error="Veículo não encontrado"), 404

            if not foto:
                cursor.execute("UPDATE veiculos SET foto_base64 = NULL WHERE id = %s AND user_id = %s", (v_id, user_id))
                conn.commit()
                return jsonify(success=True, foto_base64=None), 200

            if isinstance(foto, str) and foto.startswith("data:"):
                header, _, b64 = foto.partition(",")
                if "base64" not in header:
                    return jsonify(error="Formato de imagem inválido"), 400
                foto = b64

            try:
                amostra = base64.b64decode(foto[:64])
            except Exception:
                return jsonify(error="Imagem inválida"), 400
            if not (amostra[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\x89PNG", b"\x47IF8") or amostra[:3] == b"GIF"):
                return jsonify(error="Apenas imagens PNG/JPG/GIF são suportadas"), 400

            cursor.execute("UPDATE veiculos SET foto_base64 = %s WHERE id = %s AND user_id = %s", (foto, v_id, user_id))
            conn.commit()
            return jsonify(success=True, foto_base64=foto), 200
    except Exception as e:
        logger.error(f"Erro ao salvar foto do veiculo: {e}")
        return jsonify(error="Erro ao salvar foto do veículo"), 500

@pages_bp.route("/api/veiculos/<int:v_id>", methods=["PUT"])
@jwt_required()
def edit_veiculo(v_id):
    user_id = get_jwt_identity()
    data = request.get_json()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT id FROM veiculos WHERE id = %s AND user_id = %s", (v_id, user_id))
            if not cursor.fetchone():
                return jsonify(error="Veículo não encontrado"), 404

            ano_fab = data.get("ano_fabricacao")
            ano_compra = data.get("ano_compra")
            ano_fab = int(ano_fab) if ano_fab else None
            ano_compra = int(ano_compra) if ano_compra else None

            cursor.execute("""
                UPDATE veiculos
                SET tipo = %s, marca = %s, modelo = %s, ano_fabricacao = %s, ano_compra = %s, quilometragem = %s
                WHERE id = %s AND user_id = %s
            """, (data.get("tipo"), data.get("marca"), data.get("modelo"), ano_fab, ano_compra, data.get("quilometragem"), v_id, user_id))

            # Gatilho imediato de e-mail em segundo plano (Não trava o usuário)
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    _enqueue_alert_email(user_row)
            except Exception as email_err:
                logger.warning(f"Erro ao iniciar thread de email: {email_err}")

            _invalidate_dashboard_cache_for_user(user_id)
            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao editar veiculo: {e}")
        return jsonify(error="Erro interno ao editar veículo"), 500

@pages_bp.route("/api/veiculos/<int:v_id>", methods=["DELETE"])
@jwt_required()
def delete_veiculo(v_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("DELETE FROM veiculos WHERE id = %s AND user_id = %s", (v_id, user_id))
            if cursor.rowcount == 0:
                return jsonify(error="Veículo não encontrado"), 404

            cursor.execute("SELECT COUNT(*) as count FROM veiculos WHERE user_id = %s", (user_id,))
            if cursor.fetchone()["count"] == 0:
                cursor.execute("UPDATE users SET possui_veiculo = FALSE WHERE id = %s", (user_id,))

            _invalidate_dashboard_cache_for_user(user_id)
            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir veiculo: {e}")
        return jsonify(error="Erro interno"), 500


@pages_bp.route("/api/veiculos/<int:v_id>/modificacoes", methods=["POST"])
@jwt_required()
def set_veiculo_modificacoes(v_id):
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    modificacoes = data.get("modificacoes")
    if not isinstance(modificacoes, list):
        return jsonify(error="modificacoes deve ser uma lista."), 400
    try:
        with get_db() as (cursor, conn):
            ok, err = _require_mod_passport(cursor, user_id)
            if not ok:
                return err
            cursor.execute(
                "SELECT id, fipe_valor FROM veiculos WHERE id = %s AND user_id = %s",
                (v_id, user_id),
            )
            veh = cursor.fetchone()
            if not veh:
                return jsonify(error="Veiculo nao encontrado"), 404
            valor_ajustado, pct, extra = calcular_fipe_ajustada(veh.get("fipe_valor"), modificacoes)
            cursor.execute(
                "UPDATE veiculos SET modificacoes = %s, fipe_ajustada = %s WHERE id = %s AND user_id = %s",
                (json.dumps(modificacoes, ensure_ascii=False), valor_ajustado, v_id, user_id),
            )
            _salvar_mod_passport_version(cursor, v_id, user_id, modificacoes, veh.get("fipe_valor"), valor_ajustado)
            _invalidate_dashboard_cache_for_user(user_id)
            return jsonify(
                success=True,
                fipe_base=float(veh.get("fipe_valor")) if isinstance(veh.get("fipe_valor"), Decimal) else veh.get("fipe_valor"),
                fipe_ajustada=valor_ajustado,
                pct_ajuste=pct,
                valor_extra=extra,
                aviso=FIPE_AJUSTADA_DISCLAIMER,
            ), 200
    except Exception as e:
        logger.error("Erro ao salvar modificacoes: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@pages_bp.route("/api/veiculos/<int:v_id>/modificacoes/history", methods=["GET"])
@jwt_required()
def mod_passport_history(v_id):
    """Historico versionado do Mod Passport (evolutivo = lock-in de dados)."""
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            ok, err = _require_mod_passport(cursor, user_id)
            if not ok:
                return err
            cursor.execute("SELECT id FROM veiculos WHERE id = %s AND user_id = %s", (v_id, user_id))
            if not cursor.fetchone():
                return jsonify(error="Veiculo nao encontrado"), 404
            cursor.execute(
                "SELECT id, created_at, fipe_valor, fipe_ajustada, valor_estimado, snapshot "
                "FROM mod_passport_versions WHERE veiculo_id = %s AND user_id = %s "
                "ORDER BY created_at DESC LIMIT 50",
                (v_id, user_id),
            )
            rows = cursor.fetchall()
        out = []
        for r in rows:
            snap = r.get("snapshot")
            if isinstance(snap, str):
                try:
                    snap = json.loads(snap)
                except (ValueError, TypeError):
                    snap = []
            out.append({
                "id": r["id"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "fipe_valor": r.get("fipe_valor"),
                "fipe_ajustada": r.get("fipe_ajustada"),
                "valor_estimado": r.get("valor_estimado"),
                "qtd_modificacoes": len(snap) if isinstance(snap, list) else 0,
            })
        return jsonify(history=out), 200
    except Exception as e:
        logger.error("Erro historico mod passport: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@pages_bp.route("/api/veiculos/<int:v_id>/mod-passport/share", methods=["POST"])
@jwt_required()
def share_mod_passport(v_id):
    """Gera um link publico (token) do Mod Passport para compartilhar/exportar."""
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            ok, err = _require_mod_passport(cursor, user_id)
            if not ok:
                return err
            cursor.execute(
                "SELECT id, marca, modelo, ano_fabricacao, fipe_valor, fipe_ajustada, modificacoes "
                "FROM veiculos WHERE id = %s AND user_id = %s",
                (v_id, user_id),
            )
            veh = cursor.fetchone()
            if not veh:
                return jsonify(error="Veiculo nao encontrado"), 404
            mods = veh.get("modificacoes")
            if isinstance(mods, str):
                try:
                    mods = json.loads(mods)
                except (ValueError, TypeError):
                    mods = []
            token = uuid.uuid4().hex
            cursor.execute(
                """INSERT INTO mod_passport_versions
                   (veiculo_id, user_id, snapshot, fipe_valor, fipe_ajustada, valor_estimado, share_token, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())""",
                (v_id, user_id, json.dumps(mods or [], ensure_ascii=False), veh.get("fipe_valor"),
                 veh.get("fipe_ajustada"), veh.get("fipe_ajustada"), token),
            )
            try:
                conn.commit()
            except Exception:
                pass
            _invalidate_dashboard_cache_for_user(user_id)
        base = request.host_url.rstrip("/")
        url = "{}/api/public/mod-passport/{}".format(base, token)
        return jsonify(success=True, share_token=token, share_url=url), 200
    except Exception as e:
        logger.error("Erro compartilhar mod passport: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@pages_bp.route("/api/public/mod-passport/<token>", methods=["GET"])
def public_mod_passport(token):
    """Acesso publico, somente leitura, do Mod Passport compartilhado."""
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """SELECT v.marca, v.modelo, v.ano_fabricacao, v.foto_base64,
                          m.snapshot, m.fipe_valor, m.fipe_ajustada, m.valor_estimado, m.created_at
                   FROM mod_passport_versions m
                   JOIN veiculos v ON v.id = m.veiculo_id
                   WHERE m.share_token = %s LIMIT 1""",
                (token,),
            )
            row = cursor.fetchone()
        if not row:
            return jsonify(error="Mod Passport nao encontrado ou expirou."), 404
        snap = row.get("snapshot")
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except (ValueError, TypeError):
                snap = []
        return jsonify({
            "veiculo": {
                "marca": row.get("marca"),
                "modelo": row.get("modelo"),
                "ano_fabricacao": row.get("ano_fabricacao"),
                "foto_base64": row.get("foto_base64"),
            },
            "fipe_valor": row.get("fipe_valor"),
            "valor_estimado": row.get("valor_estimado") or row.get("fipe_ajustada"),
            "modificacoes": snap or [],
            "criado_em": row["created_at"].isoformat() if row.get("created_at") else None,
            "aviso": "Estimativa gerada por IA. Nao substitui vistoria.",
        }), 200
    except Exception as e:
        logger.error("Erro public mod passport: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@pages_bp.route("/api/public/mod-passport/<token>/pdf", methods=["GET"])
def public_mod_passport_pdf(token):
    """Exporta o Mod Passport compartilhado em PDF."""
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """SELECT v.marca, v.modelo, v.ano_fabricacao, v.fipe_valor,
                          m.snapshot, m.fipe_ajustada, m.valor_estimado
                   FROM mod_passport_versions m
                   JOIN veiculos v ON v.id = m.veiculo_id
                   WHERE m.share_token = %s LIMIT 1""",
                (token,),
            )
            row = cursor.fetchone()
        if not row:
            return jsonify(error="Mod Passport nao encontrado ou expirou."), 404
        snap = row.get("snapshot")
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except (ValueError, TypeError):
                snap = []
        veiculo = {
            "marca": row.get("marca"),
            "modelo": row.get("modelo"),
            "ano_fabricacao": row.get("ano_fabricacao"),
            "fipe_valor": row.get("fipe_valor"),
        }
        pdf_bytes = _build_modpassport_pdf(veiculo, snap, row.get("valor_estimado") or row.get("fipe_ajustada"))
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="mod_passport.pdf",
        )
    except Exception as e:
        logger.error("Erro pdf mod passport: %s", e, exc_info=True)
        return jsonify(error="Erro interno."), 500


@pages_bp.route("/api/onboarding/revisao", methods=["POST"])
@jwt_required(optional=True)
def onboarding_sugestao_revisao():
    data = request.get_json(silent=True) or {}
    marca = (data.get("marca") or "").strip()
    modelo = (data.get("modelo") or "").strip()
    ano = data.get("ano_fabricacao")
    km = data.get("quilometragem")
    if not marca or not modelo:
        return jsonify(error="Informe marca e modelo."), 400
    try:
        sugestao = _sugerir_revisao(marca, modelo, ano, km)
        return jsonify(sugestao=sugestao), 200
    except Exception as e:
        logger.error("Erro na sugestao de revisao: %s", e, exc_info=True)
        return jsonify(sugestao=""), 200


_SUGESTAO_PADRAO = (
    "Revisao preventiva sugerida: troca de oleo e filtros, inspecao de freios e "
    "pneus, verificacao de fluidos e da bateria. Confirme em uma oficina de confianca."
)
_FORBIDDEN_PATTERNS = ("http://", "https://", "www.")
_REFUSAL_PATTERNS = ("nao posso", "i cannot", "desculpe, mas", "como ia", "não posso")


def _sanitizar_sugestao(texto):
    """Aplica guardrails ao texto gerado pela IA (seguranca e escopo)."""
    if not texto:
        return _SUGESTAO_PADRAO
    t = re.sub(r"\s+", " ", texto).strip()
    for pat in _FORBIDDEN_PATTERNS:
        t = t.replace(pat, "")
    # remove citacoes de precos (R$ 1.234,56)
    t = re.sub(r"R\$\s?[\d\.,]+", "", t)
    t = t.strip(" \"'")
    t = t[:600]
    if len(t) < 10 or any(p in t.lower() for p in _REFUSAL_PATTERNS):
        return _SUGESTAO_PADRAO
    return t


def _sugerir_revisao(marca, modelo, ano, km):
    """Gera (via modelo utilitario, com cache) um plano de revisao preventiva."""
    from services.nogai import _generate_content_with_fallback
    from services.groq_client import utility_model, utility_fallback_models
    from utils.cache import make_cache_key, cache_get_json, cache_set_json
    prompt = (
        "Voce e o NOG, consultor de manutencao automotiva da AutoAssist. "
        "REGRA: sugira APENAS itens de revisao preventiva comuns e seguros "
        "(ex.: troca de oleo, filtros, freios, pneus, fluidos, bateria). "
        "NAO faca diagnostico de avarias, NAO recomende procedimentos perigosos, "
        "NAO cite precos nem orcamentos, NAO inclua links, NAO aborde temas fora "
        "de automoveis. Responda somente em portugues, com 3 a 5 bullet points "
        "curtos e linguagem simples. Se faltarem dados, baseie-se no padrao geral."
        + chr(10) + chr(10) +
        "Veiculo: " + marca + " " + modelo + " " + str(ano or "") + " - " + str(km or "km nao informado") + " km"
    )
    cache_key = make_cache_key("onboarding:revisao", marca, modelo, str(ano), str(km))
    cached = cache_get_json(cache_key)
    if cached is not None:
        return cached
    obj = _generate_content_with_fallback(
        contents=prompt,
        primary_model=utility_model(),
        fallback_models=utility_fallback_models(),
        temperature=0.3,
        log_context="Onboarding revisao",
    )
    texto = _sanitizar_sugestao(obj.text or "")
    cache_set_json(cache_key, texto, ttl=86400)
    return texto

def _predict_interval(vehicle_id, maintenance_type, description, veiculo_str, service_km):
    """Estima o próximo intervalo de manutenção.

    Usa o preditor leve (predictive_maintenance) como fonte principal e recorre
    à IA Groq apenas quando o preditor não consegue gerar um intervalo útil.
    """
    interval_days = None
    interval_km = None
    justificativa = None
    enhanced = False

    try:
        pred = _predictor().predict_next(
            vehicle_id=vehicle_id,
            maintenance_type=maintenance_type or "troca_oleo",
            kilometers_actual=service_km,
        )
        if pred:
            pred_km = pred.get("predicted_next_km")
            cur_km = int(service_km or 0)
            km_diff = (pred_km - cur_km) if pred_km is not None else None
            pred_days = None
            try:
                pred_days = (date.fromisoformat(pred["predicted_next_date"]) - date.today()).days
            except Exception:
                pred_days = None

            if pred_days and pred_days > 0 and km_diff and km_diff > 0:
                interval_days = pred_days
                interval_km = km_diff
                enhanced = True
                justificativa = (
                    f"Previsao do modelo preditivo "
                    f"(confianca {round((pred.get('confidence') or 0) * 100)}%)."
                )
    except Exception as e:
        logger.warning("Predictor indisponivel para manutencao: %s", e)

    if interval_days is None and interval_km is None:
        ai = prever_intervalo_manutencao(description, veiculo_str)
        interval_days = ai.get("intervalo_dias")
        interval_km = ai.get("intervalo_km")
        justificativa = ai.get("justificativa")
        enhanced = True

    return {
        "intervalo_dias": interval_days,
        "intervalo_km": interval_km,
        "justificativa": justificativa,
        "ai_enhanced": enhanced,
    }


def _invalidate_maintenance_user_caches(user_id):
    """Limpa os caches afetados por uma mudança de manutenção do usuário."""
    try:
        from services.nogai import _invalidate_maintenance_context, _invalidate_user_ai_cache
        _invalidate_maintenance_context(user_id)
        _invalidate_user_ai_cache(user_id)
    except Exception:
        pass
    try:
        from routes.dashboard import _invalidate_dashboard_cache
        _invalidate_dashboard_cache(user_id)
    except Exception:
        pass


def _invalidate_dashboard_cache_for_user(user_id):
    """Limpa o cache de dashboard de um usuário (após mudar veículos)."""
    try:
        from routes.dashboard import _invalidate_dashboard_cache
        _invalidate_dashboard_cache(user_id)
    except Exception:
        pass


@pages_bp.route("/api/maintenance/history", methods=["POST"])
@jwt_required()
def register_maintenance_history():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    description = (data.get("descricao") or data.get("texto") or "").strip()
    currency = (data.get("moeda") or "BRL").upper()

    if not description:
        return jsonify(error="Descricao da manutencao e obrigatoria"), 400

    raw_vehicle_id = data.get("veiculo_id")
    vehicle_id = None
    fallback_vehicle_km = None

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_maintenance_access(user, cursor)
            if premium_error:
                return premium_error

            if raw_vehicle_id is not None:
                try:
                    vehicle_id = int(raw_vehicle_id)
                except (TypeError, ValueError):
                    return jsonify(error="veiculo_id invalido"), 400

                cursor.execute(
                    "SELECT id, quilometragem, marca, modelo FROM veiculos WHERE id = %s AND user_id = %s",
                    (vehicle_id, user_id)
                )
                vehicle = cursor.fetchone()
                if not vehicle:
                    return jsonify(error="Veiculo nao encontrado"), 404
                fallback_vehicle_km = vehicle.get("quilometragem")
            else:
                cursor.execute("SELECT id, quilometragem, marca, modelo FROM veiculos WHERE user_id = %s ORDER BY id ASC", (user_id,))
                vehicles = cursor.fetchall()
                if len(vehicles) == 1:
                    vehicle = vehicles[0]
                    vehicle_id = vehicle["id"]
                    fallback_vehicle_km = vehicle.get("quilometragem")
                else:
                    vehicle = None

            parsed = parse_maintenance_entry(description)

            if parsed.get("interval_days") is None and parsed.get("interval_km") is None:
                veiculo_str = f"{vehicle.get('marca', '')} {vehicle.get('modelo', '')}".strip() if vehicle else ""
                ai_previsao = _predict_interval(vehicle_id, parsed["maintenance_type"], description, veiculo_str, parsed.get("service_km"))

                if ai_previsao.get("intervalo_dias"):
                    parsed["interval_days"] = ai_previsao["intervalo_dias"]
                    parsed["next_due_date"] = parsed["service_date"] + timedelta(days=ai_previsao["intervalo_dias"])

                if ai_previsao.get("intervalo_km"):
                    parsed["interval_km"] = ai_previsao["intervalo_km"]
                    if parsed.get("service_km") is not None:
                        parsed["next_due_km"] = parsed["service_km"] + ai_previsao["intervalo_km"]

                parsed["parser_metadata"]["ai_enhanced"] = ai_previsao.get("ai_enhanced", False)
                parsed["parser_metadata"]["ai_justificativa"] = ai_previsao.get("justificativa")

            parsed = apply_manual_overrides(parsed, data, fallback_service_km=fallback_vehicle_km)
            parser_metadata = dict(parsed.get("parser_metadata") or {})
            parser_metadata["auto_linked_vehicle"] = raw_vehicle_id is None and vehicle_id is not None

            cursor.execute(
                """
                INSERT INTO maintenance_history (
                    user_id, vehicle_id, description, maintenance_type, maintenance_label,
                    service_date, service_km, cost, currency, interval_days, interval_km,
                    next_due_date, next_due_km, parser_metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    vehicle_id,
                    parsed["description"],
                    parsed["maintenance_type"],
                    parsed["maintenance_label"],
                    parsed["service_date"],
                    parsed["service_km"],
                    parsed["cost"],
                    currency,
                    parsed["interval_days"],
                    parsed["interval_km"],
                    parsed["next_due_date"],
                    parsed["next_due_km"],
                    json.dumps(parser_metadata, ensure_ascii=False),
                )
            )
            maintenance_id = cursor.lastrowid
            # Gatilho imediato de e-mail + notificação in-app + push (só "Atencao")
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    _enqueue_alert_email(user_row)
                    days_remaining = (parsed["next_due_date"] - date.today()).days if parsed.get("next_due_date") else None
                    current_km = parsed.get("service_km") or fallback_vehicle_km
                    km_remaining = (parsed["next_due_km"] - current_km) if (parsed.get("next_due_km") is not None and current_km is not None) else None
                    status_label, status_code = _status_from_remaining(days_remaining, km_remaining)
                    if status_code == "overdue":
                        create_notification(
                            user_id=user_id,
                            title="Anotação salva",
                            body=f"{parsed.get('maintenance_label', 'Registro')} registrado com sucesso.",
                            type="warning",
                            action_url="/maintenance_history.html",
                        )
                        send_push_notification(
                            user_id=user_id,
                            title="⚠️ Anotação em Atenção",
                            body=f"{parsed.get('maintenance_label', 'Registro')} vencida.",
                            data={"url": "/maintenance_history.html"},
                        )
            except Exception as email_err:
                logger.warning(f"Erro ao iniciar thread de email: {email_err}")

            cursor.execute(
                """
                SELECT mh.*, v.marca AS vehicle_marca, v.modelo AS vehicle_modelo
                FROM maintenance_history mh
                LEFT JOIN veiculos v ON v.id = mh.vehicle_id
                WHERE mh.id = %s AND mh.user_id = %s
                """,
                (maintenance_id, user_id)
            )
            created_row = cursor.fetchone()

            _invalidate_maintenance_user_caches(user_id)
            return jsonify(
                success=True,
                registro=serialize_maintenance_row(created_row),
                observacao=None if vehicle_id is not None else "Registro salvo sem vinculo de veiculo."
            ), 201
    except Exception as e:
        logger.error(f"Erro ao registrar historico de manutencao: {e}")
        return jsonify(error="Erro interno ao registrar manutencao"), 500

@pages_bp.route("/api/maintenance/history", methods=["GET"])
@jwt_required()
def list_maintenance_history():
    user_id = get_jwt_identity()
    vehicle_id = request.args.get("veiculo_id")

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            # P1-1: listagem de manutenções é liberada para free e premium.
            if not user:
                return invalid_session_response()

            params = [user_id]
            vehicle_filter = ""
            if vehicle_id is not None:
                try:
                    vehicle_id = int(vehicle_id)
                except (TypeError, ValueError):
                    return jsonify(error="veiculo_id invalido"), 400
                vehicle_filter = " AND mh.vehicle_id = %s"
                params.append(vehicle_id)

            try:
                limit = max(1, min(int(request.args.get("limit", 50)), 200))
                offset = max(0, int(request.args.get("offset", 0)))
            except (TypeError, ValueError):
                return jsonify(error="limit/offset invalidos"), 400

            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM maintenance_history mh
                WHERE mh.user_id = %s {vehicle_filter}
                """,
                tuple(params)
            )
            total = cursor.fetchone().get("total") or 0

            cursor.execute(
                f"""
                SELECT mh.*, v.marca AS vehicle_marca, v.modelo AS vehicle_modelo
                FROM maintenance_history mh
                LEFT JOIN veiculos v ON v.id = mh.vehicle_id
                WHERE mh.user_id = %s {vehicle_filter}
                ORDER BY mh.service_date DESC, mh.created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [limit, offset])
            )
            history_rows = cursor.fetchall()
            serialized = [serialize_maintenance_row(row) for row in history_rows]

            return jsonify(
                historico=serialized,
                total=total,
                limit=limit,
                offset=offset,
                resumo=build_spending_summary(serialized)
            ), 200
    except Exception as e:
        logger.error(f"Erro ao listar historico de manutencao: {e}")
        return jsonify(error="Erro ao carregar historico de manutencao"), 500

@pages_bp.route("/api/maintenance/history/<int:maintenance_id>", methods=["PUT"])
@jwt_required()
def update_maintenance_history(maintenance_id):
    user_id = get_jwt_identity()
    data = request.get_json() or {}

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("SELECT * FROM maintenance_history WHERE id = %s AND user_id = %s", (maintenance_id, user_id))
            existing = cursor.fetchone()
            if not existing:
                return jsonify(error="Registro de manutencao nao encontrado"), 404

            current_description = (existing.get("description") or "").strip()
            new_description = (data.get("descricao") or data.get("texto") or current_description).strip()

            raw_vehicle = data.get("veiculo_id", "__UNCHANGED__")
            vehicle_id = existing.get("vehicle_id")
            fallback_vehicle_km = None

            if raw_vehicle != "__UNCHANGED__":
                if raw_vehicle in ("", None):
                    vehicle_id = None
                else:
                    try:
                        vehicle_id = int(raw_vehicle)
                    except (TypeError, ValueError):
                        return jsonify(error="veiculo_id invalido"), 400

            if vehicle_id is not None:
                cursor.execute("SELECT id, quilometragem, marca, modelo FROM veiculos WHERE id = %s AND user_id = %s", (vehicle_id, user_id))
                vehicle = cursor.fetchone()
                if not vehicle:
                    return jsonify(error="Veiculo nao encontrado"), 404
                fallback_vehicle_km = vehicle.get("quilometragem")
            else:
                vehicle = None

            parsed = parse_maintenance_entry(new_description)
            if parsed.get("interval_days") is None and parsed.get("interval_km") is None:
                description_unchanged = (new_description == current_description)
                can_reuse = existing.get("interval_days") is not None or existing.get("interval_km") is not None

                if description_unchanged and can_reuse:
                    # Reaproveita os intervalos anteriores sem re-chamar a IA
                    parsed["interval_days"] = existing.get("interval_days")
                    parsed["interval_km"] = existing.get("interval_km")
                    if existing.get("next_due_date"):
                        parsed["next_due_date"] = existing.get("next_due_date")
                    elif existing.get("interval_days") and parsed.get("service_date"):
                        parsed["next_due_date"] = parsed["service_date"] + timedelta(days=existing["interval_days"])
                    if parsed.get("service_km") is not None and existing.get("interval_km") is not None:
                        parsed["next_due_km"] = parsed["service_km"] + existing["interval_km"]
                    parsed.setdefault("parser_metadata", {})["reused_intervals"] = True
                else:
                    veiculo_str = f"{vehicle.get('marca', '')} {vehicle.get('modelo', '')}".strip() if vehicle else ""
                    ai_previsao = _predict_interval(vehicle_id, parsed["maintenance_type"], new_description, veiculo_str, parsed.get("service_km"))
                    if ai_previsao.get("intervalo_dias"):
                        parsed["interval_days"] = ai_previsao["intervalo_dias"]
                        parsed["next_due_date"] = parsed["service_date"] + timedelta(days=ai_previsao["intervalo_dias"])
                    if ai_previsao.get("intervalo_km"):
                        parsed["interval_km"] = ai_previsao["intervalo_km"]
                        if parsed.get("service_km") is not None:
                            parsed["next_due_km"] = parsed["service_km"] + ai_previsao["intervalo_km"]
                    parsed["parser_metadata"]["ai_enhanced"] = ai_previsao.get("ai_enhanced", False)
                    parsed["parser_metadata"]["ai_justificativa"] = ai_previsao.get("justificativa")

            parsed = apply_manual_overrides(parsed, data, fallback_service_km=fallback_vehicle_km)
            parser_metadata = dict(parsed.get("parser_metadata") or {})
            parser_metadata["updated_from_record_id"] = maintenance_id
            currency = (data.get("moeda") or existing.get("currency") or "BRL").upper()

            cursor.execute("""
                UPDATE maintenance_history
                SET vehicle_id = %s, description = %s, maintenance_type = %s, maintenance_label = %s,
                    service_date = %s, service_km = %s, cost = %s, currency = %s, interval_days = %s,
                    interval_km = %s, next_due_date = %s, next_due_km = %s, parser_metadata = %s,
                    alert_last_status_code = NULL, alert_last_sent_at = NULL
                WHERE id = %s AND user_id = %s
            """, (vehicle_id, parsed["description"], parsed["maintenance_type"], parsed["maintenance_label"],
                  parsed["service_date"], parsed["service_km"], parsed["cost"], currency, parsed["interval_days"],
                  parsed["interval_km"], parsed["next_due_date"], parsed["next_due_km"],
                  json.dumps(parser_metadata, ensure_ascii=False), maintenance_id, user_id))

            # Gatilho imediato de e-mail em segundo plano + notificação + push (só "Atencao")
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    _enqueue_alert_email(user_row)
                    days_remaining = (parsed["next_due_date"] - date.today()).days if parsed.get("next_due_date") else None
                    current_km = parsed.get("service_km") or fallback_vehicle_km
                    km_remaining = (parsed["next_due_km"] - current_km) if (parsed.get("next_due_km") is not None and current_km is not None) else None
                    status_label, status_code = _status_from_remaining(days_remaining, km_remaining)
                    if status_code == "overdue":
                        create_notification(
                            user_id=user_id,
                            title="Manutenção atualizada",
                            body=f"{parsed.get('maintenance_label', 'Registro')} atualizado e vencido.",
                            type="warning",
                            action_url="/dashboard.html",
                        )
                        send_push_notification(
                            user_id=user_id,
                            title="⚠️ Manutenção em Atenção",
                            body=f"{parsed.get('maintenance_label', 'Registro')} vencida.",
                            data={"url": "/maintenance_history.html"},
                        )
            except Exception as email_err:
                logger.warning(f"Erro ao iniciar thread de email: {email_err}")

            cursor.execute("""
                SELECT mh.*, v.marca AS vehicle_marca, v.modelo AS vehicle_modelo
                FROM maintenance_history mh
                LEFT JOIN veiculos v ON v.id = mh.vehicle_id
                WHERE mh.id = %s AND mh.user_id = %s
            """, (maintenance_id, user_id))
            updated_row = cursor.fetchone()
            _invalidate_maintenance_user_caches(user_id)
            return jsonify(success=True, registro=serialize_maintenance_row(updated_row)), 200
    except Exception as e:
        logger.error(f"Erro ao atualizar historico de manutencao: {e}")
        return jsonify(error="Erro ao atualizar manutencao"), 500

@pages_bp.route("/api/maintenance/history/<int:maintenance_id>", methods=["DELETE"])
@jwt_required()
def delete_maintenance_history(maintenance_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("DELETE FROM maintenance_history WHERE id = %s AND user_id = %s", (maintenance_id, user_id))
            if cursor.rowcount == 0:
                return jsonify(error="Registro de manutencao nao encontrado"), 404
            _invalidate_maintenance_user_caches(user_id)
            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir historico de manutencao: {e}")
        return jsonify(error="Erro ao excluir manutencao"), 500

@pages_bp.route("/api/maintenance/alerts", methods=["GET"])
@jwt_required()
def get_maintenance_alerts():
    user_id = get_jwt_identity()
    vehicle_id = request.args.get("veiculo_id")
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            alerts = fetch_user_maintenance_alerts(cursor, user_id, vehicle_id=vehicle_id)
            return jsonify(alertas=alerts), 200
    except Exception as e:
        logger.error(f"Erro ao buscar alertas de manutencao: {e}")
        return jsonify(error="Erro ao buscar alertas"), 500

@pages_bp.route("/api/maintenance/email-settings", methods=["GET"])
@jwt_required()
def get_email_settings():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("SELECT maintenance_email_enabled FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                return invalid_session_response()
            return jsonify(enabled=bool(user["maintenance_email_enabled"])), 200
    except Exception as e:
        logger.error(f"Erro ao buscar configuracao de email: {e}")
        return jsonify(error="Erro ao buscar configuracao de email"), 500

@pages_bp.route("/api/maintenance/email-settings", methods=["PUT"])
@jwt_required()
def update_email_settings():
    user_id = get_jwt_identity()
    data = request.get_json()
    enabled = bool(data.get("enabled", True))
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("UPDATE users SET maintenance_email_enabled = %s WHERE id = %s", (enabled, user_id))
            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao atualizar configuracao de email: {e}")
        return jsonify(error="Erro ao atualizar configuracao de email"), 500

@pages_bp.route("/api/maintenance/email/send-now", methods=["POST"])
@jwt_required()
def send_maintenance_email_now():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("SELECT id, nome, email, maintenance_email_enabled, maintenance_email_last_sent FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                return invalid_session_response()
            result = send_maintenance_alert_email_for_user(cursor, user, force=True)
            return jsonify(success=result["sent"], reason=result["reason"], alerts_count=result["alerts_count"]), (200 if result["sent"] else 202)
    except Exception as e:
        logger.error(f"Erro no envio manual de email de manutencao: {e}")
        return jsonify(error="Erro ao enviar email de manutencao"), 500

@pages_bp.route("/api/user", methods=["DELETE"])
@jwt_required()
def delete_user():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir conta: {e}")
        return jsonify(error="Erro ao excluir conta"), 500

@pages_bp.route("/api/chat/history", methods=["GET"])
@jwt_required()
def get_chat_history():
    user_id = get_jwt_identity()
    after_id = parse_after_id(request.args.get("after_id"))
    limit = parse_history_limit(request.args.get("limit"))
    raw_session = request.args.get("session_id")
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            order_direction = "ASC" if after_id else "DESC"
            after_filter = "AND id > %s" if after_id else ""
            session_clause = ""
            session_params: list = []
            if raw_session is not None:
                if raw_session.strip().lower() == "null":
                    session_clause = "AND session_id IS NULL"
                else:
                    candidate = normalize_chat_session_id(raw_session)
                    if candidate is not None:
                        session_clause = "AND session_id = %s"
                        session_params.append(candidate)
            params = [user_id, *session_params]
            if after_id:
                params.append(after_id)
            params.append(limit)

            cursor.execute(
                f"""
                SELECT id, session_id, mensagem_usuario, resposta_ia, created_at, videos, links, topic, attachments
                FROM chats
                WHERE user_id = %s
                {session_clause}
                {after_filter}
                ORDER BY id {order_direction}
                LIMIT %s
                """,
                tuple(params)
            )
            rows = cursor.fetchall()
            if not after_id:
                rows = list(reversed(rows))

            chats = [serialize_chat_row(row) for row in rows]
            latest_id = max((chat["id"] for chat in chats), default=after_id)
            return jsonify(chats=chats, latest_id=latest_id), 200
    except Exception as e:
        logger.error(f"Erro no historico: {e}")
        return jsonify(error="Erro interno"), 500


@pages_bp.route("/api/chat/conversations", methods=["GET"])
@jwt_required()
def list_chat_conversations():
    user_id = get_jwt_identity()
    q = (request.args.get("q") or "").strip()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            cursor.execute(
                """
                SELECT id, session_id, mensagem_usuario, resposta_ia, topic, created_at
                FROM chats
                WHERE user_id = %s
                ORDER BY id DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()

        groups = {}
        order = []
        needle = q.lower()
        for row in rows:
            sid = row.get("session_id")
            key = sid if sid else "__null__"
            if key not in groups:
                groups[key] = {
                    "session_id": sid,
                    "topic": (row.get("topic") or "").strip(),
                    "preview": (row.get("mensagem_usuario") or "").strip(),
                    "updated_at": row.get("created_at"),
                    "count": 0,
                    "matches": False,
                }
                order.append(key)
            groups[key]["count"] += 1
            if needle:
                hay = " ".join([
                    row.get("mensagem_usuario") or "",
                    row.get("resposta_ia") or "",
                    row.get("topic") or "",
                ]).lower()
                if needle in hay:
                    groups[key]["matches"] = True

        conversations = []
        for key in order:
            g = groups[key]
            if needle and not g["matches"]:
                continue
            title = g["topic"] or g["preview"] or "Nova conversa"
            if key == "__null__" and not g["topic"]:
                title = "Consultoria geral"
            updated = g["updated_at"]
            conversations.append({
                "session_id": g["session_id"],
                "title": title[:80],
                "preview": g["preview"][:140],
                "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
                "count": g["count"],
            })
        return jsonify(conversations=conversations), 200
    except Exception as e:
        logger.error(f"Erro ao listar conversas: {e}")
        return jsonify(error="Erro interno"), 500


@pages_bp.route("/api/chat/history/<int:chat_id>", methods=["DELETE"])
@jwt_required()
def delete_chat_history(chat_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            cursor.execute("DELETE FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
            if cursor.rowcount == 0:
                return jsonify(error="Chat nao encontrado"), 404

        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir chat: {e}")
        return jsonify(error="Erro ao excluir chat"), 500


@pages_bp.route("/api/chat/session/<session_id>", methods=["DELETE"])
@jwt_required()
def delete_chat_session(session_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            if session_id == "null":
                cursor.execute("DELETE FROM chats WHERE session_id IS NULL AND user_id = %s", (user_id,))
            else:
                cursor.execute("DELETE FROM chats WHERE session_id = %s AND user_id = %s", (session_id, user_id))

        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir sessao: {e}")
        return jsonify(error="Erro ao excluir sessao"), 500

@pages_bp.route("/api/chat/sync_guest", methods=["POST"])
@jwt_required()
def sync_guest_chat():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    chats = data.get("chats") or []
    
    if not chats:
        return jsonify(success=True), 200

    try:
        synced_count = 0
        with get_db() as (cursor, conn):
            for chat in chats:
                if not isinstance(chat, dict):
                    continue

                session_id = normalize_chat_session_id(chat.get("session_id"))
                mensagem_usuario = (chat.get("mensagem_usuario") or "").strip()
                resposta_ia = (chat.get("resposta_ia") or "").strip()
                if not mensagem_usuario and not resposta_ia:
                    continue

                created_at = parse_client_created_at(chat.get("created_at"))
                videos = parse_json_list(chat.get("videos"))
                links = parse_json_list(chat.get("links"))
                topic = (chat.get("topic") or "").strip()[:255]
                attachments = parse_json_list(chat.get("attachments"))

                if session_id:
                    cursor.execute(
                        """
                        SELECT id FROM chats
                        WHERE user_id = %s AND session_id = %s
                          AND mensagem_usuario = %s AND resposta_ia = %s
                        LIMIT 1
                        """,
                        (user_id, session_id, mensagem_usuario, resposta_ia)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id FROM chats
                        WHERE user_id = %s AND session_id IS NULL
                          AND mensagem_usuario = %s AND resposta_ia = %s
                        LIMIT 1
                        """,
                        (user_id, mensagem_usuario, resposta_ia)
                    )
                if cursor.fetchone():
                    continue

                cursor.execute(
                    """
                    INSERT INTO chats (user_id, session_id, mensagem_usuario, resposta_ia, created_at, videos, links, topic, attachments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        session_id,
                        mensagem_usuario,
                        resposta_ia,
                        created_at,
                        json.dumps(videos),
                        json.dumps(links),
                        topic,
                        json.dumps(attachments),
                    )
                )
                synced_count += 1
        return jsonify(success=True, synced=synced_count), 200
    except Exception as e:
        logger.error(f"Erro ao sincronizar chat de visitante: {e}")
        return jsonify(error="Erro interno ao sincronizar chat"), 500

@pages_bp.route("/api/videos", methods=["GET"])
@jwt_required()
def get_videos():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("SELECT * FROM videos WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
            rows = cursor.fetchall()
            return jsonify(videos=rows), 200
    except Exception as e:
        logger.error(f"Erro ao buscar videos: {e}")
        return jsonify(error="Erro interno"), 500

@pages_bp.route("/api/videos", methods=["POST"])
@jwt_required()
def add_video():
    user_id = get_jwt_identity()
    data = request.get_json()
    titulo = data.get("titulo")
    url = data.get("url")
    descricao = data.get("descricao", "")

    if not titulo or not url:
        return jsonify(error="Título e URL são obrigatórios"), 400

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute(
                "INSERT INTO videos (user_id, titulo, url, descricao) VALUES (%s, %s, %s, %s)",
                (user_id, titulo, url, descricao)
            )
            conn.commit()
        return jsonify(success=True), 201
    except Exception as e:
        logger.error(f"Erro ao adicionar video: {e}")
        return jsonify(error="Erro interno"), 500

@pages_bp.route("/api/videos/<int:video_id>", methods=["DELETE"])
@jwt_required()
def delete_video(video_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("DELETE FROM videos WHERE id = %s AND user_id = %s", (video_id, user_id))
            conn.commit()
        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir video: {e}")
        return jsonify(error="Erro interno"), 500

@pages_bp.route("/api/videos/library", methods=["GET"])
@jwt_required()
def get_video_library():
    """Consolida todos os vídeos e links recebidos no chat agrupados por tópico."""
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("""
                SELECT topic, videos, links, created_at
                FROM chats
                WHERE user_id = %s AND (videos != '[]' OR links != '[]')
                ORDER BY created_at DESC
            """, (user_id,))
            rows = cursor.fetchall()

            library = {}
            for row in rows:
                topic = row['topic'] or "Outros"
                if topic not in library:
                    library[topic] = {"videos": [], "links": [], "date": row['created_at']}

                v_list = json.loads(row['videos']) if row['videos'] else []
                l_list = json.loads(row['links']) if row['links'] else []

                # Evitar duplicatas no mesmo tópico
                for v in v_list:
                    if not any(item['url'] == v['url'] for item in library[topic]["videos"]):
                        library[topic]["videos"].append(v)

                for l in l_list:
                    if not any(item['url'] == l['url'] for item in library[topic]["links"]):
                        library[topic]["links"].append(l)

            # Converter para lista para o frontend
            result = []
            for topic, data in library.items():
                if data["videos"] or data["links"]:
                    result.append({
                        "topic": topic,
                        "videos": data["videos"],
                        "links": data["links"],
                        "last_updated": data["date"]
                    })

            return jsonify(library=result), 200
    except Exception as e:
        logger.error(f"Erro na biblioteca de videos: {e}")
        return jsonify(error="Erro ao carregar biblioteca"), 500

from extensions import limiter

def _is_effective_premium(user):
    """Premium válido considerando premium_expires_at (None = permanente)."""
    if not user or not user.get("is_premium"):
        return False
    expira = user.get("premium_expires_at")
    if expira is None:
        return True
    try:
        if isinstance(expira, str):
            expira = datetime.fromisoformat(expira.replace("Z", "+00:00"))
        return expira > datetime.now()
    except Exception:
        return True


def get_free_chat_usage_month(cursor, user_id):
    """Conta interações do usuário free no mês corrente (tabela chats)."""
    cursor.execute(
        """SELECT COUNT(*) AS cnt FROM chats
           WHERE user_id = %s AND created_at >= DATE_FORMAT(NOW(), '%%Y-%%m-01')""",
        (user_id,),
    )
    row = cursor.fetchone()
    return int((row or {}).get("cnt") or 0)


def _emit_free_limit_reached(user_id, used):
    """P0.3: emite ``free_limit_reached`` 1x por ciclo de limite (idempotente)."""
    try:
        if not has_prior_event("free_limit_reached", user_id=user_id, anonymous_id=None):
            record_analytics_event(
                "free_limit_reached",
                user_id=user_id,
                anonymous_id=None,
                path="/api/chat",
                metadata={"limit": FREE_MONTHLY_CHAT_LIMIT, "used": used},
            )
    except Exception as exc:
        logger.warning("Falha ao emitir free_limit_reached: %s", exc)


@pages_bp.route("/api/admin/analytics/burn", methods=["GET"])
@jwt_required()
def admin_burn_analytics():
    """§5: burn de IA por usuário no mês corrente (via tabela chats). Apenas admin."""
    admin_id = get_jwt_identity()
    with get_db() as (cursor, conn):
        cursor.execute("SELECT is_admin FROM users WHERE id = %s", (admin_id,))
        row = cursor.fetchone()
        if not row or not row.get("is_admin"):
            return jsonify(error="Acesso restrito."), 403
        cursor.execute(
            """
            SELECT u.id, u.nome, u.email, u.is_premium,
                   COUNT(c.id) AS msgs_mes,
                   MAX(c.created_at) AS ultima_interacao
            FROM users u
            LEFT JOIN chats c ON c.user_id = u.id AND c.created_at >= DATE_FORMAT(NOW(), '%Y-%m-01')
            GROUP BY u.id
            ORDER BY msgs_mes DESC
            LIMIT 100
            """
        )
        rows = cursor.fetchall()
    return jsonify(users=rows, mes=datetime.now().strftime("%Y-%m")), 200


@pages_bp.route("/api/chat", methods=["POST"])
@limiter.limit("20 per hour")
@turnstile_or_auth(action="chat")
def chat():
    user_id = get_optional_user_id()
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    session_id = normalize_chat_session_id(data.get("session_id"))
    img_b64 = data.get("image")
    req_anonymous_id = (data.get("anonymous_id") or "").strip()[:80] or None
    vehicle_id = data.get("vehicle_id")
    try:
        attachment = parse_chat_attachment(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    client_history = normalize_client_history(data.get("client_history"))
    ignore_global_history = bool(data.get("ignore_global_history"))

    # Localização do usuário para busca de mecânicos
    user_lat = data.get("lat")
    user_lng = data.get("lng")
    if user_lat is not None:
        try: user_lat = float(user_lat)
        except (TypeError, ValueError): user_lat = None
    if user_lng is not None:
        try: user_lng = float(user_lng)
        except (TypeError, ValueError): user_lng = None
    if not msg and not img_b64 and not attachment:
        return jsonify(error="Envie uma mensagem ou anexe um arquivo para análise."), 400

    try:
        with get_db() as (cursor, conn):
            guest_messages_remaining = None
            if user_id:
                user = load_user_chat_context(cursor, user_id)
                if not user:
                    return invalid_session_response()
                # P0-1: free tem quota mensal; premium é ilimitado.
                if not _is_effective_premium(user):
                    used = get_free_chat_usage_month(cursor, user_id)
                    if used >= FREE_MONTHLY_CHAT_LIMIT:
                        # P0.3: instrumenta a chegada ao teto do plano gratuito
                        # (idempotente por usuário: 1 evento por ciclo de limite).
                        _emit_free_limit_reached(user_id, used)
                        return jsonify(
                            error="Você atingiu seu limite mensal de consultas no plano gratuito. Assine o Premium para consultas ilimitadas com a IA NOG.",
                            code="free_limit_reached",
                            limit=FREE_MONTHLY_CHAT_LIMIT,
                            used=used,
                        ), 403
            else:
                guest_id = normalize_guest_id(data.get("guest_id") or request.headers.get("X-AutoAssist-Guest-Id"))
                if not guest_id:
                    return jsonify(error="Identificação de visitante inválida. Recarregue a página e tente novamente."), 400

                guest_messages_remaining = reserve_guest_message(cursor, guest_id)
                if guest_messages_remaining is None:
                    return jsonify(
                        error="Você atingiu o limite de 5 mensagens gratuitas. Crie uma conta ou faça login para continuar.",
                        code="guest_limit_reached",
                        limit=GUEST_CHAT_LIMIT,
                    ), 403
                user = {"nome": "Visitante", "is_guest": True}

            historico_recente = select_recent_chat_history(
                cursor,
                user_id,
                msg,
                client_history,
                ignore_global_history,
            )

            reference_images = []
            if user_id and vehicle_id:
                reference_images = get_vehicle_reference_images(cursor, user_id, vehicle_id)

        if user_lat is not None and user_lng is not None:
            user["lat"] = user_lat
            user["lng"] = user_lng

        resposta, videos, links, topic = generate_assistant_payload(
            msg,
            user_id or 0,
            user,
            historico_recente,
            image_b64=img_b64,
            attachment=attachment,
            default_topic="Consultoria Geral",
            reference_images=reference_images,
        )

        stored_message = msg
        if not stored_message and attachment:
            stored_message = f"Arquivo anexado: {attachment['name']}"
        elif not stored_message and img_b64:
            stored_message = "Imagem anexada"

        attachments = attachment_metadata(attachment)
        chat_id = None
        if user_id:
            with get_db() as (cursor, conn):
                cursor.execute(
                    """
                    INSERT INTO chats (user_id, session_id, mensagem_usuario, resposta_ia, videos, links, topic, attachments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        session_id,
                        stored_message,
                        resposta,
                        json.dumps(videos),
                        json.dumps(links),
                        topic,
                        json.dumps(attachments),
                    )
                )
                chat_id = cursor.lastrowid
                if vehicle_id and img_b64:
                    seed_vehicle_photo_if_missing(cursor, conn, user_id, vehicle_id, img_b64)

        response_payload = dict(
            response=resposta,
            videos=videos,
            links=links,
            chat=build_chat_response(chat_id, session_id, stored_message, resposta, videos, links, topic, attachments),
        )
        if guest_messages_remaining is not None:
            response_payload["guest_messages_remaining"] = guest_messages_remaining
            response_payload["guest_limit"] = GUEST_CHAT_LIMIT

        # P0.2: instrumentação do funil de negócio (NOG / Raio-X).
        # Emite somente após a resposta ser gerada com sucesso (a análise
        # de imagem, se houver, já ocorreu dentro de generate_assistant_payload).
        _emit_usage_events(
            user_id=user_id,
            anonymous_id=req_anonymous_id if not user_id else None,
            is_raio=bool(img_b64) or bool(attachment and attachment.get("kind") in ("image", "binary")),
        )
        return jsonify(response_payload)
    except Exception as e:
        logger.error(f"Erro na rota /api/chat: {e}")
        return jsonify(error="Erro interno"), 500

@pages_bp.route("/api/voice", methods=["POST"])
@turnstile_or_auth(action="chat")
def handle_voice():
    user_id = get_optional_user_id()
    if 'audio' not in request.files:
        return jsonify(error="Nenhum áudio recebido"), 400

    audio_file = request.files['audio']
    img_b64 = request.form.get("image")
    session_id = normalize_chat_session_id(request.form.get("session_id"))
    attachment = None
    if request.form.get("attachment"):
        try:
            attachment = parse_chat_attachment({"attachment": json.loads(request.form.get("attachment"))})
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            return jsonify(error="Arquivo anexado inválido."), 400

    ignore_global_history = (request.form.get("ignore_global_history") or "").lower() in ("1", "true", "yes")
    try:
        client_history = normalize_client_history(json.loads(request.form.get("client_history") or "[]"))
    except Exception:
        client_history = []

    try:
        # Converter o audio recebido para wav usando pydub (formato detectado automaticamente)
        audio_segment = AudioSegment.from_file(audio_file)
        wav_io = io.BytesIO()
        audio_segment.export(wav_io, format="wav")
        wav_io.seek(0)

        # Reconhecimento de fala
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)

        text = recognizer.recognize_google(audio_data, language="pt-BR")

        with get_db() as (cursor, conn):
            guest_messages_remaining = None
            if user_id:
                user = load_user_chat_context(cursor, user_id)
                if not user:
                    return invalid_session_response()
                # P0-1: free tem quota mensal; premium é ilimitado.
                if not _is_effective_premium(user):
                    used = get_free_chat_usage_month(cursor, user_id)
                    if used >= FREE_MONTHLY_CHAT_LIMIT:
                        # P0.3: instrumenta a chegada ao teto do plano gratuito
                        # (idempotente por usuário: 1 evento por ciclo de limite).
                        _emit_free_limit_reached(user_id, used)
                        return jsonify(
                            error="Você atingiu seu limite mensal de consultas no plano gratuito. Assine o Premium para consultas ilimitadas com a IA NOG.",
                            code="free_limit_reached",
                            limit=FREE_MONTHLY_CHAT_LIMIT,
                            used=used,
                        ), 403
            else:
                guest_id = normalize_guest_id(request.form.get("guest_id") or request.headers.get("X-AutoAssist-Guest-Id"))
                if not guest_id:
                    return jsonify(error="Identificação de visitante inválida. Recarregue a página e tente novamente."), 400

                guest_messages_remaining = reserve_guest_message(cursor, guest_id)
                if guest_messages_remaining is None:
                    return jsonify(
                        error="Você atingiu o limite de 5 mensagens gratuitas. Crie uma conta ou faça login para continuar.",
                        code="guest_limit_reached",
                        limit=GUEST_CHAT_LIMIT,
                    ), 403
                user = {"nome": "Visitante", "is_guest": True}

            historico_recente = select_recent_chat_history(
                cursor,
                user_id,
                text,
                client_history,
                ignore_global_history,
            )

        voice_lat = request.form.get("lat")
        voice_lng = request.form.get("lng")
        if voice_lat is not None:
            try: user["lat"] = float(voice_lat)
            except (TypeError, ValueError): pass
        if voice_lng is not None:
            try: user["lng"] = float(voice_lng)
            except (TypeError, ValueError): pass

        resposta, videos, links, topic = generate_assistant_payload(
            text,
            user_id or 0,
            user,
            historico_recente,
            image_b64=img_b64,
            attachment=attachment,
            default_topic="Consultoria por Voz",
        )

        attachments = attachment_metadata(attachment)
        chat_id = None
        if user_id:
            with get_db() as (cursor, conn):
                cursor.execute(
                    """
                    INSERT INTO chats (user_id, session_id, mensagem_usuario, resposta_ia, videos, links, topic, attachments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        session_id,
                        text,
                        resposta,
                        json.dumps(videos),
                        json.dumps(links),
                        topic,
                        json.dumps(attachments),
                    )
                )
                chat_id = cursor.lastrowid

        response_payload = dict(
            text=text,
            response=resposta,
            videos=videos,
            links=links,
            chat=build_chat_response(chat_id, session_id, text, resposta, videos, links, topic, attachments),
        )
        if guest_messages_remaining is not None:
            response_payload["guest_messages_remaining"] = guest_messages_remaining
            response_payload["guest_limit"] = GUEST_CHAT_LIMIT

        # P0.2: instrumentação do funil de negócio (NOG / Raio-X) via voz.
        _emit_usage_events(
            user_id=user_id,
            anonymous_id=(request.form.get("anonymous_id") or "").strip()[:80] or None
            if not user_id else None,
            is_raio=bool(image_b64) or bool(attachment and attachment.get("kind") in ("image", "binary")),
        )
        return jsonify(response_payload)

    except sr.UnknownValueError:
        return jsonify(error="Não entendi o que foi falado. Pode repetir?"), 400
    except sr.RequestError as e:
        logger.error(f"Erro de serviço SR: {e}")
        return jsonify(error="Erro no serviço de voz."), 500
    except Exception as e:
        logger.error(f"Erro na rota /api/voice: {e}")
        return jsonify(error="Erro interno ao processar voz"), 500

@pages_bp.route("/api/report", methods=["POST"])
@jwt_required()
def generate_report():
    user_id = get_jwt_identity()
    data = request.get_json()
    text = data.get("text")

    if not text:
        return jsonify(error="Texto da análise é obrigatório"), 400

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            # Criar diretório seguro se não existir
            secure_reports_dir = os.path.join(current_app.root_path, "secure_reports")
            if not os.path.exists(secure_reports_dir):
                os.makedirs(secure_reports_dir)

            # Nome de arquivo único e imprevisível
            filename = f"report_{user_id}_{uuid.uuid4().hex}.pdf"
            filepath = os.path.join(secure_reports_dir, filename)

            # Gerar o PDF
            from services.report_generator import criar_relatorio_pdf
            success = criar_relatorio_pdf(user, text, filepath)

            if success:
                # Retornar URL da rota que serve o arquivo (com auth)
                return jsonify(url=f"/api/report/{filename}"), 200
            else:
                return jsonify(error="Erro ao gerar relatório"), 500
    except Exception as e:
        logger.error(f"Erro ao gerar relatório: {e}")
        return jsonify(error="Erro interno ao gerar relatório"), 500

@pages_bp.route("/api/report/<filename>", methods=["GET"])
@jwt_required()
def serve_report(filename):
    user_id = str(get_jwt_identity())

    # Segurança básica contra Path Traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify(error="Nome de arquivo inválido"), 400

    # Verificar se o arquivo pertence ao usuário (prefixo report_USERID_)
    if not filename.startswith(f"report_{user_id}_"):
        logger.warning(f"Tentativa de IDOR: Usuário {user_id} tentou acessar {filename}")
        return jsonify(error="Acesso negado"), 403

    secure_reports_dir = os.path.join(current_app.root_path, "secure_reports")
    return send_from_directory(secure_reports_dir, filename)

@limiter.exempt
@pages_bp.route("/")
def index():
    return current_app.send_static_file("index.html")

@limiter.exempt
@pages_bp.route("/<path:path>")
def serve_html(path):
    if path.startswith("api/"):
        return jsonify(error="Recurso nao encontrado."), 404
    if path in ("robots.txt", "llms.txt", "sitemap.xml"):
        return jsonify(error="Recurso nao encontrado."), 404
    if not path.endswith(".html") and "." not in path:
        path += ".html"
    return current_app.send_static_file(path)
