from flask import Blueprint, jsonify
from services.predictive_maintenance import MaintenancePredictor

training_bp = Blueprint('training', __name__)

@training_bp.post('/train')
def train_model():
    """Endpoint to (re)train the predictive‑maintenance models.
    Returns a JSON payload indicating success or the reason for skipping.
    """
    predictor = MaintenancePredictor()
    if predictor.train():
        return jsonify(message="Training completed successfully."), 200
    else:
        return jsonify(message="Not enough historical records to train the models."), 400
