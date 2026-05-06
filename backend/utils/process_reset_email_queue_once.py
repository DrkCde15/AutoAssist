import logging
import os
import sys
from pathlib import Path


def _prepare_paths() -> None:
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    backend_dir = script_path.parents[1]

    # Evita conflito com backend/utils/email.py que pode sombrear
    # o pacote padrão "email" do Python no GitHub Actions.
    filtered = []
    for entry in sys.path:
        try:
            if Path(entry).resolve() == script_dir:
                continue
        except Exception:
            pass
        filtered.append(entry)
    sys.path[:] = filtered

    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


_prepare_paths()

from routes.auth import process_pending_password_reset_emails


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger("process_reset_email_queue_once")

    batch_size = max(1, min(int(os.getenv("RESET_EMAIL_BATCH_SIZE", "50")), 500))
    result = process_pending_password_reset_emails(batch_size=batch_size) or {}
    processed = int(result.get("processed", 0))
    sent = int(result.get("sent", 0))

    logger.info("Fila processada: pendentes_lidos=%s enviados=%s", processed, sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
