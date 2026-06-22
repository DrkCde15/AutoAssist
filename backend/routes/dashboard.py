import os
import logging
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from routes.database import get_db
from services.nogai import get_fipe_value
from utils.async_task import _predictor
from datetime import datetime

# Blueprint for dashboard data (JSON) consumed by front‑end
logger = logging.getLogger(__name__)
dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.get('/dashboard')
@jwt_required()
def get_dashboard_data():
    user_id = get_jwt_identity()
    logger.info(f"Dashboard request from user {user_id}")
    """Return data consumed by *dashboard.html*.

    The structure mirrors what the front‑end template expects:
    - ``veiculo``: basic vehicle info (tipo, marca, modelo, ano_fabricacao, quilometragem)
    - ``fipe``: market value info (Valor, MesReferencia)
    - ``saude``: list of health alerts (empty for now)
    - ``predicao``: result of the predictive maintenance model.
    """
    try:
        # ------------------------------------------------------------------
        # 1️⃣  Fetch user's vehicles (get all, or first if multiple)       
        # ------------------------------------------------------------------
        with get_db() as (cur, _):
            cur.execute(
                "SELECT id, tipo, marca, modelo, ano_fabricacao, quilometragem "
                "FROM veiculos WHERE user_id = %s ORDER BY id LIMIT 1",
                (user_id,)
            )
            vehicle = cur.fetchone()
            
            if not vehicle:
                return jsonify([]), 200

            # Buscar qtde de manutenções
            cur.execute(
                "SELECT COUNT(*) as qtde, MAX(service_date) as last_date FROM maintenance_history WHERE user_id = %s AND vehicle_id = %s",
                (user_id, vehicle["id"])
            )
            maint_data = cur.fetchone() or {"qtde": 0, "last_date": None}

            # Buscar engajamento de chats
            cur.execute("SELECT COUNT(*) as chat_count FROM chats WHERE user_id = %s", (user_id,))
            chat_data = cur.fetchone() or {"chat_count": 0}

        # ------------------------------------------------------------------
        # 2️⃣  FIPE info – fetch from FIPE API
        # ------------------------------------------------------------------
        try:
            fipe_result = get_fipe_value(
                tipo=vehicle.get("tipo"),
                marca_nome=vehicle.get("marca"),
                modelo_nome=vehicle.get("modelo"),
                ano=vehicle.get("ano_fabricacao")
            )
            if fipe_result and "Valor" in fipe_result:
                fipe_info = fipe_result
            else:
                fipe_info = {"Valor": "---", "MesReferencia": "---"}
        except Exception as e:
            logger.warning(f"Failed to fetch FIPE for dashboard: {e}")
            fipe_info = {"Valor": "---", "MesReferencia": "---"}

        # ------------------------------------------------------------------
        # 3️⃣  Predictive maintenance – use the predictor service.
        # ------------------------------------------------------------------
        try:
            pred = _predictor().predict_next(
                vehicle_id=vehicle["id"],
                maintenance_type="troca_oleo",
                kilometers_actual=vehicle.get("quilometragem")
            ) or {}
        except Exception as e:
            logger.warning("Prediction unavailable: %s", e)
            pred = {}

        # ------------------------------------------------------------------
        # 4️⃣  Assemble response structure expected by the UI.
        # ------------------------------------------------------------------
        # Calculate health score (heuristic)
        health_score = 100
        current_year = datetime.now().year
        ano_fab = vehicle.get("ano_fabricacao") or current_year
        km = vehicle.get("quilometragem") or 0
        
        health_score -= (current_year - ano_fab) * 2
        health_score -= (km // 10000) * 1.5
        health_score = max(20, min(100, int(health_score)))
        
        saude_alertas = []
        if health_score < 50:
            saude_alertas.append({"item": "Atenção Geral", "msg": "Seu veículo tem alta quilometragem/idade. Revise com frequência.", "status": "Crítico"})
        elif health_score < 80:
            saude_alertas.append({"item": "Uso Moderado", "msg": "Bom estado, mas fique atento aos prazos de revisão.", "status": "Atenção"})
        else:
            saude_alertas.append({"item": "Ótimo Estado", "msg": "Veículo novo ou pouco rodado. Continue assim!", "status": "OK"})

        response_item = {
            "veiculo": {
                "tipo": vehicle.get("tipo", "geral"),
                "marca": vehicle.get("marca", "---"),
                "modelo": vehicle.get("modelo", "---"),
                "ano_fabricacao": vehicle.get("ano_fabricacao"),
                "quilometragem": vehicle.get("quilometragem"),
            },
            "fipe": fipe_info,
            "saude": saude_alertas,
            "predicao": pred,
            "estatisticas_extras": {
                "manutencoes_realizadas": maint_data.get("qtde", 0),
                "data_ultima_manutencao": maint_data.get("last_date").strftime('%d/%m/%Y') if maint_data.get("last_date") else "Nenhuma",
                "chats_realizados": chat_data.get("chat_count", 0),
                "health_score": health_score
            }
        }
        return jsonify([response_item]), 200
    except Exception as e:
        # Log the error and return an empty payload – the UI shows a generic error.
        logger.error(f"Erro ao gerar dados do dashboard: {e}", exc_info=True)
        return jsonify([]), 500
