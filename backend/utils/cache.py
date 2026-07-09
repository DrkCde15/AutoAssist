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
