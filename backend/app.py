import os
import sys
import logging
from pathlib import Path
from datetime import timedelta

print("Iniciando carregamento do Flask...")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from routes.training import training_bp
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, jsonify, make_response, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_talisman import Talisman
from flask_compress import Compress
from werkzeug.exceptions import HTTPException
from routes.gateway import gateway_bp

basedir = os.path.abspath(os.path.dirname(__file__))
env_path = os.path.join(basedir, ".env")
try:
    from utils.secrets_encrypt import load_env_decrypted
    decrypted_path = load_env_decrypted()
    if decrypted_path:
        env_path = decrypted_path
except Exception:
    pass
load_dotenv(env_path)

from extensions import limiter

app = Flask(__name__, static_folder="../frontend/public", static_url_path="")
print("Flask instanciado.")
Compress(app)
from websocket_handler import sock as ws_sock, ws_bp
app.register_blueprint(ws_bp)
ws_sock.init_app(app)
limiter.init_app(app)
print("Extensoes inicializadas.")
app.json.sort_keys = False
app.json.compact = True

app.register_blueprint(training_bp, url_prefix="/api")

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

print("Importando rotas...")
from routes import auth_bp, analytics_bp, pages_bp, payment_bp, feedback_bp, notes_bp, gateway_bp, init_db
from routes.notifications import notifications_bp
from routes.push import push_bp
from routes.payment import cakto_webhook as cakto_webhook_handler
print("Rotas importadas.")

def get_dashboard_url() -> str:
    """Retorna a URL base da UI HTML.
    Se estiver dentro de um contexto de request, usa `request.host_url`.
    Caso contrário, recorre à variável de ambiente `URL_PROD` ou a um fallback padrão.
    """
    try:
        # request.host_url inclui a barra final
        return request.host_url.rstrip('/') + '/'
    except Exception:
        # Fora de request context (ex.: chamadas internas)
        fallback = os.getenv("URL_PROD") or "http://localhost:5000/"
        return fallback.rstrip('/') + '/'
    # Return base URL for the Flask backend (HTML UI)
    return request.host_url.rstrip('/') + '/'

# [SEGURANCA] Cabecalhos HTTP Seguros e CSP
is_production = os.getenv("FLASK_ENV") == "production"
local_testing = os.getenv("LOCAL_TESTING") == "1"
# Helper para saber se estamos rodando localmente
def is_localhost():
    # Nota: Em produção real, o request.host virá do domínio real.
    # Esta verificação ajuda a não quebrar o login em testes locais de "produção".
    try:
        host = request.host.split(':')[0]
        return host in ('localhost', '127.0.0.1')
    except Exception:
        return False


def _env_frontend_origin() -> str:
    """Origem do frontend conforme ambiente (sem barra final)."""
    raw = (os.getenv("URL_PROD") or os.getenv("URL_DEV") or "").strip().rstrip("/")
    return raw


def _env_ws_origin() -> str | None:
    """Origem WebSocket derivada de URL_PROD/URL_DEV (wss:// ou ws://)."""
    url = _env_frontend_origin()
    if url.startswith("https://"):
        return "wss://" + url[len("https://"):]
    if url.startswith("http://"):
        return "ws://" + url[len("http://"):]
    return None

csp = {
    'default-src': "'self'",
    'script-src': [
        "'self'",
        "https://cdnjs.cloudflare.com",
        "https://cdn.jsdelivr.net",
        "'unsafe-inline'",
    ] + (["'unsafe-eval'"] if os.getenv("CSP_ALLOW_UNSAFE_EVAL", "0").strip().lower() in {"1", "true", "yes", "on"} else []),
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
        "http://127.0.0.1:5000",
        "ws://localhost:5000",
        "ws://127.0.0.1:5000",
    ] + ([_env_ws_origin()] if _env_ws_origin() else [])
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
    # Log todas as requisições para /api/dashboard
    if request.path == '/api/dashboard':
        logger.info(f">>> REQUEST: {request.method} {request.path}")
        logger.info(f">>> Headers: Accept={request.headers.get('Accept')}, Auth={request.headers.get('Authorization')[:20] if request.headers.get('Authorization') else 'None'}")
    # Desativa HSTS e HTTPS forçado se for localhost para não quebrar testes
    if is_localhost():
        pass

@app.after_request
def after_request(response):
    # Log resposta para /api/dashboard
    if request.path == '/api/dashboard':
        logger.info(f"<<< RESPONSE: {response.status_code} | Content-Type: {response.headers.get('Content-Type')}")
    return response

# [SEGURANCA] Verificacao estrita da Secret Key
jwt_secret = os.getenv("JWT_SECRET_KEY")
if not jwt_secret:
    raise ValueError("FATAL: JWT_SECRET_KEY nao encontrada nas variaveis de ambiente! O servidor nao pode iniciar inseguro.")

# Configuração JWT
app.config.update(
    JWT_SECRET_KEY=jwt_secret,
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(days=30),
    JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=30),
    JWT_TOKEN_LOCATION=['headers', 'cookies'],
    JWT_COOKIE_SECURE=is_production and not local_testing,
    JWT_ACCESS_COOKIE_PATH='/',
    JWT_REFRESH_COOKIE_PATH='/',
    JWT_COOKIE_CSRF_PROTECT=True,
    JWT_COOKIE_SAMESITE='Lax',
)

jwt = JWTManager(app)

# [SEGURANCA] CORS
base_allowed_origins = [
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8501",
]
env_frontend = _env_frontend_origin()
if env_frontend:
    base_allowed_origins.append(env_frontend)

extra_origins_raw = (os.getenv("CORS_ALLOW_ORIGINS") or "").strip()
extra_allowed_origins = [item.strip() for item in extra_origins_raw.split(",") if item.strip()]
allowed_origins = [*base_allowed_origins, *extra_allowed_origins]

allowed_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
allowed_headers = [
    "Content-Type",
    "Authorization",
    "X-Requested-With",
    "X-AutoAssist-Guest-Id",
    "X-CSRF-TOKEN",
    "X-CSRF-Token",
]

STATIC_CACHE_SECONDS = max(0, int(os.getenv("STATIC_CACHE_SECONDS", "86400")))
STATIC_CACHE_EXTENSIONS = {
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
}

CORS(
    app,
    resources={
        r"/api/*": {"origins": allowed_origins},
        r"/pagamentos/*": {"origins": allowed_origins},
    },
    methods=allowed_methods,
    allow_headers=allowed_headers,
    supports_credentials=True,
)


@app.after_request
def ensure_cors_headers(response):
    """Fallback para garantir headers CORS validos em respostas e preflight."""
    path = request.path or ""
    if request.method == "GET" and response.status_code < 400:
        _, ext = os.path.splitext(path.lower())
        if ext in STATIC_CACHE_EXTENSIONS and not path.startswith("/api/"):
            response.cache_control.public = True
            response.cache_control.max_age = STATIC_CACHE_SECONDS
            response.headers.setdefault("Vary", "Accept-Encoding")
        elif not path.startswith("/api/") and not path.startswith("/pagamentos/"):
            response.headers.setdefault("Cache-Control", "no-cache")

    origin = (request.headers.get("Origin") or "").strip()
    if not origin:
        return response

    origin_allowed = origin in allowed_origins
    cors_path = path.startswith("/api/") or path.startswith("/pagamentos/")

    if origin_allowed and cors_path and not response.headers.get("Access-Control-Allow-Origin"):
        response.headers["Access-Control-Allow-Origin"] = origin

    if cors_path:
        response.headers.setdefault("Vary", "Origin")
        response.headers.setdefault("Access-Control-Allow-Methods", ", ".join(allowed_methods))
        response.headers.setdefault("Access-Control-Allow-Headers", ", ".join(allowed_headers))
        if origin_allowed:
            response.headers.setdefault("Access-Control-Allow-Credentials", "true")
        # Necessario para requests de paginas publicas HTTPS para backend local
        # (Private Network Access preflight no Chrome).
        if request.headers.get("Access-Control-Request-Private-Network") == "true":
            response.headers.setdefault("Access-Control-Allow-Private-Network", "true")

    return response


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@app.cli.command("init-db")
def init_db_command():
    """Inicializa/atualiza o schema do banco fora do ciclo de request."""
    init_db()
    print("Banco de dados inicializado.")


if _env_flag("AUTO_INIT_DB", default=not is_production):
    try:
        print("Iniciando init_db()...")
        init_db()
        print("init_db() concluido.")
        logger.info("Banco de dados inicializado no startup.")
    except Exception as e:
        logger.error("Falha ao inicializar banco no startup: %s", e, exc_info=True)
        if is_production:
            raise

# Health Check Robusto
@app.route("/health")
def health():
    checks = {"status": "healthy", "timestamp": __import__('datetime').datetime.now().isoformat()}

    if os.getenv("HEALTHCHECK_EXTERNAL_CHECKS", "0").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from routes.database import get_db
            with get_db() as (cursor, conn):
                cursor.execute("SELECT 1 AS ok")
                checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {e}"
            checks["status"] = "degraded"

        redis_url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI", "")
        if redis_url and redis_url != "memory://":
            try:
                import redis
                r = redis.from_url(redis_url)
                r.ping()
                checks["redis"] = "ok"
            except Exception as e:
                checks["redis"] = f"error: {e}"
                checks["status"] = "degraded"
    else:
        checks["database"] = "skipped"
        checks["redis"] = "skipped"

    status_code = 200 if checks["status"] == "healthy" else 503
    return jsonify(checks), status_code

# Documentacao da API (Swagger/OpenAPI)
SWAGGER_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "AutoAssist IA API",
        "version": "1.0.0",
        "description": "API do AutoAssist - Ecossistema automotivo com IA. Consulte os endpoints para chat, manutenção preditiva, FIPE, pagamentos e mais.",
    },
    "servers": [
        {"url": _env_frontend_origin() or "http://localhost:5000", "description": "Producao"},
        {"url": "http://localhost:5000", "description": "Desenvolvimento"},
    ],
    "components": {
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
        }
    },
    "security": [{"bearerAuth": []}],
    "paths": {
        "/health": {
            "get": {
                "summary": "Health check do servidor",
                "tags": ["Sistema"],
                "responses": {"200": {"description": "Servidor saudavel"}, "503": {"description": "Servidor degradado"}},
            }
        },
        "/api/cadastro": {
            "post": {
                "summary": "Cadastro de usuario",
                "tags": ["Autenticacao"],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CadastroInput"}}}},
                "responses": {"201": {"description": "Conta criada"}, "409": {"description": "Email ja cadastrado"}},
            }
        },
        "/api/login": {
            "post": {
                "summary": "Login do usuario",
                "tags": ["Autenticacao"],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/LoginInput"}}}},
                "responses": {"200": {"description": "Login bem-sucedido"}, "401": {"description": "Credenciais invalidas"}},
            }
        },
        "/api/chat": {
            "post": {
                "summary": "Enviar mensagem para o NOG AI",
                "tags": ["Chat"],
                "security": [{"bearerAuth": []}, {}],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ChatInput"}}}},
                "responses": {"200": {"description": "Resposta da IA"}, "400": {"description": "Erro na requisicao"}},
            }
        },
        "/api/user": {
            "get": {
                "summary": "Dados do usuario logado",
                "tags": ["Usuario"],
                "security": [{"bearerAuth": []}],
                "responses": {"200": {"description": "Dados do usuario"}},
            },
            "put": {
                "summary": "Atualizar dados do usuario",
                "tags": ["Usuario"],
                "security": [{"bearerAuth": []}],
                "responses": {"200": {"description": "Usuario atualizado"}},
            },
        },
        "/api/veiculos": {
            "get": {
                "summary": "Listar veiculos do usuario",
                "tags": ["Veiculos"],
                "security": [{"bearerAuth": []}],
                "responses": {"200": {"description": "Lista de veiculos"}},
            },
            "post": {
                "summary": "Adicionar veiculo",
                "tags": ["Veiculos"],
                "security": [{"bearerAuth": []}],
                "responses": {"201": {"description": "Veiculo adicionado"}},
            },
        },
        "/api/dashboard": {
            "get": {
                "summary": "Dashboard preditivo do veiculo",
                "tags": ["Dashboard"],
                "security": [{"bearerAuth": []}],
                "responses": {"200": {"description": "Dados do dashboard"}},
            }
        },
        "/api/maintenance/history": {
            "get": {
                "summary": "Listar historico de manutencao",
                "tags": ["Manutencao"],
                "security": [{"bearerAuth": []}],
                "responses": {"200": {"description": "Historico de manutencao"}},
            },
            "post": {
                "summary": "Registrar manutencao via NLP",
                "tags": ["Manutencao"],
                "security": [{"bearerAuth": []}],
                "responses": {"201": {"description": "Manutencao registrada"}},
            },
        },
        "/api/pay/preference": {
            "post": {
                "summary": "Criar preferencia de pagamento Premium",
                "tags": ["Pagamentos"],
                "security": [{"bearerAuth": []}],
                "responses": {"201": {"description": "Checkout gerado"}},
            }
        },
        "/api/pay/webhook/cakto": {
            "post": {
                "summary": "Webhook da Cakto (pagamentos)",
                "tags": ["Pagamentos"],
                "responses": {"200": {"description": "Webhook processado"}},
            }
        },
        "/api/feedback": {
            "post": {
                "summary": "Enviar feedback",
                "tags": ["Feedback"],
                "responses": {"201": {"description": "Feedback registrado"}},
            }
        },
        "/api/analytics/events": {
            "post": {
                "summary": "Registrar evento de analytics",
                "tags": ["Analytics"],
                "responses": {"200": {"description": "Evento registrado"}},
            }
        },
        "/api/docs": {
            "get": {
                "summary": "Documentacao OpenAPI/Swagger",
                "tags": ["Sistema"],
                "responses": {"200": {"description": "Especificacao OpenAPI"}},
            }
        },
    },
    "schemas": {
        "CadastroInput": {
            "type": "object",
            "required": ["nome", "email", "password"],
            "properties": {
                "nome": {"type": "string", "example": "João Silva"},
                "email": {"type": "string", "format": "email", "example": "joao@email.com"},
                "password": {"type": "string", "minLength": 6, "example": "senha123"},
                "veiculos": {"type": "array", "items": {"$ref": "#/components/schemas/VeiculoInput"}},
            },
        },
        "LoginInput": {
            "type": "object",
            "required": ["email", "password"],
            "properties": {
                "email": {"type": "string", "format": "email"},
                "password": {"type": "string"},
            },
        },
        "ChatInput": {
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string", "example": "Qual o óleo ideal para meu carro?"},
                "session_id": {"type": "string"},
                "attachment": {"type": "object"},
            },
        },
        "VeiculoInput": {
            "type": "object",
            "properties": {
                "marca": {"type": "string"},
                "modelo": {"type": "string"},
                "ano_fabricacao": {"type": "integer"},
                "tipo": {"type": "string", "enum": ["carro", "moto", "caminhao"]},
                "quilometragem": {"type": "integer"},
            },
        },
    },
}

@app.route("/api/docs")
def api_docs():
    return jsonify(SWAGGER_SPEC)

@app.route("/api/swagger-ui")
def swagger_ui():
    return f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>AutoAssist API - Swagger</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui.min.css" />
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui-bundle.min.js"></script>
    <script>
        SwaggerUIBundle({{
            url: '{request.host_url}api/docs',
            dom_id: '#swagger-ui',
            presets: [SwaggerUIBundle.presets.apis],
            layout: "BaseLayout",
        }});
    </script>
</body>
</html>
"""


@app.route("/", methods=["POST"])
def root_post_webhook_fallback():
    logger.warning(
        "POST / recebido. Encaminhando como fallback para webhook Cakto; "
        "configure a URL correta: /api/pay/webhook/cakto"
    )
    return cakto_webhook_handler()


# Registro de Blueprints
# Register predictive dashboard blueprint FIRST (antes de pages_bp catch-all)
from routes.dashboard import dashboard_bp
app.register_blueprint(dashboard_bp, url_prefix="/api")

app.register_blueprint(auth_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(gateway_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(push_bp)

# Gera VAPID keys se nao existirem
if not os.getenv("VAPID_PRIVATE_KEY") or not os.getenv("VAPID_PUBLIC_KEY"):
    try:
        import base64
        from cryptography.hazmat.primitives import serialization
        from pywebpush import Vapid
        v = Vapid()
        v.generate_keys()
        private_der = v.private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_der = v.public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        private_b64 = base64.b64encode(private_der).decode()
        public_b64 = base64.b64encode(public_der).decode()
        logger.info("VAPID keys geradas. Adicione ao .env:")
        logger.info("VAPID_PRIVATE_KEY=%s", private_b64)
        logger.info("VAPID_PUBLIC_KEY=%s", public_b64)
        os.environ["VAPID_PRIVATE_KEY"] = private_b64
        os.environ["VAPID_PUBLIC_KEY"] = public_b64
    except ImportError:
        logger.warning("pywebpush nao disponivel — VAPID keys devem ser configuradas manualmente no .env")

# [SEGURANCA] Padronizacao de Erros (Information Disclosure)
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code

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
    origin_allowed = origin in allowed_origins

    response = make_response("", 204)
    if origin_allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = "true"

    response.headers["Access-Control-Allow-Methods"] = ", ".join(allowed_methods)
    response.headers["Access-Control-Allow-Headers"] = ", ".join(allowed_headers)

    if request.headers.get("Access-Control-Request-Private-Network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"

    return response


# Run Flask only (Streamlit removed)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

