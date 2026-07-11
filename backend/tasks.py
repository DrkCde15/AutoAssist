import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def train_model():
    from utils.async_task import _predictor
    try:
        _predictor().train()
    except Exception as e:
        logger.warning("Falha ao treinar modelo em background: %s", e)

def refresh_fipe(vehicle_id, tipo, marca, modelo, ano):
    from services.nogai import get_fipe_value
    from routes.database import get_db
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

def dispatch_maintenance_emails(user_id=None):
    from routes.pages import _dispatch_maintenance_emails_background
    _dispatch_maintenance_emails_background(user_id=user_id)

def send_maintenance_alert_email(user_row, force=False, status_codes=None, transition_only=True):
    from routes.pages import send_maintenance_alert_email_for_user
    send_maintenance_alert_email_for_user(
        cursor=None,
        user_row=user_row,
        force=force,
        status_codes=status_codes,
        transition_only=transition_only,
    )

def save_health_score(user_id, vehicle_id, health_score):
    from routes.database import get_db
    try:
        with get_db() as (cur, conn):
            cur.execute(
                "INSERT INTO health_score_history (user_id, vehicle_id, score) VALUES (%s, %s, %s)",
                (user_id, vehicle_id, health_score),
            )
            conn.commit()
    except Exception as e:
        logger.warning("Erro ao salvar health score: %s", e)
