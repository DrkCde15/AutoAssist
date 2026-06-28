import os
import pymysql
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from pymysql.cursors import DictCursor

from dbutils.pooled_db import PooledDB

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

# Inicializa o Pool de Conexões
pool = PooledDB(
    creator=pymysql,
    mincached=2,
    maxcached=10,
    maxconnections=20,
    blocking=True,
    **MYSQL_CONFIG
)

@contextmanager
def get_db():
    conn = pool.connection()
    cursor = conn.cursor()
    try:
        yield cursor, conn
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close() # Retorna a conexão ao pool

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
        # Otimização: Busca colunas existentes para evitar ALTER TABLE desnecessário
        cursor.execute("SHOW COLUMNS FROM users")
        existing_columns = {row['Field'] for row in cursor.fetchall()}
        
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
            if col not in existing_columns:
                try:
                    print(f"Adicionando coluna faltante {col} em users...")
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
                except Exception as e:
                    print(f"Erro ao adicionar coluna {col}: {e}")
        
        cursor.execute("SHOW COLUMNS FROM veiculos")
        existing_veiculos_columns = {row['Field'] for row in cursor.fetchall()}
        veiculos_columns = [
            ("quilometragem", "INT"),
            ("fipe_valor", "VARCHAR(50) NULL"),
            ("fipe_mes_referencia", "VARCHAR(50) NULL"),
            ("fipe_updated_at", "DATETIME NULL"),
        ]
        for col, dtype in veiculos_columns:
            if col not in existing_veiculos_columns:
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
                session_id VARCHAR(50),
                mensagem_usuario TEXT,
                resposta_ia TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        try:
            cursor.execute("ALTER TABLE chats ADD COLUMN session_id VARCHAR(50)")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE chats ADD COLUMN videos JSON")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE chats ADD COLUMN links JSON")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE chats ADD COLUMN topic VARCHAR(255)")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE chats ADD COLUMN attachments JSON")
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
        reset_columns = [
            ("email_sent", "BOOLEAN DEFAULT FALSE"),
            ("email_attempts", "INT DEFAULT 0"),
            ("last_attempt_at", "DATETIME NULL"),
            ("send_error", "TEXT NULL")
        ]
        for col, dtype in reset_columns:
            try:
                cursor.execute(f"ALTER TABLE redefinicao_senha ADD COLUMN {col} {dtype}")
            except Exception:
                pass
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
                alert_last_status_code VARCHAR(30) NULL,
                alert_last_sent_at DATETIME NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_maintenance_user_date (user_id, service_date),
                INDEX idx_maintenance_vehicle (vehicle_id),
                INDEX idx_maintenance_due_date (next_due_date),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (vehicle_id) REFERENCES veiculos(id) ON DELETE SET NULL
            )
        """)
        maintenance_columns = [
            ("alert_last_status_code", "VARCHAR(30) NULL"),
            ("alert_last_sent_at", "DATETIME NULL"),
        ]
        for col, dtype in maintenance_columns:
            try:
                cursor.execute(f"ALTER TABLE maintenance_history ADD COLUMN {col} {dtype}")
            except Exception:
                pass
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_notes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                note TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_maintenance_notes_user_created (user_id, created_at),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        try:
            cursor.execute("ALTER TABLE maintenance_notes ADD COLUMN user_id INT NULL")
        except Exception:
            pass
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                nome VARCHAR(100),
                email VARCHAR(100),
                estrelas INT DEFAULT 5,
                comentario TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analytics_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                anonymous_id VARCHAR(80) NULL,
                event_type VARCHAR(80) NOT NULL,
                path VARCHAR(500) NULL,
                metadata JSON NULL,
                user_agent VARCHAR(500) NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_analytics_created (created_at),
                INDEX idx_analytics_event_created (event_type, created_at),
                INDEX idx_analytics_user_created (user_id, created_at),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS guest_chat_usage (
                guest_id_hash CHAR(64) PRIMARY KEY,
                message_count INT NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        # Otimizações de Banco de Dados: Adicionando Índices para consultas frequentes
        indexes = [
            "CREATE INDEX idx_chats_user_created ON chats (user_id, created_at DESC)",
            "CREATE INDEX idx_chats_user_id ON chats (user_id, id)",
            "CREATE INDEX idx_feedbacks_created ON feedbacks (created_at DESC)",
            "CREATE INDEX idx_veiculos_user ON veiculos (user_id)",
            "CREATE INDEX idx_videos_user ON videos (user_id)",
            "CREATE INDEX idx_videos_user_created ON videos (user_id, created_at DESC)",
            "CREATE INDEX idx_redefinicao_token ON redefinicao_senha (token)",
            "CREATE INDEX idx_redefinicao_queue ON redefinicao_senha (email_sent, data_expiracao, last_attempt_at, id)",
            "CREATE INDEX idx_users_email ON users (email)",
            "CREATE INDEX idx_users_google_id ON users (google_id)",
            "CREATE INDEX idx_maintenance_user_vehicle_date ON maintenance_history (user_id, vehicle_id, service_date DESC, created_at DESC)",
            "CREATE INDEX idx_maintenance_notes_user_created ON maintenance_notes (user_id, created_at DESC)",
            "CREATE INDEX idx_analytics_anonymous_created ON analytics_events (anonymous_id, created_at)"
        ]
        for idx_query in indexes:
            try:
                cursor.execute(idx_query)
            except Exception:
                pass # Ignora se o índice já existir

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

    # Trial de 30 dias
    expiry_date = created_at + timedelta(days=30)
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

    expiry_date = created_at + timedelta(days=30)
    delta = expiry_date - datetime.now(timezone.utc if created_at.tzinfo else None)
    return max(0, delta.days)

def get_mysql_history(user_id: int, limit: int = 5, cursor=None):
    """Recupera o histórico de conversas do MySQL."""
    if cursor is not None:
        try:
            cursor.execute(
                "SELECT mensagem_usuario, resposta_ia FROM chats WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            )
            rows = cursor.fetchall()
            history = []
            for row in reversed(rows):
                if row['mensagem_usuario']:
                    history.append({"role": "user", "content": row['mensagem_usuario']})
                if row['resposta_ia']:
                    history.append({"role": "model", "content": row['resposta_ia']})
            return history
        except Exception as e:
            logging.error(f"Erro histórico MySQL: {e}")
            return []

    try:
        from database import get_db
    except ImportError:
        # Fallback se for chamado de dentro do próprio módulo
        from .database import get_db

    try:
        with get_db() as (cursor, conn):
            cursor.execute(
                "SELECT mensagem_usuario, resposta_ia FROM chats WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            )
            rows = cursor.fetchall()
            history = []
            for row in reversed(rows):
                if row['mensagem_usuario']:
                    history.append({"role": "user", "content": row['mensagem_usuario']})
                if row['resposta_ia']:
                    history.append({"role": "model", "content": row['resposta_ia']})
            return history
    except Exception as e:
        logging.error(f"Erro histórico MySQL: {e}")
        return []

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def is_valid_email_domain(email):
    if not isinstance(email, str):
        return False
    return bool(EMAIL_PATTERN.fullmatch(email.strip().lower()))
