import os

# Render free tier = 1 worker (512MB RAM)
workers = int(os.getenv("GUNICORN_WORKERS", "1"))
worker_class = "gevent"
preload_app = True
timeout = 300
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
errorlog = "-"
accesslog = "-"
loglevel = "info"
