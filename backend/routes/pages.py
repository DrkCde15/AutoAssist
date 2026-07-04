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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import quote, quote_plus
from flask import Blueprint, request, jsonify, current_app, send_from_directory, has_request_context, redirect, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
import uuid
import speech_recognition as sr
from pydub import AudioSegment
from services.nogai import (
    gerar_resposta,
    get_fipe_value,
    gerar_termos_busca,
    prever_intervalo_manutencao
)
from utils.async_task import _predictor, train_in_background
import json
from services.youtube_service import buscar_videos_youtube
from services.vision_ai import analisar_imagem
from services.attachment_ai import analisar_arquivo
from services.report_generator import criar_relatorio_pdf
from services.maintenance_service import (
    parse_maintenance_entry,
    apply_manual_overrides,
    serialize_maintenance_row,
    consolidate_active_maintenance_records,
    build_maintenance_alerts,
)
from .database import get_db, is_trial_expired, get_trial_days_remaining, get_mysql_history
from utils.email import enviar_email
from .notifications import create_notification
from .push import send_push_notification

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

def build_spending_summary(history_rows):
    total_cost = 0.0
    by_type = {}

    for row in history_rows:
        cost = row.get("cost")
        if cost is None:
            continue

        value = float(cost)
        total_cost += value
        label = row.get("maintenance_label") or "Manutencao geral"
        by_type[label] = by_type.get(label, 0.0) + value

    gastos_por_tipo = [
        {"tipo": label, "valor": round(amount, 2)}
        for label, amount in sorted(by_type.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "total_gastos": round(total_cost, 2),
        "quantidade_registros": len(history_rows),
        "gastos_por_tipo": gastos_por_tipo,
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

    # Validacao MIME contra extensao
    mime_to_ext = {
        "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
        "image/gif": "gif", "application/pdf": "pdf",
        "text/plain": "txt", "text/csv": "csv", "text/markdown": "md",
        "application/json": "json",
    }
    expected_ext = mime_to_ext.get(mime_type)
    if expected_ext and ext and ext != expected_ext:
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
        links.append({
            "titulo": f"Ver ofertas de {termo_loja}",
            "url": f"https://www.webmotors.com.br/carros/estoque?q={quote_plus(termo_loja)}",
            "tipo": "veiculo",
            "icon": "fas fa-car"
        })

    if termo_pecas:
        links.append({
            "titulo": f"Comprar {termo_pecas} no Mercado Livre",
            "url": f"https://lista.mercadolivre.com.br/{quote(termo_pecas.replace(' ', '-'), safe='')}",
            "tipo": "peca",
            "icon": "fas fa-tools"
        })

    topic = termo_yt or termo_loja or termo_pecas or default_topic
    return videos, links, topic


def generate_assistant_payload(
    message,
    user_id,
    user,
    historico_recente,
    image_b64=None,
    attachment=None,
    default_topic="Consultoria Geral"
):
    prompt_message = message
    if attachment and attachment["kind"] == "text":
        prompt_message = build_text_attachment_message(message, attachment)

    with ThreadPoolExecutor(max_workers=2) as executor:
        if attachment and attachment["kind"] in ("image", "binary"):
            resposta_future = executor.submit(
                analisar_arquivo,
                attachment["data"],
                attachment["mime_type"],
                attachment["name"],
                message,
            )
        elif image_b64:
            resposta_future = executor.submit(analisar_imagem, image_b64, message)
        else:
            resposta_future = executor.submit(
                gerar_resposta,
                prompt_message,
                user_id,
                user_data=user,
                historico=historico_recente,
            )
        recommendations_future = None
        if not attachment and not image_b64:
            recommendations_future = executor.submit(
                build_recommendations,
                message,
                historico_recente,
                default_topic,
            )

        resposta = resposta_future.result()
        videos, links, topic = resolve_recommendations(recommendations_future, default_topic)

    return resposta, videos, links, topic or default_topic


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
                   maintenance_email_enabled, maintenance_email_last_sent
            FROM users WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()
        if not user:
            return invalid_session_response()
        user["maintenance_email_last_sent"] = serialize_datetime_field(user.get("maintenance_email_last_sent"))

        cursor.execute("SELECT COUNT(*) AS total FROM chats WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()

        cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
        veiculos = cursor.fetchall()

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

            cursor.execute("SELECT COUNT(*) AS total FROM chats WHERE user_id = %s", (user_id,))
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
                SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem
                FROM veiculos
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,)
            )
            veiculos = cursor.fetchall()
            return jsonify(veiculos=veiculos), 200
    except Exception as e:
        logger.error(f"Erro ao listar veiculos: {e}")
        return jsonify(error="Erro ao listar veiculos"), 500

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

            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"Erro ao excluir veiculo: {e}")
        return jsonify(error="Erro interno"), 500

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
            premium_error = ensure_premium_user(user)
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
                ai_previsao = prever_intervalo_manutencao(description, veiculo_str)

                if ai_previsao.get("intervalo_dias"):
                    parsed["interval_days"] = ai_previsao["intervalo_dias"]
                    parsed["next_due_date"] = parsed["service_date"] + timedelta(days=ai_previsao["intervalo_dias"])

                if ai_previsao.get("intervalo_km"):
                    parsed["interval_km"] = ai_previsao["intervalo_km"]
                    if parsed.get("service_km") is not None:
                        parsed["next_due_km"] = parsed["service_km"] + ai_previsao["intervalo_km"]

                parsed["parser_metadata"]["ai_enhanced"] = True
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
            # Gatilho imediato de e-mail em segundo plano + push
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    _enqueue_alert_email(user_row)
                    send_push_notification(
                        user_id=user_id,
                        title="📝 Anotação salva",
                        body=f"{parsed.get('maintenance_label', 'Registro')} registrado com sucesso.",
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
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            params = [user_id]
            vehicle_filter = ""
            if vehicle_id is not None:
                try:
                    vehicle_id = int(vehicle_id)
                except (TypeError, ValueError):
                    return jsonify(error="veiculo_id invalido"), 400
                vehicle_filter = " AND mh.vehicle_id = %s"
                params.append(vehicle_id)

            cursor.execute(
                f"""
                SELECT mh.*, v.marca AS vehicle_marca, v.modelo AS vehicle_modelo
                FROM maintenance_history mh
                LEFT JOIN veiculos v ON v.id = mh.vehicle_id
                WHERE mh.user_id = %s {vehicle_filter}
                ORDER BY mh.service_date DESC, mh.created_at DESC
                """,
                tuple(params)
            )
            history_rows = cursor.fetchall()
            serialized = [serialize_maintenance_row(row) for row in history_rows]

            return jsonify(
                historico=serialized,
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
                veiculo_str = f"{vehicle.get('marca', '')} {vehicle.get('modelo', '')}".strip() if vehicle else ""
                ai_previsao = prever_intervalo_manutencao(new_description, veiculo_str)
                if ai_previsao.get("intervalo_dias"):
                    parsed["interval_days"] = ai_previsao["intervalo_dias"]
                    parsed["next_due_date"] = parsed["service_date"] + timedelta(days=ai_previsao["intervalo_dias"])
                if ai_previsao.get("intervalo_km"):
                    parsed["interval_km"] = ai_previsao["intervalo_km"]
                    if parsed.get("service_km") is not None:
                        parsed["next_due_km"] = parsed["service_km"] + ai_previsao["intervalo_km"]

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

            # Gatilho imediato de e-mail em segundo plano + notificação + push
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    _enqueue_alert_email(user_row)
                    create_notification(
                        user_id=user_id,
                        title="Manutenção atualizada",
                        body=f"{parsed.get('maintenance_label', 'Registro')} atualizado com sucesso.",
                        type="info",
                        action_url="/dashboard.html",
                    )
                    send_push_notification(
                        user_id=user_id,
                        title="🛠️ Manutenção atualizada",
                        body=f"{parsed.get('maintenance_label', 'Registro')} atualizado com sucesso.",
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
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            order_direction = "ASC" if after_id else "DESC"
            after_filter = "AND id > %s" if after_id else ""
            params = [user_id]
            if after_id:
                params.append(after_id)
            params.append(limit)

            cursor.execute(
                f"""
                SELECT id, session_id, mensagem_usuario, resposta_ia, created_at, videos, links, topic, attachments
                FROM chats
                WHERE user_id = %s
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

@pages_bp.route("/api/chat", methods=["POST"])
@limiter.limit("20 per hour")
def chat():
    user_id = get_optional_user_id()
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    session_id = normalize_chat_session_id(data.get("session_id"))
    img_b64 = data.get("image")
    try:
        attachment = parse_chat_attachment(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    client_history = normalize_client_history(data.get("client_history"))
    ignore_global_history = bool(data.get("ignore_global_history"))
    if not msg and not img_b64 and not attachment:
        return jsonify(error="Envie uma mensagem ou anexe um arquivo para análise."), 400

    try:
        with get_db() as (cursor, conn):
            guest_messages_remaining = None
            if user_id:
                user = load_user_chat_context(cursor, user_id)
                if not user:
                    return invalid_session_response()
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

        resposta, videos, links, topic = generate_assistant_payload(
            msg,
            user_id or 0,
            user,
            historico_recente,
            image_b64=img_b64,
            attachment=attachment,
            default_topic="Consultoria Geral",
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

        response_payload = dict(
            response=resposta,
            videos=videos,
            links=links,
            chat=build_chat_response(chat_id, session_id, stored_message, resposta, videos, links, topic, attachments),
        )
        if guest_messages_remaining is not None:
            response_payload["guest_messages_remaining"] = guest_messages_remaining
            response_payload["guest_limit"] = GUEST_CHAT_LIMIT
        return jsonify(response_payload)
    except Exception as e:
        logger.error(f"Erro na rota /api/chat: {e}")
        return jsonify(error="Erro interno"), 500

@pages_bp.route("/api/voice", methods=["POST"])
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
        # Converter webm para wav usando pydub
        audio_segment = AudioSegment.from_file(audio_file, format="webm")
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

@pages_bp.route("/")
def index():
    return current_app.send_static_file("index.html")

@pages_bp.route("/<path:path>")
def serve_html(path):
    if path.startswith("api/"):
        return jsonify(error="Recurso nao encontrado."), 404
    if not path.endswith(".html") and "." not in path:
        path += ".html"
    return current_app.send_static_file(path)
