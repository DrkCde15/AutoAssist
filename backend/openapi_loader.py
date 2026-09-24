"""Loader do OpenAPI a partir de backend/openapi.yaml (P1).

Mantém compat com /api/docs e /api/swagger-ui. Se o YAML não existir ou
PyYAML não estiver instalado, retorna spec mínima.
"""
from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def load_spec(frontend_origin: str | None = None) -> dict:
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "openapi.yaml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        try:
            import yaml  # type: ignore

            spec = yaml.safe_load(text) or {}
        except ImportError:
            import json

            # Fallback mínimo se PyYAML ausente (openapi.yaml é YAML superset de JSON? não;
            # então retorna spec mínima e loga).
            spec = {
                "openapi": "3.0.3",
                "info": {"title": "AutoAssist IA API", "version": "1.0.0"},
                "paths": {},
            }
        if frontend_origin:
            try:
                servers = spec.get("servers") or []
                if servers:
                    servers[0]["url"] = frontend_origin
                else:
                    spec["servers"] = [{"url": frontend_origin, "description": "Producao"}]
            except Exception:
                pass
        return spec
    except FileNotFoundError:
        return {
            "openapi": "3.0.3",
            "info": {"title": "AutoAssist IA API", "version": "1.0.0"},
            "paths": {},
        }
