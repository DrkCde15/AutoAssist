import os
import pymysql
import logging
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from pymysql.cursors import DictCursor
from utils.email import enviar_email

# Carrega variáveis de ambiente procurando o .env na pasta pai (backend/)
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '..', '.env'))

# Configurações de Banco
MYSQL_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost').strip(),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', '').strip(),
    'password': os.getenv('DB_PASSWORD', '').strip(),
    'database': os.getenv('DB_NAME', '').strip(),
    'charset': 'utf8mb4',
    'cursorclass': DictCursor,
    'autocommit': True,
    'connect_timeout': 10,
    'ssl': {'ssl_disabled': False}
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
                veiculo_quilometragem INT,
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
                quilometragem INT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        # Adiciona colunas para usuários existentes
        columns = [
            ("possui_veiculo", "BOOLEAN DEFAULT FALSE"),
            ("veiculo_marca", "VARCHAR(50)"),
            ("veiculo_modelo", "VARCHAR(50)"),
            ("veiculo_ano_fabricacao", "INT"),
            ("veiculo_ano_compra", "INT"),
            ("veiculo_tipo", "VARCHAR(50)"),
            ("veiculo_quilometragem", "INT"),
            ("two_factor_secret", "VARCHAR(255)"), 
            ("is_two_factor_enabled", "BOOLEAN DEFAULT FALSE"),
            ("google_id", "VARCHAR(255)"),
            ("profile_pic", "VARCHAR(500)"),
            ("maintenance_email_enabled", "BOOLEAN DEFAULT TRUE"),
            ("maintenance_email_last_sent", "DATETIME NULL"),
            ("is_admin", "BOOLEAN DEFAULT FALSE")
        ]
        for col, dtype in columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
            except Exception: 
                pass

        veiculos_columns = [
            ("quilometragem", "INT")
        ]
        for col, dtype in veiculos_columns:
            try:
                cursor.execute(f"ALTER TABLE veiculos ADD COLUMN {col} {dtype}")
            except Exception:
                pass

        try:
            cursor.execute("""
                INSERT INTO veiculos (user_id, tipo, marca, modelo, ano_fabricacao, ano_compra, quilometragem)
                SELECT id, veiculo_tipo, veiculo_marca, veiculo_modelo, veiculo_ano_fabricacao, veiculo_ano_compra, veiculo_quilometragem
                FROM users 
                WHERE possui_veiculo = TRUE 
                AND veiculo_marca IS NOT NULL
                AND id NOT IN (SELECT DISTINCT user_id FROM veiculos)
            """)
        except Exception as e:
            print(f"Aviso migração veículos: {e}")
        
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
        try:
            cursor.execute("ALTER TABLE chats ADD COLUMN links JSON")
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                vehicle_id INT NULL,
                description TEXT NOT NULL,
                maintenance_type VARCHAR(60) NOT NULL DEFAULT 'manutencao_geral',
                maintenance_label VARCHAR(100) NOT NULL DEFAULT 'Manutencao geral',
                service_date DATE NOT NULL,
                service_km INT NULL,
                cost DECIMAL(10,2) NULL,
                currency VARCHAR(10) NOT NULL DEFAULT 'BRL',
                interval_days INT NULL,
                interval_km INT NULL,
                next_due_date DATE NULL,
                next_due_km INT NULL,
                parser_metadata JSON NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_maintenance_user_date (user_id, service_date),
                INDEX idx_maintenance_vehicle (vehicle_id),
                INDEX idx_maintenance_due_date (next_due_date),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (vehicle_id) REFERENCES veiculos(id) ON DELETE SET NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments_orders (
                id VARCHAR(100) PRIMARY KEY,
                user_id INT NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                amount DECIMAL(10,2),
                provider VARCHAR(50) DEFAULT 'cakto',
                provider_order_id VARCHAR(100),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        print("✅ Banco de dados inicializado com sucesso!")

# (enviar_email removido daqui e movido para utils.email)

def is_trial_expired(user):
    if not user or not user.get("created_at"):
        return True
    
    created_at = user["created_at"]
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        except ValueError:
            return True
            
    # Trial de 7 dias
    expiry_date = created_at + timedelta(days=7)
    return datetime.now(timezone.utc if created_at.tzinfo else None) > expiry_date

def get_trial_days_remaining(user):
    if not user or not user.get("created_at"):
        return 0
        
    created_at = user["created_at"]
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        except ValueError:
            return 0
            
    expiry_date = created_at + timedelta(days=7)
    delta = expiry_date - datetime.now(timezone.utc if created_at.tzinfo else None)
    return max(0, delta.days)

def is_valid_email_domain(email):
    allowed_domains = ["@gmail.com", "@hotmail.com", "@yahoo.com", "@email.com", "@testuser.com"]
    email_lower = email.lower()
    return any(email_lower.endswith(domain) for domain in allowed_domains)
