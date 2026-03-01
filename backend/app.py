import os
import logging
from datetime import timedelta, datetime, timezone
from contextlib import contextmanager
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from passlib.hash import bcrypt
from dotenv import load_dotenv
import pymysql
from pymysql.cursors import DictCursor
from nogai import gerar_resposta, get_fipe_value
from vision_ai import analisar_imagem
from report_generator import criar_relatorio_pdf
import speech_recognition as sr
from pydub import AudioSegment
import io
import pyotp
import base64

# ======================================================
# CONFIGURAÇÃO DE LOGGING
# ======================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__, static_folder='../frontend', static_url_path='')

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/<path:path>")
def serve_html(path):
    if not path.endswith(".html") and "." not in path:
        path += ".html"
    return app.send_static_file(path)


# [SEGURANÇA] Cabeçalhos HTTP Seguros
# force_https=True em produção garante que nada trafegue sem SSL
is_production = os.getenv('FLASK_ENV') == 'production'
Talisman(app, force_https=is_production, content_security_policy=None) 

# [SEGURANÇA] Verificação estrita da Secret Key
jwt_secret = os.getenv("JWT_SECRET_KEY")
if not jwt_secret:
    raise ValueError("FATAL: JWT_SECRET_KEY não encontrada nas variáveis de ambiente! O servidor não pode iniciar inseguro.")

app.config.update(
    JWT_SECRET_KEY=jwt_secret,
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=24),
    JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=30),
)

jwt = JWTManager(app)

# [SEGURANÇA] CORS Restrito
# Altere as origens conforme necessário. Nunca use "*" com credenciais em produção.
allowed_origins = [
    "https://autoassis.onrender.com",  # Produção
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:5500",           # Live Server
    "http://127.0.0.1:5500",           # Live Server
    "http://localhost:3000",           # Common dev port
    "http://127.0.0.1:3000",           # Common dev port
]

CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://"
)

# Configuração do Banco
MYSQL_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME'),
    'charset': 'utf8mb4',
    'cursorclass': DictCursor,
    'autocommit': True
}

@contextmanager
def get_db():
    conn = pymysql.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    try:
        yield cursor, conn
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

def init_db():
    with get_db() as (cursor, conn):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                is_premium BOOLEAN DEFAULT FALSE,
                possui_veiculo BOOLEAN DEFAULT FALSE,
                veiculo_marca VARCHAR(50),
                veiculo_modelo VARCHAR(50),
                veiculo_ano_fabricacao INT,
                veiculo_ano_compra INT,
                veiculo_tipo VARCHAR(50),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Adiciona colunas para usuários existentes (ignora erros se já existirem)
        columns = [
            ("possui_veiculo", "BOOLEAN DEFAULT FALSE"),
            ("veiculo_marca", "VARCHAR(50)"),
            ("veiculo_modelo", "VARCHAR(50)"),
            ("veiculo_ano_fabricacao", "INT"),
            ("veiculo_ano_compra", "INT"),
            ("veiculo_tipo", "VARCHAR(50)"),
            ("two_factor_secret", "VARCHAR(255)"), # Aumentado para suportar hashes de senha
            ("is_two_factor_enabled", "BOOLEAN DEFAULT FALSE")
        ]
        for col, dtype in columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
            except Exception: 
                # Se a coluna já existia (VARCHAR 32), forçamos o aumento para 255
                if col == "two_factor_secret":
                    cursor.execute("ALTER TABLE users MODIFY COLUMN two_factor_secret VARCHAR(255)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                mensagem_usuario TEXT,
                resposta_ia TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        print("✅ Banco de dados inicializado com sucesso!")

@app.before_request
def first_request():
    if not hasattr(app, "_db_initialized"):
        try:
            init_db()
            app._db_initialized = True
        except Exception as e:
            logging.error(f"⚠️ Falha ao inicializar banco: {e}")

def is_trial_expired(user):
    if user.get("is_premium"): return False
    created_at = user["created_at"]
    if isinstance(created_at, str): created_at = datetime.fromisoformat(created_at)
    if created_at.tzinfo is None: created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at).days >= 30

@app.route("/health")
def health(): return jsonify(status="healthy"), 200

# --- AUTH ENDPOINTS ---
@app.route("/api/cadastro", methods=["POST"])
def cadastro():
    data = request.get_json()
    nome, email, password = data.get("nome"), data.get("email"), data.get("password")
    
    veiculo = data.get("veiculo", {})
    possui_veiculo = veiculo.get("possui", False)
    
    if not nome or not email or len(password) < 6: return jsonify(error="Dados inválidos"), 400
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
        logging.error(f"❌ Erro no cadastro: {e}")
        return jsonify(error="Erro ao processar cadastro ou email já existe"), 409

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    email, password = data.get("email"), data.get("password")
    
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE email = %s", (email.lower(),))
            user = cursor.fetchone()
            
            if not user or not bcrypt.verify(password, user["password"]):
                return jsonify(error="Credenciais inválidas"), 401
                
            # Se 2FA estiver habilitado, não envia o token de acesso real ainda
            if user.get("is_two_factor_enabled"):
                # Gera um token temporário de 5 minutos apenas para o passo de verificação do 2FA
                # Usamos um claim adicional "2fa_pending" para segurança
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

@app.route("/api/auth/2fa/verify", methods=["POST"])
def verify_2fa_login():
    """Rota pública para completar o login via 2FA."""
    data = request.get_json()
    pending_token = data.get("pending_token")
    code = data.get("code")
    
    if not pending_token or not code:
        return jsonify(error="Token e código são obrigatórios"), 400
        
    try:
        from flask_jwt_extended import decode_token
        decoded = decode_token(pending_token)
        
        if not decoded.get("sub") or not decoded.get("2fa_pending"):
            return jsonify(error="Token inválido ou expirado"), 401
            
        user_id = decoded["sub"]
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            if not user or not user["is_two_factor_enabled"]:
                return jsonify(error="2FA não configurado"), 400
                
            # Verifica se o código (senha secundária) bate com o hash no banco
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

@app.route("/api/auth/2fa/enable", methods=["POST"])
@jwt_required()
def enable_2fa():
    """Ativa o 2FA salvando uma senha secundária escolhida pelo usuário."""
    user_id = get_jwt_identity()
    data = request.get_json()
    secondary_password = data.get("password")
    
    if not secondary_password or len(secondary_password) < 4:
        return jsonify(error="A senha secundária deve ter pelo menos 4 caracteres"), 400
        
    try:
        with get_db() as (cursor, conn):
            # Salva o hash da senha secundária na coluna two_factor_secret
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

@app.route("/api/auth/2fa/disable", methods=["POST"])
@jwt_required()
def disable_2fa():
    """Desativa o 2FA verificando a senha secundária atual."""
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

@app.route("/api/user", methods=["GET"])
@jwt_required()
def get_user():
    user_id = get_jwt_identity()
    with get_db() as (cursor, conn):
        cursor.execute("""
            SELECT nome, email, is_premium, created_at, possui_veiculo,
                   veiculo_marca, veiculo_modelo, veiculo_ano_fabricacao,
                   veiculo_ano_compra, veiculo_tipo, is_two_factor_enabled
            FROM users WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) AS total FROM chats WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()
        return jsonify({
            **user,
            "trial_expired": is_trial_expired(user),
            "is_premium": bool(user["is_premium"]),
            "total_consultas": int(total["total"])
        }), 200

@app.route("/api/user", methods=["PUT"])
@jwt_required()
def update_user():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    nome = (data.get("nome") or "").strip()
    email = (data.get("email") or "").strip().lower()

    if not nome or not email:
        return jsonify(error="Dados inválidos"), 400

    try:
        with get_db() as (cursor, conn):
            # Verifica se o email já existe para outro usuário
            cursor.execute("SELECT id FROM users WHERE email = %s AND id <> %s", (email, user_id))
            if cursor.fetchone():
                return jsonify(error="Email já está em uso"), 409

            # Atualiza os dados
            cursor.execute("""
                UPDATE users SET 
                    nome = %s, email = %s, possui_veiculo = %s,
                    veiculo_marca = %s, veiculo_modelo = %s, veiculo_ano_fabricacao = %s,
                    veiculo_ano_compra = %s, veiculo_tipo = %s
                WHERE id = %s
            """, (
                nome, email, data.get("possui_veiculo", False),
                data.get("veiculo_marca"), data.get("veiculo_modelo"),
                data.get("veiculo_ano_fabricacao"), data.get("veiculo_ano_compra"),
                data.get("veiculo_tipo"), user_id
            ))
            conn.commit()
            
            # Busca dados atualizados para retornar ao frontend
            cursor.execute("""
                SELECT nome, email, is_premium, created_at, possui_veiculo,
                       veiculo_marca, veiculo_modelo, veiculo_ano_fabricacao,
                       veiculo_ano_compra, veiculo_tipo
                FROM users WHERE id = %s
            """, (user_id,))
            user = cursor.fetchone()
            
            cursor.execute("SELECT COUNT(*) AS total FROM chats WHERE user_id = %s", (user_id,))
            total = cursor.fetchone()

            return jsonify({
                **user,
                "trial_expired": is_trial_expired(user),
                "is_premium": bool(user["is_premium"]),
                "total_consultas": int(total["total"]),
                "success": True
            }), 200
    except Exception as e:
        logging.error(f"❌ Erro ao atualizar perfil: {e}")
        return jsonify(error="Erro ao atualizar perfil"), 500

@app.route("/api/user", methods=["DELETE"])
@jwt_required()
def delete_user():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return jsonify(success=True), 200
    except Exception as e:
        logging.error(f"❌ Erro ao excluir conta: {e}")
        return jsonify(error="Erro ao excluir conta"), 500

@app.route("/api/chat", methods=["POST"])
@jwt_required()
def chat():
    user_id = get_jwt_identity()
    data = request.get_json()
    msg, img_b64 = data.get("message"), data.get("image")
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if is_trial_expired(user): return jsonify(error="TRIAL_EXPIRED"), 402
            
            resposta = analisar_imagem(img_b64, msg) if img_b64 else gerar_resposta(msg, user_id, user_data=user)
            cursor.execute("INSERT INTO chats (user_id, mensagem_usuario, resposta_ia) VALUES (%s, %s, %s)",
                           (user_id, msg or "[Imagem]", resposta))
            return jsonify(response=resposta)
    except Exception as e:
        logger.error(f"❌ Erro na rota /api/chat: {e}")
        return jsonify(error="Erro interno ao processar chat."), 500

@app.route("/api/voice", methods=["POST"])
@jwt_required()
def voice_to_text():
    user_id = get_jwt_identity()
    if 'audio' not in request.files:
        return jsonify(error="Arquivo de áudio não enviado"), 400
    
    audio_file = request.files['audio']
    try:
        # 1. Converter WebM/Ogg (padrão browser) para WAV (requisito do SpeechRecognition)
        audio = AudioSegment.from_file(io.BytesIO(audio_file.read()))
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)

        # 2. Transcrever usando Google (SpeechRecognition)
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="pt-BR")
            
        logger.info(f"🎙️ Voz transcrita para usuário {user_id}: {text}")
        
        # 3. Processar resposta com o NOG
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            resposta = gerar_resposta(text, user_id, user_data=user)
            cursor.execute("INSERT INTO chats (user_id, mensagem_usuario, resposta_ia) VALUES (%s, %s, %s)",
                           (user_id, text, resposta))
            
            return jsonify(text=text, response=resposta)

    except sr.UnknownValueError:
        return jsonify(error="Não entendi o que você disse"), 422
    except sr.RequestError as e:
        logger.error(f"Erro no serviço de voz do Google: {e}")
        return jsonify(error="Serviço de voz indisponível no momento"), 503
    except Exception as e:
        logger.error(f"Erro no processamento de voz: {e}")
        return jsonify(error="Falha técnica ao processar áudio"), 500

@app.route("/api/chat/history", methods=["GET"])
@jwt_required()
def get_chat_history():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("""
                SELECT mensagem_usuario, resposta_ia, created_at 
                FROM chats 
                WHERE user_id = %s 
                ORDER BY created_at ASC
            """, (user_id,))
            chats = cursor.fetchall()
            # Converte datetime para string se necessário
            for c in chats:
                if isinstance(c['created_at'], datetime):
                    c['created_at'] = c['created_at'].isoformat()
            return jsonify(chats=chats), 200
    except Exception as e:
        logging.error(f"❌ Erro ao buscar histórico: {e}")
        return jsonify(error="Erro ao buscar histórico"), 500

@app.route("/api/dashboard", methods=["GET"])
@jwt_required()
def get_dashboard():
    user_id = get_jwt_identity()
    try:
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            if not user or not user.get("possui_veiculo"):
                return jsonify(error="VEHICLE_NOT_FOUND"), 404
                
            ano_atual = datetime.now().year
            ano_fab = user["veiculo_ano_fabricacao"] or ano_atual
            idade = ano_atual - ano_fab
            
            # Lógica de Saúde (Baseada em idade e tipo)
            alertas = []
            if idade >= 5:
                alertas.append({"item": "Suspensão", "status": "Atenção", "msg": "Revisar amortecedores e buchas."})
            if idade >= 3:
                alertas.append({"item": "Líquido Arrefecimento", "status": "Aviso", "msg": "Troca recomendada a cada 2-3 anos."})
            
            alertas.append({"item": "Pneus", "status": "Ok" if idade < 4 else "Atenção", "msg": "Verificar TWI e validade."})
            alertas.append({"item": "Freios", "status": "Ok", "msg": "Monitorar espessura das pastilhas."})
            
            # Mapeamento do tipo para a API Fipe
            tipo_map = {
                "carro": "carros",
                "moto": "motos",
                "caminhao": "caminhoes",
                "caminhão": "caminhoes"
            }
            tipo_fipe = tipo_map.get(user["veiculo_tipo"].lower(), "carros") if user["veiculo_tipo"] else "carros"
            
            # Busca valor real na API Fipe
            dados_fipe = get_fipe_value(
                tipo_fipe, 
                user["veiculo_marca"], 
                user["veiculo_modelo"], 
                ano_fab
            )
            
            if dados_fipe:
                preco_fipe = dados_fipe.get("Valor", "N/A")
                mes_fipe = dados_fipe.get("MesReferencia", datetime.now().strftime("%B %Y"))
            else:
                # Fallback: Cálculo de depreciação simplificado se a API falhar
                valor_base = 80000 if user["veiculo_tipo"] == "carro" else 30000
                valor_estimado = valor_base * (0.92 ** idade)
                preco_fipe = f"R$ {valor_estimado:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                mes_fipe = f"{datetime.now().strftime('%B %Y')} (Estimado)"
            
            return jsonify({
                "veiculo": {
                    "marca": user["veiculo_marca"],
                    "modelo": user["veiculo_modelo"],
                    "ano": ano_fab,
                    "tipo": user["veiculo_tipo"]
                },
                "saude": alertas,
                "fipe": {
                    "preco": preco_fipe,
                    "mes": mes_fipe
                }
            }), 200
    except Exception as e:
        logging.error(f"❌ Erro no dashboard: {e}")
        return jsonify(error="Erro ao carregar dashboard"), 500

# [NOVO] Endpoint de Relatório (Faltava no original)
@app.route("/api/report", methods=["POST"])
@jwt_required()
def generate_report_endpoint():
    user_id = get_jwt_identity()
    data = request.get_json()
    text_content = data.get("text")
    
    if not text_content:
        return jsonify(error="Conteúdo do relatório vazio"), 400

    try:
        # Verifica se é premium antes de gerar e pega dados do usuário
        with get_db() as (cursor, conn):
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user or not user['is_premium']:
                return jsonify(error="Recurso exclusivo para Premium"), 403
        
        # Garante diretório de relatórios
        report_dir = os.path.join(app.static_folder, 'reports')
        if not os.path.exists(report_dir):
            os.makedirs(report_dir)

        filename = f"laudo_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        filepath = os.path.join(report_dir, filename)
        
        # Gera o PDF
        criar_relatorio_pdf(user, text_content, filepath)
        
        # Retorna a URL para download (relativa à raiz estática)
        return jsonify(url=f"/reports/{filename}"), 200
    except Exception as e:
        logging.error(f"❌ Erro ao gerar relatório: {e}")
        return jsonify(error="Falha na geração do PDF"), 500

@app.route("/api/pay/mock", methods=["POST"])
@jwt_required()
def pay():
    user_id = get_jwt_identity()
    with get_db() as (cursor, conn):
        cursor.execute("UPDATE users SET is_premium = TRUE WHERE id = %s", (user_id,))
    return jsonify(success=True, message="Upgrade concluído!")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
