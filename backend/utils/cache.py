import time


class TTLCache:
    """Cache em memória (por processo) com expiração por tempo (TTL).

    Sem Redis: cada worker mantém seu próprio cache. No Render free (1 worker)
    o ganho é pleno; com múltiplos workers cada um tem cache independente.
    A chave deve sempre incluir o user_id (ou ser composta) para nunca vazar
    dados entre usuários.
    """

    def __init__(self, default_ttl=180, maxsize=None):
        self._store = {}
        self.default_ttl = default_ttl
        self._maxsize = maxsize

    def get(self, key):
        item = self._store.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at > time.time():
            return value
        self._store.pop(key, None)
        return None

    def set(self, key, value, ttl=None):
        ttl = self.default_ttl if ttl is None else ttl
        if self._maxsize and len(self._store) >= self._maxsize:
            try:
                self._store.pop(next(iter(self._store)))
            except StopIteration:
                pass
        self._store[key] = (value, time.time() + ttl)

    def delete(self, key):
        self._store.pop(key, None)

    def clear(self):
        self._store.clear()


import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

_REDIS_CLIENT = None
_REDIS_UNAVAILABLE = False


def get_redis_client():
    """Retorna um cliente Redis (decode_responses=True) ou None se indisponível.

    Degrada graciosamente: se REDIS_URL não estiver configurado ou o Redis
    estiver fora do ar, retorna None e os chamadores devem usar fallback local.
    """
    global _REDIS_CLIENT, _REDIS_UNAVAILABLE
    if _REDIS_UNAVAILABLE:
        return None
    if _REDIS_CLIENT is None:
        url = os.getenv("REDIS_URL") or os.getenv("RATELIMIT_STORAGE_URI", "")
        if not url or url == "memory://":
            _REDIS_UNAVAILABLE = True
            return None
        try:
            from redis import Redis
            _REDIS_CLIENT = Redis.from_url(
                url, socket_timeout=2, socket_connect_timeout=2, decode_responses=True
            )
        except Exception as exc:
            logger.warning("Redis indisponivel para cache: %s", exc)
            _REDIS_UNAVAILABLE = True
            return None
    return _REDIS_CLIENT


def make_cache_key(prefix, *parts):
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
    return f"{prefix}:{h.hexdigest()}"


_local_json_cache = TTLCache(default_ttl=3600, maxsize=2048)


def cache_get_json(key):
    client = get_redis_client()
    if client is not None:
        try:
            raw = client.get(key)
            if raw is not None:
                return json.loads(raw)
        except Exception:
            pass
    return _local_json_cache.get(key)


def cache_set_json(key, value, ttl=3600):
    client = get_redis_client()
    if client is not None:
        try:
            client.set(key, json.dumps(value, default=str), ex=int(ttl))
            return
        except Exception:
            pass
    _local_json_cache.set(key, value, ttl=ttl)


class SharedCache:
    """Cache que usa Redis quando disponível e cai para TTLCache local."""

    def __init__(self, prefix, ttl=30, maxsize=512):
        self.prefix = prefix
        self.ttl = int(ttl)
        self._local = TTLCache(default_ttl=ttl, maxsize=maxsize)

    def _key(self, key):
        return f"{self.prefix}:{key}"

    def get(self, key):
        client = get_redis_client()
        if client is not None:
            try:
                raw = client.get(self._key(key))
                if raw is not None:
                    return json.loads(raw)
            except Exception:
                pass
        return self._local.get(key)

    def set(self, key, value, ttl=None):
        ttl = self.ttl if ttl is None else ttl
        client = get_redis_client()
        if client is not None:
            try:
                client.set(self._key(key), json.dumps(value, default=str), ex=int(ttl))
                return
            except Exception:
                pass
        self._local.set(key, value, ttl=ttl)

    def delete(self, key):
        client = get_redis_client()
        if client is not None:
            try:
                client.delete(self._key(key))
            except Exception:
                pass
        self._local.delete(key)
