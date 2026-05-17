import os
import io
import html
import logging
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from time import monotonic
from urllib.parse import quote, quote_plus
from flask import Blueprint, request, jsonify, current_app, send_from_directory, has_request_context
from flask_jwt_extended import jwt_required, get_jwt_identity
import uuid
import speech_recognition as sr
from pydub import AudioSegment
from services.nogai import (
    gerar_resposta,
    get_fipe_value,
    gerar_termos_busca,
    prever_intervalo_manutencao
)

import json
from services.youtube_service import buscar_videos_youtube
from services.vision_ai import analisar_imagem
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

def get_dashboard_url() -> str:
    frontend_url = (os.getenv("URL_PROD") or "").strip()
    if not frontend_url and has_request_context():
        frontend_url = request.host_url
    if not frontend_url:
        frontend_url = "https://autoassist-l9lr.onrender.com/"
    base = frontend_url if frontend_url.endswith("/") else f"{frontend_url}/"
    return f"{base}dashboard.html"

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


def generate_assistant_payload(message, user_id, user, historico_recente, image_b64=None, default_topic="Consultoria Geral"):
    with ThreadPoolExecutor(max_workers=2) as executor:
        resposta_future = executor.submit(
            analisar_imagem,
            image_b64,
            message
        ) if image_b64 else executor.submit(
            gerar_resposta,
            message,
            user_id,
            user_data=user,
            historico=historico_recente,
        )
        recommendations_future = executor.submit(
            build_recommendations,
            message,
            historico_recente,
            default_topic,
        )

        resposta = resposta_future.result()
        videos, links, topic = recommendations_future.result()

    return resposta, videos, links, topic or default_topic

def serialize_datetime_field(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value

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
    if not sent_ok:
        return {"sent": False, "reason": "send_failed", "alerts_count": len(alerts)}

    mark_maintenance_alerts_sent(cursor, user_row["id"], alerts)
    cursor.execute(
        "UPDATE users SET maintenance_email_last_sent = NOW() WHERE id = %s",
        (user_row["id"],)
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

    threading.Thread(
        target=_dispatch_maintenance_emails_background,
        daemon=True,
    ).start()
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
                    threading.Thread(
                        target=send_maintenance_alert_email_for_user,
                        args=(None, user_row), # Cursor None pois abriremos nova conexão na thread
                        kwargs={
                            "force": False,
                            "status_codes": CRITICAL_MAINTENANCE_STATUSES,
                            "transition_only": True,
                        },
                        daemon=True,
                    ).start()
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

            # Gatilho imediato de e-mail em segundo plano
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    threading.Thread(
                        target=send_maintenance_alert_email_for_user,
                        args=(None, user_row),
                        kwargs={
                            "force": False,
                            "status_codes": CRITICAL_MAINTENANCE_STATUSES,
                            "transition_only": True,
                        },
                        daemon=True,
                    ).start()
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

            # Gatilho imediato de e-mail em segundo plano
            try:
                user_row = get_user_by_id(cursor, user_id)
                if user_row:
                    threading.Thread(
                        target=send_maintenance_alert_email_for_user,
                        args=(None, user_row),
                        kwargs={
                            "force": False,
                            "status_codes": CRITICAL_MAINTENANCE_STATUSES,
                            "transition_only": True,
                        },
                        daemon=True,
                    ).start()
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

@pages_bp.route("/api/dashboard", methods=["GET"])
@jwt_required()
def get_dashboard_data():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("SELECT * FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            if not veiculos:
                return jsonify([]), 404

            dashboard_data = []
            for v in veiculos:
                fipe = get_fipe_value(v["tipo"], v["marca"], v["modelo"], v["ano_fabricacao"])
                alerts = fetch_user_maintenance_alerts(cursor, user_id, vehicle_id=v["id"])
                dashboard_data.append({
                    "veiculo": v,
                    "fipe": fipe,
                    "saude": alerts
                })
            return jsonify(dashboard_data), 200
    except Exception as e:
        logger.error(f"Erro no dashboard: {e}")
        return jsonify(error="Erro interno"), 500

@pages_bp.route("/api/chat/history", methods=["GET"])
@jwt_required()
def get_chat_history():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()

            cursor.execute(
                """
                SELECT id, mensagem_usuario, resposta_ia, created_at, videos, links, topic
                FROM chats
                WHERE user_id = %s
                ORDER BY created_at ASC
                """,
                (user_id,)
            )
            rows = cursor.fetchall()
            chats = []
            for r in rows:
                v_data = r["videos"]
                if isinstance(v_data, str):
                    try: v_data = json.loads(v_data)
                    except: v_data = []
                l_data = r.get("links")
                if isinstance(l_data, str):
                    try: l_data = json.loads(l_data)
                    except: l_data = []
                if is_generic_chat_message(r["mensagem_usuario"]):
                    v_data = []
                    l_data = []
                chats.append({
                    "id": r["id"],
                    "mensagem_usuario": r["mensagem_usuario"],
                    "resposta_ia": r["resposta_ia"],
                    "created_at": serialize_datetime_field(r["created_at"]),
                    "videos": v_data or [],
                    "links": l_data or [],
                    "topic": r.get("topic") or ""
                })
            return jsonify(chats=chats), 200
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
@jwt_required()
@limiter.limit("20 per hour")
def chat():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    img_b64 = data.get("image")
    client_history = normalize_client_history(data.get("client_history"))
    ignore_global_history = bool(data.get("ignore_global_history"))
    if not msg and not img_b64:
        return jsonify(error="Mensagem ou imagem e obrigatoria"), 400

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()
            cursor.execute("SELECT tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            if veiculos:
                user['lista_veiculos'] = veiculos
            if is_generic_chat_message(msg):
                historico_recente = []
            elif ignore_global_history:
                historico_recente = client_history
            else:
                historico_recente = get_mysql_history(user_id, limit=3, cursor=cursor)

        resposta, videos, links, topic = generate_assistant_payload(
            msg,
            user_id,
            user,
            historico_recente,
            image_b64=img_b64,
            default_topic="Consultoria Geral",
        )

        with get_db() as (cursor, conn):
            cursor.execute(
                "INSERT INTO chats (user_id, mensagem_usuario, resposta_ia, videos, links, topic) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, msg, resposta, json.dumps(videos), json.dumps(links), topic)
            )
            chat_id = cursor.lastrowid

        return jsonify(
            response=resposta,
            videos=videos,
            links=links,
            chat={
                "id": chat_id,
                "mensagem_usuario": msg,
                "resposta_ia": resposta,
                "created_at": datetime.now().isoformat(),
                "videos": videos,
                "links": links,
                "topic": topic or "",
            },
        )
    except Exception as e:
        logger.error(f"Erro na rota /api/chat: {e}")
        return jsonify(error="Erro interno"), 500

@pages_bp.route("/api/voice", methods=["POST"])
@jwt_required()
def handle_voice():
    user_id = get_jwt_identity()
    if 'audio' not in request.files:
        return jsonify(error="Nenhum áudio recebido"), 400

    audio_file = request.files['audio']
    img_b64 = request.form.get("image")
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
            user = get_user_by_id(cursor, user_id)
            if not user:
                return invalid_session_response()
            cursor.execute("SELECT tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            if veiculos:
                user['lista_veiculos'] = veiculos
            if is_generic_chat_message(text):
                historico_recente = []
            elif ignore_global_history:
                historico_recente = client_history
            else:
                historico_recente = get_mysql_history(user_id, limit=3, cursor=cursor)

        resposta, videos, links, topic = generate_assistant_payload(
            text,
            user_id,
            user,
            historico_recente,
            image_b64=img_b64,
            default_topic="Consultoria por Voz",
        )

        with get_db() as (cursor, conn):
            cursor.execute(
                "INSERT INTO chats (user_id, mensagem_usuario, resposta_ia, videos, links, topic) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, text, resposta, json.dumps(videos), json.dumps(links), topic)
            )
            chat_id = cursor.lastrowid

        return jsonify(
            text=text,
            response=resposta,
            videos=videos,
            links=links,
            chat={
                "id": chat_id,
                "mensagem_usuario": text,
                "resposta_ia": resposta,
                "created_at": datetime.now().isoformat(),
                "videos": videos,
                "links": links,
                "topic": topic or "",
            },
        )

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
    if not path.endswith(".html") and "." not in path:
        path += ".html"
    return current_app.send_static_file(path)
