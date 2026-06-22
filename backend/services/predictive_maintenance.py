import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import logging
from routes.database import get_db
from config import PREDICTIVE_MODEL_DIR, MIN_RECORDS_FOR_PREDICTION

_base_logger = logging.getLogger(__name__)
logger = logging.LoggerAdapter(_base_logger, {"component": "predictive_maintenance"})

pd.set_option('future.no_silent_downcasting', True)

# ─── constantes de fallback (usadas se não houver dados) ─────────────────
_DEFAULT_KM_INTERVAL = 10000
_DEFAULT_DAYS_INTERVAL = 180
_CONFIDENCE_LOW = 0.15

# ─── arquivos de parâmetros leves ────────────────────────────────────────
_PARAMS_FILE = PREDICTIVE_MODEL_DIR / "params.json"
_CLASSES_FILE = PREDICTIVE_MODEL_DIR / "classes.npy"
_SCALER_MEAN_FILE = PREDICTIVE_MODEL_DIR / "scaler_mean.npy"
_SCALER_STD_FILE = PREDICTIVE_MODEL_DIR / "scaler_std.npy"


class MaintenancePredictor:
    def __init__(self) -> None:
        PREDICTIVE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self._params: dict | None = None
        self._classes: list[str] | None = None
        self._scaler_mean: np.ndarray | None = None
        self._scaler_std: np.ndarray | None = None

    # ── carregamento leve (nunca importa sklearn) ──────────────────────────

    def _load_params(self) -> bool:
        try:
            if _PARAMS_FILE.exists():
                with open(_PARAMS_FILE, "r", encoding="utf-8") as f:
                    self._params = json.load(f)
            if _CLASSES_FILE.exists():
                arr = np.load(_CLASSES_FILE, allow_pickle=False)
                self._classes = arr.tolist() if arr.ndim == 1 else []
            if _SCALER_MEAN_FILE.exists():
                self._scaler_mean = np.load(_SCALER_MEAN_FILE, allow_pickle=False)
            if _SCALER_STD_FILE.exists():
                self._scaler_std = np.load(_SCALER_STD_FILE, allow_pickle=False)
            return self._params is not None
        except Exception as e:
            logger.warning("Falha ao carregar parâmetros leves: %s", e)
            return False

    def _get_type_stats(self, maint_type: str) -> dict:
        if self._params and maint_type in self._params:
            return self._params[maint_type]
        return {"avg_km": _DEFAULT_KM_INTERVAL, "avg_days": _DEFAULT_DAYS_INTERVAL}

    def _get_type_encoded(self, maint_type: str) -> int:
        if self._classes and maint_type in self._classes:
            return self._classes.index(maint_type)
        return 0

    # ── dados de treino ────────────────────────────────────────────────────

    def fetch_training_data(self):
        try:
            with get_db() as (cursor, conn):
                cursor.execute(
                    "SELECT vehicle_id, maintenance_type, service_date, service_km, cost FROM maintenance_history"
                )
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao buscar dados para treinamento: {e}")
            return []

    # ── treino (usa sklearn — só é chamado explicitamente) ─────────────────

    def train(self, history_data=None):
        # Import sklearn SOMENTE dentro deste método
        from sklearn.ensemble import RandomForestRegressor, IsolationForest
        from sklearn.preprocessing import LabelEncoder, StandardScaler
        from sklearn.metrics import mean_absolute_error
        import joblib

        if history_data is None:
            history_data = self.fetch_training_data()

        if len(history_data) < MIN_RECORDS_FOR_PREDICTION:
            logger.warning(
                "Not enough historical records (%d) for training; minimum required is %d.",
                len(history_data),
                MIN_RECORDS_FOR_PREDICTION,
            )
            return False

        df = pd.DataFrame(history_data)
        df = self._prepare_features(df)

        if len(df) < 4:
            logger.warning("Not enough valid intervals (%d) after feature preparation.", len(df))
            return False

        le = LabelEncoder()
        scaler = StandardScaler()

        df['type_encoded'] = le.fit_transform(df['maintenance_type'])

        X = df[['type_encoded', 'service_km', 'km_per_day']]
        y_km = df['km_diff']
        y_days = df['days_diff']

        split_idx = int(len(df) * 0.8)
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_km_train, y_km_test = y_km.iloc[:split_idx], y_km.iloc[split_idx:]
        y_days_train, y_days_test = y_days.iloc[:split_idx], y_days.iloc[split_idx:]

        scaler.fit(X_train)
        X_train_scaled = scaler.transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        model_km = RandomForestRegressor(n_estimators=100, random_state=42)
        model_km.fit(X_train_scaled, y_km_train)

        model_date = RandomForestRegressor(n_estimators=100, random_state=42)
        model_date.fit(X_train_scaled, y_days_train)

        km_mae = mean_absolute_error(y_km_test, model_km.predict(X_test_scaled))
        days_mae = mean_absolute_error(y_days_test, model_date.predict(X_test_scaled))
        logger.info(
            "Test MAE — km: %.1f, days: %.1f (on %d records)",
            km_mae, days_mae, len(X_test),
        )

        X_anomaly = df[['type_encoded', 'km_diff', 'cost']]
        iso_forest = IsolationForest(contamination=0.1, random_state=42)
        iso_forest.fit(X_anomaly)

        # Salva modelos sklearn (pesados, usados só em re-treinos)
        joblib.dump(model_km, PREDICTIVE_MODEL_DIR / "model_km.pkl")
        joblib.dump(model_date, PREDICTIVE_MODEL_DIR / "model_date.pkl")
        joblib.dump(iso_forest, PREDICTIVE_MODEL_DIR / "model_anomaly.pkl")
        joblib.dump(le, PREDICTIVE_MODEL_DIR / "label_encoder.pkl")
        joblib.dump(scaler, PREDICTIVE_MODEL_DIR / "scaler.pkl")

        # Salva parâmetros leves (numpy/json — carregados sem sklearn)
        self._save_lightweight_params(df, le, scaler)

        return True

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values(["vehicle_id", "service_date"]).reset_index(drop=True)
        df['service_date'] = pd.to_datetime(df['service_date'])

        df['prev_km'] = df.groupby('vehicle_id')['service_km'].shift(1)
        df['prev_date'] = df.groupby('vehicle_id')['service_date'].shift(1)

        df['km_diff'] = df['service_km'] - df['prev_km']
        df['days_diff'] = (df['service_date'] - df['prev_date']).dt.days
        df['km_per_day'] = df['km_diff'] / df['days_diff'].replace(0, np.nan)

        df = df.dropna(subset=['km_diff', 'days_diff', 'km_per_day'])
        df = df.replace([np.inf, -np.inf], np.nan).fillna(0)

        return df

    def _save_lightweight_params(self, df: pd.DataFrame, le, scaler) -> None:
        """Salva parâmetros leves que podem ser carregados sem sklearn."""
        # Per-type averages
        params = {}
        for mt in df['maintenance_type'].unique():
            subset = df[df['maintenance_type'] == mt]
            params[mt] = {
                "avg_km": float(subset['km_diff'].mean()),
                "avg_days": float(subset['days_diff'].mean()),
                "count": int(len(subset)),
            }
        with open(_PARAMS_FILE, "w", encoding="utf-8") as f:
            json.dump(params, f, indent=2)

        # Label encoder classes
        classes = le.classes_.tolist() if hasattr(le, "classes_") else []
        np.save(_CLASSES_FILE, np.array(classes, dtype=str), allow_pickle=False)

        # Scaler params
        np.save(_SCALER_MEAN_FILE, scaler.mean_, allow_pickle=False)
        np.save(_SCALER_STD_FILE, scaler.scale_, allow_pickle=False)

        logger.info("Parâmetros leves salvos (%d tipos, %d classes)", len(params), len(classes))

    # ── predição leve (numpy only) ─────────────────────────────────────────

    def predict_next(
        self,
        vehicle_id: int,
        maintenance_type: str = "oil_change",
        kilometers_actual: int | None = None,
    ) -> dict | None:
        try:
            if self._params is None:
                self._load_params()

            # Quilometragem atual
            if kilometers_actual is not None:
                current_km = kilometers_actual
            else:
                with get_db() as (cursor, conn):
                    cursor.execute(
                        "SELECT quilometragem FROM veiculos WHERE id = %s",
                        (vehicle_id,),
                    )
                    vehicle = cursor.fetchone()
                    if not vehicle:
                        return None
                    current_km = vehicle["quilometragem"]
            current_km = int(current_km or 0)

            # Busca histórico recente do veículo para ajuste personalizado
            vehicle_avg_km, vehicle_avg_days = self._get_vehicle_averages(vehicle_id)

            # Estatísticas por tipo de manutenção
            type_stats = self._get_type_stats(maintenance_type)

            # Pesos: quanto mais histórico do veículo, mais peso ele tem
            km_interval = (
                vehicle_avg_km * 0.7 + type_stats["avg_km"] * 0.3
                if vehicle_avg_km
                else type_stats["avg_km"]
            )
            days_interval = (
                vehicle_avg_days * 0.7 + type_stats["avg_days"] * 0.3
                if vehicle_avg_days
                else type_stats["avg_days"]
            )

            # Confiança baseada na quantidade de dados do veículo
            confidence = _CONFIDENCE_LOW
            with get_db() as (cursor, conn):
                cursor.execute(
                    "SELECT COUNT(*) AS cnt FROM maintenance_history WHERE vehicle_id = %s",
                    (vehicle_id,),
                )
                row = cursor.fetchone()
                count = row["cnt"] if row else 0
                confidence = min(0.95, 0.15 + count * 0.05)

            return {
                "predicted_next_km": int(current_km + km_interval),
                "predicted_next_date": (
                    datetime.now() + timedelta(days=int(days_interval))
                ).strftime("%Y-%m-%d"),
                "confidence": round(confidence, 2),
                "maintenance_type_used": maintenance_type,
            }
        except Exception as e:
            logger.error(f"Erro na inferência preditiva: {e}")
            return None

    def _get_vehicle_averages(self, vehicle_id: int) -> tuple[float | None, float | None]:
        try:
            with get_db() as (cursor, conn):
                cursor.execute(
                    """SELECT service_km, service_date FROM maintenance_history
                       WHERE vehicle_id = %s ORDER BY service_date ASC""",
                    (vehicle_id,),
                )
                rows = cursor.fetchall()
                if len(rows) < 2:
                    return None, None
                diffs_km = []
                diffs_days = []
                for i in range(1, len(rows)):
                    diffs_km.append(rows[i]["service_km"] - rows[i - 1]["service_km"])
                    diffs_days.append(
                        (rows[i]["service_date"] - rows[i - 1]["service_date"]).days
                    )
                return float(np.mean(diffs_km)), float(np.mean(diffs_days))
        except Exception:
            return None, None

    # ── detecção de anomalia (regras simples, sem sklearn) ─────────────────

    def detect_anomaly(self, maintenance_record: dict) -> dict:
        try:
            km_diff = maintenance_record.get("km_diff", 0)
            cost = maintenance_record.get("cost", 0)

            if km_diff is not None and km_diff < 2000:
                return {
                    "anomaly_detected": True,
                    "reason": f"Manutenção realizada precocemente (apenas {km_diff} km desde a última).",
                }

            # Verifica se o custo está >3 desvios acima da média do tipo
            maint_type = maintenance_record.get("maintenance_type", "")
            type_stats = self._get_type_stats(maint_type)
            if cost and type_stats.get("avg_cost"):
                if cost > type_stats["avg_cost"] * 2.5:
                    return {
                        "anomaly_detected": True,
                        "reason": f"Custo ({cost}) muito acima da média para {maint_type}.",
                    }

            return {"anomaly_detected": False}
        except Exception:
            return {"anomaly_detected": False}

    # ── métricas do veículo (usado externamente) ───────────────────────────

    def get_vehicle_metrics(self, vehicle_id: int) -> tuple:
        try:
            with get_db() as (cursor, conn):
                cursor.execute(
                    """SELECT service_km, service_date FROM maintenance_history
                       WHERE vehicle_id = %s ORDER BY service_date DESC LIMIT 5""",
                    (vehicle_id,),
                )
                history = cursor.fetchall()
                if len(history) < 2:
                    return 30, 180, 0
                km_total = history[0]["service_km"] - history[-1]["service_km"]
                days_total = (
                    history[0]["service_date"] - history[-1]["service_date"]
                ).days
                avg_km_day = max(1, km_total / days_total) if days_total > 0 else 30
                return avg_km_day, 180, history[0]["service_km"]
        except Exception:
            return 30, 180, 0


predictor = MaintenancePredictor()
