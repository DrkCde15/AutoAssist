"""Rate-limit por usuário para o chat B2C (P2).

O limiter global usa IP (`get_remote_address`). Para o chat isso permite que
um IP atrás de NAT consuma a cota de todos, e que um usuário logado troque de
IP para burlar. Aqui a chave é `user:<id>` quando há JWT, senão `ip:<addr>` —
compatível com Flask-Limiter via `key_func` por rota.
"""
from __future__ import annotations

import time

from flask import request
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from flask_limiter.util import get_remote_address

# WS: controle simples em memória (por processo) como segunda camada.
# O REST já tem Flask-Limiter; o WS não passa pelo limiter.
_ws_hits: dict[str, list[float]] = {}

CHAT_WS_MAX_PER_MIN = 20


def chat_rate_key() -> str:
    try:
        verify_jwt_in_request(optional=True)
        uid = get_jwt_identity()
        if uid:
            return f"user:{uid}"
    except Exception:
        pass
    return f"ip:{get_remote_address()}"


def ws_chat_allowed(user_id=None, guest_id: str | None = None) -> bool:
    if user_id:
        key = f"user:{user_id}"
    elif guest_id:
        key = f"guest:{guest_id}"
    else:
        try:
            key = f"ip:{get_remote_address()}"
        except Exception:
            key = "ip:unknown"
    now = time.time()
    window_start = now - 60
    with __import__("threading").Lock():
        hits = [t for t in _ws_hits.get(key, []) if t > window_start]
        if len(hits) >= CHAT_WS_MAX_PER_MIN:
            _ws_hits[key] = hits
            return False
        hits.append(now)
        _ws_hits[key] = hits
        return True
