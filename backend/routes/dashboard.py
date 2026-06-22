import os
import logging
import threading
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
    """Busca FIPE em background e atualiza o cache no banco."""
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


@dashboard_bp.get('/dashboard')
@jwt_required()
def get_dashboard_data():
    user_id = get_jwt_identity()
    logger.info(f"Dashboard request from user {user_id}")

    try:
        # 1️⃣  Tudo em uma única query com JOIN
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
                   ORDER BY v.id LIMIT 1""",
                (user_id, user_id),
            )
            row = cur.fetchone()

        if not row:
            return jsonify([]), 200

        vehicle = {
            "id": row["id"],
            "tipo": row["tipo"],
            "marca": row["marca"],
            "modelo": row["modelo"],
            "ano_fabricacao": row["ano_fabricacao"],
            "quilometragem": row["quilometragem"],
        }

        # 2️⃣  FIPE — usa cache se <24h, dispara refresh em background se stale
        fipe_updated = row.get("fipe_updated_at")
        fipe_stale = (
            fipe_updated is None
            or (datetime.now() - fipe_updated) > timedelta(hours=FIPE_CACHE_HOURS)
        )

        if fipe_stale:
            threading.Thread(
                target=_refresh_fipe,
                args=(
                    row["id"],
                    row["tipo"],
                    row["marca"],
                    row["modelo"],
                    row["ano_fabricacao"],
                ),
                daemon=True,
            ).start()

        if row.get("fipe_valor"):
            fipe_info = {
                "Valor": row["fipe_valor"],
                "MesReferencia": row.get("fipe_mes_referencia", "---"),
            }
        else:
            fipe_info = {"Valor": "---", "MesReferencia": "---"}

        # 3️⃣  Predição
        try:
            pred = _predictor().predict_next(
                vehicle_id=row["id"],
                maintenance_type="troca_oleo",
                kilometers_actual=row.get("quilometragem"),
            ) or {}
        except Exception as e:
            logger.warning("Prediction unavailable: %s", e)
            pred = {}

        # 4️⃣  Health score e resposta
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

        return jsonify([{
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
        }]), 200

    except Exception as e:
        logger.error(f"Erro ao gerar dados do dashboard: {e}", exc_info=True)
        return jsonify([]), 500
