"""Métricas de uso/custo Groq por endpoint (P2).

Captura `usage.{prompt_tokens,completion_tokens,total_tokens}` da resposta
OpenAI-compatível e agrega contadores em memória + Redis (quando disponível).
Exposto em GET /api/admin/groq-metrics (admin JWT).
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_counters: dict[tuple[str, str], dict[str, int]] = {}
_started_at = time.time()


def record(endpoint: str, model: str, usage: dict | None, *, error: bool = False) -> None:
    ep = (endpoint or "unknown").strip() or "unknown"
    md = (model or "unknown").strip() or "unknown"
    key = (ep, md)
    prompt = 0
    completion = 0
    total = 0
    try:
        if isinstance(usage, dict):
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
            total = int(usage.get("total_tokens") or (prompt + completion))
    except (TypeError, ValueError):
        pass
    with _lock:
        slot = _counters.setdefault(
            key, {"requests": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        )
        slot["requests"] += 1
        if error:
            slot["errors"] += 1
        slot["prompt_tokens"] += prompt
        slot["completion_tokens"] += completion
        slot["total_tokens"] += total
    # Persistência best-effort no Redis (agregado, TTL 7 dias)
    try:
        from utils.cache import get_redis_client

        redis = get_redis_client()
        if redis is not None:
            pipe = redis.pipeline()
            base = f"groq:metrics:{ep}:{md}"
            pipe.hincrby(base, "requests", 1)
            if error:
                pipe.hincrby(base, "errors", 1)
            pipe.hincrby(base, "prompt_tokens", prompt)
            pipe.hincrby(base, "completion_tokens", completion)
            pipe.hincrby(base, "total_tokens", total)
            pipe.expire(base, 7 * 24 * 3600)
            pipe.execute()
    except Exception as exc:
        logger.debug("Falha ao persistir métrica Groq no Redis: %s", exc)


def snapshot() -> dict:
    with _lock:
        rows = [
            {
                "endpoint": ep,
                "model": md,
                "requests": v["requests"],
                "errors": v["errors"],
                "prompt_tokens": v["prompt_tokens"],
                "completion_tokens": v["completion_tokens"],
                "total_tokens": v["total_tokens"],
            }
            for (ep, md), v in sorted(_counters.items())
        ]
    # Merge com Redis (se houver outros workers)
    try:
        from utils.cache import get_redis_client

        redis = get_redis_client()
        if redis is not None:
            merged: dict[tuple[str, str], dict] = {(r["endpoint"], r["model"]): dict(r) for r in rows}
            for key in redis.scan_iter("groq:metrics:*:*"):
                try:
                    parts = key.decode() if isinstance(key, bytes) else str(key)
                    _, _, ep, md = parts.split(":", 3)
                    h = redis.hgetall(key)
                    norm = { (k.decode() if isinstance(k, bytes) else k): int(v) for k, v in h.items() }
                    slot = merged.setdefault(
                        (ep, md),
                        {"endpoint": ep, "model": md, "requests": 0, "errors": 0,
                         "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    )
                    for f in ("requests", "errors", "prompt_tokens", "completion_tokens", "total_tokens"):
                        slot[f] = max(slot.get(f, 0), int(norm.get(f, 0)))
                except Exception:
                    continue
            rows = sorted(merged.values(), key=lambda r: (r["endpoint"], r["model"]))
    except Exception:
        pass
    total_tokens = sum(r["total_tokens"] for r in rows)
    return {
        "uptime_seconds": int(time.time() - _started_at),
        "total_tokens": total_tokens,
        "metrics": rows,
    }


def reset() -> None:
    with _lock:
        _counters.clear()
