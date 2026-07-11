import os

workers = 1
worker_class = "gthread"
threads = 4

preload_app = False

timeout = 300
keepalive = 5

max_requests = 1000
max_requests_jitter = 100

errorlog = "-"
accesslog = "-"
loglevel = "info"