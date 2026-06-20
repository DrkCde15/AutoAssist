import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import joblib
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor, IsolationForest
from sklearn.preprocessing import LabelEncoder
import logging
from routes.database import get_db
from config import PREDICTIVE_MODEL_DIR, MIN_RECORDS_FOR_PREDICTION

# Logger with contextual adapter
_base_logger = logging.getLogger(__name__)
logger = logging.LoggerAdapter(_base_logger, {"component": "predictive_maintenance"})

# Paths and constants are now defined in backend.config
pd.set_option('future.no_silent_downcasting', True)

class MaintenancePredictor:
    def __init__(self) -> None:
        """Initialize the predictor.

        Creates the model directory if it does not exist and prepares a
        ``LabelEncoder`` for maintenance type encoding. Models are loaded lazily
        on first inference.
        """
        PREDICTIVE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.le_type: LabelEncoder = LabelEncoder()
        # Lazy‑loaded models (None until first use)
        self._model_km: RandomForestRegressor | None = None
        self._model_date: RandomForestRegressor | None = None
        self._iso_forest: IsolationForest | None = None
    def _load_models(self) -> None:
        """Load persisted models and the label encoder.

        Raises:
            FileNotFoundError: If a required model file is missing.
        """
        try:
            self._model_km = joblib.load(PREDICTIVE_MODEL_DIR / "model_km.pkl")
            self._model_date = joblib.load(PREDICTIVE_MODEL_DIR / "model_date.pkl")
            self._iso_forest = joblib.load(PREDICTIVE_MODEL_DIR / "model_anomaly.pkl")
            self.le_type = joblib.load(PREDICTIVE_MODEL_DIR / "label_encoder.pkl")
        except FileNotFoundError as fnf_err:
            logger.error("Missing model file during lazy load: %s", fnf_err)
            raise
    def fetch_training_data(self):
        """Busca todos os registros de manutenção do banco de dados para treinamento."""
        try:
            with get_db() as (cursor, conn):
                cursor.execute("SELECT vehicle_id, maintenance_type, service_date, service_km, cost FROM maintenance_history")
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Erro ao buscar dados para treinamento: {e}")
            return []

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform raw maintenance history into numerical features.

        The function sorts the data, creates lag features, computes differences
        and encodes the maintenance type. It returns a DataFrame ready for model
        training.
        """
        df = df.sort_values(["vehicle_id", "service_date"]).reset_index(drop=True)
        
        # Engenharia de Atributos
        df['service_date'] = pd.to_datetime(df['service_date'])
        df['prev_km'] = df.groupby('vehicle_id')['service_km'].shift(1)
        df['prev_date'] = df.groupby('vehicle_id')['service_date'].shift(1)
        
        # KM rodados desde a última manutenção
        df['km_diff'] = df['service_km'] - df['prev_km']
        # Dias entre manutenções
        df['days_diff'] = (df['service_date'] - df['prev_date']).dt.days
        
        # Média de KM/dia do usuário (Padrão de uso)
        df['km_per_day'] = df['km_diff'] / df['days_diff'].replace(0, np.nan)
        
        # Preenche vazios com médias globais/locais
        df = df.fillna(0)
        
        # Encode do tipo de manutenção
        df['type_encoded'] = self.le_type.fit_transform(df['maintenance_type'])
        
        return df

    def train(self, history_data=None):
        """Treina os modelos de regressão e anomalia."""
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
        
        # Features para Regressão (Próximo KM e Próxima Data)
        X = df[['type_encoded', 'service_km', 'km_per_day', 'days_diff', 'cost']]
        y_km = df['km_diff'] # Vamos prever o próximo intervalo
        y_days = df['days_diff']
        
        # Modelo 1: Predição de KM
        model_km = RandomForestRegressor(n_estimators=100, random_state=42)
        model_km.fit(X, y_km)
        
        # Modelo 2: Predição de Dias
        model_date = RandomForestRegressor(n_estimators=100, random_state=42)
        model_date.fit(X, y_days)
        
        # Modelo 3: Detecção de Anomalias (Isolation Forest)
        # Analisa custo e KM em relação ao tipo
        X_anomaly = df[['type_encoded', 'km_diff', 'cost']]
        iso_forest = IsolationForest(contamination=0.1, random_state=42)
        iso_forest.fit(X_anomaly)
        
        # Persistência
        joblib.dump(model_km, PREDICTIVE_MODEL_DIR / "model_km.pkl")
        joblib.dump(model_date, PREDICTIVE_MODEL_DIR / "model_date.pkl")
        joblib.dump(iso_forest, PREDICTIVE_MODEL_DIR / "model_anomaly.pkl")
        joblib.dump(self.le_type, PREDICTIVE_MODEL_DIR / "label_encoder.pkl")
        
        return True

    def get_vehicle_metrics(self, vehicle_id):
        """Calcula métricas específicas do comportamento do veículo/motorista."""
        try:
            with get_db() as (cursor, conn):
                cursor.execute("""
                    SELECT service_km, service_date FROM maintenance_history 
                    WHERE vehicle_id = %s ORDER BY service_date DESC LIMIT 5
                """, (vehicle_id,))
                history = cursor.fetchall()
                
                if len(history) < 2:
                    return 30, 180, 0 # Valores padrão: 30km/dia, 180 dias intervalo
                
                # Cálculo simples de KM/dia entre a primeira e última manutenção do histórico
                km_total = history[0]['service_km'] - history[-1]['service_km']
                days_total = (history[0]['service_date'] - history[-1]['service_date']).days
                
                avg_km_day = max(1, km_total / days_total) if days_total > 0 else 30
                return avg_km_day, 180, history[0]['service_km']
        except Exception:
            return 30, 180, 0

    def predict_next(self, vehicle_id: int, maintenance_type: str = "oil_change", kilometers_actual: int | None = None) -> dict | None:
        """Perform inference for the next scheduled maintenance.

        Optional ``kilometers_actual`` can be provided to override the
        vehicle's current mileage stored in the database. This makes the
        method easier to test and more flexible.

        Returns a dictionary with predicted km, date and confidence, or ``None``
        if an error occurs.
        """
        try:
            if self._model_km is None or self._model_date is None or self.le_type is None:
                self._load_models()
            model_km = self._model_km
            model_date = self._model_date
            le = self.le_type

            # Get current vehicle mileage – use explicit value if given
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

            avg_km_day, avg_days, last_km = self.get_vehicle_metrics(vehicle_id)

            # Prepare input for the models
            known_types = [str(item) for item in list(getattr(le, "classes_", []))]
            if not known_types:
                return None

            maintenance_type_used = str(maintenance_type or "").strip()
            if maintenance_type_used not in known_types:
                maintenance_type_used = next(
                    (
                        candidate for candidate in (
                            "troca_oleo",
                            "oil_change",
                            "manutencao_geral",
                            known_types[0],
                        )
                        if candidate in known_types
                    ),
                    known_types[0],
                )
            type_enc = le.transform([maintenance_type_used])[0]

            X_input = pd.DataFrame([[
                type_enc,
                current_km,
                avg_km_day,
                avg_days,
                0  # cost placeholder – could be refined with average cost per type
            ]], columns=['type_encoded', 'service_km', 'km_per_day', 'days_diff', 'cost'])

            pred_interval_km = model_km.predict(X_input)[0]
            pred_interval_days = model_date.predict(X_input)[0]

            # Confidence estimate based on variance among trees
            all_tree_preds = np.array([tree.predict(X_input.values)[0] for tree in model_km.estimators_])
            std_dev = np.std(all_tree_preds)
            mean_pred = np.mean(all_tree_preds)
            confidence = 1.0 - (std_dev / (mean_pred + 1))
            confidence = max(0.1, min(0.99, confidence))

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
        """Detecta se um novo registro foge do padrão esperado."""
        try:
            if self._iso_forest is None or self.le_type is None:
                self._load_models()
            iso_forest = self._iso_forest
            le = self.le_type
            
            type_enc = le.transform([maintenance_record['maintenance_type']])[0]
            
            # Dados para análise: [tipo, km_desde_ultima, custo]
            X_input = [[
                type_enc,
                maintenance_record.get('km_diff', 0),
                maintenance_record['cost']
            ]]
            
            is_anomaly = iso_forest.predict(X_input)[0] == -1
            
            if is_anomaly:
                # Lógica simples de explicação
                reason = "Custo ou intervalo de quilometragem fora do padrão histórico para este serviço."
                if maintenance_record.get('km_diff', 0) < 2000:
                    reason = f"Manutenção realizada precocemente (apenas {maintenance_record['km_diff']} km desde a última)."
                
                return {
                    "anomaly_detected": True,
                    "reason": reason
                }
                
            return {"anomaly_detected": False}
        except Exception:
            return {"anomaly_detected": False}

# Singleton para fácil acesso
predictor = MaintenancePredictor()
