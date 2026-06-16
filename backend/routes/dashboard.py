import os
from flask import Blueprint, jsonify
from routes.database import get_db
from services.predictive_maintenance import predictor

# Blueprint for dashboard data (JSON) consumed by front‑end

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.get('/api/dashboard')
def get_dashboard_data():
    """Return data consumed by *dashboard.html*.

    The structure mirrors what the front‑end template expects:
    - ``veiculo``: basic vehicle info (tipo, marca, modelo, ano_fabricacao, quilometragem)
    - ``fipe``: market value info (Valor, MesReferencia)
    - ``saude``: list of health alerts (empty for now)
    - ``predicao``: result of the predictive maintenance model.
    """
    try:
        # ------------------------------------------------------------------
        # 1️⃣  Fetch a representative vehicle (simplified – first row)       
        # ------------------------------------------------------------------
        with get_db() as (cur, _):
            cur.execute(
                "SELECT id, tipo, marca, modelo, ano_fabricacao, quilometragem "
                "FROM veiculos ORDER BY id LIMIT 1"
            )
            vehicle = cur.fetchone()
        if not vehicle:
            # No vehicle registered – front‑end already handles this case.
            return jsonify([]), 200

        # ------------------------------------------------------------------
        # 2️⃣  FIPE info – placeholder (real implementation would call an API)
        # ------------------------------------------------------------------
        fipe_info = {"Valor": "---", "MesReferencia": "---"}

        # ------------------------------------------------------------------
        # 3️⃣  Predictive maintenance – use the predictor service.
        # ------------------------------------------------------------------
        pred = predictor.predict_next(
            vehicle_id=vehicle["id"],
            maintenance_type="oil_change",
            kilometers_actual=vehicle.get("quilometragem")
        ) or {}

        # ------------------------------------------------------------------
        # 4️⃣  Assemble response structure expected by the UI.
        # ------------------------------------------------------------------
        response_item = {
            "veiculo": {
                "tipo": vehicle.get("tipo", "geral"),
                "marca": vehicle.get("marca", "---"),
                "modelo": vehicle.get("modelo", "---"),
                "ano_fabricacao": vehicle.get("ano_fabricacao"),
                "quilometragem": vehicle.get("quilometragem"),
            },
            "fipe": fipe_info,
            "saude": [],  # health alerts could be added later
            "predicao": pred,
        }
        return jsonify([response_item]), 200
    except Exception as e:
        # Log the error and return an empty payload – the UI shows a generic error.
        from backend.app import logger
        logger.error(f"Erro ao gerar dados do dashboard: {e}", exc_info=True)
        return jsonify([]), 500
