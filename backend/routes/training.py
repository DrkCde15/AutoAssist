from flask import Blueprint, jsonify

training_bp = Blueprint('training', __name__)

@training_bp.post('/train')
def train_model():
    from services.predictive_maintenance import MaintenancePredictor
    predictor = MaintenancePredictor()
    if predictor.train():
        return jsonify(message="Training completed successfully."), 200
    else:
        return jsonify(message="Not enough historical records to train the models."), 400
