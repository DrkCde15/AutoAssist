import os
import logging
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

from routes.gateway import gateway_bp

# Carrega variaveis de ambiente localizando o arquivo .env no diretorio atual do script
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))

# Configuracao de Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Importando as rotas e inicializacao do banco
from routes import auth_bp, pages_bp, payment_bp, init_db

app = Flask(__name__, static_folder="../frontend/public", static_url_path="")

# [SEGURANCA] Cabecalhos HTTP Seguros
is_production = os.getenv("FLASK_ENV") == "production"
Talisman(app, force_https=is_production, content_security_policy=None)

# [SEGURANCA] Verificacao estrita da Secret Key
jwt_secret = os.getenv("JWT_SECRET_KEY")
if not jwt_secret:
    raise ValueError("FATAL: JWT_SECRET_KEY nao encontrada nas variaveis de ambiente! O servidor nao pode iniciar inseguro.")

app.config.update(
    JWT_SECRET_KEY=jwt_secret,
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(days=7),
    JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=365),
)

jwt = JWTManager(app)

# [SEGURANCA] CORS
base_allowed_origins = [
    "https://autoassis.onrender.com",
    "https://drkcde15.github.io",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

extra_origins_raw = (os.getenv("CORS_ALLOW_ORIGINS") or "").strip()
extra_allowed_origins = [item.strip() for item in extra_origins_raw.split(",") if item.strip()]
allowed_origins = [*base_allowed_origins, *extra_allowed_origins]

allowed_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
allowed_headers = ["Content-Type", "Authorization", "X-Requested-With", "X-Cron-Secret"]

CORS(
    app,
    resources={
        r"/api/*": {"origins": [*allowed_origins, r"https://.*\\.github\\.io"]},
        r"/pagamentos/*": {"origins": [*allowed_origins, r"https://.*\\.github\\.io"]},
    },
    methods=allowed_methods,
    allow_headers=allowed_headers,
    supports_credentials=False,
)


@app.after_request
def ensure_cors_headers(response):
    """Fallback para garantir headers CORS validos em respostas e preflight."""
    origin = (request.headers.get("Origin") or "").strip()
    if not origin:
        return response

    origin_allowed = origin in allowed_origins or origin.endswith(".github.io")
    path = request.path or ""
    cors_path = path.startswith("/api/") or path.startswith("/pagamentos/")

    if origin_allowed and cors_path and not response.headers.get("Access-Control-Allow-Origin"):
        response.headers["Access-Control-Allow-Origin"] = origin

    if cors_path:
        response.headers.setdefault("Vary", "Origin")
        response.headers.setdefault("Access-Control-Allow-Methods", ", ".join(allowed_methods))
        response.headers.setdefault("Access-Control-Allow-Headers", ", ".join(allowed_headers))

    return response


limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://",
)


# Inicializacao do Banco de Dados
@app.before_request
def first_request():
    if not hasattr(app, "_db_initialized"):
        try:
            init_db()
            app._db_initialized = True
        except Exception as e:
            logging.error(f"Falha ao inicializar banco: {e}")


# Rota de Health Check
@app.route("/health")
def health():
    return jsonify(status="healthy"), 200


# Registro de Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(gateway_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
