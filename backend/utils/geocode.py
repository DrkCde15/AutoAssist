"""Reverse geocoding utilitário (Nominatim/OSM) para inferir a UF do usuário a
partir das coordenadas enviadas pelo navegador (geolocalização)."""
import logging
import re

import requests

from utils.cache import cache_get_json, cache_set_json

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_UA = "AutoAssist/1.0 (notificacoes de eventos automotivos)"
GEOCODE_CACHE_TTL = 30 * 24 * 3600  # 30 dias
NOMINATIM_TIMEOUT = 5


def reverse_geocode_uf(lat, lng, cache=True):
    """Retorna a UF (2 letras, ex.: 'SP') do ponto geográfico, ou '' se falhar.

    Usa o serviço Nominatim do OpenStreetMap e mantém um cache (chave com
    coordenadas arredondadas em ~1km para não estourar o rate limit).
    """
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return ""
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return ""

    cache_key = f"geocode:uf:{round(lat, 2)}:{round(lng, 2)}"
    if cache:
        cached = cache_get_json(cache_key)
        if cached is not None:
            return cached

    uf = ""
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "lat": lat,
                "lon": lng,
                "format": "jsonv2",
                "accept-language": "pt-BR",
            },
            headers={"User-Agent": NOMINATIM_UA},
            timeout=NOMINATIM_TIMEOUT,
        )
        resp.raise_for_status()
        addr = (resp.json() or {}).get("address") or {}
        iso = (addr.get("ISO3166-2-lvl4") or "").upper()
        if iso.startswith("BR-") and len(iso) == 5:
            uf = iso[3:5]
        elif (addr.get("country_code") or "").lower() == "br":
            code = (addr.get("state_code") or "").upper()
            if len(code) == 2 and code.isalpha():
                uf = code
    except Exception as e:
        pass

    if uf and cache:
        try:
            cache_set_json(cache_key, uf, ttl=GEOCODE_CACHE_TTL)
        except Exception:
            pass
    return uf

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"


def _norm_query(q):
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def geocode_address(query, cache=True):
    """Geocodifica um endereço/cidade (Brasil) e retorna (lat, lng).

    Retorna (None, None) se não encontrar. Usa Nominatim/OSM com cache de 30 dias.
    """
    q = _norm_query(query)
    if not q:
        return (None, None)
    cache_key = f"geocode:addr:{hash(q)}"
    if cache:
        cached = cache_get_json(cache_key)
        if cached:
            return (cached.get("lat"), cached.get("lng"))
    lat = lng = None
    try:
        resp = requests.get(
            NOMINATIM_SEARCH_URL,
            params={"q": q, "format": "jsonv2", "limit": 1,
                    "countrycodes": "br", "accept-language": "pt-BR"},
            headers={"User-Agent": NOMINATIM_UA},
            timeout=NOMINATIM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json() or []
        if data:
            lat = float(data[0]["lat"])
            lng = float(data[0]["lon"])
    except Exception as e:
        logger.warning("Geocodificacao de '%s' falhou: %s", q, e)
    if lat is not None and lng is not None and cache:
        try:
            cache_set_json(cache_key, {"lat": lat, "lng": lng}, ttl=GEOCODE_CACHE_TTL)
        except Exception:
            pass
    return (lat, lng)
