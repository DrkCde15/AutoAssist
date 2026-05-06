import logging
import os
import sys
from pathlib import Path

import pymysql


def _prepare_paths() -> None:
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    backend_dir = script_path.parents[1]

    # Evita conflito com backend/utils/email.py que pode sombrear
    # o pacote padrão "email" do Python no GitHub Actions.
    filtered = []
    for entry in sys.path:
        try:
            if Path(entry).resolve() == script_dir:
                continue
        except Exception:
            pass
        filtered.append(entry)
    sys.path[:] = filtered

    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


_prepare_paths()

from utils.email import enviar_email


RESET_DISPATCH_LOCK_NAME = "autoassist_reset_email_dispatcher"


def _db_config() -> dict:
    return {
        "host": (os.getenv("DB_HOST") or "localhost").strip(),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": (os.getenv("DB_USER") or "").strip(),
        "password": (os.getenv("DB_PASSWORD") or "").strip(),
        "database": (os.getenv("DB_NAME") or "").strip(),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": True,
        "connect_timeout": 10,
        "ssl": {"ssl_disabled": False},
    }


def _frontend_base_url() -> str:
    is_production = os.getenv("FLASK_ENV") == "production"
    env_key = "URL_PROD" if is_production else "URL_DEV"
    base = (
        os.getenv(env_key)
        or os.getenv("URL_PROD")
        or os.getenv("URL_DEV")
        or "https://autoassist-l9lr.onrender.com/"
    ).strip()
    return base if base.endswith("/") else f"{base}/"


def _build_reset_html(reset_link: str) -> str:
    return f"""
        <h2 style="margin-top: 0; color: #111827; font-size: 20px;">Redefinicao de Senha</h2>
        <p style="color: #4b5563; font-size: 16px; margin-bottom: 25px;">
            Ola! Recebemos uma solicitacao para redefinir a senha da sua conta no <strong>AutoAssist</strong>.
        </p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{reset_link}" style="display: inline-block; padding: 14px 28px; background-color: #2563eb; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">Redefinir Minha Senha</a>
        </div>
        <p style="color: #6b7280; font-size: 14px; margin-top: 25px;">
            Este link e valido por <strong>15 minutos</strong>. Se voce nao solicitou esta alteracao, pode ignorar este e-mail com seguranca.
        </p>
    """


def _ensure_reset_queue_columns(cursor) -> None:
    needed = [
        ("email_sent", "BOOLEAN DEFAULT FALSE"),
        ("email_attempts", "INT DEFAULT 0"),
        ("last_attempt_at", "DATETIME NULL"),
        ("send_error", "TEXT NULL"),
    ]
    for col, ddl in needed:
        try:
            cursor.execute(f"ALTER TABLE redefinicao_senha ADD COLUMN {col} {ddl}")
        except Exception:
            # Coluna ja existe (ou banco sem permissao de alter): segue fluxo.
            pass


def process_pending_password_reset_emails(batch_size: int = 50) -> dict:
    retry_seconds = max(1, int(os.getenv("RESET_EMAIL_RETRY_SECONDS", "15")))
    processed = 0
    sent = 0
    conn = pymysql.connect(**_db_config())
    try:
        with conn.cursor() as cursor:
            _ensure_reset_queue_columns(cursor)
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
                    (retry_seconds, int(batch_size)),
                )
                pendentes = cursor.fetchall() or []
                processed = len(pendentes)
                base = _frontend_base_url()

                for row in pendentes:
                    req_id = row.get("id")
                    token = row.get("token")
                    email = row.get("email")
                    ok = False
                    err_msg = None

                    try:
                        if token and email:
                            link = f"{base}redefinir-senha.html?token={token}"
                            html = _build_reset_html(link)
                            ok = bool(enviar_email(email, "Redefinicao de senha", html))
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
                            (req_id,),
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
                            ((err_msg or "send_failed")[:500], req_id),
                        )
            finally:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (RESET_DISPATCH_LOCK_NAME,))
    finally:
        conn.close()

    return {"processed": processed, "sent": sent}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger("process_reset_email_queue_once")

    batch_size = max(1, min(int(os.getenv("RESET_EMAIL_BATCH_SIZE", "50")), 500))
    result = process_pending_password_reset_emails(batch_size=batch_size) or {}
    processed = int(result.get("processed", 0))
    sent = int(result.get("sent", 0))

    logger.info("Fila processada: pendentes_lidos=%s enviados=%s", processed, sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
