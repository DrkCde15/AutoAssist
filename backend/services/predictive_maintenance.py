import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import joblib
from sklearn.ensemble import RandomForestRegressor, IsolationForest
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import mean_absolute_error
import logging
from routes.database import get_db
from config import PREDICTIVE_MODEL_DIR, MIN_RECORDS_FOR_PREDICTION

_base_logger = logging.getLogger(__name__)
logger = logging.LoggerAdapter(_base_logger, {"component": "predictive_maintenance"})

pd.set_option('future.no_silent_downcasting', True)


class MaintenancePredictor:
    def __init__(self) -> None:
        PREDICTIVE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.le_type: LabelEncoder = LabelEncoder()
        self.scaler: StandardScaler = StandardScaler()
        self._model_km: RandomForestRegressor | None = None
        self._model_date: RandomForestRegressor | None = None
        self._iso_forest: IsolationForest | None = None

    def _load_models(self) -> None:
        model_files = [
            PREDICTIVE_MODEL_DIR / "model_km.pkl",
            PREDICTIVE_MODEL_DIR / "model_date.pkl",
            PREDICTIVE_MODEL_DIR / "model_anomaly.pkl",
            PREDICTIVE_MODEL_DIR / "label_encoder.pkl",
            PREDICTIVE_MODEL_DIR / "scaler.pkl",
        ]
        if not all(p.exists() for p in model_files):
            logger.info("Model files not found — attempting auto-train...")
            if self.train():
                logger.info("Auto-train concluído, carregando modelos.")
            else:
                logger.warning("Auto-train falhou — dados insuficientes.")
                raise FileNotFoundError(
                    "Modelos não encontrados e não foi possível treinar automaticamente."
                )
        self._model_km = joblib.load(PREDICTIVE_MODEL_DIR / "model_km.pkl")
        self._model_date = joblib.load(PREDICTIVE_MODEL_DIR / "model_date.pkl")
        self._iso_forest = joblib.load(PREDICTIVE_MODEL_DIR / "model_anomaly.pkl")
        self.le_type = joblib.load(PREDICTIVE_MODEL_DIR / "label_encoder.pkl")
        self.scaler = joblib.load(PREDICTIVE_MODEL_DIR / "scaler.pkl")

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

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values(["vehicle_id", "service_date"]).reset_index(drop=True)
        df['service_date'] = pd.to_datetime(df['service_date'])

        df['prev_km'] = df.groupby('vehicle_id')['service_km'].shift(1)
        df['prev_date'] = df.groupby('vehicle_id')['service_date'].shift(1)

        df['km_diff'] = df['service_km'] - df['prev_km']
        df['days_diff'] = (df['service_date'] - df['prev_date']).dt.days
        df['km_per_day'] = df['km_diff'] / df['days_diff'].replace(0, np.nan)

        df['type_encoded'] = self.le_type.fit_transform(df['maintenance_type'])

        df = df.dropna(subset=['km_diff', 'days_diff', 'km_per_day'])
        df = df.replace([np.inf, -np.inf], np.nan).fillna(0)

        return df

    def train(self, history_data=None):
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

        X = df[['type_encoded', 'service_km', 'km_per_day']]
        y_km = df['km_diff']
        y_days = df['days_diff']

        split_idx = int(len(df) * 0.8)
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_km_train, y_km_test = y_km.iloc[:split_idx], y_km.iloc[split_idx:]
        y_days_train, y_days_test = y_days.iloc[:split_idx], y_days.iloc[split_idx:]

        self.scaler.fit(X_train)
        X_train_scaled = self.scaler.transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

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

        joblib.dump(model_km, PREDICTIVE_MODEL_DIR / "model_km.pkl")
        joblib.dump(model_date, PREDICTIVE_MODEL_DIR / "model_date.pkl")
        joblib.dump(iso_forest, PREDICTIVE_MODEL_DIR / "model_anomaly.pkl")
        joblib.dump(self.le_type, PREDICTIVE_MODEL_DIR / "label_encoder.pkl")
        joblib.dump(self.scaler, PREDICTIVE_MODEL_DIR / "scaler.pkl")

        return True

    def get_vehicle_metrics(self, vehicle_id):
        try:
            with get_db() as (cursor, conn):
                cursor.execute("""
                    SELECT service_km, service_date FROM maintenance_history
                    WHERE vehicle_id = %s ORDER BY service_date DESC LIMIT 5
                """, (vehicle_id,))
                history = cursor.fetchall()

                if len(history) < 2:
                    return 30, 180, 0

                km_total = history[0]['service_km'] - history[-1]['service_km']
                days_total = (history[0]['service_date'] - history[-1]['service_date']).days

                avg_km_day = max(1, km_total / days_total) if days_total > 0 else 30
                return avg_km_day, 180, history[0]['service_km']
        except Exception:
            return 30, 180, 0

    def predict_next(self, vehicle_id: int, maintenance_type: str = "oil_change", kilometers_actual: int | None = None) -> dict | None:
        try:
            if not all([self._model_km, self._model_date]):
                self._load_models()

            if kilometers_actual is not None:
                current_km = kilometers_actual
            else:
                with get_db() as (cursor, conn):
                    cursor.execute("SELECT quilometragem FROM veiculos WHERE id = %s", (vehicle_id,))
                    vehicle = cursor.fetchone()
                    if not vehicle:
                        return None
                    current_km = vehicle['quilometragem']
            current_km = int(current_km or 0)

            avg_km_day, avg_days, _ = self.get_vehicle_metrics(vehicle_id)

            known_types = [str(c) for c in getattr(self.le_type, "classes_", [])]
            if not known_types:
                return None

            maintenance_type_used = str(maintenance_type or "").strip()
            if maintenance_type_used not in known_types:
                maintenance_type_used = next(
                    (c for c in ("troca_oleo", "oil_change", "manutencao_geral", known_types[0]) if c in known_types),
                    known_types[0],
                )
            type_enc = self.le_type.transform([maintenance_type_used])[0]

            X_input = pd.DataFrame(
                [[type_enc, current_km, avg_km_day]],
                columns=['type_encoded', 'service_km', 'km_per_day'],
            )
            X_input_scaled = self.scaler.transform(X_input)

            pred_interval_km = self._model_km.predict(X_input_scaled)[0]
            pred_interval_days = self._model_date.predict(X_input_scaled)[0]

            all_tree_preds = np.array([
                tree.predict(X_input_scaled)[0] for tree in self._model_km.estimators_
            ])
            std_dev = np.std(all_tree_preds)
            mean_pred = np.mean(all_tree_preds)
            confidence = max(0.1, min(0.99, 1.0 - std_dev / (mean_pred + 1)))

            return {
                "predicted_next_km": int(current_km + pred_interval_km),
                "predicted_next_date": (datetime.now() + timedelta(days=int(pred_interval_days))).strftime('%Y-%m-%d'),
                "confidence": round(confidence, 2),
                "maintenance_type_used": maintenance_type_used,
            }
        except Exception as e:
            logger.error(f"Erro na inferência preditiva: {e}")
            return None

    def detect_anomaly(self, maintenance_record):
        try:
            if self._iso_forest is None:
                self._load_models()

            type_enc = self.le_type.transform([maintenance_record['maintenance_type']])[0]
            X_input = [[type_enc, maintenance_record.get('km_diff', 0), maintenance_record['cost']]]

            is_anomaly = self._iso_forest.predict(X_input)[0] == -1

            if is_anomaly:
                reason = "Custo ou intervalo de quilometragem fora do padrão histórico para este serviço."
                if maintenance_record.get('km_diff', 0) < 2000:
                    reason = f"Manutenção realizada precoceamente (apenas {maintenance_record['km_diff']} km desde a última)."
                return {"anomaly_detected": True, "reason": reason}

            return {"anomaly_detected": False}
        except Exception:
            return {"anomaly_detected": False}


predictor = MaintenancePredictor()
