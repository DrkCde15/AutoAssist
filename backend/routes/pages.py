import os
import io
import html
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import speech_recognition as sr
from pydub import AudioSegment
from services.nogai import gerar_resposta, get_fipe_value, gerar_termo_busca_youtube, gerar_termo_busca_loja, gerar_termo_busca_pecas
import json
from services.youtube_service import buscar_videos_youtube
from services.web_scraping import WebScraper
from services.vision_ai import analisar_imagem
from services.report_generator import criar_relatorio_pdf
from services.maintenance_service import (
    parse_maintenance_entry,
    apply_manual_overrides,
    serialize_maintenance_row,
    consolidate_active_maintenance_records,
    build_maintenance_alerts,
)
from .database import get_db, is_trial_expired, get_trial_days_remaining, enviar_email

pages_bp = Blueprint('pages', __name__)
logger = logging.getLogger(__name__)

PREMIUM_ONLY_ERROR = "Recurso exclusivo para Premium"

def get_user_by_id(cursor, user_id):
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    return cursor.fetchone()

def ensure_premium_user(user):
    return None


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
        alerts = [a for a in alerts if a.get("status_code") in ("overdue", "due_soon")]
    return alerts


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
    safe_name = html.escape(user_name or "usuario")
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows = []
    for alert in alerts:
        item = html.escape(str(alert.get("item") or "Manutencao"))
        msg = html.escape(str(alert.get("msg") or ""))
        status_code = alert.get("status_code")
        if status_code == "overdue":
            badge_color = "#b91c1c"
            badge_bg = "#fee2e2"
        elif status_code == "due_soon":
            badge_color = "#b45309"
            badge_bg = "#fef3c7"
        else:
            badge_color = "#166534"
            badge_bg = "#dcfce7"
        status = html.escape(str(alert.get("status") or "Aviso"))
        rows.append(
            f"""
            <tr>
                <td style="padding:12px;border-bottom:1px solid #e5e7eb;">
                    <strong>{item}</strong><br>
                    <span style="color:#4b5563;">{msg}</span>
                </td>
                <td style="padding:12px;border-bottom:1px solid #e5e7eb;text-align:right;">
                    <span style="display:inline-block;padding:4px 10px;border-radius:999px;background:{badge_bg};color:{badge_color};font-size:12px;font-weight:700;">
                        {status}
                    </span>
                </td>
            </tr>
            """
        )

    rows_html = "".join(rows) if rows else """
        <tr><td style="padding:12px;color:#4b5563;">Sem alertas no momento.</td></tr>
    """

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;color:#111827;">
        <h2 style="margin-bottom:4px;">AutoAssist - Alertas de manutencao</h2>
        <p style="margin-top:0;color:#4b5563;">Ola, {safe_name}. Aqui esta o resumo automatico de hoje ({generated_at}).</p>
        <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
            {rows_html}
        </table>
        <p style="margin-top:16px;color:#6b7280;font-size:12px;">
            Este e um envio automatico de alertas de manutencao do AutoAssist.
        </p>
    </div>
    """


def send_maintenance_alert_email_for_user(cursor, user_row, force=False):
    if not user_row.get("email"):
        return {"sent": False, "reason": "missing_email", "alerts_count": 0}
    if not user_row.get("maintenance_email_enabled", True) and not force:
        return {"sent": False, "reason": "disabled", "alerts_count": 0}
    if not should_send_maintenance_email(user_row, force=force):
        return {"sent": False, "reason": "already_sent_today", "alerts_count": 0}

    alerts = fetch_user_maintenance_alerts(
        cursor,
        user_id=user_row["id"],
        only_actionable=True
    )
    if not alerts:
        return {"sent": False, "reason": "no_actionable_alerts", "alerts_count": 0}

    subject = f"AutoAssist: {len(alerts)} alerta(s) de manutencao para revisar"
    html_body = render_maintenance_email_html(user_row.get("nome"), alerts)
    sent_ok = enviar_email(user_row["email"], subject, html_body)
    if not sent_ok:
        return {"sent": False, "reason": "send_failed", "alerts_count": len(alerts)}

    cursor.execute(
        "UPDATE users SET maintenance_email_last_sent = NOW() WHERE id = %s",
        (user_row["id"],)
    )
    return {"sent": True, "reason": "sent", "alerts_count": len(alerts)}

@pages_bp.route("/")
def index():
    return current_app.send_static_file("index.html")

@pages_bp.route("/<path:path>")
def serve_html(path):
    if not path.endswith(".html") and "." not in path:
        path += ".html"
    return current_app.send_static_file(path)

@pages_bp.route("/api/user", methods=["GET"])
@jwt_required()
def get_user():
    user_id = get_jwt_identity()
    with get_db() as (cursor, conn):
        cursor.execute("""
            SELECT nome, email, is_premium, created_at, possui_veiculo,
                   veiculo_marca, veiculo_modelo, veiculo_ano_fabricacao,
                   veiculo_ano_compra, veiculo_tipo, veiculo_quilometragem, is_two_factor_enabled,
                   maintenance_email_enabled, maintenance_email_last_sent
            FROM users WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify(error="Usuário não encontrado"), 404
        user["maintenance_email_last_sent"] = serialize_datetime_field(user.get("maintenance_email_last_sent"))

        cursor.execute("SELECT COUNT(*) AS total FROM chats WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()
        
        cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
        veiculos = cursor.fetchall()
        
        return jsonify({
            **user,
            "trial_expired": is_trial_expired(user),
            "trial_days_remaining": get_trial_days_remaining(user),
            "is_premium": True,
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
                return jsonify(error="Usuário não encontrado"), 404
            
            cursor.execute("SELECT COUNT(*) AS total FROM chats WHERE user_id = %s", (user_id,))
            total = cursor.fetchone()

            return jsonify({
                **user,
                "trial_expired": is_trial_expired(user),
                "trial_days_remaining": get_trial_days_remaining(user),
                "is_premium": True,
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
            return jsonify(success=True, id=v_id), 201
    except Exception as e:
        logger.error(f"Erro ao adicionar veiculo: {e}")
        return jsonify(error="Erro interno ao adicionar veículo"), 500

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
            if raw_vehicle_id is not None:
                try:
                    vehicle_id = int(raw_vehicle_id)
                except (TypeError, ValueError):
                    return jsonify(error="veiculo_id invalido"), 400

                cursor.execute(
                    "SELECT id, quilometragem FROM veiculos WHERE id = %s AND user_id = %s",
                    (vehicle_id, user_id)
                )
                vehicle = cursor.fetchone()
                if not vehicle:
                    return jsonify(error="Veiculo nao encontrado"), 404
                fallback_vehicle_km = vehicle.get("quilometragem")
            else:
                cursor.execute("SELECT id, quilometragem FROM veiculos WHERE user_id = %s ORDER BY id ASC", (user_id,))
                vehicles = cursor.fetchall()
                if len(vehicles) == 1:
                    vehicle_id = vehicles[0]["id"]
                    fallback_vehicle_km = vehicles[0].get("quilometragem")

            parsed = parse_maintenance_entry(description)
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


@pages_bp.route("/api/maintenance/alerts", methods=["GET"])
@jwt_required()
def get_maintenance_alerts():
    user_id = get_jwt_identity()
    vehicle_id = request.args.get("veiculo_id")

    try:
        with get_db() as (cursor, conn):
            vehicle_filter = ""
            params = [user_id]
            vehicle_params = [user_id]

            if vehicle_id is not None:
                try:
                    vehicle_id = int(vehicle_id)
                except (TypeError, ValueError):
                    return jsonify(error="veiculo_id invalido"), 400

                vehicle_filter = " AND vehicle_id = %s"
                params.append(vehicle_id)
                vehicle_params.append(vehicle_id)

            cursor.execute(
                f"SELECT id, quilometragem FROM veiculos WHERE user_id = %s{' AND id = %s' if vehicle_id is not None else ''}",
                tuple(vehicle_params)
            )
            vehicles = cursor.fetchall()
            vehicle_km_map = {item["id"]: item.get("quilometragem") for item in vehicles}

            cursor.execute(
                f"""
                SELECT *
                FROM maintenance_history
                WHERE user_id = %s {vehicle_filter}
                ORDER BY service_date DESC, created_at DESC
                """,
                tuple(params)
            )
            history_rows = cursor.fetchall()
            active_records = consolidate_active_maintenance_records(history_rows)
            alerts = build_maintenance_alerts(active_records, vehicle_km_map=vehicle_km_map)

            return jsonify(
                alertas=alerts,
                total_alertas=len(alerts),
                total_atrasados=len([a for a in alerts if a.get("status_code") == "overdue"])
            ), 200
    except Exception as e:
        logger.error(f"Erro ao gerar alertas de manutencao: {e}")
        return jsonify(error="Erro ao gerar alertas de manutencao"), 500


@pages_bp.route("/api/maintenance/email-settings", methods=["GET"])
@jwt_required()
def get_maintenance_email_settings():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """
                SELECT maintenance_email_enabled, maintenance_email_last_sent
                FROM users
                WHERE id = %s
                """,
                (user_id,)
            )
            settings = cursor.fetchone()
            if not settings:
                return jsonify(error="Usuario nao encontrado"), 404

            return jsonify(
                maintenance_email_enabled=bool(settings.get("maintenance_email_enabled", True)),
                maintenance_email_last_sent=serialize_datetime_field(settings.get("maintenance_email_last_sent"))
            ), 200
    except Exception as e:
        logger.error(f"Erro ao buscar configuracao de email automatico: {e}")
        return jsonify(error="Erro ao buscar configuracao de email"), 500


@pages_bp.route("/api/maintenance/email-settings", methods=["PUT"])
@jwt_required()
def update_maintenance_email_settings():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        return jsonify(error="Campo 'enabled' deve ser booleano"), 400

    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "UPDATE users SET maintenance_email_enabled = %s WHERE id = %s",
                (enabled, user_id)
            )
            return jsonify(success=True, maintenance_email_enabled=enabled), 200
    except Exception as e:
        logger.error(f"Erro ao atualizar configuracao de email automatico: {e}")
        return jsonify(error="Erro ao atualizar configuracao de email"), 500


@pages_bp.route("/api/maintenance/email/send-now", methods=["POST"])
@jwt_required()
def send_maintenance_email_now():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                """
                SELECT id, nome, email, maintenance_email_enabled, maintenance_email_last_sent
                FROM users
                WHERE id = %s
                """,
                (user_id,)
            )
            user = cursor.fetchone()
            if not user:
                return jsonify(error="Usuario nao encontrado"), 404

            result = send_maintenance_alert_email_for_user(cursor, user, force=True)
            return jsonify(
                success=result["sent"],
                reason=result["reason"],
                alerts_count=result["alerts_count"]
            ), (200 if result["sent"] else 202)
    except Exception as e:
        logger.error(f"Erro no envio manual de email de manutencao: {e}")
        return jsonify(error="Erro ao enviar email de manutencao"), 500


@pages_bp.route("/api/maintenance/email/dispatch", methods=["POST"])
def dispatch_maintenance_email_batch():
    cron_secret = os.getenv("MAINTENANCE_EMAIL_CRON_SECRET", "").strip()
    sent_secret = (request.headers.get("X-Cron-Secret") or "").strip()
    auth_header = request.headers.get("Authorization", "").strip()
    bearer_secret = ""
    if auth_header.lower().startswith("bearer "):
        bearer_secret = auth_header[7:].strip()

    if not cron_secret:
        return jsonify(error="MAINTENANCE_EMAIL_CRON_SECRET nao configurado"), 500
    if cron_secret not in (sent_secret, bearer_secret):
        return jsonify(error="Nao autorizado"), 401

    payload = request.get_json(silent=True) or {}
    force = bool(payload.get("force", False))
    limit = payload.get("limit", 500)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 500
    limit = max(1, min(limit, 2000))

    try:
        with get_db() as (cursor, conn):
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
                (limit,)
            )
            users = cursor.fetchall()

            summary = {
                "processed": 0,
                "sent": 0,
                "no_actionable_alerts": 0,
                "already_sent_today": 0,
                "failed": 0
            }

            for user in users:
                summary["processed"] += 1
                result = send_maintenance_alert_email_for_user(cursor, user, force=force)
                if result["sent"]:
                    summary["sent"] += 1
                elif result["reason"] == "no_actionable_alerts":
                    summary["no_actionable_alerts"] += 1
                elif result["reason"] == "already_sent_today":
                    summary["already_sent_today"] += 1
                else:
                    summary["failed"] += 1

            return jsonify(success=True, force=force, resumo=summary), 200
    except Exception as e:
        logger.error(f"Erro no dispatch automatico de emails de manutencao: {e}")
        return jsonify(error="Erro ao executar dispatch de emails"), 500


@pages_bp.route("/api/user", methods=["DELETE"])
@jwt_required()
def delete_user():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"❌ Erro ao excluir conta: {e}")
        return jsonify(error="Erro ao excluir conta"), 500

@pages_bp.route("/api/chat", methods=["POST"])
@jwt_required()
def chat():
    user_id = get_jwt_identity()
    data = request.get_json()
    msg, img_b64 = data.get("message"), data.get("image")
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return jsonify(error="Usuário não encontrado"), 404
                
            # Trial check removed - everything is free
            
            cursor.execute("SELECT tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            if veiculos:
                user['lista_veiculos'] = veiculos

            resposta = analisar_imagem(img_b64, msg) if img_b64 else gerar_resposta(msg, user_id, user_data=user)
            
            videos = []
            if not img_b64 and msg:
                # Buscar peças
                termo_pecas = gerar_termo_busca_pecas(msg)
                if termo_pecas:
                    pecas_lojas = WebScraper().search_car_parts(termo_pecas)
                    for loja in pecas_lojas:
                        domain = loja['url'].split('//')[-1].split('/')[0]
                        titulo = f"🔧 {domain}"
                        descricao = f"Busca em lojas de peças sugerida pelo NOG"
                        videos.append({'titulo': titulo, 'url': loja['url'], 'descricao': descricao})
                        cursor.execute("""
                            INSERT INTO videos (user_id, titulo, url, descricao)
                            VALUES (%s, %s, %s, %s)
                        """, (user_id, titulo, loja['url'], descricao))

                # Buscar links de lojas de veículos e salvar na base "videos" (cards)
                termo_loja = gerar_termo_busca_loja(msg)
                if termo_loja:
                    lojas = WebScraper().search_car_stores(termo_loja)
                    for loja in lojas:
                        domain = loja['url'].split('//')[-1].split('/')[0]
                        titulo = f"🛒 {domain}"
                        descricao = f"Busca em lojas web sugerida pelo NOG"
                        videos.append({'titulo': titulo, 'url': loja['url'], 'descricao': descricao})
                        cursor.execute("""
                            INSERT INTO videos (user_id, titulo, url, descricao)
                            VALUES (%s, %s, %s, %s)
                        """, (user_id, titulo, loja['url'], descricao))

                if True: # User is always premium
                    termo_busca = gerar_termo_busca_youtube(msg, resposta)
                    if termo_busca:
                        yt_videos = buscar_videos_youtube(termo_busca)
                        for v in yt_videos:
                            videos.append(v)
                            cursor.execute("""
                                INSERT INTO videos (user_id, titulo, url, descricao)
                                VALUES (%s, %s, %s, %s)
                            """, (user_id, v['titulo'], v['url'], "Recomendado pelo NOG IA durante o chat"))
                    
            videos_json = json.dumps(videos) if videos else None
            
            cursor.execute("INSERT INTO chats (user_id, mensagem_usuario, resposta_ia, videos) VALUES (%s, %s, %s, %s)",
                           (user_id, msg or "[Imagem]", resposta, videos_json))
            return jsonify(response=resposta, videos=videos)
    except Exception as e:
        logger.error(f"❌ Erro na rota /api/chat: {e}")
        return jsonify(error="Erro interno ao processar chat."), 500

@pages_bp.route("/api/voice", methods=["POST"])
@jwt_required()
def voice_to_text():
    user_id = get_jwt_identity()
    if 'audio' not in request.files:
        return jsonify(error="Arquivo de áudio não enviado"), 400
    
    audio_file = request.files['audio']
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_file.read()))
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="pt-BR")
            
        logger.info(f"🎙️ Voz transcrita para usuário {user_id}: {text}")
        
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return jsonify(error="Usuário não encontrado"), 404
            
            cursor.execute("SELECT tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            if veiculos:
                user['lista_veiculos'] = veiculos
            
            resposta = gerar_resposta(text, user_id, user_data=user)
            
            videos = []
            # Buscar peças via voz
            termo_pecas = gerar_termo_busca_pecas(text)
            if termo_pecas:
                pecas_lojas = WebScraper().search_car_parts(termo_pecas)
                for loja in pecas_lojas:
                    domain = loja['url'].split('//')[-1].split('/')[0]
                    titulo = f"🔧 {domain}"
                    descricao = f"Busca em lojas de peças sugerida pelo NOG via áudio"
                    videos.append({'titulo': titulo, 'url': loja['url'], 'descricao': descricao})
                    cursor.execute("""
                        INSERT INTO videos (user_id, titulo, url, descricao)
                        VALUES (%s, %s, %s, %s)
                    """, (user_id, titulo, loja['url'], descricao))

            # Buscar links de lojas de automóveis via voz
            termo_loja = gerar_termo_busca_loja(text)
            if termo_loja:
                lojas = WebScraper().search_car_stores(termo_loja)
                for loja in lojas:
                    domain = loja['url'].split('//')[-1].split('/')[0]
                    titulo = f"🛒 {domain}"
                    descricao = f"Busca em lojas sugerida pelo NOG via áudio"
                    videos.append({'titulo': titulo, 'url': loja['url'], 'descricao': descricao})
                    cursor.execute("""
                        INSERT INTO videos (user_id, titulo, url, descricao)
                        VALUES (%s, %s, %s, %s)
                    """, (user_id, titulo, loja['url'], descricao))
            
            if True: # User is always premium
                termo_busca = gerar_termo_busca_youtube(text, resposta)
                if termo_busca:
                    yt_videos = buscar_videos_youtube(termo_busca)
                    for v in yt_videos:
                        videos.append(v)
                        cursor.execute("""
                            INSERT INTO videos (user_id, titulo, url, descricao)
                            VALUES (%s, %s, %s, %s)
                        """, (user_id, v['titulo'], v['url'], "Recomendado pelo NOG IA via comando de voz"))
                
            videos_json = json.dumps(videos) if videos else None
            
            cursor.execute("INSERT INTO chats (user_id, mensagem_usuario, resposta_ia, videos) VALUES (%s, %s, %s, %s)",
                           (user_id, text, resposta, videos_json))
            
            return jsonify(text=text, response=resposta, videos=videos)

    except sr.UnknownValueError:
        return jsonify(error="Não entendi o que você disse"), 422
    except sr.RequestError as e:
        logger.error(f"Erro no serviço de voz do Google: {e}")
        return jsonify(error="Serviço de voz indisponível no momento"), 503
    except Exception as e:
        logger.error(f"Erro no processamento de voz: {e}")
        return jsonify(error="Falha técnica ao processar áudio"), 500

@pages_bp.route("/api/chat/history", methods=["GET"])
@jwt_required()
def get_chat_history():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("""
                SELECT mensagem_usuario, resposta_ia, created_at, videos
                FROM chats 
                WHERE user_id = %s 
                ORDER BY created_at ASC
            """, (user_id,))
            chats = cursor.fetchall()
            for c in chats:
                if isinstance(c['created_at'], datetime):
                    c['created_at'] = c['created_at'].isoformat()
                
                # Parse videos JSON if available
                if c.get('videos'):
                    if isinstance(c['videos'], str):
                        try:
                            c['videos'] = json.loads(c['videos'])
                        except json.JSONDecodeError:
                            c['videos'] = []
                else:
                    c['videos'] = []
                    
            return jsonify(chats=chats), 200
    except Exception as e:
        logger.error(f"❌ Erro ao buscar histórico: {e}")
        return jsonify(error="Erro ao buscar histórico"), 500

@pages_bp.route("/api/dashboard", methods=["GET"])
@jwt_required()
def get_dashboard():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return jsonify(error="Usuário não encontrado"), 404

            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()

            if not veiculos:
                return jsonify(error="VEHICLE_NOT_FOUND"), 404

            cursor.execute("""
                SELECT *
                FROM maintenance_history
                WHERE user_id = %s
                ORDER BY service_date DESC, created_at DESC
            """, (user_id,))
            maintenance_history_rows = cursor.fetchall()
            vehicle_km_map = {v["id"]: v.get("quilometragem") for v in veiculos}
            active_maintenance = consolidate_active_maintenance_records(maintenance_history_rows)
            intelligent_alerts = build_maintenance_alerts(active_maintenance, vehicle_km_map=vehicle_km_map)
            intelligent_alerts_by_vehicle = {}
            for alert in intelligent_alerts:
                v_id = alert.get("vehicle_id")
                if v_id is None:
                    continue
                intelligent_alerts_by_vehicle.setdefault(v_id, []).append(alert)

            resultados = []

            for v in veiculos:
                ano_atual = datetime.now().year
                ano_fab = v["ano_fabricacao"] or ano_atual
                idade = ano_atual - ano_fab

                km = v.get("quilometragem") or 0
                alertas = []

                if idade >= 5:
                    alertas.append({"item": "Suspensão", "status": "Atenção", "msg": "Revisar amortecedores e buchas."})
                if idade >= 3:
                    alertas.append({"item": "Líquido Arrefecimento", "status": "Aviso", "msg": "Troca recomendada a cada 2-3 anos."})

                if km >= 50000:
                    alertas.append({"item": "Correia Dentada", "status": "Atenção", "msg": "Verificar estado da correia dentada/tensor."})
                if km >= 10000:
                    alertas.append({"item": "Óleo do Motor", "status": "Aviso", "msg": "Próximo da revisão periódica (10k km)."})

                alertas.append({"item": "Pneus", "status": "Ok" if idade < 4 and km < 40000 else "Atenção", "msg": "Verificar TWI, validade e desgaste."})
                alertas.append({"item": "Freios", "status": "Ok" if km < 20000 else "Atenção", "msg": "Monitorar pastilhas e discos."})

                vehicle_intelligent_alerts = intelligent_alerts_by_vehicle.get(v["id"], [])
                for ia in vehicle_intelligent_alerts:
                    alertas.append({
                        "item": ia.get("item"),
                        "status": ia.get("status"),
                        "msg": ia.get("msg")
                    })

                tipo_map = {
                    "carro": "carros",
                    "moto": "motos",
                    "caminhao": "caminhoes",
                    "caminhão": "caminhoes"
                }
                v_tipo = v.get("tipo") or "carro"
                tipo_fipe = tipo_map.get(v_tipo.lower(), "carros")

                dados_fipe = get_fipe_value(
                    tipo_fipe,
                    v["marca"],
                    v["modelo"],
                    ano_fab
                )

                if dados_fipe:
                    preco_fipe = dados_fipe.get("Valor", "N/A")
                    mes_fipe = dados_fipe.get("MesReferencia", datetime.now().strftime("%B %Y"))
                else:
                    valor_base = 80000 if v_tipo == "carro" else 30000
                    valor_estimado = valor_base * (0.92 ** idade)
                    preco_fipe = f"R$ {valor_estimado:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    mes_fipe = f"{datetime.now().strftime('%B %Y')} (Estimado)"

                resultados.append({
                    "id": v["id"],
                    "veiculo": {
                        "marca": v["marca"],
                        "modelo": v["modelo"],
                        "ano": ano_fab,
                        "tipo": v_tipo,
                        "quilometragem": km
                    },
                    "saude": alertas,
                    "manutencao_inteligente": vehicle_intelligent_alerts,
                    "fipe": {
                        "preco": preco_fipe,
                        "mes": mes_fipe
                    }
                })

            return jsonify(resultados), 200
    except Exception as e:
        logger.error(f"❌ Erro no dashboard: {e}")
        return jsonify(error="Erro ao carregar dashboard"), 500

@pages_bp.route("/api/report", methods=["POST"])
@jwt_required()
def generate_report_endpoint():
    user_id = get_jwt_identity()
    data = request.get_json()
    text_content = data.get("text")
    
    if not text_content:
        return jsonify(error="Conteúdo do relatório vazio"), 400

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return jsonify(error="Usuário não encontrado"), 404
                
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error
        
        report_dir = os.path.join(current_app.static_folder, 'reports')
        if not os.path.exists(report_dir):
            os.makedirs(report_dir)

        filename = f"laudo_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        filepath = os.path.join(report_dir, filename)
        
        criar_relatorio_pdf(user, text_content, filepath)
        
        return jsonify(url=f"/reports/{filename}"), 200
    except Exception as e:
        logger.error(f"❌ Erro ao gerar relatório: {e}")
        return jsonify(error="Falha na geração do PDF"), 500

@pages_bp.route("/api/videos", methods=["GET"])
@jwt_required()
def get_videos():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return jsonify(error="Usuário não encontrado"), 404
                
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("""
                SELECT id, titulo, url, descricao, created_at
                FROM videos
                WHERE user_id = %s
                ORDER BY created_at DESC
            """, (user_id,))
            videos = cursor.fetchall()
            for v in videos:
                if isinstance(v['created_at'], datetime):
                    v['created_at'] = v['created_at'].isoformat()
            return jsonify(videos=videos), 200
    except Exception as e:
        logger.error(f"❌ Erro ao buscar vídeos: {e}")
        return jsonify(error="Erro ao buscar vídeos"), 500

@pages_bp.route("/api/videos", methods=["POST"])
@jwt_required()
def add_video():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    titulo = (data.get("titulo") or "").strip()
    url = (data.get("url") or "").strip()
    descricao = (data.get("descricao") or "").strip()

    if not titulo or not url:
        return jsonify(error="Título e URL são obrigatórios"), 400

    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return jsonify(error="Usuário não encontrado"), 404
                
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

            cursor.execute("""
                INSERT INTO videos (user_id, titulo, url, descricao)
                VALUES (%s, %s, %s, %s)
            """, (user_id, titulo, url, descricao))
            video_id = cursor.lastrowid
            
            cursor.execute("SELECT * FROM videos WHERE id = %s", (video_id,))
            video = cursor.fetchone()
            if isinstance(video['created_at'], datetime):
                video['created_at'] = video['created_at'].isoformat()
                
            return jsonify(video=video, success=True), 201
    except Exception as e:
        logger.error(f"❌ Erro ao adicionar vídeo: {e}")
        return jsonify(error="Erro ao adicionar vídeo"), 500

@pages_bp.route("/api/videos/<int:video_id>", methods=["DELETE"])
@jwt_required()
def delete_video(video_id):
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user:
                return jsonify(error="Usuário não encontrado"), 404
                
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error
            # Verifica se o vídeo pertence ao usuário
            cursor.execute("SELECT id FROM videos WHERE id = %s AND user_id = %s", (video_id, user_id))
            if not cursor.fetchone():
                return jsonify(error="Vídeo não encontrado ou acesso negado"), 404
                
            cursor.execute("DELETE FROM videos WHERE id = %s AND user_id = %s", (video_id, user_id))
            return jsonify(success=True), 200
    except Exception as e:
        logger.error(f"❌ Erro ao deletar vídeo: {e}")
        return jsonify(error="Erro ao deletar vídeo"), 500

