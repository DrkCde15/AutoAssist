import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(os.path.join(Path(__file__).resolve().parent, ".env"))

from redis import Redis
from rq import Connection, Worker

redis_url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI", "redis://localhost:6379/0")
conn = Redis.from_url(redis_url)

if __name__ == "__main__":
    with Connection(conn):
        w = Worker(["default"])
        w.work()
