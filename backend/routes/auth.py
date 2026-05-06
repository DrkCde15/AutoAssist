from flask import Blueprint, request, jsonify, redirect, url_for
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    decode_token,
    set_access_cookies,
    set_refresh_cookies
)
from passlib.hash import bcrypt
import secrets
import os
import logging
import pyotp
from extensions import limiter
import requests
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from oauthlib.oauth2 import WebApplicationClient
from .database import get_db, is_valid_email_domain, is_trial_expired, enviar_email, get_trial_days_remaining

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)
RESET_DISPATCH_LOCK_NAME = "autoassist_reset_email_dispatcher"

def _get_frontend_base_url_for_email() -> str:
    is_production = os.getenv("FLASK_ENV") == "production"
    env_key = "URL_PROD" if is_production else "URL_DEV"
    frontend_env = (os.getenv(env_key) or "").strip()
    if not frontend_env:
        frontend_env = (
            os.getenv("URL_PROD")
            or os.getenv("URL_DEV")
        ).strip()
    return frontend_env if frontend_env.endswith("/") else f"{frontend_env}/"

def _build_reset_password_email_html(reset_link: str) -> str:
    return f"""
        <h2 style="margin-top: 0; color: #111827; font-size: 20px;">RedefiniÃ§Ã£o de Senha</h2>
        <p style="color: #4b5563; font-size: 16px; margin-bottom: 25px;">
            OlÃ¡! Recebemos uma solicitaÃ§Ã£o para redefinir a senha da sua conta no <strong>AutoAssist</strong>.
        </p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{reset_link}" style="display: inline-block; padding: 14px 28px; background-color: #2563eb; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">Redefinir Minha Senha</a>
        </div>
        <p style="color: #6b7280; font-size: 14px; margin-top: 25px;">
            Este link Ã© vÃ¡lido por <strong>15 minutos</strong>. Se vocÃª nÃ£o solicitou esta alteraÃ§Ã£o, pode ignorar este e-mail com seguranÃ§a.
        </p>
    """

def _send_password_reset_email(dest_email: str, token: str) -> bool:
    frontend_base = _get_frontend_base_url_for_email()
    reset_link = f"{frontend_base}redefinir-senha.html?token={token}"
    mensagem = _build_reset_password_email_html(reset_link)
    return enviar_email(dest_email, "RedefiniÃ§Ã£o de senha", mensagem)

def process_pending_password_reset_emails(batch_size: int = 20):
    retry_seconds = max(1, int(os.getenv("RESET_EMAIL_RETRY_SECONDS", "15")))
    processed = 0
    sent = 0

    with get_db() as (cursor, conn):
        cursor.execute("SELECT GET_LOCK(%s, 0) AS got_lock", (RESET_DISPATCH_LOCK_NAME,))
        lock_row = cursor.fetchone() or {}
        got_lock = int(lock_row.get("got_lock") or 0)
        if got_lock != 1:
            return {"processed": 0, "sent": 0}

        try:
            cursor.execute(
                """
                SELECT rs.id, rs.token, u.email
                FROM redefinicao_senha rs
                JOIN users u ON u.id = rs.usuario_id
                WHERE rs.email_sent = FALSE
                  AND rs.data_expiracao > NOW()
                  AND (
                    rs.last_attempt_at IS NULL
                    OR rs.last_attempt_at <= DATE_SUB(NOW(), INTERVAL %s SECOND)
                  )
                ORDER BY rs.id ASC
                LIMIT %s
                """,
                (retry_seconds, int(batch_size))
            )
            pendentes = cursor.fetchall() or []
            processed = len(pendentes)

            for row in pendentes:
                token = row.get("token")
                email = row.get("email")
                req_id = row.get("id")
                ok = False
                err_msg = None

                try:
                    ok = bool(token and email and _send_password_reset_email(email, token))
                    if not ok:
                        err_msg = "send_failed"
                except Exception as exc:
                    err_msg = str(exc)[:500]
                    ok = False

                if ok:
                    sent += 1
                    cursor.execute(
                        """
                        UPDATE redefinicao_senha
                        SET email_sent = TRUE,
                            email_attempts = COALESCE(email_attempts, 0) + 1,
                            last_attempt_at = NOW(),
                            send_error = NULL
                        WHERE id = %s
                        """,
                        (req_id,)
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE redefinicao_senha
                        SET email_attempts = COALESCE(email_attempts, 0) + 1,
                            last_attempt_at = NOW(),
                            send_error = %s
                        WHERE id = %s
                        """,
                        ((err_msg or "send_failed")[:500], req_id)
                    )
        finally:
            cursor.execute("SELECT RELEASE_LOCK(%s)", (RESET_DISPATCH_LOCK_NAME,))

    return {"processed": processed, "sent": sent}

def get_frontend_url() -> str:
    """Retorna a URL base do frontend com fallback para a origem atual."""
    is_production = os.getenv("FLASK_ENV") == "production"
    env_key = "URL_PROD" if is_production else "URL_DEV"
    frontend_env = (os.getenv(env_key) or "").strip()
    if frontend_env:
        return frontend_env

    # Fallback seguro quando nÃ£o houver variÃ¡vel de frontend definida.
    return request.host_url


def fetch_veiculos_user(cursor, user_id):
    cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
    return cursor.fetchall()


# ConfiguraÃƒÂ§ÃƒÂ£o Google OAuth2
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

google_client = WebApplicationClient(GOOGLE_CLIENT_ID) if GOOGLE_CLIENT_ID else None

@dataclass
class GoogleHosts:
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str

def get_google_oauth_hosts():
    try:
        response = requests.get("https://accounts.google.com/.well-known/openid-configuration")
        if response.status_code != 200:
            return None
        data = response.json()
        return GoogleHosts(
            authorization_endpoint=data.get("authorization_endpoint"), 
            token_endpoint=data.get("token_endpoint"), 
            userinfo_endpoint=data.get("userinfo_endpoint")
        )
    except Exception as e:
        logger.error(f"Erro ao buscar endpoints do Google: {e}")
        return None

@auth_bp.route("/api/auth/google/login")
def google_login():
    hosts = get_google_oauth_hosts()
    if not hosts or not google_client:
        logger.error("ConfiguraÃ§Ã£o Google OAuth2 ausente ou incompleta")
        return jsonify(error="ConfiguraÃ§Ã£o do Google OAuth2 incompleta"), 500

    state = secrets.token_urlsafe(16)
    
    authorization_url = google_client.prepare_request_uri(
        uri=hosts.authorization_endpoint,
        redirect_uri=GOOGLE_REDIRECT_URI,
        scope=["openid", "email", "profile"],
        state=state
    )
    
    from flask import make_response
    resp = make_response(redirect(authorization_url))
    
    # State cookie expira em 10 minutos
    # SÃ³ forÃ§a Secure se for produÃ§Ã£o E nÃ£o for localhost/127.0.0.1
    is_prod = os.getenv("FLASK_ENV") == "production"
    is_secure = is_prod and not (request.host.startswith("localhost") or request.host.startswith("127.0.0.1"))
    
    resp.set_cookie(
        "oauth_state", 
        state, 
        httponly=True, 
        secure=is_secure, 
        samesite='Lax', 
        max_age=600
    )
    return resp

@auth_bp.route("/api/auth/google/callback")
def google_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    cookie_state = request.cookies.get("oauth_state")
    
    hosts = get_google_oauth_hosts()
    
    if not state or state != cookie_state:
        logger.error(f"Estado OAuth invalido. State: {state}, Cookie: {cookie_state}")
        return jsonify(error="Estado OAuth invÃƒÂ¡lido ou expirado. Tente novamente."), 400

    if not hosts or not google_client or not code:
        return jsonify(error="Dados de callback invÃƒÂ¡lidos"), 400

    try:
        # Trocar cÃƒÂ³digo por token
        token_url, headers, body = google_client.prepare_token_request(
            token_url=hosts.token_endpoint,
            authorization_response=request.url.replace("http://", "https://") if os.getenv('FLASK_ENV') == 'production' else request.url,
            redirect_url=GOOGLE_REDIRECT_URI,
            code=code
        )
        
        token_response = requests.post(
            token_url,
            headers=headers,
            data=body,
            auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
        )

        if token_response.status_code != 200:
            logger.error(f"Erro ao trocar token: {token_response.text}")
            return jsonify(error="Falha na autenticaÃƒÂ§ÃƒÂ£o com Google"), 400

        google_client.parse_request_body_response(json.dumps(token_response.json()))

        # Pegar dados do usuÃƒÂ¡rio
        uri, headers, body = google_client.add_token(hosts.userinfo_endpoint)
        user_info_response = requests.get(uri, headers=headers, data=body)
        
        if user_info_response.status_code != 200:
            return jsonify(error="Falha ao obter dados do usuÃƒÂ¡rio"), 400

        user_info = user_info_response.json()
        if not user_info.get("email_verified"):
            return jsonify(error="Email Google nÃƒÂ£o verificado"), 400

        google_id = user_info["sub"]
        email = user_info["email"].lower()
        nome = user_info.get("name", email.split('@')[0])
        picture = user_info.get("picture")

        # Persistir no MySQL
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()

            if user:
                # Atualiza usuÃƒÂ¡rio existente com info do Google
                cursor.execute("""
                    UPDATE users 
                    SET google_id = %s, profile_pic = %s 
                    WHERE email = %s
                """, (google_id, picture, email))
            else:
                # Cria novo usuÃƒÂ¡rio sem senha (Login Social) e ativa e-mails por padrÃ£o
                cursor.execute("""
                    INSERT INTO users (nome, email, google_id, profile_pic, maintenance_email_enabled) 
                    VALUES (%s, %s, %s, %s, TRUE)
                """, (nome, email, google_id, picture))
                
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            veiculos = fetch_veiculos_user(cursor, user["id"])

        # Gerar tokens JWT (iguais ao login regular)
        access_token = create_access_token(identity=str(user["id"]))
        refresh_token = create_refresh_token(identity=str(user["id"]))
        
        # Obter a URL do frontend do .env
        frontend_base = get_frontend_url()
        
        # Redirecionar para o frontend (index.html)
        if "index.html" in frontend_base:
            redirect_url = frontend_base
        else:
            base = frontend_base if frontend_base.endswith("/") else f"{frontend_base}/"
            redirect_url = f"{base}index.html"
            
        # Preparar dados do usuÃ¡rio para o frontend
        user_data = {
            "id": user["id"],
            "nome": user["nome"],
            "email": user["email"],
            "is_premium": bool(user["is_premium"]),
            "profile_pic": user.get("profile_pic")
        }
        
        import urllib.parse
        params = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": json.dumps(user_data)
        }
        
        # ConstrÃ³i a URL final com os parÃ¢metros para o auth.js processar
        final_redirect_url = f"{redirect_url}?{urllib.parse.urlencode(params)}"
        
        from flask import make_response
        resp = make_response(redirect(final_redirect_url))
        
        # MantÃ©m os cookies JWT como camada extra de seguranÃ§a (HttpOnly)
        set_access_cookies(resp, access_token)
        set_refresh_cookies(resp, refresh_token)
        
        # Limpa o cookie de estado
        resp.set_cookie("oauth_state", "", expires=0)
        
        return resp

    except Exception as e:
        logger.error(f"Erro no callback do Google: {e}", exc_info=True)
        return jsonify(error="Erro interno no login Google"), 500

@auth_bp.route("/api/cadastro", methods=["POST"])
@limiter.limit("5 per hour")
def cadastro():
    data = request.get_json()
    nome, email, password = data.get("nome"), data.get("email"), data.get("password")
    
    veiculo = data.get("veiculo", {})
    veiculos = data.get("veiculos", [])
    if veiculo and veiculo.get("possui"):
        veiculos.append(veiculo)
    
    possui_veiculo = len(veiculos) > 0
    
    if not nome or not email or len(password) < 6: return jsonify(error="Dados invÃƒÂ¡lidos"), 400
    
    if not is_valid_email_domain(email):
        return jsonify(error="Insira um endereÃƒÂ§o de email valido"), 400
    try:
        with get_db() as (cursor, conn):
            cursor.execute("""
                INSERT INTO users (
                    nome, email, password, possui_veiculo, maintenance_email_enabled
                ) VALUES (%s, %s, %s, %s, TRUE)
            """, (
                nome, email.lower(), bcrypt.hash(password), possui_veiculo
            ))
            user_id = cursor.lastrowid
            
            for v in veiculos:
                ano_fab = v.get("ano_fabricacao")
                ano_compra = v.get("ano_compra")
                ano_fab = int(ano_fab) if ano_fab else None
                ano_compra = int(ano_compra) if ano_compra else None
                
                cursor.execute("""
                    INSERT INTO veiculos (user_id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    user_id, v.get("tipo"), v.get("marca"), v.get("modelo"),
                    ano_fab, ano_compra, v.get("quilometragem")
                ))
        return jsonify(success=True), 201
    except Exception as e:
        logger.error(f"Ã¢ Å’ Erro no cadastro: {e}")
        return jsonify(error="Erro ao processar cadastro ou email jÃƒÂ¡ existe"), 409

@auth_bp.route("/api/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json() or {}
    email, password = data.get("email"), data.get("password")

    if not email or not is_valid_email_domain(email):
        return jsonify(error="Insira um endereÃ§o de email valido"), 401
    if not password or not isinstance(password, str):
        return jsonify(error="Credenciais invÃ¡lidas"), 401

    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE email = %s", (email.lower(),))
            user = cursor.fetchone()

            if not user:
                return jsonify(error="Credenciais invÃ¡lidas"), 401

            password_hash = user.get("password")
            if not password_hash:
                return jsonify(error="Esta conta usa login social. Entre com Google."), 401

            if not bcrypt.verify(password, password_hash):
                return jsonify(error="Credenciais invÃ¡lidas"), 401

            if user.get("is_two_factor_enabled"):
                pending_token = create_access_token(
                    identity=str(user['id']),
                    expires_delta=timedelta(minutes=5),
                    additional_claims={"2fa_pending": True}
                )
                return jsonify({
                    "two_factor_required": True,
                    "pending_token": pending_token
                }), 200

            veiculos = fetch_veiculos_user(cursor, user["id"])
            
            access_token = create_access_token(identity=str(user["id"]))
            refresh_token = create_refresh_token(identity=str(user["id"]))
            
            resp = jsonify(
                access_token=access_token,
                refresh_token=refresh_token,
                user={
                    "nome": user["nome"],
                    "is_premium": bool(user.get("is_premium")),
                    "trial_expired": is_trial_expired(user),
                    "trial_days_remaining": get_trial_days_remaining(user),
                    "possui_veiculo": len(veiculos) > 0,
                    "veiculos": veiculos
                }
            )
            set_access_cookies(resp, access_token)
            set_refresh_cookies(resp, refresh_token)
            return resp, 200
    except Exception as e:
        logger.error(f"âŒ Erro no login: {e}")
        return jsonify(error="Erro ao processar login"), 500
    
@auth_bp.route("/api/auth/2fa/verify", methods=["POST"])
def verify_2fa_login():
    data = request.get_json()
    pending_token = data.get("pending_token")
    code = data.get("code")
    
    if not pending_token or not code:
        return jsonify(error="Token e cÃƒÂ³digo sÃƒÂ£o obrigatÃƒÂ³rios"), 400
        
    try:
        decoded = decode_token(pending_token)
        
        if not decoded.get("sub") or not decoded.get("2fa_pending"):
            return jsonify(error="Token invÃƒÂ¡lido ou expirado"), 401
            
        user_id = decoded["sub"]
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            if not user or not user["is_two_factor_enabled"]:
                return jsonify(error="2FA nÃ£o configurado"), 400
                
            secret = user.get("two_factor_secret")
            if not secret:
                return jsonify(error="ConfiguraÃ§Ã£o de 2FA corrompida"), 500
                
            # Verificar se o segredo Ã© um hash bcrypt (antigo) ou base32 (novo)
            is_totp = not secret.startswith("$2") # Bcrypt hashes comeÃ§am com $2
            
            if is_totp:
                totp = pyotp.TOTP(secret)
                is_valid = totp.verify(code)
            else:
                # Fallback para o sistema antigo de senha secundÃ¡ria durante a transiÃ§Ã£o
                try:
                    is_valid = bcrypt.verify(code, secret)
                except Exception:
                    is_valid = False
            
            if is_valid:
                veiculos = fetch_veiculos_user(cursor, user_id)
                access_token = create_access_token(identity=str(user_id))
                refresh_token = create_refresh_token(identity=str(user_id))
                
                resp = jsonify(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    user={
                        "nome": user["nome"], 
                        "is_premium": bool(user.get("is_premium")),
                        "trial_expired": is_trial_expired(user),
                        "trial_days_remaining": get_trial_days_remaining(user),
                        "possui_veiculo": len(veiculos) > 0,
                        "veiculos": veiculos
                    }
                )
                set_access_cookies(resp, access_token)
                set_refresh_cookies(resp, refresh_token)
                return resp, 200
            else:
                return jsonify(error="CÃ³digo 2FA ou senha secundÃ¡ria invÃ¡lida"), 401
    except Exception as e:
        logger.error(f"Erro na verificaÃƒÂ§ÃƒÂ£o 2FA: {e}")
        return jsonify(error="Erro interno na verificaÃƒÂ§ÃƒÂ£o"), 500

@auth_bp.route("/api/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    access_token = create_access_token(identity=str(user_id))
    resp = jsonify(access_token=access_token)
    set_access_cookies(resp, access_token)
    return resp, 200

@auth_bp.route("/api/auth/2fa/setup", methods=["GET"])
@jwt_required()
def setup_2fa():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                return jsonify(error="UsuÃ¡rio nÃ£o encontrado"), 404
            
            secret = pyotp.random_base32()
            totp = pyotp.TOTP(secret)
            provisioning_url = totp.provisioning_uri(name=user["email"], issuer_name="AutoAssist")
            
            return jsonify(secret=secret, provisioning_url=provisioning_url), 200
    except Exception as e:
        logger.error(f"Erro no setup 2FA: {e}")
        return jsonify(error="Erro ao configurar 2FA"), 500

@auth_bp.route("/api/auth/2fa/confirm", methods=["POST"])
@jwt_required()
def confirm_2fa():
    user_id = get_jwt_identity()
    data = request.get_json()
    secret = data.get("secret")
    code = data.get("code")
    
    if not secret or not code:
        return jsonify(error="Secret e cÃ³digo sÃ£o obrigatÃ³rios"), 400
        
    try:
        totp = pyotp.TOTP(secret)
        if totp.verify(code):
            with get_db() as (cursor, conn):
                cursor.execute("""
                    UPDATE users 
                    SET is_two_factor_enabled = TRUE, two_factor_secret = %s 
                    WHERE id = %s
                """, (secret, user_id))
                conn.commit()
            return jsonify(message="2FA (TOTP) ativado com sucesso"), 200
        else:
            return jsonify(error="CÃ³digo invÃ¡lido. Verifique se o relÃ³gio do seu celular estÃ¡ correto."), 400
    except Exception as e:
        logger.error(f"Erro ao confirmar 2FA: {e}")
        return jsonify(error="Erro ao confirmar 2FA"), 500

@auth_bp.route("/api/auth/2fa/disable", methods=["POST"])
@jwt_required()
def disable_2fa():
    user_id = get_jwt_identity()
    data = request.get_json()
    password = data.get("password")
    
    if not password:
        return jsonify(error="Senha secundÃƒÂ¡ria ÃƒÂ© necessÃƒÂ¡ria para desativar"), 400
        
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT two_factor_secret FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            if not user or not user["two_factor_secret"]:
                return jsonify(error="ConfiguraÃ§Ã£o de 2FA nÃ£o encontrada"), 404
            
            # Para desativar, podemos exigir o cÃ³digo TOTP ou a senha principal
            # Aqui vamos exigir o cÃ³digo TOTP para confirmar posse do dispositivo
            totp = pyotp.TOTP(user["two_factor_secret"])
            if totp.verify(password): # O campo 'password' aqui serÃ¡ o cÃ³digo de 6 dÃ­gitos
                cursor.execute("UPDATE users SET is_two_factor_enabled = FALSE, two_factor_secret = NULL WHERE id = %s", (user_id,))
                conn.commit()
                return jsonify(message="2FA desativado com sucesso"), 200
            else:
                return jsonify(error="CÃ³digo TOTP invÃ¡lido"), 400
    except Exception as e:
        logger.error(f"Erro ao desativar 2FA: {e}")
        return jsonify(error="Erro ao desativar 2FA"), 500

@auth_bp.route("/api/auth/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email é obrigatório"}), 400

    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "SELECT id, nome FROM users WHERE email=%s",
                (email.lower(),)
            )
            user = cursor.fetchone()

            if not user:
                return jsonify({
                    "message": "Se o email existir, um link será enviado."
                }), 200

            token = secrets.token_urlsafe(32)
            expiracao = datetime.utcnow() + timedelta(minutes=15)

            cursor.execute("""
                INSERT INTO redefinicao_senha
                (usuario_id, token, data_expiracao)
                VALUES (%s,%s,%s)
            """, (user["id"], token, expiracao))

            logger.info(
                "Solicitacao de reset enfileirada para envio externo (usuario_id=%s, email=%s).",
                user["id"],
                email,
            )

            return jsonify({
                "message": "Se o email existir, um link será enviado."
            }), 200
    except Exception as e:
        logger.error(f"Erro em forgot-password: {e}")
        return jsonify({"error": "Erro interno do servidor"}), 500

@auth_bp.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json()
    token = data.get("token")
    new_password = data.get("password")

    if not token or not new_password or len(new_password) < 6:
        return jsonify(error="Senha invÃƒÂ¡lida"), 400

    try:
        with get_db() as (cursor, conn):
            cursor.execute("""
                SELECT usuario_id
                FROM redefinicao_senha
                WHERE token=%s
                AND data_expiracao > NOW()
            """, (token,))
            registro = cursor.fetchone()

            if not registro:
                return jsonify(error="Token invÃƒÂ¡lido ou expirado"), 400

            hashed = bcrypt.hash(new_password)
            cursor.execute("UPDATE users SET password=%s WHERE id=%s", (hashed, registro["usuario_id"]))
            cursor.execute("DELETE FROM redefinicao_senha WHERE token=%s", (token,))

            return jsonify(message="Senha redefinida com sucesso"), 200
    except Exception as e:
        logger.error(f"Erro ao redefinir senha: {e}")
        return jsonify(error="Erro ao redefinir senha"), 500

