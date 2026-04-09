import os
import pymysql
import smtplib
import logging
from dotenv import load_dotenv

# Carrega variáveis de ambiente procurando o .env na pasta pai (backend/)
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '..', '.env'))
from datetime import datetime, timezone
from contextlib import contextmanager
from pymysql.cursors import DictCursor
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Configurações de Email
EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE")
EMAIL_SENHA_APP = os.getenv("EMAIL_SENHA_APP")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

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
        # Criação da tabela de múltiplos veículos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS veiculos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                tipo VARCHAR(50),
                marca VARCHAR(50),
                modelo VARCHAR(50),
                ano_fabricacao INT,
                ano_compra INT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        # Migração de dados de veículos existentes da tabela users
        try:
            cursor.execute("""
                INSERT INTO veiculos (user_id, tipo, marca, modelo, ano_fabricacao, ano_compra)
                SELECT id, veiculo_tipo, veiculo_marca, veiculo_modelo, veiculo_ano_fabricacao, veiculo_ano_compra 
                FROM users 
                WHERE possui_veiculo = TRUE 
                AND veiculo_marca IS NOT NULL
                AND id NOT IN (SELECT DISTINCT user_id FROM veiculos)
            """)
        except Exception as e:
            print(f"Aviso migração veículos: {e}")
        # Adiciona colunas para usuários existentes (ignora erros se já existirem)
        columns = [
            ("possui_veiculo", "BOOLEAN DEFAULT FALSE"),
            ("veiculo_marca", "VARCHAR(50)"),
            ("veiculo_modelo", "VARCHAR(50)"),
            ("veiculo_ano_fabricacao", "INT"),
            ("veiculo_ano_compra", "INT"),
            ("veiculo_tipo", "VARCHAR(50)"),
            ("two_factor_secret", "VARCHAR(255)"), 
            ("is_two_factor_enabled", "BOOLEAN DEFAULT FALSE"),
            ("google_id", "VARCHAR(255)"),
            ("profile_pic", "VARCHAR(500)")
        ]
        for col, dtype in columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
            except Exception: 
                pass
        
        # Permitir senha NULA para usuários de Login Social
        try:
            cursor.execute("ALTER TABLE users MODIFY COLUMN password VARCHAR(255) NULL")
        except Exception as e:
            print(f"Erro ao modificar coluna password: {e}")
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
        try:
            cursor.execute("ALTER TABLE chats ADD COLUMN videos JSON")
        except Exception:
            pass
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS redefinicao_senha (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                token VARCHAR(255) NOT NULL,
                data_expiracao DATETIME NOT NULL,
                FOREIGN KEY (usuario_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                titulo VARCHAR(255) NOT NULL,
                url VARCHAR(500) NOT NULL,
                descricao TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        print("✅ Banco de dados inicializado com sucesso!")

def enviar_email(destinatario, assunto, mensagem_html):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_REMETENTE
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.attach(MIMEText(mensagem_html, "html"))
    try:
        servidor = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        servidor.starttls()
        servidor.login(EMAIL_REMETENTE, EMAIL_SENHA_APP)
        servidor.sendmail(EMAIL_REMETENTE, destinatario, msg.as_string())
        servidor.quit()
        print("📧 Email enviado com sucesso!")
    except Exception as e:
        print("Erro ao enviar email:", e)

def is_trial_expired(user):
    return False

def get_trial_days_remaining(user):
    return 9999

def is_valid_email_domain(email):
    """Valida se o email pertence aos domínios permitidos."""
    allowed_domains = ["@gmail.com", "@hotmail.com", "@yahoo.com", "@email.com", "@testuser.com", "@client.com"]
    email_lower = email.lower()
    return any(email_lower.endswith(domain) for domain in allowed_domains)
