import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# ── torna o backend importavel ──────────────────────────────────────────────
BACKEND = Path("/opt/airflow/backend")
sys.path.insert(0, str(BACKEND))

import importlib.util
import types

# Stubs para evitar carregar o package `routes` inteiro (Flask/passlib/etc).
_routes_pkg = types.ModuleType("routes")
_routes_pkg.__path__ = [str(BACKEND / "routes")]
sys.modules.setdefault("routes", _routes_pkg)

_database_spec = importlib.util.spec_from_file_location(
    "routes.database", BACKEND / "routes" / "database.py"
)
database_mod = importlib.util.module_from_spec(_database_spec)
sys.modules.setdefault("routes.database", database_mod)
_database_spec.loader.exec_module(database_mod)

import config as _config  # noqa: E402

sys.modules.setdefault("config", _config)

# Carrega o preditor isoladamente.
_predictor_spec = importlib.util.spec_from_file_location(
    "predictive_maintenance", BACKEND / "services" / "predictive_maintenance.py"
)
predictive_maintenance = importlib.util.module_from_spec(_predictor_spec)
sys.modules.setdefault("predictive_maintenance", predictive_maintenance)
_predictor_spec.loader.exec_module(predictive_maintenance)
MaintenancePredictor = predictive_maintenance.MaintenancePredictor

default_args = {
    "owner": "autoassist",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "start_date": datetime(2026, 1, 1),
}


def extract_training_data(**context):
    """ETL: extrai o historico de manutencoes do MySQL."""
    predictor = MaintenancePredictor()
    data = predictor.fetch_training_data()
    context["ti"].xcom_push(key="record_count", value=len(data))
    print(f"[EXTRACT] {len(data)} registros de manutencao encontrados.")
    return len(data)


def train_model(**context):
    """ML: treina e salva os modelos/parametros leves em PREDICTIVE_MODEL_DIR."""
    predictor = MaintenancePredictor()
    ok = predictor.train()
    context["ti"].xcom_push(key="trained", value=bool(ok))
    print("[TRAIN] concluido." if ok else "[TRAIN] insuficiente para treinar.")
    return ok


def predict_batch(**context):
    """Inferencia em lote: gera predicoes para todos os veiculos com historico."""
    import pymysql
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")
    cfg = dict(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER", ""),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", ""),
        charset="utf8mb4",
    )
    predictor = MaintenancePredictor()
    predictions = []
    try:
        conn = pymysql.connect(**cfg)
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT DISTINCT vehicle_id FROM maintenance_history")
            vehicle_ids = [r["vehicle_id"] for r in cur.fetchall()]
        conn.close()

        for vid in vehicle_ids:
            pred = predictor.predict_next(vehicle_id=vid)
            if pred:
                pred["vehicle_id"] = vid
                predictions.append(pred)
    except Exception as e:
        print(f"[PREDICT] erro ao prever em lote: {e}")
        return []

    out_dir = Path(os.getenv("PREDICTIVE_MODEL_DIR", "/opt/airflow/backend/models/predictive"))
    out_path = out_dir / "predictions_batch.json"
    out_path.write_text(__import__("json").dumps(predictions, indent=2, default=str), encoding="utf-8")
    print(f"[PREDICT] {len(predictions)} predicoes salvas em {out_path}")
    context["ti"].xcom_push(key="prediction_count", value=len(predictions))
    return len(predictions)


def anomaly_scan(**context):
    """Detecta anomalias nos registros de manutencao mais recentes."""
    import pymysql
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")
    cfg = dict(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER", ""),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", ""),
        charset="utf8mb4",
    )
    predictor = MaintenancePredictor()
    anomalies = []
    try:
        conn = pymysql.connect(**cfg)
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT id, vehicle_id, maintenance_type, service_km, cost "
                "FROM maintenance_history ORDER BY service_date DESC LIMIT 50"
            )
            rows = cur.fetchall()
        conn.close()

        for r in rows:
            prev_km = r.get("service_km")
            result = predictor.detect_anomaly(
                {
                    "maintenance_type": r.get("maintenance_type"),
                    "km_diff": prev_km,
                    "cost": r.get("cost") or 0,
                }
            )
            if result.get("anomaly_detected"):
                anomalies.append({"id": r.get("id"), "vehicle_id": r.get("vehicle_id"), **result})
    except Exception as e:
        print(f"[ANOMALY] erro: {e}")
        return []

    if anomalies:
        print(f"[ANOMALY] {len(anomalies)} anomalias detectadas:")
        for a in anomalies:
            print(f"  - veiculo {a['vehicle_id']}: {a['reason']}")
    else:
        print("[ANOMALY] nenhuma anomalia detectada.")
    context["ti"].xcom_push(key="anomaly_count", value=len(anomalies))
    return len(anomalies)


with DAG(
    dag_id="predictive_pipeline",
    default_args=default_args,
    description="ETL + ML do modelo preditivo de manutencao do AutoAssist",
    schedule="0 3 * * *",
    catchup=False,
    tags=["autoassist", "ml", "predictive"],
) as dag:

    t_extract = PythonOperator(task_id="extract_training_data", python_callable=extract_training_data)
    t_train = PythonOperator(task_id="train_model", python_callable=train_model)
    t_predict = PythonOperator(task_id="predict_batch", python_callable=predict_batch)
    t_anomaly = PythonOperator(task_id="anomaly_scan", python_callable=anomaly_scan)

    t_extract >> t_train >> [t_predict, t_anomaly]
