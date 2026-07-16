from pathlib import Path
import os

# Base directory of the project (backend folder's parent)
BASE_DIR = Path(__file__).resolve().parent.parent

# Directory where predictive models are stored.
# Pode ser sobrescrito por env var (ex.: Airflow usa volume proprio).
PREDICTIVE_MODEL_DIR: Path = Path(
    os.getenv("PREDICTIVE_MODEL_DIR")
    or (Path(__file__).resolve().parent / "models" / "predictive")
)

# Minimum number of historical records required to train/predict
MIN_RECORDS_FOR_PREDICTION: int = int(os.getenv("MIN_RECORDS_FOR_PREDICTION", "5"))
