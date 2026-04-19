from flask import Blueprint, request, jsonify, redirect, url_for
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    decode_token
)
from passlib.hash import bcrypt
import secrets
import os
import logging
import requests
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from oauthlib.oauth2 import WebApplicationClient
from .database import get_db, is_valid_email_domain, is_trial_expired, enviar_email, get_trial_days_remaining

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

def fetch_veiculos_user(cursor, user_id):
    cursor.execute("SELECT id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem FROM veiculos WHERE user_id = %s", (user_id,))
    return cursor.fetchall()


# Configuração Google OAuth2
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
        logger.error("Configuração Google OAuth2 ausente ou incompleta")
        return jsonify(error="Configuração do Google OAuth2 incompleta"), 500
    
    authorization_url = google_client.prepare_request_uri(
        uri=hosts.authorization_endpoint,
        redirect_uri=GOOGLE_REDIRECT_URI,
        scope=["openid", "email", "profile"]
    )
    return redirect(authorization_url)

@auth_bp.route("/api/auth/google/callback")
def google_callback():
    code = request.args.get("code")
    hosts = get_google_oauth_hosts()
    
    if not hosts or not google_client or not code:
        return jsonify(error="Dados de callback inválidos"), 400

    try:
        # Trocar código por token
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
            return jsonify(error="Falha na autenticação com Google"), 400

        google_client.parse_request_body_response(json.dumps(token_response.json()))

        # Pegar dados do usuário
        uri, headers, body = google_client.add_token(hosts.userinfo_endpoint)
        user_info_response = requests.get(uri, headers=headers, data=body)
        
        if user_info_response.status_code != 200:
            return jsonify(error="Falha ao obter dados do usuário"), 400

        user_info = user_info_response.json()
        if not user_info.get("email_verified"):
            return jsonify(error="Email Google não verificado"), 400

        google_id = user_info["sub"]
        email = user_info["email"].lower()
        nome = user_info.get("name", email.split('@')[0])
        picture = user_info.get("picture")

        # Persistir no MySQL
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()

            if user:
                # Atualiza usuário existente com info do Google
                cursor.execute("""
                    UPDATE users 
                    SET google_id = %s, profile_pic = %s 
                    WHERE email = %s
                """, (google_id, picture, email))
            else:
                # Cria novo usuário sem senha (Login Social)
                cursor.execute("""
                    INSERT INTO users (nome, email, google_id, profile_pic) 
                    VALUES (%s, %s, %s, %s)
                """, (nome, email, google_id, picture))
                
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            veiculos = fetch_veiculos_user(cursor, user["id"])

        # Gerar tokens JWT (iguais ao login regular)
        access_token = create_access_token(identity=str(user["id"]))
        refresh_token = create_refresh_token(identity=str(user["id"]))
        
        # Obter a URL do frontend do .env
        frontend_base = os.getenv("FRONTEND_URL", "http://localhost:5500/")
        
        # Preparar dados do usuário para o frontend
        user_payload = {
            "nome": user["nome"], 
            "is_premium": True, 
            "trial_expired": False,
            "trial_days_remaining": 9999,
            "possui_veiculo": len(veiculos) > 0,
            "veiculos": veiculos,
            "profile_pic": user.get("profile_pic")
        }

        # Redirecionar com os tokens na URL
        import urllib.parse
        params = urllib.parse.urlencode({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": json.dumps(user_payload)
        })
        
        # Trata a URL de redirecionamento
        if "index.html" in frontend_base:
            separator = "&" if "?" in frontend_base else "?"
            redirect_url = f"{frontend_base}{separator}{params}"
        else:
            # Garante que termina com / antes de index.html
            base = frontend_base if frontend_base.endswith("/") else f"{frontend_base}/"
            redirect_url = f"{base}index.html?{params}"
            
        return redirect(redirect_url)

    except Exception as e:
        logger.error(f"Erro no callback do Google: {e}", exc_info=True)
        return jsonify(error="Erro interno no login Google"), 500

@auth_bp.route("/api/cadastro", methods=["POST"])
def cadastro():
    data = request.get_json()
    nome, email, password = data.get("nome"), data.get("email"), data.get("password")
    
    veiculo = data.get("veiculo", {})
    veiculos = data.get("veiculos", [])
    if veiculo and veiculo.get("possui"):
        veiculos.append(veiculo)
    
    possui_veiculo = len(veiculos) > 0
    
    if not nome or not email or len(password) < 6: return jsonify(error="Dados inválidos"), 400
    
    if not is_valid_email_domain(email):
        return jsonify(error="Insira um endereço de email valido"), 400
    try:
        with get_db() as (cursor, conn):
            cursor.execute("""
                INSERT INTO users (
                    nome, email, password, possui_veiculo
                ) VALUES (%s, %s, %s, %s)
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
        logger.error(f"❌ Erro no cadastro: {e}")
        return jsonify(error="Erro ao processar cadastro ou email já existe"), 409

@auth_bp.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    email, password = data.get("email"), data.get("password")
    
    if not email or not is_valid_email_domain(email):
        return jsonify(error="Insira um endereço de email valido"), 401

    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE email = %s", (email.lower(),))
            user = cursor.fetchone()
            
            if not user or not bcrypt.verify(password, user["password"]):
                return jsonify(error="Credenciais inválidas"), 401
                
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
            return jsonify(
                access_token=create_access_token(identity=str(user["id"])),
                refresh_token=create_refresh_token(identity=str(user["id"])),
                user={
                    "nome": user["nome"], 
                    "is_premium": True, 
                    "trial_expired": False,
                    "trial_days_remaining": 9999,
                    "possui_veiculo": len(veiculos) > 0,
                    "veiculos": veiculos
                }
            ), 200
    except Exception as e:
        logger.error(f"❌ Erro no login: {e}")
        return jsonify(error="Erro ao processar login"), 500

@auth_bp.route("/api/auth/2fa/verify", methods=["POST"])
def verify_2fa_login():
    data = request.get_json()
    pending_token = data.get("pending_token")
    code = data.get("code")
    
    if not pending_token or not code:
        return jsonify(error="Token e código são obrigatórios"), 400
        
    try:
        decoded = decode_token(pending_token)
        
        if not decoded.get("sub") or not decoded.get("2fa_pending"):
            return jsonify(error="Token inválido ou expirado"), 401
            
        user_id = decoded["sub"]
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            if not user or not user["is_two_factor_enabled"]:
                return jsonify(error="2FA não configurado"), 400
                
            try:
                secret_hash = user.get("two_factor_secret")
                if not secret_hash or not bcrypt.verify(code, secret_hash):
                    return jsonify(error="Senha secundária incorreta"), 401
                
                veiculos = fetch_veiculos_user(cursor, user_id)
                return jsonify(
                    access_token=create_access_token(identity=str(user_id)),
                    refresh_token=create_refresh_token(identity=str(user_id)),
                    user={
                        "nome": user["nome"], 
                        "is_premium": True, 
                        "trial_expired": False,
                        "trial_days_remaining": 9999,
                        "possui_veiculo": len(veiculos) > 0,
                        "veiculos": veiculos
                    }
                ), 200
            except Exception as e:
                logger.error(f"Erro ao verificar hash de 2FA: {e}")
                return jsonify(error="Erro de compatibilidade no 2FA. Por favor, desative e reative sua senha secundária."), 401
    except Exception as e:
        logger.error(f"Erro na verificação 2FA: {e}")
        return jsonify(error="Erro interno na verificação"), 500

@auth_bp.route("/api/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    return jsonify(access_token=create_access_token(identity=str(user_id))), 200

@auth_bp.route("/api/auth/2fa/enable", methods=["POST"])
@jwt_required()
def enable_2fa():
    user_id = get_jwt_identity()
    data = request.get_json()
    secondary_password = data.get("password")
    
    if not secondary_password or len(secondary_password) < 4:
        return jsonify(error="A senha secundária deve ter pelo menos 4 caracteres"), 400
        
    try:
        with get_db() as (cursor, conn):
            hashed_password = bcrypt.hash(secondary_password)
            cursor.execute("""
                UPDATE users 
                SET is_two_factor_enabled = TRUE, two_factor_secret = %s 
                WHERE id = %s
            """, (hashed_password, user_id))
            return jsonify(message="Senha secundária (2FA) ativada com sucesso"), 200
    except Exception as e:
        logger.error(f"Erro ao ativar 2FA: {e}")
        return jsonify(error="Erro ao ativar 2FA"), 500

@auth_bp.route("/api/auth/2fa/disable", methods=["POST"])
@jwt_required()
def disable_2fa():
    user_id = get_jwt_identity()
    data = request.get_json()
    password = data.get("password")
    
    if not password:
        return jsonify(error="Senha secundária é necessária para desativar"), 400
        
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT two_factor_secret FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify(error="Usuário não encontrado"), 404
                
            if bcrypt.verify(password, user["two_factor_secret"]):
                cursor.execute("UPDATE users SET is_two_factor_enabled = FALSE, two_factor_secret = NULL WHERE id = %s", (user_id,))
                return jsonify(message="2FA desativado com sucesso"), 200
            else:
                return jsonify(error="Senha secundária incorreta"), 400
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

            frontend_url = os.getenv("FRONTEND_URL", request.host_url)
            if not frontend_url.endswith("/"):
                frontend_url += "/"
            
            reset_link = f"{frontend_url}redefinir-senha.html?token={token}"

            mensagem = f"""
<h2>Redefinição de senha</h2>
<p>Você solicitou redefinir sua senha.</p>
<p>Clique no link abaixo:</p>
<a href="{reset_link}">Redefinir senha</a>
<p>Este link expira em 15 minutos.</p>
<p>Se você não solicitou isso, ignore este email.</p>
"""
            enviar_email(email, "Redefinição de senha", mensagem)
            logger.info(f"Email de redefinição enviado para {email}")

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
        return jsonify(error="Senha inválida"), 400

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
                return jsonify(error="Token inválido ou expirado"), 400

            hashed = bcrypt.hash(new_password)
            cursor.execute("UPDATE users SET password=%s WHERE id=%s", (hashed, registro["usuario_id"]))
            cursor.execute("DELETE FROM redefinicao_senha WHERE token=%s", (token,))

            return jsonify(message="Senha redefinida com sucesso"), 200
    except Exception as e:
        logger.error(f"Erro ao redefinir senha: {e}")
        return jsonify(error="Erro ao redefinir senha"), 500
