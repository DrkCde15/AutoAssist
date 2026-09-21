# backend/services/web_scrapping.py
import os
import re
import math
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
from utils.cache import cache_get_json, cache_set_json

logger = logging.getLogger(__name__)


def _affiliate_id(network: str):
    """P2-2: IDs de afiliado configuráveis por rede (env). Sem ID, o link fica limpo."""
    env_map = {
        "mercadolivre": "AFFILIATE_MERCADOLIVRE_ID",
        "webmotors": "AFFILIATE_WEBMOTORS_ID",
    }
    key = env_map.get(network)
    return os.getenv(key, "").strip() if key else ""


def _with_affiliate(url: str, network: str):
    aid = _affiliate_id(network)
    if not aid:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}u={quote(aid)}"


GOOGLE_CACHE_TTL = 86400  # 24h (resultados de busca mudam pouco)
GOOGLE_SEARCH_URL = "https://www.google.com.br/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class WebScraper:
    def __init__(self, url: str = None):
        self.url = url
        self.soup = None

    def fetch_content(self):
        if not self.url:
            raise ValueError("URL não definida.")
        response = requests.get(self.url, timeout=(3.05, 10))
        response.raise_for_status()
        self.soup = BeautifulSoup(response.text, "html.parser")

    def get_headings(self, tag: str = "h2"):
        if not self.soup:
            raise ValueError("Conteúdo não carregado. Use fetch_content() primeiro.")
        return [item.get_text(strip=True) for item in self.soup.select(tag)]

    def search_car_stores(self, query: str):
        q_plus = query.replace(' ', '+')
        q_encoded = quote(query)
        q_dash = query.replace(' ', '-')
        return [
            {'url': _with_affiliate(f"https://www.webmotors.com.br/carros/estoque?busca={q_plus}", "webmotors")},
            {'url': f"https://www.icarros.com.br/ache/listaanuncios.jsp?busca={q_encoded}"},
            {'url': _with_affiliate(f"https://lista.mercadolivre.com.br/veiculos/{q_dash}", "mercadolivre")},
            {'url': f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q={q_plus}"},
        ]

    def search_car_parts(self, query: str):
        q_plus = query.replace(' ', '+')
        q_dash = query.replace(' ', '-')
        return [
            {'url': _with_affiliate(f"https://lista.mercadolivre.com.br/acessorios-veiculos/{q_dash}", "mercadolivre")},
            {'url': f"https://www.canaldapeca.com.br/busca?q={q_plus}"},
            {'url': f"https://www.olx.com.br/autos-e-pecas/pecas-e-acessorios?q={q_plus}"},
        ]


def get_market_price_estimate(make, model, year):
    """Melhor-esforco: mediana de precos de anuncios reais (Mercado Livre).

    Usado apenas para FUNDAMENTAR o valor estimado de mercado (nao e fonte
    oficial). Falha silenciosa e rapida (timeout curto, cache 24h): se nao
    houver amostra confiavel, retorna None e o chamador usa a Tabela FIPE.
    Retorna (mediana:float, amostra:int) ou None.
    """
    try:
        if not (make and model and year):
            return None
        query = f"{make} {model} {year}".replace(" ", "-")
        url = f"https://lista.mercadolivre.com.br/veiculos/{query}"
        cache_key = f"ml_price:{query}"
        cached = cache_get_json(cache_key)
        if cached is not None:
            return tuple(cached) if cached else None
        resp = requests.get(url, headers=HEADERS, timeout=5)
        if resp.status_code != 200:
            cache_set_json(cache_key, None, ttl=GOOGLE_CACHE_TTL)
            return None
        html = resp.text
        precos = set()
        # JSON embutido / meta de preco
        for m in re.finditer(r'"price"\s*:\s*"?(\d{4,7}(?:\.\d{1,2})?)', html):
            try:
                precos.add(float(m.group(1)))
            except ValueError:
                pass
        # spans de valor do Mercado Livre
        for m in re.finditer(r'andes-money-amount__fraction">([\d.]+)<', html):
            try:
                precos.add(float(m.group(1).replace(".", "")))
            except ValueError:
                pass
        # filtra faixas plausiveis de carro
        vals = [p for p in precos if 3000 <= p <= 2_000_000]
        if len(vals) < 3:
            cache_set_json(cache_key, None, ttl=GOOGLE_CACHE_TTL)
            return None
        vals.sort()
        n = len(vals)
        mediana = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        cache_set_json(cache_key, [mediana, n], ttl=GOOGLE_CACHE_TTL)
        return (mediana, n)
    except Exception as e:
        logger.debug("market price indisponivel: %s", e)
        return None


# ───────────────────── saúde das fontes + fallback SerpApi ─────────────────────

SOURCE_HEALTH = {}
SOURCE_DEAD_THRESHOLD = int(os.getenv("SOURCE_DEAD_THRESHOLD", "3"))


def _record_source_health(name, ok):
    """Registra sucesso/falha de uma fonte; dispara alerta apos N falhas seguidas."""
    st = SOURCE_HEALTH.setdefault(name, {"failures": 0, "dead": False})
    if ok:
        st["failures"] = 0
        st["dead"] = False
    else:
        st["failures"] += 1
        if st["failures"] >= SOURCE_DEAD_THRESHOLD and not st["dead"]:
            st["dead"] = True
            logger.error(
                "ALERTA FONTE MORTA: '%s' falhou %d vezes consecutivas.",
                name, st["failures"],
            )


def dead_sources():
    """Retorna lista de nomes de fontes consideradas 'mortas' (falha repetida)."""
    return [n for n, st in SOURCE_HEALTH.items() if st["dead"]]


def _radius_to_zoom(radius):
    """Converte raio em km num zoom do Google Maps (~alcance da busca).

    O engine google_maps não aceita 'radius'; o vão é aproximado via zoom.
    """
    try:
        r = float(radius)
    except (TypeError, ValueError):
        r = 10
    if r <= 5:
        return 14
    if r <= 10:
        return 13
    if r <= 20:
        return 12
    if r <= 50:
        return 11
    return 10


_SERVICE_QUERY = {
    "troca_oleo": "troca de oleo",
    "freios": "freios",
    "suspensao": "suspensao",
    "arrefecimento": "arrefecimento",
    "eletrica": "eletrica",
    "pneus": "pneus",
    "motor": "motor",
}


def _serpapi_query(service_type):
    extra = _SERVICE_QUERY.get(service_type)
    return f"oficina mecanica {extra}" if extra else "oficina mecanica"


_SERPAPI_DAY_MAP = {
    "segunda-feira": "seg", "terca-feira": "ter", "terça-feira": "ter",
    "quarta-feira": "qua", "quinta-feira": "qui", "sexta-feira": "sex",
    "sabado": "sab", "sábado": "sab", "domingo": "dom",
}


def _parse_operating_hours(oh):
    """Converte operating_hours do SerpApi (PT, nomes completos) para o formato
    do app (chaves seg/ter/qua/qui/sex/sab/dom, hífens normais)."""
    if not isinstance(oh, dict):
        return None
    result = {}
    for full, short in _SERPAPI_DAY_MAP.items():
        val = oh.get(full)
        if not val:
            continue
        val = val.replace("–", "-").replace("—", "-").strip()
        result[short] = val
    if not result:
        return None
    for d in ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]:
        result.setdefault(d, "fechado")
    return result


def _parse_address_br(address):
    """Extrai (endereco_rua, cidade, estado) de um endereço BR.

    Aceita 'Rua X, 242 - Bairro, Cidade - UF, CEP'.
    """
    if not address:
        return "", "", ""
    parts = [p.strip() for p in address.split(",")]
    street, cidade, estado = parts, "", ""
    for i, p in enumerate(parts):
        if " - " in p:
            cidade, _, uf = p.rpartition(" - ")
            if len(uf) == 2 and uf.isalpha():
                cidade = cidade.strip()
                estado = uf.upper()
                street = parts[:i]
                break
    return ", ".join(street), cidade, estado


def _serpapi_specialties(types, service_type):
    """Mapeia 'types' do SerpApi (PT) para o enum de especialidades do app."""
    mapping = {
        "oleo": "troca_oleo",
        "freio": "freios",
        "suspensao": "suspensao",
        "arrefecimento": "arrefecimento",
        "eletrica": "eletrica",
        "eletrico": "eletrica",
        "pneu": "pneus",
        "motor": "motor",
    }
    found = set()
    for t in (types or []):
        tl = (t or "").lower()
        for k, v in mapping.items():
            if k in tl:
                found.add(v)
    if service_type:
        found.add(service_type)
    if not found:
        found.add("troca_oleo")
    return sorted(found)


def search_mechanics_serpapi(user_lat, user_lng, radius, service_type=None):
    """Fallback de busca de oficinas via SerpApi (Google Maps).

    Funciona de qualquer IP (inclusive producao em datacenter) pois usa a API
    oficial da SerpApi com SERPAPI_KEY e retorna coordenadas GPS reais.
    Requer a variavel de ambiente SERPAPI_KEY; sem ela retorna [] (sem custo).
    """
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        return []

    cache_key = f"serpapi_mechanics:{user_lat:.4f}:{user_lng:.4f}:{radius}:{service_type or ''}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return cached

    zoom = _radius_to_zoom(radius)
    query = _serpapi_query(service_type)

    try:
        resp = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_maps",
                "q": query,
                "ll": f"@{user_lat:.6f},{user_lng:.6f},{zoom}z",
                "type": "search",
                "hl": "pt-br",
                "gl": "br",
                "api_key": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        local = data.get("local_results") or []
        results = []
        for item in local:
            try:
                nome = (item.get("title") or "").strip()
                if not nome:
                    continue
                geo = item.get("gps_coordinates") or {}
                lat = float(geo.get("latitude", user_lat))
                lng = float(geo.get("longitude", user_lng))
                distance_km = round(_haversine(user_lat, user_lng, lat, lng), 1)
                if distance_km > radius:
                    continue
                rating = item.get("rating")
                reviews = item.get("reviews") or 0
                address = item.get("address", "")
                endereco, cidade, estado = _parse_address_br(address)
                place_id = item.get("place_id") or re.sub(r"[^a-zA-Z0-9]", "", nome)[:20]
                results.append({
                    "id": f"serpapi_{place_id}",
                    "nome": nome,
                    "endereco": endereco,
                    "cidade": cidade,
                    "estado": estado,
                    "latitude": lat,
                    "longitude": lng,
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                    "telefone": item.get("phone", ""),
                    "website": item.get("website", ""),
                    "descricao": item.get("description", "") or "",
                    "especialidades": _serpapi_specialties(item.get("types"), service_type),
                    "servicos": [],
                    "horario_funcionamento": _parse_operating_hours(item.get("operating_hours")),
                    "avaliacao_media": float(rating) if rating else None,
                    "total_avaliacoes": int(reviews) if reviews else 0,
                    "foto_url": item.get("serpapi_thumbnail") or item.get("thumbnail"),
                    "is_verified": False,
                    "distance_km": distance_km,
                    "_source": "serpapi",
                })
            except Exception:
                continue
        _record_source_health("serpapi", True)
        cache_set_json(cache_key, results, ttl=GOOGLE_CACHE_TTL)
        return results
    except Exception as e:
        _record_source_health("serpapi", False)
        logger.warning("SerpApi indisponivel: %s", e)
        return []


def _haversine(lat1, lng1, lat2, lng2):
    """Distancia em km entre duas coordenadas."""
    from math import radians, sin, cos, asin, sqrt
    r = 6371
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(a))


def validate_url(url, timeout=3):
    """Verifica se uma URL retorna status 2xx via HEAD request.

    Retorna True se a URL for acessível, False caso contrário.
    Em caso de erro de conexão ou timeout, retorna False.
    """
    if not url or not url.startswith("http"):
        return False
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True,
                             headers={"User-Agent": "AutoAssist/1.0"})
        return 200 <= resp.status_code < 400
    except Exception:
        return False


def validate_links(links, max_workers=5):
    """Filtra uma lista de links, mantendo apenas os que retornam 2xx.

    Faz requests HEAD em paralelo para não bloquear.
    Retorna apenas os links válidos.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def check(link):
        url = link.get("url", "")
        if validate_url(url):
            return link
        logger.info("Link quebrado removido: %s", url)
        return None

    if not links:
        return links

    valid = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(check, link): link for link in links}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                valid.append(result)
    return valid
