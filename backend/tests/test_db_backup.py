"""Backup MySQL → S3/R2 (mocks de banco e boto3)."""
import gzip
import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services import db_backup as bk


class FakeCursor:
    def __init__(self):
        self.last_sql = ""

    def execute(self, sql, *a):
        self.last_sql = sql

    def fetchall(self):
        sql = self.last_sql
        if sql.startswith("SHOW TABLES"):
            return [{"Tables_in_db": "users"}, {"Tables_in_db": "veiculos"}]
        if "LIMIT" in sql and "OFFSET 0" in sql:
            return [
                {"id": 1, "nome": "Severino's", "saldo": Decimal("10.5"),
                 "foto": b"\xff\xd8\xff", "nada": None, "ativo": True,
                 "criado": datetime(2026, 1, 2, 3, 4, 5)},
            ]
        return []

    def fetchone(self):
        sql = self.last_sql
        if sql.startswith("SHOW CREATE TABLE"):
            t = sql.split("`")[1]
            return {"Table": t, "Create Table": f"CREATE TABLE `{t}` (`id` INT)"}
        if "COUNT(*)" in sql:
            return {"cnt": 1 if "users" in sql else 0}
        return None


class FakeDB:
    def __init__(self):
        self.cur = FakeCursor()

    def __enter__(self):
        return (self.cur, MagicMock())

    def __exit__(self, *a):
        return False


class FakeS3:
    def __init__(self):
        self.put = []
        self.deleted = []
        self.objects = [
            {"Key": "db-backups/autoassist-20200101-000000.sql.gz", "Size": 10,
             "LastModified": "2020-01-01"},
        ]

    def put_object(self, Bucket, Key, Body, ContentType):
        self.put.append((Bucket, Key, Body))
        self.objects.append({"Key": Key, "Size": len(Body), "LastModified": "now"})
        return {}

    def list_objects_v2(self, **kw):
        return {"Contents": list(self.objects)}

    def delete_objects(self, Bucket, Delete):
        self.deleted.extend(o["Key"] for o in Delete["Objects"])
        self.objects = [o for o in self.objects if o["Key"] not in self.deleted]
        return {}


class DbBackupTest(unittest.TestCase):
    def test_sql_literal(self):
        self.assertEqual(bk._sql_literal(None), "NULL")
        self.assertEqual(bk._sql_literal(True), "1")
        self.assertEqual(bk._sql_literal(7), "7")
        self.assertEqual(bk._sql_literal(Decimal("1.2")), "1.2")
        self.assertEqual(bk._sql_literal(b"\x00\xff"), "0x00ff")
        self.assertEqual(bk._sql_literal("a'b"), "'a\\'b'")
        self.assertIn("2026-01-02", bk._sql_literal(datetime(2026, 1, 2, 3, 4, 5)))

    def test_full_pipeline(self):
        fake, s3 = FakeDB(), FakeS3()
        with patch.dict("os.environ", {"BACKUP_S3_BUCKET": "bkt", "BACKUP_RETENTION_DAYS": "7"}):
            with patch("services.db_backup._s3", return_value=s3):
                import routes.database as dbmod
                with patch.object(dbmod, "get_db", return_value=fake):
                    manifest = bk.run_backup()
        self.assertEqual(manifest["tables"], 2)
        self.assertEqual(manifest["rows"], 1)
        self.assertTrue(manifest["key"].endswith(".sql.gz"))
        self.assertEqual(len(s3.put), 1)
        body = s3.put[0][2]
        sql = gzip.decompress(body).decode("utf-8")
        self.assertIn("CREATE TABLE `users`", sql)
        self.assertIn("INSERT INTO `users`", sql)
        self.assertIn("Severino\\'s", sql)
        self.assertIn("0xffd8ff", sql)
        # retenção apagou o backup de 2020 e preservou o novo
        self.assertIn("db-backups/autoassist-20200101-000000.sql.gz", s3.deleted)
        self.assertNotIn(manifest["key"], s3.deleted)

    def test_no_bucket(self):
        env = {k: v for k, v in __import__("os").environ.items()
               if k not in ("BACKUP_S3_BUCKET", "S3_BUCKET")}
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(RuntimeError):
                bk._bucket()


if __name__ == "__main__":
    unittest.main()
