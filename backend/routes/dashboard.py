import os
import logging
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from routes.database import get_db
from services.nogai import get_fipe_value
from utils.async_task import _predictor

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint('dashboard', __name__)

FIPE_CACHE_HOURS = 24


def _refresh_fipe(vehicle_id, tipo, marca, modelo, ano):
    try:
        from redis import Redis
        from rq import Queue
        redis_url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI", "redis://localhost:6379/0")
        if redis_url != "memory://":
            q = Queue("default", connection=Redis.from_url(redis_url))
            q.enqueue("tasks.refresh_fipe", vehicle_id, tipo, marca, modelo, ano)
        else:
            _refresh_fipe_sync(vehicle_id, tipo, marca, modelo, ano)
    except Exception:
        _refresh_fipe_sync(vehicle_id, tipo, marca, modelo, ano)


def _refresh_fipe_sync(vehicle_id, tipo, marca, modelo, ano):
    try:
        fipe = get_fipe_value(tipo, marca, modelo, ano)
        if fipe and "Valor" in fipe:
            with get_db() as (cur, conn):
                cur.execute(
                    "UPDATE veiculos SET fipe_valor=%s, fipe_mes_referencia=%s, "
                    "fipe_updated_at=NOW() WHERE id=%s",
                    (fipe["Valor"], fipe.get("MesReferencia", ""), vehicle_id),
                )
                conn.commit()
    except Exception:
        pass


def _get_next_maintenance_type(vehicle_id):
    """Retorna o tipo de manutenção mais próximo do vencimento do veículo."""
    try:
        with get_db() as (cur, conn):
            cur.execute(
                "SELECT maintenance_type FROM maintenance_history "
                "WHERE vehicle_id=%s AND next_due_date IS NOT NULL "
                "ORDER BY next_due_date ASC LIMIT 1",
                (vehicle_id,),
            )
            row = cur.fetchone()
            if row and row.get("maintenance_type"):
                return row["maintenance_type"]
    except Exception:
        pass
    return "troca_oleo"


def _build_vehicle_dashboard(user_id, row):
    """Processa os dados de um único veículo para o dashboard."""
    vehicle = {
        "id": row["id"],
        "tipo": row["tipo"],
        "marca": row["marca"],
        "modelo": row["modelo"],
        "ano_fabricacao": row["ano_fabricacao"],
        "quilometragem": row["quilometragem"],
    }

    # FIPE — usa cache se <24h, dispara refresh em background se stale
    fipe_updated = row.get("fipe_updated_at")
    fipe_stale = (
        fipe_updated is None
        or (datetime.now() - fipe_updated) > timedelta(hours=FIPE_CACHE_HOURS)
    )

    if fipe_stale:
        _refresh_fipe(row["id"], row["tipo"], row["marca"], row["modelo"], row["ano_fabricacao"])

    if row.get("fipe_valor"):
        fipe_info = {
            "Valor": row["fipe_valor"],
            "MesReferencia": row.get("fipe_mes_referencia", "---"),
        }
    else:
        fipe_info = {"Valor": "Não listado na Tabela FIPE", "MesReferencia": "---"}

    # Predição — usa o tipo de manutenção mais próximo do vencimento
    maint_type = _get_next_maintenance_type(row["id"])
    try:
        pred = _predictor().predict_next(
            vehicle_id=row["id"],
            maintenance_type=maint_type,
            kilometers_actual=row.get("quilometragem"),
        ) or {}
    except Exception as e:
        logger.warning("Prediction unavailable: %s", e)
        pred = {}

    if pred:
        try:
            from services.maintenance_service import MAINTENANCE_RULES
            pred["maintenance_label"] = MAINTENANCE_RULES.get(maint_type, {}).get("label", maint_type)
        except Exception:
            pred["maintenance_label"] = maint_type

    # Health score
    current_year = datetime.now().year
    ano_fab = row.get("ano_fabricacao") or current_year
    km = row.get("quilometragem") or 0

    health_score = max(20, min(100, int(
        100 - (current_year - ano_fab) * 2 - (km // 10000) * 1.5
    )))

    if health_score < 50:
        alertas = [{"item": "Atenção Geral", "msg": "Seu veículo tem alta quilometragem/idade. Revise com frequência.", "status": "Crítico"}]
    elif health_score < 80:
        alertas = [{"item": "Uso Moderado", "msg": "Bom estado, mas fique atento aos prazos de revisão.", "status": "Atenção"}]
    else:
        alertas = [{"item": "Ótimo Estado", "msg": "Veículo novo ou pouco rodado. Continue assim!", "status": "OK"}]

    ultima = row.get("ultima_manutencao")
    data_ultima = ultima.strftime('%d/%m/%Y') if ultima else "Nenhuma"

    # Health score mantido no histórico no máximo 1x/dia por veículo
    _record_health_score(user_id, row["id"], health_score)

    return {
        "veiculo": vehicle,
        "fipe": fipe_info,
        "saude": alertas,
        "predicao": pred,
        "estatisticas_extras": {
            "manutencoes_realizadas": row.get("qtde_manutencao", 0),
            "data_ultima_manutencao": data_ultima,
            "chats_realizados": row.get("qtde_chats", 0),
            "health_score": health_score,
        },
    }


def _record_health_score(user_id, vehicle_id, score):
    """Insere o health score no histórico apenas 1x por dia por veículo."""
    try:
        with get_db() as (cur, conn):
            cur.execute(
                "SELECT 1 FROM health_score_history "
                "WHERE user_id=%s AND vehicle_id=%s AND DATE(recorded_at)=CURDATE() LIMIT 1",
                (user_id, vehicle_id),
            )
            if cur.fetchone():
                return
            cur.execute(
                "INSERT INTO health_score_history (user_id, vehicle_id, score) VALUES (%s, %s, %s)",
                (user_id, vehicle_id, score),
            )
            conn.commit()
    except Exception:
        pass


@dashboard_bp.get('/dashboard')
@jwt_required()
def get_dashboard_data():
    user_id = get_jwt_identity()
    logger.info(f"Dashboard request from user {user_id}")

    try:
        # Todos os veículos do usuário (um registro agregado por veículo)
        with get_db() as (cur, conn):
            cur.execute(
                """SELECT v.id, v.tipo, v.marca, v.modelo,
                          v.ano_fabricacao, v.quilometragem,
                          v.fipe_valor, v.fipe_mes_referencia, v.fipe_updated_at,
                          COUNT(mh.id) AS qtde_manutencao,
                          MAX(mh.service_date) AS ultima_manutencao,
                          (SELECT COUNT(*) FROM chats WHERE user_id=%s) AS qtde_chats
                   FROM veiculos v
                   LEFT JOIN maintenance_history mh ON mh.vehicle_id=v.id
                   WHERE v.user_id=%s
                   GROUP BY v.id
                   ORDER BY v.id""",
                (user_id, user_id),
            )
            rows = cur.fetchall()

        if not rows:
            return jsonify([]), 200

        items = [_build_vehicle_dashboard(user_id, row) for row in rows]
        return jsonify(items), 200

    except Exception as e:
        logger.error(f"Erro ao gerar dados do dashboard: {e}", exc_info=True)
        return jsonify([]), 500


@dashboard_bp.get("/dashboard/health-trend")
@jwt_required()
def health_trend():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cur, conn):
            cur.execute(
                "SELECT vehicle_id, score, recorded_at FROM health_score_history "
                "WHERE user_id = %s ORDER BY recorded_at DESC LIMIT 30",
                (user_id,),
            )
            rows = cur.fetchall()
        return jsonify([{
            "vehicle_id": r["vehicle_id"],
            "score": r["score"],
            "recorded_at": r["recorded_at"].isoformat() if r.get("recorded_at") else None,
        } for r in reversed(rows)]), 200
    except Exception as e:
        logger.error("Erro ao buscar health trend: %s", e)
        return jsonify([]), 200
