"""Storage externo para fotos de veículos (P2).

Backend selecionado via env:
    VEHICLE_PHOTO_BACKEND=local|s3   (default: local)
    VEHICLE_PHOTO_DIR=/var/data/vehicle_photos
    VEHICLE_PHOTO_MAX_MB=8
    S3_BUCKET, S3_REGION, S3_ENDPOINT_URL (R2/MinIO), AWS_*,
    S3_PUBLIC_URL (se vazio, usa redirect interno /api/veiculos/<id>/foto/raw),
    S3_PREFIX=veiculos/, S3_PRESIGN_TTL=3600

Compatibilidade:
- Dual-write: POST /foto aceita JSON legado {foto: dataURL} e multipart {file}.
- Dual-read: se foto_url preenchido usa storage; senão cai para foto_base64 legado.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Optional, Protocol

logger = logging.getLogger(__name__)

ALLOWED_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
EXT_BY_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}


def max_bytes() -> int:
    try:
        return int(float(os.getenv("VEHICLE_PHOTO_MAX_MB", "8")) * 1024 * 1024)
    except (TypeError, ValueError):
        return 8 * 1024 * 1024


def sniff_mime(data: bytes) -> Optional[str]:
    if data[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb", b"\xff\xd8\xff\xee"):
        return "image/jpeg"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def parse_data_url(value: str) -> tuple[bytes, str]:
    """Aceita DataURL ou base64 puro. Retorna (bytes, mime). Levanta ValueError."""
    v = (value or "").strip()
    if not v:
        raise ValueError("Foto vazia.")
    if v.startswith("data:"):
        header, _, b64 = v.partition(",")
        if "base64" not in header or not b64:
            raise ValueError("DataURL inválido.")
        try:
            data = base64.b64decode(b64, validate=True)
        except Exception:
            raise ValueError("Imagem inválida.") from None
    else:
        try:
            data = base64.b64decode(v, validate=True)
        except Exception:
            raise ValueError("Imagem inválida.") from None
    if len(data) > max_bytes():
        raise ValueError(f"Imagem muito grande (máx {max_bytes() // (1024*1024)}MB).")
    if not data:
        raise ValueError("Imagem vazia.")
    mime = sniff_mime(data)
    if mime not in ALLOWED_MIMES:
        raise ValueError("Apenas PNG/JPG/GIF/WebP.")
    return data, mime


class VehiclePhotoStorage(Protocol):
    def save(self, user_id: int, vehicle_id: int, data: bytes, mime: str) -> str: ...
    def get(self, key: str) -> Optional[tuple[bytes, str]]: ...
    def delete(self, key: str) -> None: ...
    def public_url(self, key: str) -> Optional[str]: ...


class LocalDiskStorage:
    def __init__(self, base_dir: Optional[str] = None):
        root = base_dir or os.getenv("VEHICLE_PHOTO_DIR") or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "storage", "vehicle_photos"
        )
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # key formato: {user_id}/{vehicle_id}-{uuid}.ext — sem traversal
        safe = key.replace("..", "").lstrip("/")
        return self.root / safe

    def save(self, user_id: int, vehicle_id: int, data: bytes, mime: str) -> str:
        ext = EXT_BY_MIME.get(mime, ".jpg")
        key = f"{int(user_id)}/{int(vehicle_id)}-{uuid.uuid4().hex}{ext}"
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def get(self, key: str) -> Optional[tuple[bytes, str]]:
        try:
            p = self._path(key)
            if not p.is_file():
                return None
            mime, _ = mimetypes.guess_type(str(p))
            return p.read_bytes(), mime or "image/jpeg"
        except Exception as exc:
            logger.warning("Falha ao ler foto local %s: %s", key, exc)
            return None

    def delete(self, key: str) -> None:
        try:
            p = self._path(key)
            if p.is_file():
                p.unlink()
        except Exception as exc:
            logger.warning("Falha ao remover foto local %s: %s", key, exc)

    def public_url(self, key: str) -> Optional[str]:
        return None  # servido via /api/veiculos/<id>/foto/raw


class S3Storage:
    def __init__(self):
        self.bucket = (os.getenv("S3_BUCKET") or "").strip()
        self.region = (os.getenv("S3_REGION") or "sa-east-1").strip()
        self.endpoint = (os.getenv("S3_ENDPOINT_URL") or "").strip() or None
        self.prefix = (os.getenv("S3_PREFIX") or "veiculos/").strip()
        self.public_base = (os.getenv("S3_PUBLIC_URL") or "").strip().rstrip("/") or None
        try:
            self.ttl = int(os.getenv("S3_PRESIGN_TTL", "3600"))
        except (TypeError, ValueError):
            self.ttl = 3600
        self._client = None
        if not self.bucket:
            raise RuntimeError("S3_BUCKET não configurado.")

    def _s3(self):
        if self._client is None:
            import boto3

            kwargs: dict = {"region_name": self.region}
            if self.endpoint:
                kwargs["endpoint_url"] = self.endpoint
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def save(self, user_id: int, vehicle_id: int, data: bytes, mime: str) -> str:
        ext = EXT_BY_MIME.get(mime, ".jpg")
        key = f"{self.prefix}{int(user_id)}/{int(vehicle_id)}-{uuid.uuid4().hex}{ext}"
        self._s3().put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=mime)
        return key

    def get(self, key: str) -> Optional[tuple[bytes, str]]:
        try:
            obj = self._s3().get_object(Bucket=self.bucket, Key=key)
            data = obj["Body"].read()
            mime = obj.get("ContentType", "image/jpeg")
            return data, mime
        except Exception as exc:
            logger.warning("Falha ao ler foto S3 %s: %s", key, exc)
            return None

    def delete(self, key: str) -> None:
        try:
            self._s3().delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            logger.warning("Falha ao remover foto S3 %s: %s", key, exc)

    def public_url(self, key: str) -> Optional[str]:
        if self.public_base:
            return f"{self.public_base}/{key}"
        try:
            return self._s3().generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=self.ttl
            )
        except Exception as exc:
            logger.warning("Falha ao gerar URL S3 %s: %s", key, exc)
            return None


def get_storage() -> VehiclePhotoStorage:
    backend = (os.getenv("VEHICLE_PHOTO_BACKEND") or "local").strip().lower()
    if backend == "s3":
        try:
            return S3Storage()
        except Exception as exc:
            logger.warning("S3 indisponível (%s); usando disco local.", exc)
    return LocalDiskStorage()


def photo_url_for(vehicle_id: int, storage_key: Optional[str]) -> Optional[str]:
    """URL interna canônica para <img src>. S3 com PUBLIC_URL retorna CDN direto."""
    if not storage_key:
        return None
    try:
        store = get_storage()
        url = store.public_url(storage_key)
        if url:
            return url
    except Exception:
        pass
    return f"/api/veiculos/{int(vehicle_id)}/foto/raw"
