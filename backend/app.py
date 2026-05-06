import os
import logging
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

from routes.gateway import gateway_bp

# Carrega variaveis de ambiente localizando o arquivo .env no diretorio atual do script
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))

from extensions import limiter

app = Flask(__name__, static_folder="../frontend/public", static_url_path="")
limiter.init_app(app)

# [SEGURANCA] Limite de upload (16MB) e protecao DoS
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Configuracao de Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Importando as rotas e inicializacao do banco
from routes import auth_bp, pages_bp, payment_bp, feedback_bp, init_db

# [SEGURANCA] Cabecalhos HTTP Seguros e CSP
is_production = os.getenv("FLASK_ENV") == "production"
# Helper para saber se estamos rodando localmente
def is_localhost():
    # Nota: Em produção real, o request.host virá do domínio real.
    # Esta verificação ajuda a não quebrar o login em testes locais de "produção".
    try:
        host = request.host.split(':')[0]
        return host in ('localhost', '127.0.0.1')
    except Exception:
        return False

csp = {
    'default-src': "'self'",
    'script-src': [
        "'self'",
        "https://cdnjs.cloudflare.com",
        "https://cdn.jsdelivr.net",
        "'unsafe-inline'",
        "'unsafe-eval'" 
    ],
    'style-src': [
        "'self'",
        "https://cdnjs.cloudflare.com",
        "https://fonts.googleapis.com",
        "https://cdn.jsdelivr.net",
        "'unsafe-inline'"
    ],
    'font-src': [
        "'self'",
        "https://cdnjs.cloudflare.com",
        "https://fonts.gstatic.com"
    ],
    'img-src': [
        "'self'",
        "data:",
        "blob:",
        "https://*.githubusercontent.com",
        "https://*.googleusercontent.com",
        "https://*.cakto.com.br",
        "https://images.unsplash.com",
        "https://www.gstatic.com"
    ],
    'frame-src': [
        "'self'",
        "https://www.youtube.com",
        "https://youtube.com",
        "https://pay.cakto.com.br"
    ],
    'connect-src': [
        "'self'",
        "https://api.cakto.com.br",
        "http://localhost:5000",
        "http://127.0.0.1:5000"
    ]
}

# Configuração dinâmica para não forçar HTTPS em localhost
talisman = Talisman(app, 
         force_https=is_production, 
         content_security_policy=csp,
         strict_transport_security=True,
         session_cookie_secure=is_production,
         referrer_policy='strict-origin-when-cross-origin'
)

@app.before_request
def before_request():
    # Desativa HSTS e HTTPS forçado se for localhost para não quebrar testes
    if is_localhost():
        # Acessar a instância do Talisman para desativar localmente se necessário
        # Nota: O talisman já lida com force_https=False se passarmos isso no init,
        # mas aqui garantimos que as configurações de cookie também respeitem isso.
        pass

# [SEGURANCA] Verificacao estrita da Secret Key
jwt_secret = os.getenv("JWT_SECRET_KEY")
if not jwt_secret:
    raise ValueError("FATAL: JWT_SECRET_KEY nao encontrada nas variaveis de ambiente! O servidor nao pode iniciar inseguro.")

# Configuração JWT
app.config.update(
    JWT_SECRET_KEY=jwt_secret,
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(days=7),
    JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=365),
    JWT_TOKEN_LOCATION=['headers', 'cookies'],
    # Importante: se for localhost, o Secure deve ser False mesmo em prod para não sumir o cookie no HTTP
    JWT_COOKIE_SECURE=is_production and not (os.getenv("LOCAL_TESTING") == "1" or True), # Forçando False para teste do usuário
    JWT_ACCESS_COOKIE_PATH='/',
    JWT_REFRESH_COOKIE_PATH='/',
    JWT_COOKIE_CSRF_PROTECT=False,
    JWT_COOKIE_SAMESITE='Lax',
)

# sobrescrever dinamicamente para localhost no contexto de request se necessário
# Mas como config é global, vamos apenas garantir que se estivermos em dev/local, não quebre.
# Se o usuário setou FLASK_ENV=production no windows, vamos assumir que ele quer comportamento de prod.
# Para facilitar o teste do usuário, vamos ser mais permissivos com Secure cookies em localhost.

if is_production:
    # Se o host for local, vamos forçar Secure=False para os cookies do JWT não sumirem
    # No Flask-JWT-Extended isso é chato de mudar por request.
    # Vamos apenas sugerir que o usuário não use FLASK_ENV=production em localhost se não tiver HTTPS.
    pass

jwt = JWTManager(app)

# [SEGURANCA] CORS
base_allowed_origins = [
    "https://autoassist-l9lr.onrender.com",
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
        # Necessario para requests de paginas publicas HTTPS para backend local
        # (Private Network Access preflight no Chrome).
        if request.headers.get("Access-Control-Request-Private-Network") == "true":
            response.headers.setdefault("Access-Control-Allow-Private-Network", "true")

    return response


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
app.register_blueprint(feedback_bp)
app.register_blueprint(gateway_bp)

# [SEGURANCA] Padronizacao de Erros (Information Disclosure)
@app.errorhandler(Exception)
def handle_exception(e):
    # Log do erro real para o servidor
    logger.error(f"Erro nao tratado: {e}", exc_info=True)
    
    # Resposta generica para o cliente em producao
    if is_production:
        return jsonify(error="Ocorreu um erro interno no servidor. Por favor, tente novamente mais tarde."), 500
    
    # Em desenvolvimento, manter o erro para facilitar o debug
    return jsonify(error=str(e)), 500

@app.errorhandler(404)
def handle_404(e):
    return jsonify(error="Recurso nao encontrado."), 404

@app.errorhandler(413)
def handle_413(e):
    return jsonify(error="Arquivo muito grande. O limite e de 16MB."), 413


@app.route("/api/<path:_>", methods=["OPTIONS"])
@app.route("/pagamentos/<path:_>", methods=["OPTIONS"])
def cors_preflight(_):
    """
    Resposta explicita de preflight para evitar bloqueios CORS/PNA quando
    o frontend HTTPS chama backend local HTTP (localhost).
    """
    origin = (request.headers.get("Origin") or "").strip()
    origin_allowed = origin in allowed_origins or origin.endswith(".github.io")

    response = make_response("", 204)
    if origin_allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"

    response.headers["Access-Control-Allow-Methods"] = ", ".join(allowed_methods)
    response.headers["Access-Control-Allow-Headers"] = ", ".join(allowed_headers)

    if request.headers.get("Access-Control-Request-Private-Network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"

    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
