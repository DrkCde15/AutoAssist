import os
import sys
from pathlib import Path
import logging

# Ensure the project root (AutoAssist) is in PYTHONPATH so we can import backend modules
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from backend.services.predictive_maintenance import MaintenancePredictor

def main() -> None:
    """Entrypoint to train all predictive‑maintenance models.
    The function simply instantiates :class:`MaintenancePredictor` and
    invokes its ``train`` method.  If the underlying data set does not meet
    the minimum number of records (see ``MIN_RECORDS_FOR_PREDICTION`` in
    ``backend/config.py``) the method will log a warning and return ``False``.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    predictor = MaintenancePredictor()
    if predictor.train():
        print("✅  Model training completed successfully.")
    else:
        print("⚠️  Model training skipped – not enough historical records.")

if __name__ == "__main__":
    main()
