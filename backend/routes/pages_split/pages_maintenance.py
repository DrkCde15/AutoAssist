"""Split de routes/pages.py — módulo pages_maintenance (P1).

Carregado via exec() em routes/pages.py compartilhando os mesmos globals
(imports, pages_bp, constantes, logger). Não importar diretamente.
"""

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # noqa: F401 — nomes providos em runtime pelos globals de routes/pages.py (exec)
    from datetime import date
    from utils.async_task import _predictor
    from services.maintenance_service import _status_from_remaining
    from services.maintenance_service import apply_manual_overrides
    from routes.notifications import create_notification
    from datetime import datetime
    from utils.email import enviar_email
    from routes.database import get_db
    from flask_jwt_extended import get_jwt_identity
    import html
    import json
    from flask import jsonify
    from flask_jwt_extended import jwt_required
    from functools import lru_cache
    from time import monotonic
    import os
    from services.maintenance_service import parse_maintenance_entry
    from services.nogai import prever_intervalo_manutencao
    from flask import request
    from routes.push import send_push_notification
    from services.maintenance_service import serialize_maintenance_row
    from datetime import timedelta
    from .pages_users import ensure_maintenance_access, ensure_premium_user, get_dashboard_url, get_user_by_id, invalid_session_response
    from ..pages import ACTIONABLE_MAINTENANCE_STATUSES, CRITICAL_MAINTENANCE_STATUSES, MAINTENANCE_DISPATCH_LOCK_NAME, _maintenance_dispatch_thread_lock, logger, pages_bp

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

            maintenance_id = insert_get_id(
                cursor,
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

