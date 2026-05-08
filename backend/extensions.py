import logging
import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

logger = logging.getLogger(__name__)

RATELIMIT_STORAGE_URI = (
    os.getenv("RATELIMIT_STORAGE_URI")
    or os.getenv("REDIS_URL")
    or "memory://"
)

if os.getenv("FLASK_ENV") == "production" and RATELIMIT_STORAGE_URI == "memory://":
    logger.warning(
        "RATELIMIT_STORAGE_URI/REDIS_URL nao configurado; usando rate limit em memoria."
    )

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=RATELIMIT_STORAGE_URI,
)
