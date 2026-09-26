"""Backup do MySQL para S3/R2 (opção A escolhida).

Dump 100% Python (o runtime do Render não tem o binário `mysqldump`):
schema via SHOW CREATE TABLE + dados em INSERTs por chunk, gzip em
memória e upload via boto3. Retenção por idade no próprio bucket.

Env:
    BACKUP_S3_BUCKET (fallback: S3_BUCKET) — obrigatório
    BACKUP_S3_PREFIX  (default: "db-backups/")
    BACKUP_RETENTION_DAYS (default: 7)
    BACKUP_CHUNK_ROWS (default: 500)
    Reusa S3_REGION, S3_ENDPOINT_URL e credenciais AWS do storage de fotos.
"""
from __future__ import annotations

import gzip
import io
import logging
import os
import re
import time
from datetime import date, datetime, time as dtime, timedelta

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(r"(\d{8}-\d{6})\.sql\.gz$")


def _bucket() -> str:
    bucket = (os.getenv("BACKUP_S3_BUCKET") or os.getenv("S3_BUCKET") or "").strip()
    if not bucket:
        raise RuntimeError("BACKUP_S3_BUCKET (ou S3_BUCKET) não configurado.")
    return bucket


def _prefix() -> str:
    p = (os.getenv("BACKUP_S3_PREFIX") or "db-backups/").strip()
    return p if p.endswith("/") else p + "/"


def _retention_days() -> int:
    try:
        return max(1, int(os.getenv("BACKUP_RETENTION_DAYS", "7")))
    except (TypeError, ValueError):
        return 7


def _chunk_rows() -> int:
    try:
        return max(100, int(os.getenv("BACKUP_CHUNK_ROWS", "500")))
    except (TypeError, ValueError):
        return 500


def _s3():
    import boto3
    from botocore.config import Config

    endpoint = (os.getenv("S3_ENDPOINT_URL") or "").strip()
    style = (os.getenv("S3_ADDRESSING_STYLE") or "auto").strip().lower()
    ep = endpoint.lower()
    use_path = style == "path" or (
        style == "auto" and bool(ep) and (
            "localhost" in ep or "127." in ep
            or "/192.168." in ep or "/10." in ep or "/172.1" in ep
        )
    )
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path" if use_path else "virtual"},
    )
    kwargs: dict = {
        "region_name": (os.getenv("S3_REGION") or "sa-east-1").strip(),
        "config": config,
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("s3", **kwargs)


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return str(value)
    except Exception:
        pass
    if isinstance(value, (datetime, date, dtime, timedelta)):
        return "'%s'" % str(value).replace("'", "''")
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex() if value else "''"
    s = str(value)
    s = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
    s = s.replace("\x00", "\\0").replace("\x1a", "\\Z")
    return "'%s'" % s


def _list_tables(cursor) -> list[str]:
    cursor.execute("SHOW TABLES")
    rows = cursor.fetchall()
    if not rows:
        return []
    first_key = next(iter(rows[0]))
    return [str(r[first_key]) for r in rows]


def dump_database() -> tuple[bytes, dict]:
    """Gera o dump gzipado. Retorna (bytes, manifest)."""
    from routes.database import get_db

    started = time.time()
    buf = io.StringIO()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    buf.write(f"-- AutoAssist MySQL dump {stamp}\nSET FOREIGN_KEY_CHECKS=0;\n\n")
    tables = 0
    rows_total = 0
    chunk = _chunk_rows()
    with get_db() as (cursor, _conn):
        for table in _list_tables(cursor):
            tables += 1
            cursor.execute(f"SHOW CREATE TABLE `{table}`")
            create_row = cursor.fetchone()
            create_sql = next(v for k, v in create_row.items() if k.lower() != "table")
            buf.write(f"-- Table {table}\n{create_sql};\n")
            cursor.execute(f"SELECT COUNT(*) AS cnt FROM `{table}`")
            total = int((cursor.fetchone() or {}).get("cnt") or 0)
            offset = 0
            while offset < total:
                cursor.execute(f"SELECT * FROM `{table}` LIMIT {chunk} OFFSET {offset}")
                batch = cursor.fetchall()
                if not batch:
                    break
                cols = list(batch[0].keys())
                col_list = ", ".join(f"`{c}`" for c in cols)
                for row in batch:
                    vals = ", ".join(_sql_literal(row[c]) for c in cols)
                    buf.write(f"INSERT INTO `{table}` ({col_list}) VALUES ({vals});\n")
                    rows_total += 1
                offset += len(batch)
            buf.write("\n")
    buf.write("SET FOREIGN_KEY_CHECKS=1;\n")
    raw = buf.getvalue().encode("utf-8")
    gz = gzip.compress(raw, compresslevel=6)
    manifest = {
        "tables": tables,
        "rows": rows_total,
        "bytes_raw": len(raw),
        "bytes_gzip": len(gz),
        "seconds": round(time.time() - started, 1),
    }
    return gz, manifest


def _key_for_now() -> str:
    return f"{_prefix()}autoassist-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sql.gz"


def upload_backup(data: bytes) -> str:
    key = _key_for_now()
    _s3().put_object(Bucket=_bucket(), Key=key, Body=data, ContentType="application/gzip")
    return key


def apply_retention(keep_latest: int = 1) -> list[str]:
    """Apaga backups mais velhos que a retenção. Sempre preserva o mais novo."""
    client = _s3()
    bucket, prefix = _bucket(), _prefix()
    cutoff = datetime.now() - timedelta(days=_retention_days())
    token = None
    candidates: list[tuple[datetime, str]] = []
    while True:
        kwargs: dict = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            m = _KEY_RE.search(obj.get("Key", ""))
            if not m:
                continue
            try:
                ts = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
            except ValueError:
                continue
            candidates.append((ts, obj["Key"]))
        token = resp.get("NextContinuationToken")
        if not token:
            break
    candidates.sort()
    deletable = [k for ts, k in candidates[:-keep_latest] if ts < cutoff] if candidates else []
    removed: list[str] = []
    for i in range(0, len(deletable), 1000):
        batch = deletable[i:i + 1000]
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in batch]})
        removed.extend(batch)
    return removed


def list_backups(limit: int = 50) -> list[dict]:
    client = _s3()
    resp = client.list_objects_v2(Bucket=_bucket(), Prefix=_prefix(), MaxKeys=1000)
    items = [
        {"key": o["Key"], "size": o.get("Size", 0),
         "last_modified": str(o.get("LastModified", ""))}
        for o in resp.get("Contents", [])
        if o.get("Key", "").endswith(".sql.gz")
    ]
    items.sort(key=lambda i: i["key"], reverse=True)
    return items[: max(1, limit)]


def run_backup() -> dict:
    """Pipeline completo: dump → upload → retenção. Retorna o manifest."""
    data, manifest = dump_database()
    key = upload_backup(data)
    manifest["key"] = key
    try:
        manifest["removed"] = apply_retention()
    except Exception as exc:
        logger.warning("Retenção de backups falhou: %s", exc)
        manifest["removed"] = []
    manifest["retention_days"] = _retention_days()
    logger.info("Backup MySQL concluído: %s (%s tabelas, %s linhas, %s bytes gzip)",
                key, manifest["tables"], manifest["rows"], manifest["bytes_gzip"])
    return manifest
