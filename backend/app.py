import os
import logging
from datetime import timedelta
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from dotenv import load_dotenv
from routes.gateway import gateway_bp

# Carrega variáveis de ambiente localizando o arquivo .env no diretório atual do script
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Importando as rotas e inicialização do banco
from routes import auth_bp, pages_bp, payment_bp, init_db

app = Flask(__name__, static_folder='../frontend', static_url_path='')

# [SEGURANÇA] Cabeçalhos HTTP Seguros
is_production = os.getenv('FLASK_ENV') == 'production'
Talisman(app, force_https=is_production, content_security_policy=None) 

# [SEGURANÇA] Verificação estrita da Secret Key
jwt_secret = os.getenv("JWT_SECRET_KEY")
if not jwt_secret:
    raise ValueError("FATAL: JWT_SECRET_KEY não encontrada nas variáveis de ambiente! O servidor não pode iniciar inseguro.")

app.config.update(
    JWT_SECRET_KEY=jwt_secret,
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(days=7),
    JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=365),
)

jwt = JWTManager(app)

# [SEGURANÇA] CORS Restrito
allowed_origins = [
    "https://autoassis.onrender.com",
    "https://drkcde15.github.io",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://"
)

# Inicialização do Banco de Dados
@app.before_request
def first_request():
    if not hasattr(app, "_db_initialized"):
        try:
            init_db()
            app._db_initialized = True
        except Exception as e:
            logging.error(f"⚠️ Falha ao inicializar banco: {e}")

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
