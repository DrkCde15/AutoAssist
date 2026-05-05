import os
import io
import html
import logging
import threading
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity
import uuid
import speech_recognition as sr
from pydub import AudioSegment
from services.nogai import (
    gerar_resposta, 
    get_fipe_value, 
    gerar_termo_busca_youtube, 
    gerar_termo_busca_loja, 
    gerar_termo_busca_pecas,
    prever_intervalo_manutencao
)

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
from .database import get_db, is_trial_expired, get_trial_days_remaining, enviar_email, get_mysql_history

pages_bp = Blueprint('pages', __name__)
logger = logging.getLogger(__name__)

PREMIUM_ONLY_ERROR = "Recurso exclusivo para Premium"

def get_user_by_id(cursor, user_id):
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    return cursor.fetchone()

def ensure_premium_user(user):
    if user and bool(user.get("is_premium")):
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
            <a href="https://drkcde15.github.io/AutoAssist/dashboard.html" style="display: inline-block; padding: 14px 28px; background-color: #2563eb; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">Ver Painel Completo</a>
        </div>
    """

def send_maintenance_alert_email_for_user(cursor, user_row, force=False):
    if not user_row.get("email"):
        return {"sent": False, "reason": "missing_email", "alerts_count": 0}
    if not user_row.get("maintenance_email_enabled", True) and not force:
        return {"sent": False, "reason": "disabled", "alerts_count": 0}
    if not should_send_maintenance_email(user_row, force=force):
        return {"sent": False, "reason": "already_sent_today", "alerts_count": 0}

    # Se chamado de uma thread sem cursor, abre nova conexão
    if cursor is None:
        with get_db() as (new_cursor, conn):
            return _send_maintenance_alert_logic(new_cursor, user_row, force)
    else:
        return _send_maintenance_alert_logic(cursor, user_row, force)

def _send_maintenance_alert_logic(cursor, user_row, force):
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
                return jsonify(error="Usuário não encontrado"), 404
            
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
                    send_maintenance_alert_email_for_user(cursor, user_row, force=False)
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
                        kwargs={"force": False}
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
                        kwargs={"force": True} # Forçamos o envio para dar feedback imediato ao usuário
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
                    interval_km = %s, next_due_date = %s, next_due_km = %s, parser_metadata = %s
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
                        kwargs={"force": False}
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
                return jsonify(error="Usuario nao encontrado"), 404
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
                return jsonify(error="Usuario nao encontrado"), 404
            result = send_maintenance_alert_email_for_user(cursor, user, force=True)
            return jsonify(success=result["sent"], reason=result["reason"], alerts_count=result["alerts_count"]), (200 if result["sent"] else 202)
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

    import secrets
    if not cron_secret:
        return jsonify(error="MAINTENANCE_EMAIL_CRON_SECRET nao configurado"), 500
    
    is_valid = secrets.compare_digest(cron_secret, sent_secret) or secrets.compare_digest(cron_secret, bearer_secret)
    if not is_valid:
        return jsonify(error="Nao autorizado"), 401

    payload = request.get_json(silent=True) or {}
    force = bool(payload.get("force", False))
    limit = max(1, min(int(payload.get("limit", 500)), 2000))

    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT id, nome, email, maintenance_email_enabled, maintenance_email_last_sent FROM users WHERE email IS NOT NULL AND email <> '' AND maintenance_email_enabled = TRUE ORDER BY id ASC LIMIT %s", (limit,))
            users = cursor.fetchall()
            summary = {"processed": 0, "sent": 0, "no_actionable_alerts": 0, "already_sent_today": 0, "failed": 0}
            for user in users:
                summary["processed"] += 1
                result = send_maintenance_alert_email_for_user(cursor, user, force=force)
                if result["sent"]: summary["sent"] += 1
                elif result["reason"] == "no_actionable_alerts": summary["no_actionable_alerts"] += 1
                elif result["reason"] == "already_sent_today": summary["already_sent_today"] += 1
                else: summary["failed"] += 1
            return jsonify(success=True, force=force, resumo=summary), 200
    except Exception as e:
        logger.error(f"Erro no dispatch automatico de emails: {e}")
        return jsonify(error="Erro ao executar dispatch"), 500


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
            cursor.execute("SELECT mensagem_usuario, resposta_ia, created_at, videos FROM chats WHERE user_id = %s ORDER BY created_at ASC", (user_id,))
            rows = cursor.fetchall()
            chats = []
            for r in rows:
                v_data = r["videos"]
                if isinstance(v_data, str):
                    try: v_data = json.loads(v_data)
                    except: v_data = []
                chats.append({
                    "mensagem_usuario": r["mensagem_usuario"],
                    "resposta_ia": r["resposta_ia"],
                    "created_at": serialize_datetime_field(r["created_at"]),
                    "videos": v_data or []
                })
            return jsonify(chats=chats), 200
    except Exception as e:
        logger.error(f"Erro no historico: {e}")
        return jsonify(error="Erro interno"), 500

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

from extensions import limiter

@pages_bp.route("/api/chat", methods=["POST"])
@jwt_required()
@limiter.limit("20 per hour")
def chat():
    user_id = get_jwt_identity()
    data = request.get_json()
    msg, img_b64 = data.get("message"), data.get("image")
    try:
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user: return jsonify(error="Usuário não encontrado"), 404
            cursor.execute("SELECT tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            if veiculos: user['lista_veiculos'] = veiculos

            # Recuperar histórico para contextualizar a busca de vídeos e links
            historico_recente = get_mysql_history(user_id, limit=3)
            
            resposta = analisar_imagem(img_b64, msg) if img_b64 else gerar_resposta(msg, user_id, user_data=user)
            videos = []
            links = [] # Novos links de recomendação
            
            # 1. Busca de Vídeos Contextual
            termo_yt = gerar_termo_busca_youtube(msg, historico=historico_recente)
            if termo_yt:
                try:
                    videos_yt = buscar_videos_youtube(termo_yt)
                    if videos_yt:
                        videos.extend(videos_yt)
                except Exception as e:
                    logger.warning(f"Erro ao buscar videos: {e}")

            # 2. Busca de Veículos (Links)
            termo_loja = gerar_termo_busca_loja(msg, historico=historico_recente)
            if termo_loja:
                links.append({
                    "titulo": f"Ver ofertas de {termo_loja}",
                    "url": f"https://www.webmotors.com.br/carros/estoque?q={termo_loja.replace(' ', '%20')}",
                    "tipo": "veiculo",
                    "icon": "fas fa-car"
                })

            # 3. Busca de Peças (Links)
            termo_pecas = gerar_termo_busca_pecas(msg, historico=historico_recente)
            if termo_pecas:
                links.append({
                    "titulo": f"Comprar {termo_pecas} no Mercado Livre",
                    "url": f"https://lista.mercadolivre.com.br/{termo_pecas.replace(' ', '-')}",
                    "tipo": "peca",
                    "icon": "fas fa-tools"
                })

            # Salvar no histórico
            cursor.execute(
                "INSERT INTO chats (user_id, mensagem_usuario, resposta_ia, videos, links) VALUES (%s, %s, %s, %s, %s)",
                (user_id, msg, resposta, json.dumps(videos), json.dumps(links))
            )
            conn.commit()

            return jsonify(response=resposta, videos=videos, links=links)
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
        
        # Gerar resposta da IA
        with get_db() as (cursor, conn):
            user = get_user_by_id(cursor, user_id)
            if not user: return jsonify(error="Usuário não encontrado"), 404
            
            cursor.execute("SELECT tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
            veiculos = cursor.fetchall()
            if veiculos: user['lista_veiculos'] = veiculos

            resposta = analisar_imagem(img_b64, text) if img_b64 else gerar_resposta(text, user_id, user_data=user)
            videos = []
            links = []
            termo_yt = gerar_termo_busca_youtube(text)
            if termo_yt:
                try:
                    videos_yt = buscar_videos_youtube(termo_yt)
                    if videos_yt:
                        videos.extend(videos_yt)
                except Exception as e:
                    logger.warning(f"Erro ao buscar videos (voz): {e}")

            # Salvar no histórico
            cursor.execute(
                "INSERT INTO chats (user_id, mensagem_usuario, resposta_ia, videos) VALUES (%s, %s, %s, %s)",
                (user_id, text, resposta, json.dumps(videos))
            )
            conn.commit()
            
            return jsonify(text=text, response=resposta, videos=videos)
            
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
            premium_error = ensure_premium_user(user)
            if premium_error:
                return premium_error

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
