import logging
import threading

_logger = logging.getLogger(__name__)

_predictor_instance = None

def _predictor():
    global _predictor_instance
    if _predictor_instance is None:
        from services.predictive_maintenance import predictor
        _predictor_instance = predictor
    return _predictor_instance


def _train_task():
    """Internal helper to train the predictive model.

    Wrapped in a separate thread to avoid blocking the request handling.
    """
    try:
        _predictor().train()
    except Exception as e:
        _logger.warning("Failed to train predictive model in background: %s", e)

def train_in_background():
    """Start a daemon thread that runs the model training routine.

    This function returns immediately; any errors during training are logged.
    """
    thread = threading.Thread(target=_train_task, daemon=True)
    thread.start()
