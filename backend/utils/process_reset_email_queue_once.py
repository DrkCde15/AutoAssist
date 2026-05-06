import logging
import os
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
