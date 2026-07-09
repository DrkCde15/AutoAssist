import os
import logging
from datetime import datetime, timedelta, date
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from routes.database import get_db
from services.nogai import get_fipe_value
from utils.async_task import _predictor
from utils.cache import TTLCache

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint('dashboard', __name__)

FIPE_CACHE_HOURS = 24

# Cache do payload do dashboard por usuário (invalidado em writes de manutenção/veículo)
_dashboard_cache = TTLCache(default_ttl=int(os.getenv("DASHBOARD_CACHE_TTL_SECONDS", "30")), maxsize=512)


def _invalidate_dashboard_cache(user_id):
    """Invalida o dashboard em cache de um usuário (após editar manutenção/veículo)."""
    _dashboard_cache.delete(user_id)


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


def _compute_health_score(row):
    current_year = datetime.now().year
    ano_fab = row.get("ano_fabricacao") or current_year
    km = row.get("quilometragem") or 0
    return max(20, min(100, int(
        100 - (current_year - ano_fab) * 2 - (km // 10000) * 1.5
    )))


def _is_today(dt):
    if dt is None:
        return False
    d = dt.date() if isinstance(dt, datetime) else dt
    return d == date.today()


def _next_maint_type_from_hist(hist):
    """Tipo de manutenção com o next_due_date mais próximo (calculado em memória)."""
    candidates = [h for h in hist if h.get("next_due_date") is not None]
    if not candidates:
        return "troca_oleo"
    candidates.sort(key=lambda h: h["next_due_date"])
    return candidates[0].get("maintenance_type") or "troca_oleo"


def _vehicle_averages_from_hist(hist):
    """Médias de km/dias entre registros consecutivos (espelha _get_vehicle_averages)."""
    if len(hist) < 2:
        return None, None
    diffs_km, diffs_days = [], []
    for i in range(1, len(hist)):
        km1 = hist[i].get("service_km")
        km0 = hist[i - 1].get("service_km")
        if km1 is not None and km0 is not None:
            diffs_km.append(km1 - km0)
        d1 = hist[i].get("service_date")
        d0 = hist[i - 1].get("service_date")
        if d1 is not None and d0 is not None:
            try:
                diffs_days.append((d1 - d0).days)
            except Exception:
                pass
    if not diffs_km or not diffs_days:
        return None, None
    return float(sum(diffs_km) / len(diffs_km)), float(sum(diffs_days) / len(diffs_days))


def _prepare_predictions(rows, hist_por_veiculo):
    """Predição para todos os veículos de uma vez (sem N queries ao banco)."""
    result = {}
    for row in rows:
        vid = row["id"]
        hist = hist_por_veiculo.get(vid, [])
        maint_type = _next_maint_type_from_hist(hist)
        avg_km, avg_days = _vehicle_averages_from_hist(hist)
        pred = _predictor().predict_next(
            vehicle_id=vid,
            maintenance_type=maint_type,
            kilometers_actual=row.get("quilometragem"),
            vehicle_averages=(avg_km, avg_days),
            record_count=len(hist),
        ) or {}
        try:
            from services.maintenance_service import MAINTENANCE_RULES
            pred["maintenance_label"] = MAINTENANCE_RULES.get(maint_type, {}).get("label", maint_type)
        except Exception:
            pred["maintenance_label"] = maint_type
        result[vid] = pred
    return result


def _build_vehicle_dashboard(row, health_score, pred):
    """Processa os dados de um único veículo para o dashboard (sem acesso a banco)."""
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

    if health_score < 50:
        alertas = [{"item": "Atenção Geral", "msg": "Seu veículo tem alta quilometragem/idade. Revise com frequência.", "status": "Crítico"}]
    elif health_score < 80:
        alertas = [{"item": "Uso Moderado", "msg": "Bom estado, mas fique atento aos prazos de revisão.", "status": "Atenção"}]
    else:
        alertas = [{"item": "Ótimo Estado", "msg": "Veículo novo ou pouco rodado. Continue assim!", "status": "OK"}]

    ultima = row.get("ultima_manutencao")
    data_ultima = ultima.strftime('%d/%m/%Y') if ultima else "Nenhuma"

    return {
        "veiculo": vehicle,
        "fipe": fipe_info,
        "saude": alertas,
        "predicao": pred or {},
        "estatisticas_extras": {
            "manutencoes_realizadas": row.get("qtde_manutencao", 0),
            "data_ultima_manutencao": data_ultima,
            "chats_realizados": row.get("qtde_chats", 0),
            "health_score": health_score,
        },
    }


def _bulk_record_health_score(records):
    """Grava health scores pendentes em uma única query (1x/dia por veículo)."""
    if not records:
        return
    try:
        with get_db() as (cur, conn):
            cur.executemany(
                "INSERT INTO health_score_history (user_id, vehicle_id, score) VALUES (%s, %s, %s)",
                records,
            )
            conn.commit()
    except Exception:
        pass


@dashboard_bp.get('/dashboard')
@jwt_required()
def get_dashboard_data():
    user_id = get_jwt_identity()
    logger.info(f"Dashboard request from user {user_id}")

    cached = _dashboard_cache.get(user_id)
    if cached is not None:
        return jsonify(cached), 200

    try:
        with get_db() as (cur, conn):
            # 1) Veículos agregados (1 query)
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
                _dashboard_cache.set(user_id, [])
                return jsonify([]), 200

            # 2) Histórico de manutenção do usuário (1 query, todos os veículos)
            cur.execute(
                "SELECT vehicle_id, maintenance_type, service_date, service_km, next_due_date "
                "FROM maintenance_history WHERE user_id=%s ORDER BY vehicle_id, service_date ASC",
                (user_id,),
            )
            hist_rows = cur.fetchall()

            # 3) Último registro de health score por veículo (1 query)
            cur.execute(
                "SELECT vehicle_id, MAX(recorded_at) AS last_recorded FROM health_score_history "
                "WHERE user_id=%s GROUP BY vehicle_id",
                (user_id,),
            )
            health_last = {r["vehicle_id"]: r["last_recorded"] for r in cur.fetchall()}

        # Agrupa histórico por veículo em Python (sem DB)
        from collections import defaultdict
        hist_por_veiculo = defaultdict(list)
        for hr in hist_rows:
            hist_por_veiculo[hr["vehicle_id"]].append(hr)

        # Predições para todos os veículos (sem N queries)
        predictions = _prepare_predictions(rows, hist_por_veiculo)

        items = []
        pending_health = []
        for row in rows:
            vid = row["id"]
            health_score = _compute_health_score(row)
            items.append(_build_vehicle_dashboard(row, health_score, predictions.get(vid)))
            if not _is_today(health_last.get(vid)):
                pending_health.append((user_id, vid, health_score))

        # Grava pendentes em 1 única query
        _bulk_record_health_score(pending_health)

        _dashboard_cache.set(user_id, items)
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
