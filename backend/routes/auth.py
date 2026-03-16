from flask import Blueprint, request, jsonify
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
from datetime import datetime, timedelta
from .database import get_db, is_valid_email_domain, is_trial_expired, enviar_email

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

@auth_bp.route("/api/cadastro", methods=["POST"])
def cadastro():
    data = request.get_json()
    nome, email, password = data.get("nome"), data.get("email"), data.get("password")
    
    veiculo = data.get("veiculo", {})
    possui_veiculo = veiculo.get("possui", False)
    
    if not nome or not email or len(password) < 6: return jsonify(error="Dados inválidos"), 400
    
    if not is_valid_email_domain(email):
        return jsonify(error="Insira um endereço de email valido"), 400
    try:
        with get_db() as (cursor, conn):
            cursor.execute("""
                INSERT INTO users (
                    nome, email, password, possui_veiculo, 
                    veiculo_marca, veiculo_modelo, veiculo_ano_fabricacao, 
                    veiculo_ano_compra, veiculo_tipo
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                nome, email.lower(), bcrypt.hash(password), possui_veiculo,
                veiculo.get("marca"), veiculo.get("modelo"), veiculo.get("ano_fabricacao"),
                veiculo.get("ano_compra"), veiculo.get("tipo")
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

            return jsonify(
                access_token=create_access_token(identity=str(user["id"])),
                refresh_token=create_refresh_token(identity=str(user["id"])),
                user={
                    "nome": user["nome"], 
                    "is_premium": bool(user["is_premium"]), 
                    "trial_expired": is_trial_expired(user),
                    "possui_veiculo": bool(user["possui_veiculo"]),
                    "veiculo_marca": user["veiculo_marca"],
                    "veiculo_modelo": user["veiculo_modelo"]
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
                
                return jsonify(
                    access_token=create_access_token(identity=str(user_id)),
                    refresh_token=create_refresh_token(identity=str(user_id)),
                    user={
                        "nome": user["nome"], 
                        "is_premium": bool(user["is_premium"]), 
                        "trial_expired": is_trial_expired(user),
                        "possui_veiculo": bool(user["possui_veiculo"]),
                        "veiculo_marca": user["veiculo_marca"],
                        "veiculo_modelo": user["veiculo_modelo"]
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
