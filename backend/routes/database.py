import os
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

from dbutils.pooled_db import PooledDB

# Carrega variáveis de ambiente procurando o .env na pasta pai (backend/)

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '..', '.env'))

# ── Engine: mysql (default, Aiven/local) ou postgres (Neon) ──
# Ativa PG via DATABASE_URL=postgresql://... (formato do Neon) ou DB_ENGINE=postgres.
# Todo SQL do app usa placeholder %s (compatível com pymysql e psycopg).
_DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
DB_ENGINE = (os.getenv("DB_ENGINE") or "").strip().lower()
if not DB_ENGINE:
    DB_ENGINE = "postgres" if _DATABASE_URL.startswith(("postgres://", "postgresql://")) else "mysql"


def is_postgres() -> bool:
    return DB_ENGINE == "postgres"


if is_postgres():
    try:
        import psycopg  # noqa: F401 (driver PG)
    except ImportError as exc:
        raise RuntimeError("DB_ENGINE=postgres exige psycopg instalado.") from exc
    _pg_conninfo = _DATABASE_URL or None
    if _pg_conninfo is None:
        # Monta conninfo a partir das peças DB_HOST/DB_USER/... (sslmode=require p/ Neon).
        _pg_parts = [
            f"host={os.getenv('DB_HOST', 'localhost').strip()}",
            f"port={os.getenv('DB_PORT', '5432').strip()}",
            f"dbname={os.getenv('DB_NAME', '').strip()}",
            f"user={os.getenv('DB_USER', '').strip()}",
            f"password={os.getenv('DB_PASSWORD', '').strip()}",
            f"sslmode={os.getenv('DB_SSLMODE', 'require').strip()}",
            f"connect_timeout={os.getenv('DB_CONNECT_TIMEOUT', '10').strip()}",
        ]
        _pg_conninfo = " ".join(_pg_parts)
    pool = PooledDB(
        creator=__import__("psycopg"),
        mincached=int(os.getenv("DB_MIN_CACHED", "5")),
        maxcached=int(os.getenv("DB_MAX_CACHED", "20")),
        maxconnections=int(os.getenv("DB_MAX_CONNECTIONS", "50")),
        blocking=True,
        conninfo=_pg_conninfo,
        autocommit=True,
    )
else:
    import pymysql
    from pymysql.cursors import DictCursor
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
    }

    # SSL: suporta Aiven (certificado obrigatorio) e MySQL local (sem ssl).
    _ssl_ca = os.getenv('DB_SSL_CA', '').strip()
    _ssl_verify = os.getenv('DB_SSL_VERIFY', 'true').strip().lower() == 'true'
    if _ssl_ca:
        MYSQL_CONFIG['ssl'] = {'ca': _ssl_ca, 'ssl_verify_cert': _ssl_verify}
    elif os.getenv('DB_SSL', 'false').strip().lower() == 'true' or \
            os.getenv('DB_HOST', '').strip().endswith('aivencloud.com'):
        MYSQL_CONFIG['ssl'] = {'ssl_verify_cert': _ssl_verify}
    else:
        MYSQL_CONFIG['ssl'] = {'ssl_disabled': True}

    # Inicializa o Pool de Conexões
    pool = PooledDB(
        creator=pymysql,
        mincached=int(os.getenv("DB_MIN_CACHED", "5")),
        maxcached=int(os.getenv("DB_MAX_CACHED", "20")),
        maxconnections=int(os.getenv("DB_MAX_CONNECTIONS", "50")),
        blocking=True,
        **MYSQL_CONFIG
    )

@contextmanager
def get_db():
    conn = pool.connection()
    if is_postgres():
        from psycopg.rows import dict_row
        cursor = conn.cursor(row_factory=dict_row)
    else:
        cursor = conn.cursor()
    try:
        yield cursor, conn
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close() # Retorna a conexão ao pool


def insert_get_id(cursor, sql, params=(), id_column="id"):

    """INSERT que retorna o id gerado nos dois engines.

    Postgres não tem cursor.lastrowid: usa RETURNING + fetchone.
    """
    if is_postgres():
        cursor.execute(sql.rstrip().rstrip(";") + f" RETURNING {id_column}", params)
        row = cursor.fetchone()
        if isinstance(row, dict):
            return row[id_column]
        return row[0]
    cursor.execute(sql, params)
    return cursor.lastrowid


def month_start_sql():
    """Primeiro dia do mês corrente nos dois engines (filtros 'do mês')."""
    if is_postgres():
        return "date_trunc('month', NOW())"
    return "DATE_FORMAT(NOW(), '%Y-%m-01')"


_PG_UNIQUE_KEY_RE = re.compile(r"UNIQUE\s+KEY\s+\w+\s*(\([^)]+\))", re.IGNORECASE)
_PG_INDEX_RE = re.compile(r",?\s*INDEX\s+(\w+)\s*\(([^)]+)\)", re.IGNORECASE)


def translate_ddl_to_pg(sql):
    """Converte DDL MySQL do TABLES_SQL para Postgres. Retorna (table_sql, [index_sql])."""
    table = ""
    m = re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)", sql, re.IGNORECASE)
    if m:
        table = m.group(1)
    s = sql
    s = re.sub(r"\bBIGINT\s+AUTO_INCREMENT\s+PRIMARY\s+KEY",
               "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", s, flags=re.IGNORECASE)
    s = re.sub(r"\bINT\s+AUTO_INCREMENT\s+PRIMARY\s+KEY",
               "INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", s, flags=re.IGNORECASE)
    s = re.sub(r"\bMEDIUMTEXT\b", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bTINYINT\s*\(\d+\)", "SMALLINT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bTINYINT\b", "SMALLINT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bDATETIME\b", "TIMESTAMP", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+ON\s+UPDATE\s+CURRENT_TIMESTAMP", "", s, flags=re.IGNORECASE)
    s = _PG_UNIQUE_KEY_RE.sub(r"UNIQUE \1", s)
    indexes = []
    for im in _PG_INDEX_RE.finditer(s):
        idx_name, cols = im.group(1), im.group(2)
        if table:
            indexes.append(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({cols})")
    s = _PG_INDEX_RE.sub("", s)
    s = re.sub(r",\s*\n\s*\)", "\n)", s)  # vírgula órfã antes do fecha-parêntese
    return s, indexes


def exec_ddl(cursor, sql):
    """Executa DDL traduzindo para o engine ativo (tabela + índices inline)."""
    if not is_postgres():
        cursor.execute(sql)
        return
    table_sql, indexes = translate_ddl_to_pg(sql)
    cursor.execute(table_sql)
    for idx_sql in indexes:
        try:
            cursor.execute(idx_sql)
        except Exception:
            pass


def _pg_dtype(dtype):
    d = dtype
    d = re.sub(r"\bMEDIUMTEXT\b", "TEXT", d, flags=re.IGNORECASE)
    d = re.sub(r"\bTINYINT\s*\(\d+\)", "SMALLINT", d, flags=re.IGNORECASE)
    d = re.sub(r"\bTINYINT\b", "SMALLINT", d, flags=re.IGNORECASE)
    d = re.sub(r"\bDATETIME\b", "TIMESTAMP", d, flags=re.IGNORECASE)
    d = re.sub(r"\s+ON\s+UPDATE\s+CURRENT_TIMESTAMP", "", d, flags=re.IGNORECASE)
    return d


def add_column_if_missing(cursor, table, col, dtype):
    if is_postgres():
        dtype = _pg_dtype(dtype)
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")


def existing_tables(cursor):
    if is_postgres():
        cursor.execute("SELECT tablename AS tb FROM pg_tables WHERE schemaname = 'public'")
    else:
        cursor.execute("SELECT TABLE_NAME AS tb FROM information_schema.tables WHERE table_schema = DATABASE()")
    return {row["tb"] for row in cursor.fetchall()}


def existing_columns(cursor, table):
    if is_postgres():
        cursor.execute(
            "SELECT column_name AS col FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        return {row["col"] for row in cursor.fetchall()}
    cursor.execute(f"SHOW COLUMNS FROM {table}")
    return {row['Field'] for row in cursor.fetchall()}

TABLES_SQL = {
    "users": """CREATE TABLE IF NOT EXISTS users (
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
    )""",
    "veiculos": """CREATE TABLE IF NOT EXISTS veiculos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        tipo VARCHAR(50),
        marca VARCHAR(50),
        modelo VARCHAR(50),
        ano_fabricacao INT,
        ano_compra INT,
        quilometragem INT,
        foto_base64 MEDIUMTEXT NULL,
        foto_url VARCHAR(500) NULL,
        foto_storage_key VARCHAR(500) NULL,
        foto_mime VARCHAR(50) NULL,
        foto_storage VARCHAR(20) NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "chats": """CREATE TABLE IF NOT EXISTS chats (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT,
        session_id VARCHAR(50),
        mensagem_usuario TEXT,
        resposta_ia TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "redefinicao_senha": """CREATE TABLE IF NOT EXISTS redefinicao_senha (
        id INT AUTO_INCREMENT PRIMARY KEY,
        usuario_id INT NOT NULL,
        token VARCHAR(255) NOT NULL,
        data_expiracao DATETIME NOT NULL,
        FOREIGN KEY (usuario_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "videos": """CREATE TABLE IF NOT EXISTS videos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT,
        titulo VARCHAR(255) NOT NULL,
        url VARCHAR(500) NOT NULL,
        descricao TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "maintenance_history": """CREATE TABLE IF NOT EXISTS maintenance_history (
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
    )""",
    "maintenance_notes": """CREATE TABLE IF NOT EXISTS maintenance_notes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NULL,
        note TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_maintenance_notes_user_created (user_id, created_at),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "payments_orders": """CREATE TABLE IF NOT EXISTS payments_orders (
        id VARCHAR(100) PRIMARY KEY,
        user_id INT NOT NULL,
        status VARCHAR(50) DEFAULT 'pending',
        plan VARCHAR(50),
        amount DECIMAL(10,2),
        currency VARCHAR(10) DEFAULT 'BRL',
        provider VARCHAR(50) DEFAULT 'cakto',
        provider_order_id VARCHAR(100),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "feedbacks": """CREATE TABLE IF NOT EXISTS feedbacks (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NULL,
        nome VARCHAR(100),
        email VARCHAR(100),
        estrelas INT DEFAULT 5,
        comentario TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
    )""",
    "analytics_events": """CREATE TABLE IF NOT EXISTS analytics_events (
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
    )""",
    "guest_chat_usage": """CREATE TABLE IF NOT EXISTS guest_chat_usage (
        guest_id_hash CHAR(64) PRIMARY KEY,
        message_count INT NOT NULL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )""",
    "notifications": """CREATE TABLE IF NOT EXISTS notifications (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        title VARCHAR(255) NOT NULL,
        body TEXT,
        type VARCHAR(50) NOT NULL DEFAULT 'info',
        action_url VARCHAR(500),
        is_read TINYINT(1) DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_notif_user_read (user_id, is_read, created_at DESC),
        INDEX idx_notif_user_created (user_id, created_at DESC),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "health_score_history": """CREATE TABLE IF NOT EXISTS health_score_history (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        vehicle_id INT NULL,
        score INT NOT NULL,
        recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_health_user_vehicle (user_id, vehicle_id, recorded_at DESC),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "push_subscriptions": """CREATE TABLE IF NOT EXISTS push_subscriptions (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        endpoint TEXT NOT NULL,
        p256dh VARCHAR(255) NOT NULL,
        auth VARCHAR(255) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_push_user (user_id)
    )""",
    "mechanics": """CREATE TABLE IF NOT EXISTS mechanics (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(100) NOT NULL,
        cnpj VARCHAR(18),
        endereco TEXT NOT NULL,
        cidade VARCHAR(50) NOT NULL,
        estado VARCHAR(2) NOT NULL,
        cep VARCHAR(9),
        latitude DECIMAL(10, 8),
        longitude DECIMAL(11, 8),
        telefone VARCHAR(20),
        email VARCHAR(100),
        website VARCHAR(200),
        descricao TEXT,
        especialidades JSON,  -- ["troca_oleo", "freios", "suspensao"]
        servicos JSON,  -- [{"nome": "Troca de óleo", "preco": 150.00}]
        horario_funcionamento JSON,  -- {"seg": "08:00-18:00", "dom": "fechado"}
        avaliacao_media DECIMAL(3, 2) DEFAULT 0.00,
        total_avaliacoes INT DEFAULT 0,
        foto_url VARCHAR(500),
        is_verified BOOLEAN DEFAULT FALSE,
        is_active BOOLEAN DEFAULT TRUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_mechanics_location (cidade, estado),
        INDEX idx_mechanics_rating (avaliacao_media DESC),
        INDEX idx_mechanics_active (is_active, is_verified)
    )""",
    "mechanic_reviews": """CREATE TABLE IF NOT EXISTS mechanic_reviews (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        mechanic_id INT NOT NULL,
        user_id INT NOT NULL,
        avaliacao INT NOT NULL CHECK (avaliacao BETWEEN 1 AND 5),
        comentario TEXT,
        service_type VARCHAR(50),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_reviews_mechanic (mechanic_id, created_at DESC),
        INDEX idx_reviews_user (user_id),
        FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "mechanic_favorites": """CREATE TABLE IF NOT EXISTS mechanic_favorites (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        mechanic_id INT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_favorite (user_id, mechanic_id),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE CASCADE
    )""",
    "api_clients": """CREATE TABLE IF NOT EXISTS api_clients (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NULL,
        nome VARCHAR(120) NOT NULL,
        api_key_hash VARCHAR(128) NOT NULL UNIQUE,
        api_key_prefix VARCHAR(12) NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        rate_limit_per_min INT DEFAULT 30,
        plan VARCHAR(40) NULL,
        requests_used INT DEFAULT 0,
        requests_limit INT DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_used_at DATETIME NULL
    )""",
    "api_usage_logs": """CREATE TABLE IF NOT EXISTS api_usage_logs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        client_id INT NOT NULL,
        endpoint VARCHAR(120) NOT NULL,
        status_code INT,
        request_id VARCHAR(40) DEFAULT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_usage_client_time (client_id, created_at DESC),
        FOREIGN KEY (client_id) REFERENCES api_clients(id) ON DELETE CASCADE
    )""",
    "chat_feedback": """CREATE TABLE IF NOT EXISTS chat_feedback (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NULL,
        chat_id INT NULL,
        message_id VARCHAR(80) NULL,
        avaliacao TINYINT NOT NULL CHECK (avaliacao IN (1, -1)),
        motivo VARCHAR(60) NULL,
        comentario TEXT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_chat_feedback_user (user_id, created_at DESC),
        INDEX idx_chat_feedback_chat (chat_id),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
    )""",
    "b2b_leads": """CREATE TABLE IF NOT EXISTS b2b_leads (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(120) NOT NULL,
        email VARCHAR(120) NOT NULL,
        empresa VARCHAR(120) NULL,
        telefone VARCHAR(30) NULL,
        mensagem TEXT NULL,
        origem VARCHAR(60) NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_b2b_leads_created (created_at DESC)
    )""",
    "mod_passport_versions": """CREATE TABLE IF NOT EXISTS mod_passport_versions (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        veiculo_id INT NOT NULL,
        user_id INT NOT NULL,
        snapshot JSON NULL,
        fipe_valor VARCHAR(50) NULL,
        fipe_ajustada VARCHAR(50) NULL,
        valor_estimado VARCHAR(50) NULL,
        share_token VARCHAR(64) NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_mpv_veiculo (veiculo_id),
        INDEX idx_mpv_token (share_token)
    )""",
    "events": """CREATE TABLE IF NOT EXISTS events (
        id VARCHAR(40) NOT NULL,
        title VARCHAR(200) NOT NULL,
        original_title VARCHAR(200),
        normalized_title VARCHAR(200),
        description TEXT,
        category VARCHAR(30),
        categoria_label VARCHAR(40),
        start_date DATE,
        end_date DATE,
        start_time TIME,
        end_time TIME,
        venue_name VARCHAR(160),
        address VARCHAR(200),
        city VARCHAR(80),
        state VARCHAR(2),
        country VARCHAR(2) DEFAULT 'BR',
        latitude DECIMAL(10,8),
        longitude DECIMAL(11,8),
        organizer VARCHAR(160),
        organizer_url VARCHAR(500),
        event_url VARCHAR(500),
        image_url VARCHAR(500),
        source VARCHAR(30) NOT NULL,
        source_url VARCHAR(500),
        status VARCHAR(20) DEFAULT 'unknown',
        confidence DECIMAL(3,2) DEFAULT 0.50,
        last_verified_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        INDEX idx_events_state (state),
        INDEX idx_events_city (city),
        INDEX idx_events_start (start_date),
        INDEX idx_events_status (status),
        INDEX idx_events_source (source)
    )""",
    "leads": """CREATE TABLE IF NOT EXISTS leads (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(100) NULL,
        email VARCHAR(100) NOT NULL,
        anonymous_id VARCHAR(80) NULL,
        utm_source VARCHAR(120) NULL,
        utm_medium VARCHAR(120) NULL,
        utm_campaign VARCHAR(120) NULL,
        utm_term VARCHAR(120) NULL,
        utm_content VARCHAR(120) NULL,
        initial_referrer VARCHAR(500) NULL,
        referred_by VARCHAR(20) NULL,
        lead_magnet VARCHAR(60) NULL,
        converted_user_id INT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_leads_email (email),
        INDEX idx_leads_created (created_at),
        INDEX idx_leads_referred (referred_by)
    )""",
}


def init_db():
    with get_db() as (cursor, conn):
        existing = existing_tables(cursor)

        for table_name, ddl in TABLES_SQL.items():
            if table_name not in existing:
                logging.getLogger("database").info("Criando tabela %s...", table_name)
                exec_ddl(cursor, ddl)
                existing.add(table_name)

        existing_columns_set = existing_columns(cursor, "users")
        
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
            ("is_admin", "BOOLEAN DEFAULT FALSE"),
            ("uf", "VARCHAR(2) NULL"),
            ("referral_code", "VARCHAR(20) NULL"),
            ("referred_by", "VARCHAR(20) NULL"),
            ("premium_expires_at", "DATETIME NULL"),
            ("mod_passport", "BOOLEAN DEFAULT FALSE"),
            ("signup_ip", "VARCHAR(45) NULL"),
            ("referral_credit_months", "INT DEFAULT 0"),
            ("anonymous_id", "VARCHAR(80) NULL"),
            ("utm_source", "VARCHAR(120) NULL"),
            ("utm_medium", "VARCHAR(120) NULL"),
            ("utm_campaign", "VARCHAR(120) NULL"),
            ("utm_term", "VARCHAR(120) NULL"),
            ("utm_content", "VARCHAR(120) NULL"),
            ("initial_referrer", "VARCHAR(500) NULL")
        ]
        for col, dtype in columns:
            if col not in existing_columns_set:
                try:
                    logging.getLogger("database").info("Adicionando coluna faltante %s em users...", col)
                    add_column_if_missing(cursor, "users", col, dtype)
                except Exception as e:
                    logging.getLogger("database").warning("Erro ao adicionar coluna %s: %s", col, e)

        existing_veiculos_columns = existing_columns(cursor, "veiculos")
        veiculos_columns = [
            ("quilometragem", "INT"),
            ("fipe_valor", "VARCHAR(50) NULL"),
            ("fipe_mes_referencia", "VARCHAR(50) NULL"),
            ("fipe_updated_at", "DATETIME NULL"),
            ("modificacoes", "TEXT NULL"),
            ("fipe_ajustada", "VARCHAR(50) NULL"),
            ("foto_base64", "MEDIUMTEXT NULL"),
            # P2: storage externo de fotos (dual-read com foto_base64 legado)
            ("foto_url", "VARCHAR(500) NULL"),
            ("foto_storage_key", "VARCHAR(500) NULL"),
            ("foto_mime", "VARCHAR(50) NULL"),
            ("foto_storage", "VARCHAR(20) NULL"),
        ]
        for col, dtype in veiculos_columns:
            if col not in existing_veiculos_columns:
                try:
                    add_column_if_missing(cursor, "veiculos", col, dtype)
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
            logging.getLogger("database").warning("Aviso migracao veiculos: %s", e)

        try:
            if is_postgres():
                cursor.execute("ALTER TABLE users ALTER COLUMN password TYPE VARCHAR(255)")
                cursor.execute("ALTER TABLE users ALTER COLUMN password DROP NOT NULL")
            else:
                cursor.execute("ALTER TABLE users MODIFY COLUMN password VARCHAR(255) NULL")
        except Exception as e:
            logging.getLogger("database").warning("Erro ao modificar coluna password: %s", e)

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
        reset_columns = [
            ("email_sent", "BOOLEAN DEFAULT FALSE"),
            ("email_attempts", "INT DEFAULT 0"),
            ("last_attempt_at", "DATETIME NULL"),
            ("send_error", "TEXT NULL")
        ]
        for col, dtype in reset_columns:
            try:
                add_column_if_missing(cursor, "redefinicao_senha", col, dtype)
            except Exception:
                pass
        maintenance_columns = [
            ("alert_last_status_code", "VARCHAR(30) NULL"),
            ("alert_last_sent_at", "DATETIME NULL"),
        ]
        for col, dtype in maintenance_columns:
            try:
                add_column_if_missing(cursor, "maintenance_history", col, dtype)
            except Exception:
                pass
        try:
            cursor.execute("ALTER TABLE maintenance_notes ADD COLUMN user_id INT NULL")
        except Exception:
            pass
        payments_columns = [
            ("plan", "VARCHAR(50)"),
            ("currency", "VARCHAR(10) DEFAULT 'BRL'"),
        ]
        for col, dtype in payments_columns:
            try:
                add_column_if_missing(cursor, "payments_orders", col, dtype)
            except Exception:
                pass
        api_clients_columns = [
            ("user_id", "INT NULL"),
            ("plan", "VARCHAR(40) NULL"),
            ("requests_used", "INT DEFAULT 0"),
            ("requests_limit", "INT DEFAULT 0"),
        ]
        for col, dtype in api_clients_columns:
            try:
                add_column_if_missing(cursor, "api_clients", col, dtype)
            except Exception:
                pass
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
                if is_postgres():
                    cursor.execute(idx_query.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1))
                else:
                    cursor.execute(idx_query)
            except Exception:
                pass # Ignora se o índice já existir

        if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            logging.getLogger("database").info("Banco de dados inicializado com sucesso!")


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
