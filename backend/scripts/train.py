import os
import sys
from pathlib import Path
import logging

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.predictive_maintenance import MaintenancePredictor

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
        print("[OK] Model training completed successfully.")
    else:
        print("[SKIP] Not enough historical records for training.")

if __name__ == "__main__":
    main()
