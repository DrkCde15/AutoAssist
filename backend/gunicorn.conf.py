import os

workers = int(os.getenv("GUNICORN_WORKERS", "1"))
preload_app = False

timeout = 300
keepalive = 5
max_requests = 1000
max_requests_jitter = 100

errorlog = "-"
accesslog = "-"
loglevel = "info"