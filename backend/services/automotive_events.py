# backend/services/automotive_events.py
"""Varredura de eventos automotivos no Brasil.

Fontes por web scraping:
  - nfeiras.com (calendário de feiras de automobilismo no Brasil)
  - sindirepabrasil.org.br/eventos (feiras e eventos da reparação)
  - diretriz.com.br (promotora de feiras - Autopar, Minasparts, ...)
  - interlagos.com.br (Shopping Interlagos - apenas itens automotivos)
  - SerpApi (Google, via SERPAPI_KEY) - busca web estruturada e confiável
    (funciona de qualquer IP, inclusive datacenter; reforça o canal "web")
  - Google Search (fallback + eventos Sympla via site:sympla.com.br,
    além de busca geral por feiras/encontros/exposições automotivas)

Se uma fonte falhar, o erro é registrado e não quebra as demais.
Resultados são normalizados num schema comum e cacheados (padrão 6h).

Apenas eventos com country=BR (Brasil) são retornados — eventos
internacionais são descartados na varredura.
"""
import re
import os
import base64
import hashlib
import difflib
import logging
from math import radians, sin, cos, atan2, sqrt
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from utils.cache import cache_get_json, cache_set_json
from urllib.parse import quote

logger = logging.getLogger(__name__)

EVENTS_CACHE_TTL = 6 * 3600  # 6 horas
REQUEST_TIMEOUT = 6
MAX_EVENTS = 150
MAX_GOOGLE_EVENTS = 80

WEB_SEARCH_URL = "https://www.bing.com/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MONTHS = {
    "janeiro": 1, "jan": 1, "januar": 1,
    "fevereiro": 2, "fev": 2, "februar": 2,
    "marco": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "maio": 5, "mai": 5,
    "junho": 6, "jun": 6,
    "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9,
    "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12,
}
_MONTH_ALT = "|".join(sorted(set(MONTHS), key=len, reverse=True))

# Filtra conteúdos não-automotivos das fontes genéricas.
# STRONG: termo sozinho já indica automotivo (carro, peça, marca, etc.).
# WEAK: substantivo de evento ("encontro", "exposição", "feira"...) que só
#   conta SE vier acompanhado de um termo veicular - evita falsos positivos
#   como "Encontro com Patrícia Poeta" ou "Exposição no MASP".
AUTOMOTIVE_STRONG = (
    "automot", "autopar", "automecanika", "automec", "veicul", "veiculo",
    "automove", "autopec", "autop", "pecas", "peca", "reposicao", "reposto",
    "pneu", "mecanic", "oficina", "carro", "carros", "caminhao", "caminhão",
    "truck", "parts", "moto", "motos", "turbo", "drift", "rally", "rali",
    "corrida", "formula", "eletrocar", "fenajeep", "jeep", "suv", "atv",
    "motoshow", "hot wheels", "hotwheel", "diecast", "miniatura", "colecionador",
    "leilao", "leilão", "motor", "trackday", "arrancada", "off road", "off-road",
    "4x4", "jipe", "jipeiro", "kart", "monster", "tuning", "trator", "ônibus",
    "onibus", "pilotagem", "restauracao", "restauração", "garagem", "chassi",
    "motorista", "combustivel", "gasolina", "diesel", "bumper", "carroceria",
    "autodrom",
)
AUTOMOTIVE_WEAK = (
    "encontro", "expo", "exposi", "feira", "salao", "salão", "mostra",
    "show", "feirinha", "antigo", "antiga", "classic", "clássico", "clássicos",
    "clubes", "clube", "encontros", "meet", "meetup",
)
# palavras-veículo usadas para validar os termos WEAK
_VEHICLE_WORDS = (
    "carro", "carros", "veicul", "moto", "caminhao", "caminhão", "auto", "pneu",
    "jeep", "4x4", "trator", "ônibus", "onibus", "bike", "quadriciclo",
    "hot wheels", "diecast", "miniatura", "reboque", "tanque",
)

def _web_queries(location="São Paulo"):
    """Queries do Google: Sympla (plataforma) + buscas gerais amplas + viés local.

    - O ano é calculado dinamicamente (e o próximo, se estivermos no fim do ano).
    - As queries "broad" capturam eventos genéricos (feira/expo/encontro/leilão)
      que antes escapavam (ex.: Hot Wheels, colecionadores, comunidade).
    - As queries "local" incluem a cidade para surfar a aba de Eventos do Google
      e o Google Maps ("Próximos eventos"), que é onde eventos de bairro
      (ex.: Aricanduva)_costumam aparecer.
    """
    year = datetime.now().year
    years = [year]
    if datetime.now().month >= 10:
        years.append(year + 1)

    base = []
    for y in years:
        base += [
            f"site:sympla.com.br evento automotivo {y}",
            f"site:sympla.com.br encontro de carros {y}",
            f"site:sympla.com.br feira autopecas {y}",
        ]

    broad = [
        "eventos automotivos Brasil",
        "evento de carros Brasil",
        "feira de carros Brasil",
        "encontro de carros Brasil",
        "exposição de carros Brasil",
        "feira auto peças Brasil",
        "salão do automóvel Brasil",
        "hot wheels evento Brasil",
        "hot wheels encontro Brasil",
        "leilão de carros Brasil",
        "encontro de motos Brasil",
        "rally de carros Brasil",
        "expo automotiva Brasil",
        "feirinha de carros Brasil",
    ]

    local = [
        f"eventos de carros em {location} Brasil",
        f"feira de carros em {location} Brasil",
        f"encontro de carros em {location} Brasil",
        f"evento automotivo {location} Brasil",
        f"hot wheels {location} Brasil",
        f"encontro de carros antigos {location} Brasil",
    ]

    # anexa o ano a cada query ampla/local para restringir a eventos atuais
    broad = [f"{q} {year}" for q in broad]
    local = [f"{q} {year}" for q in local]
    return base + broad + local

# Classificação de categoria por palavras-chave (ordem importa: a primeira
# regra que bater define a categoria - específicas antes das genéricas).
CATEGORIA_RULES = [
    ("encontro", ("encontro", "encontros", "meetup", "meet up", "car meeting")),
    ("competicao", ("corrida", "rally", "rali", "drift", "competi", "campeonato",
                    "prova", "copa de", "temporada", "etapa de")),
    ("congresso", ("congresso", "semin", "palestr", "workshop", "forum", "conference")),
    ("feira", ("feira", "autopecas", "autopecas", "autopar", "autop", "reposicao",
               "reposto", "automecanika", "automec", "parts", "expoautopecas",
               "fenatra", "reparacao")),
    ("exposicao", ("exposi", "expo ", "salao", "salao", "mostra", "showroom",
                   "avante", "classic show")),
]

CATEGORIA_LABELS = {
    "feira": "Feira",
    "encontro": "Encontro",
    "competicao": "Competição",
    "exposicao": "Exposição",
    "congresso": "Congresso",
    "outros": "Outros",
}

_ACCENTS_TRANS = str.maketrans(
    "áàâãäéèêëíìîïóòôõöúùûüç",
    "aaaaaeeeeiiiiooooouuuuc",
)


# ─────────────────────── helpers genéricos ───────────────────────


def _clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _normalize_title(value):
    """Título normalizado para matching/deduplicação (minúsculo, sem acento)."""
    if not value:
        return ""
    s = _clean_text(value).lower().translate(_ACCENTS_TRANS)
    return re.sub(r"\s+", " ", s).strip()


def _iso_to_date(value):
    """Converte 'YYYY-MM-DD' em date; retorna None se inválido."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _stable_event_id(fonte, normalized_title, start_date, city):
    """ID determinístico e estável entre processos (substitui o hash() frágil)."""
    seed = f"{fonte}|{normalized_title}|{start_date or ''}|{city or ''}"
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"{fonte}:{h}"


# Confiança da fonte (0-1): quanto mais estruturada/confiável, maior.
# Fontes oficiais/especializadas têm HTML estável e curado; busca web genérica
# é ruído e raramente traz data estruturada -> confiança baixa.
CONFIDENCE_BY_SOURCE = {
    "nfeas": 0.90,
    "sindirepa": 0.90,
    "diretriz": 0.90,
    "interlagos": 0.90,
    "serpapi": 0.72,
    "web": 0.40,
}


def _source_confidence(fonte):
    return CONFIDENCE_BY_SOURCE.get(fonte, 0.50)


def derive_status(start_date, end_date, text=""):
    """Status temporal do evento (não apaga registros passados)."""
    if "cancelad" in (text or "").lower():
        return "cancelled"
    today = date.today()
    sd, ed = _iso_to_date(start_date), _iso_to_date(end_date)
    if ed and ed < today:
        return "finished"
    if sd and sd < today:
        return "finished"
    if sd and sd > today:
        return "upcoming"
    if sd and sd <= today and ed and ed >= today:
        return "ongoing"
    return "unknown"


def _haversine(lat1, lng1, lat2, lng2):
    """Distância em km entre dois pontos (fórmula de Haversine)."""
    try:
        lat1, lng1, lat2, lng2 = map(float, (lat1, lng1, lat2, lng2))
    except (TypeError, ValueError):
        return float("inf")
    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


def _fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _parse_br_dates(text: str):
    """Extrai (data_inicio, data_fim) de textos de data em pt-BR.

    Formatos suportados:
      "06 a 09 de maio de 2026"           -> (2026-05-06, 2026-05-09)
      "21 de julho a 1 de agosto de 2026" -> (2026-07-21, 2026-08-01)
      "19 a 22 agosto 2026"
      "Abril de 2026"                      -> (2026-04-01, 2026-04-30)
    Retorna (None, None) se não for possível parsear.
    """
    if not text:
        return None, None
    t = text.lower()
    t = t.replace("º", "").replace("°", "")
    t = re.sub(r"[^\w\s]", " ", t)   # remove pontuação (inclui º, à, ...)
    t = re.sub(r"\s+", " ", t).strip()

    # 1) período cruzando mês: "21 de julho a 1 de agosto de 2026"
    m = re.search(
        rf"(\d{{1,2}})\s*(?:de\s+)?({_MONTH_ALT})\s*(?:de\s+)?a\s+"
        rf"(\d{{1,2}})\s*(?:de\s+)?({_MONTH_ALT})\s*(?:de\s+)?(20\d{{2}})",
        t,
    )
    if m:
        d1, m1s, d2, m2s, y = m.groups()
        m1, m2 = MONTHS.get(m1s), MONTHS.get(m2s)
        if m1 and m2:
            return f"{y}-{m1:02d}-{int(d1):02d}", f"{y}-{m2:02d}-{int(d2):02d}"

    # 2) mesmo mês: "06 a 09 de maio de 2026"
    m = re.search(
        rf"(\d{{1,2}})\s*(?:de\s+)?a\s+(\d{{1,2}})\s*(?:de\s+)?({_MONTH_ALT})"
        rf"\s*(?:de\s+)?(20\d{{2}})",
        t,
    )
    if m:
        d1, d2, ms, y = m.groups()
        mo = MONTHS.get(ms)
        if mo:
            return f"{y}-{mo:02d}-{int(d1):02d}", f"{y}-{mo:02d}-{int(d2):02d}"

    # 3) data única: "7 de maio de 2026"
    m = re.search(rf"(\d{{1,2}})\s*(?:de\s+)?({_MONTH_ALT})\s*(?:de\s+)?(20\d{{2}})", t)
    if m:
        d, ms, y = m.groups()
        mo = MONTHS.get(ms)
        if mo:
            return f"{y}-{mo:02d}-{int(d):02d}", f"{y}-{mo:02d}-{int(d):02d}"

    # 4) só mês e ano: "Abril de 2026"
    m = re.search(rf"({_MONTH_ALT})\s*(?:de\s+)?(20\d{{2}})", t)
    if m:
        ms, y = m.groups()
        mo = MONTHS.get(ms)
        if mo:
            last = 30 if mo in (4, 6, 9, 11) else (29 if mo == 2 else 31)
            return f"{y}-{mo:02d}-01", f"{y}-{mo:02d}-{last:02d}"
    return None, None


def _extract_city_uf(text: str):
    """Extrai (cidade, uf, local_detalhe) de textos como:
    "Curitiba (PR) - Expotrade Pinhais" | "Fortaleza, Brasil" | "Buenos Aires - Argentina".
    """
    text = _clean_text(text)
    if not text:
        return "", "", ""
    m = re.search(
        r"([A-Za-zÁÃÂÀÉÊÍÓÔÚÛÇáãâàéêíóôúûç'’\-\. ]+?)\s*\(\s*([A-Z]{2})\s*\)",
        text,
    )
    if m:
        cidade = _clean_text(m.group(1))
        uf = m.group(2).upper()
        resto = _clean_text(text[m.end():]).lstrip("- ").strip()
        return cidade, uf, resto or _clean_text(text[:m.start()])
    parts = [p.strip() for p in re.split(r"[,\-]|\s-\s", text) if p.strip()]
    if parts:
        if len(parts) >= 2 and re.fullmatch(r"[A-Z]{2}", parts[1]):
            return parts[0], parts[1].upper(), parts[2] if len(parts) > 2 else ""
        if len(parts) >= 2:
            # "Fortaleza, Brasil" (UF não informada) ou "Buenos Aires - Argentina" (exterior)
            if parts[1].lower() == "brasil":
                return parts[0], _uf_from_city(parts[0]), ""
            if len(parts) > 2:
                return parts[0], "INT", "".join(parts[1:])
            return parts[0], "INT", ""
        # token único: só é cidade se reconhecida no mapeamento (evita
        # poluir o campo com o snippet inteiro quando não há localização)
        cidade = parts[0]
        uf = _uf_from_city(cidade)
        return (cidade, uf, "") if uf else ("", "", "")
    return "", "", ""


# Capitais e principais cidades → UF (usado quando a fonte não informa a UF)
_CITY_TO_UF = {
    # Norte
    "rio branco": "AC", "macapa": "AP", "manaus": "AM", "belem": "PA",
    "porto velho": "RO", "boa vista": "RR", "palmas": "TO",
    # Nordeste
    "maceio": "AL", "salvador": "BA", "fortaleza": "CE", "sao luis": "MA",
    "joao pessoa": "PB", "recife": "PE", "teresina": "PI", "natal": "RN",
    "aracaju": "SE", "feira de santana": "BA",
    # Centro-Oeste
    "brasilia": "DF", "goiania": "GO", "cuiaba": "MT", "campo grande": "MS",
    # Sudeste
    "vitoria": "ES", "belo horizonte": "MG", "contagem": "MG",
    "uberlancia": "MG", "juiz de fora": "MG", "sao paulo": "SP",
    "campinas": "SP", "santos": "SP", "guarulhos": "SP",
    "osasco": "SP", "sao jose dos campos": "SP", "ribeirao preto": "SP",
    "sorocaba": "SP", "rio de janeiro": "RJ", "niteroi": "RJ",
    "sao goncalo": "RJ", "nova iguacu": "RJ", "duque de caxias": "RJ",
    # Sul
    "curitiba": "PR", "londrina": "PR", "maringa": "PR", "cascavel": "PR",
    "florianopolis": "SC", "joinville": "SC", "blumenau": "SC",
    "criciuma": "SC", "porto alegre": "RS", "caxias do sul": "RS",
    "pelotas": "RS", "santa maria": "RS", "passo fundo": "RS",
    "novo hamburgo": "RS", "gramado": "RS", "canela": "RS",
}


def _uf_from_city(cidade: str) -> str:
    """Infere a UF a partir do nome da cidade (quando a fonte não informa)."""
    key = (cidade or "").strip().lower().translate(_ACCENTS_TRANS)
    return _CITY_TO_UF.get(key, "")


def _is_automotive(text: str) -> bool:
    """True se o texto for claramente do mundo automotivo.

    Termos STRONG validam sozinhos; termos WEAK (encontro, exposição, feira...)
    só contam acompanhados de uma palavra-veículo, para evitar ruído como
    'Encontro com Patrícia Poeta' ou 'Exposição no MASP'.
    """
    t = (text or "").lower()
    if any(k in t for k in AUTOMOTIVE_STRONG):
        return True
    if any(w in t for w in AUTOMOTIVE_WEAK) and any(v in t for v in _VEHICLE_WORDS):
        return True
    return False


def _classify_category(titulo="", descricao="", local=""):
    """Classifica o evento numa categoria amigável de filtro.

    Categorias: feira, encontro, competicao, exposicao, congresso, outros.
    A análise usa título + descrição + local (a primeira regra que bater vence).
    """
    text = " ".join([titulo, descricao, local]).lower().translate(_ACCENTS_TRANS)
    for categoria, keywords in CATEGORIA_RULES:
        if any(k in text for k in keywords):
            return categoria
    return "outros"


def _make_event(*, titulo, url, fonte, fonte_nome, data_inicio=None, data_fim=None,
                cidade="", uf="", local="", descricao="", venue_name="",
                address="", organizer="", organizer_url="", image_url="",
                latitude=None, longitude=None, country="BR",
                start_time=None, end_time=None, source_url=""):
    hoje = date.today().isoformat()
    titulo_clean = _clean_text(titulo)[:200]
    cidade_clean = _clean_text(cidade)[:80]
    normalized = _normalize_title(titulo_clean)
    desc_clean = _clean_text(descricao)[:400]
    local_clean = _clean_text(local)[:120]
    status = derive_status(data_inicio, data_fim, f"{titulo_clean} {desc_clean}")
    return {
        "id": _stable_event_id(fonte, normalized, data_inicio, cidade_clean),
        "titulo": titulo_clean,
        "original_title": titulo_clean,
        "normalized_title": normalized,
        "url": (url or "").strip(),
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "start_time": start_time,
        "end_time": end_time,
        "cidade": cidade_clean,
        "uf": ((uf or "").upper()) or _uf_from_city(cidade_clean),
        "local": local_clean,
        "venue_name": _clean_text(venue_name)[:160],
        "address": _clean_text(address)[:200],
        "descricao": desc_clean,
        "categoria": _classify_category(titulo_clean, desc_clean, local_clean),
        "categoria_label": "",
        "organizer": _clean_text(organizer)[:160],
        "organizer_url": (organizer_url or "").strip(),
        "event_url": (url or source_url or "").strip(),
        "image_url": (image_url or "").strip(),
        "latitude": latitude,
        "longitude": longitude,
        "country": (country or "BR")[:2].upper(),
        "fonte": fonte,
        "fonte_nome": fonte_nome,
        "source_url": (source_url or url or "").strip(),
        "status": status,
        "confidence": _source_confidence(fonte),
        "passado": bool(data_inicio and data_inicio < hoje),
        "last_verified_at": None,
    }


# ─────────────────────────────── fontes ───────────────────────────────


def _scrape_nfeiras():
    """https://www.nfeiras.com/automobilismo/brasil - calendário de feiras."""
    soup = BeautifulSoup(_fetch_html("https://www.nfeiras.com/automobilismo/brasil"), "html.parser")
    events = []
    for card in soup.select("article.card-tradeShow"):
        try:
            a = card.select_one("a.text-dark")
            if not a:
                continue
            titulo = _clean_text(a.get_text())
            data_inicio = data_fim = None
            for t in card.select("time"):
                classes = t.get("class") or []
                if "dtstart" in classes:
                    data_inicio = (t.get("datetime") or "")[:10] or None
                if "dtend" in classes:
                    data_fim = (t.get("datetime") or "")[:10] or None
            bloco = card.select_one(".mb-3")
            texto_local = ""
            if bloco:
                linhas = [l.strip() for l in bloco.get_text("|", strip=True).split("|") if l.strip()]
                if len(linhas) >= 2:
                    # última linha costuma ser "Cidade, Brasil"
                    cidade, uf, _ = _extract_city_uf(linhas[-1])
                    texto_local = " - ".join(linhas[:-1])
                    if not uf and len(linhas) > 2:
                        _, uf, _ = _extract_city_uf(" ".join(linhas[:-1]))
                else:
                    cidade, uf, _ = _extract_city_uf(linhas[0] if linhas else "")
            else:
                cidade, uf = "", ""
            events.append(_make_event(
                titulo=titulo,
                url=a.get("href") or card.get("data-href") or "",
                data_inicio=data_inicio,
                data_fim=data_fim,
                cidade=cidade,
                uf=uf or "",
                local=texto_local,
                fonte="nfeas",
                fonte_nome="NFeiras.com",
            ))
        except Exception:
            continue
    return events


def _scrape_sindirepa():
    """https://sindirepabrasil.org.br/eventos - feiras da reparação automotiva."""
    soup = BeautifulSoup(_fetch_html("https://sindirepabrasil.org.br/eventos/"), "html.parser")
    events = []
    for card in soup.select(".se-card"):
        try:
            h3 = card.select_one("h3")
            if not h3:
                continue
            titulo = _clean_text(h3.get_text())
            desc_el = card.select_one(".se-desc")
            descricao = _clean_text(desc_el.get_text()) if desc_el else ""
            data_text = ""
            local_text = ""
            for p in card.select("p.se-info"):
                icon = p.select_one("span.dashicons")
                txt = _clean_text(p.get_text(" ", strip=True))
                if icon:
                    cls = " ".join(icon.get("class") or [])
                    if "calendar" in cls:
                        data_text = txt
                    elif "location" in cls:
                        local_text = txt
                elif not data_text:
                    data_text = txt
            if not data_text:
                data_text = _clean_text(card.get_text(" "))
            inicio, fim = _parse_br_dates(data_text)
            cidade, uf, local = _extract_city_uf(local_text)
            events.append(_make_event(
                titulo=titulo,
                url="https://sindirepabrasil.org.br/eventos/",
                data_inicio=inicio,
                data_fim=fim,
                cidade=cidade,
                uf=uf,
                local=local,
                descricao=descricao,
                fonte="sindirepa",
                fonte_nome="Sindirepa Brasil",
            ))
        except Exception:
            continue
    return events


def _scrape_diretriz():
    """Feiras da Diretriz - mantendo apenas o segmento automotivo.

    A página é Elementor: cada card tem um h2.elementor-heading-title
    (título), um widget-text-editor com "Cidade / UF" e "data | ano" e um
    botão "Visitar site" com o link.
    """
    soup = BeautifulSoup(_fetch_html("https://diretriz.com.br/proximas-feiras/"), "html.parser")
    events = []
    for h2 in soup.select("h2.elementor-heading-title"):
        titulo = _clean_text(h2.get_text())
        if not titulo or not _is_automotive(titulo):
            continue
        # sobe até o bloco ".e-con" que contém o editor de texto
        node = h2
        editor = None
        for _ in range(8):
            node = node.parent
            if node is None:
                break
            editor = node.select_one(".elementor-widget-text-editor")
            if editor:
                break
        if not editor:
            continue
        txt = _clean_text(editor.get_text(" "))
        m_loc = re.search(r"([A-ZÁ-Ú][A-Za-zÁ-Úá-ú'\- ]+?)\s*/\s*([A-Z]{2})", txt)
        cidade = m_loc.group(1).strip() if m_loc else ""
        uf = m_loc.group(2).strip() if m_loc else ""
        inicio, fim = _parse_br_dates(txt)
        link_a = None
        parent = editor.parent
        for _ in range(8):
            if parent is None:
                break
            link_a = parent.select_one("a.elementor-button")
            if link_a:
                break
            parent = parent.parent
        events.append(_make_event(
            titulo=titulo,
            url=link_a.get("href") if link_a else "https://diretriz.com.br",
            data_inicio=inicio,
            data_fim=fim,
            cidade=cidade,
            uf=uf,
            local="",
            descricao=txt[:300],
            fonte="diretriz",
            fonte_nome="Diretriz Feiras",
        ))
    return events


def _scrape_interlagos():
    """Shopping Interlagos - seção ACONTECE (só itens automotivos)."""
    soup = BeautifulSoup(_fetch_html("https://www.interlagos.com.br/"), "html.parser")
    events = []
    for thumb in soup.select("#carousel-noticias .thumbnail"):
        try:
            h4 = thumb.select_one(".caption h4")
            if not h4:
                continue
            titulo = _clean_text(h4.get_text())
            if not _is_automotive(titulo):
                continue
            a = thumb.select_one("a")
            url = a.get("href") if a else ""
            if url.startswith("/"):
                url = "https://www.interlagos.com.br" + url
            events.append(_make_event(
                titulo=titulo,
                url=url,
                cidade="São Paulo",
                uf="SP",
                local="Shopping Interlagos",
                descricao="Shopping Interlagos",
                fonte="interlagos",
                fonte_nome="Shopping Interlagos",
            ))
        except Exception:
            continue
    return events


def _is_bot_page(html: str) -> bool:
    """Detecta páginas de bloqueio/CAPTCHA do Google (devolve 200 mas sem resultados)."""
    markers = (
        "nosso sistema detectou", "verificação de segurança", "unusual traffic",
        "digite os caracteres", "our systems have detected", "before you continue",
        "captcha", "robots", "sistema detectou tráfego incomum",
    )
    low = (html or "").lower()
    return any(m in low for m in markers)


# Domínios de plataformas de evento - isentos da exigência de data (já são
# eventos por definição) e priorizados na busca web.
EVENT_DOMAINS = (
    "sympla", "eventbrite", "feverup", "fever", "facebook.com/events",
    "meetup.com", "ingresso", "bileto", "guiaeventos", "eventos.com.br",
    "wikievents", "loominee", "even3", "tickets", "lewear", "vamos",
)
# Domínios que nunca são eventos - descartados da busca web.
NON_EVENT_DOMAINS = (
    "wikipedia", "wikimedia", "youtube.com", "youtu.be", "gov.br", "gov",
    "nyc.gov", "microsoft", "bing.com", "googleusercontent", "amazon",
    "mercadolivre", "olx", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "tiktok", "pinterest", "reddit.com",
)


def _is_event_domain(url: str) -> bool:
    u = (url or "").lower()
    return any(d in u for d in EVENT_DOMAINS)


def _is_blocked_domain(url: str) -> bool:
    u = (url or "").lower()
    return any(d in u for d in NON_EVENT_DOMAINS)


def _decode_search_redirect(href: str) -> str:
    """Decodifica URLs de redirecionamento do Bing (`/ck/a?...&u=a1<base64>`).

    O Bing envolve o link real num redirecionador; o alvo vem em base64 no
    parâmetro `u=a1...`. Sem isso, todos os links apontariam para bing.com.
    """
    if not href or "bing.com/ck/a" not in href:
        return href
    m = re.search(r"u=a1([^&]+)", href)
    if not m:
        return href
    try:
        s = m.group(1)
        s += "=" * (-len(s) % 4)
        dec = base64.urlsafe_b64decode(s).decode("utf-8", "ignore")
        if dec.startswith("http"):
            return dec
    except Exception:
        pass
    return href


def _extract_event_blocks(soup, fonte_nome="Busca Web"):
    """Extrai blocos de evento de uma SERP (Bing).

    O Bing renderiza resultados server-side em `li.b_algo` (não exige JS, ao
    contrário do Google que devolve um interstitial "enablejs"). Filtra
    não-automotivos e extrai data/cidade do título+snippet.
    """
    results = []
    for el in soup.select("li.b_algo"):
        try:
            a = el.select_one("h2 a")
            if not a:
                continue
            url = _decode_search_redirect(a.get("href", ""))
            if not url.startswith("http"):
                continue
            if any(d in url for d in ("bing.com", "microsoft.com", "msn.com", "live.com")):
                continue
            if _is_blocked_domain(url):
                continue

            titulo = _clean_text(a.get_text(strip=True))
            if not titulo or len(titulo) < 3:
                continue

            snippet_el = el.select_one(".b_caption p, p")
            snippet = _clean_text(snippet_el.get_text(" ", strip=True)) if snippet_el else ""

            raw = f"{titulo} | {snippet}"
            if not _is_automotive(raw):
                continue

            cidade, uf, local = _extract_city_uf(snippet) if snippet else ("", "", "")
            inicio, fim = _parse_br_dates(raw)
            # Evento de verdade tem data; plataformas de evento são isentas.
            if not _is_event_domain(url) and inicio is None:
                continue
            results.append(_make_event(
                titulo=titulo,
                url=url,
                data_inicio=inicio,
                data_fim=fim,
                cidade=cidade,
                uf=uf,
                local=local,
                descricao=snippet,
                fonte="web",
                fonte_nome=fonte_nome,
            ))
        except Exception:
            continue
    return results


def _scrape_bing_events():
    """Busca web via Bing usando Scrapling (curl_cffi, TLS stealth, sem navegador).

    O Google exige JS (interstitial "enablejs"); o Bing ainda serve o HTML dos
    resultados sem JS. O Scrapling aplica fingerprint TLS de navegador (curl_cffi),
    lendo a SERP sem cair em captcha e sem abrir um browser - é a fonte primária
    da busca web, com Brave API e Playwright como fallbacks.
    """
    queries = _web_queries()

    def _search(query):
        try:
            from scrapling.fetchers import Fetcher
            url = (WEB_SEARCH_URL + "?q=" + quote(query)
                   + "&setlang=pt-BR&cc=BR&count=20")
            resp = Fetcher.get(
                url,
                impersonate="chrome",
                timeout=REQUEST_TIMEOUT,
                headers={"Accept-Language": "pt-BR,pt;q=0.9"},
            )
            body = getattr(resp, "body", b"") or b""
            if isinstance(body, (bytes, bytearray)):
                html = body.decode("utf-8", "ignore")
            else:
                html = str(body)
            if not html:
                return []
            if _is_bot_page(html):
                logger.warning("Bing retornou bloqueio para '%s'", query)
                return []
            soup = BeautifulSoup(html, "html.parser")
            return _extract_event_blocks(soup)
        except Exception as e:
            logger.warning("Busca web falhou (%s): %s", query, e)
            return []

    events = []
    seen_urls = set()
    with ThreadPoolExecutor(max_workers=min(len(queries), 12)) as pool:
        futures = [pool.submit(_search, q) for q in queries]
        for fut in as_completed(futures):
            for item in fut.result() or []:
                if len(events) >= MAX_GOOGLE_EVENTS:
                    break
                if item["url"] in seen_urls:
                    continue
                seen_urls.add(item["url"])
                events.append(item)
    return events


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def _parse_iso_date(value):
    """Tenta extrair YYYY-MM-DD de um timestamp ISO (ex.: page_age da Brave)."""
    if not value:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(value))
    if m:
        try:
            date.fromisoformat(m.group(1))
            return m.group(1)
        except ValueError:
            return None
    return None


def _scrape_brave_events(api_key: str):
    """Busca web via Brave Search API (JSON estruturado, sem desafio de JS).

    Retorna resultados muito mais limpos e estáveis que o scraping de SERPs.
    Requer BRAVE_API_KEY. Usa só as queries genéricas/localizadas (as queries
    `site:sympla` são cobertas pelas fontes diretas), para economizar a cota
    gratuita (~2000 consultas/mês).
    """
    queries = [q for q in _web_queries() if "site:sympla" not in q]

    def _search(query):
        try:
            resp = requests.get(
                BRAVE_SEARCH_URL,
                params={
                    "q": query,
                    "country": "BR",
                    "search_lang": "pt-BR",
                    "count": "20",
                    "safesearch": "moderate",
                },
                headers={
                    "X-Subscription-Token": api_key,
                    "Accept": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.warning("Brave API status %s para '%s'", resp.status_code, query)
                return []
            data = resp.json() or {}
            results = []
            for item in (data.get("web") or {}).get("results") or []:
                try:
                    url = (item.get("url") or "").strip()
                    if not url.startswith("http"):
                        continue
                    if _is_blocked_domain(url):
                        continue
                    titulo = _clean_text(item.get("title", ""))
                    if not titulo or len(titulo) < 3:
                        continue
                    snippet = _clean_text(item.get("description", ""))
                    raw = f"{titulo} | {snippet}"
                    if not _is_automotive(raw):
                        continue
                    cidade, uf, local = _extract_city_uf(snippet) if snippet else ("", "", "")
                    inicio = _parse_iso_date(item.get("page_age") or item.get("age")) \
                        or _parse_br_dates(raw)[0]
                    # Evento de verdade tem data; plataformas de evento são isentas.
                    if not _is_event_domain(url) and inicio is None:
                        continue
                    results.append(_make_event(
                        titulo=titulo,
                        url=url,
                        data_inicio=inicio,
                        data_fim=None,
                        cidade=cidade,
                        uf=uf,
                        local=local,
                        descricao=snippet,
                        fonte="web",
                        fonte_nome="Brave Search",
                    ))
                except Exception:
                    continue
            return results
        except Exception as e:
            logger.warning("Brave falhou (%s): %s", query, e)
            return []

    events = []
    seen_urls = set()
    with ThreadPoolExecutor(max_workers=min(len(queries), 12)) as pool:
        futures = [pool.submit(_search, q) for q in queries]
        for fut in as_completed(futures):
            for item in fut.result() or []:
                if len(events) >= MAX_GOOGLE_EVENTS:
                    break
                if item["url"] in seen_urls:
                    continue
                seen_urls.add(item["url"])
                events.append(item)
    return events


def _scrape_web_playwright():
    """Fallback de busca web via navegador real (Playwright).

    Usado quando o Scrapling/Bing e a Brave API falham em retornar eventos. Um
    Chromium headless com User-Agent e locale pt-BR lê a SERP renderizada do Bing
    (com `li.b_algo`), contornando bloqueios que o HTTP puro não supera.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.info("[Events] Playwright indisponível - busca web via browser pulada.")
        return []

    queries = _web_queries()
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    events = []
    seen = set()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            ctx = browser.new_context(
                user_agent=ua, locale="pt-BR", viewport={"width": 1280, "height": 800}
            )
            for q in queries:
                try:
                    page = ctx.new_page()
                    page.goto(
                        WEB_SEARCH_URL + "?q=" + quote(q),
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    try:
                        page.wait_for_selector("li.b_algo", timeout=8000)
                    except Exception:
                        pass
                    html = page.content()
                    page.close()
                except Exception as e:
                    logger.warning("[Events] Playwright query falhou (%s): %s", q, e)
                    continue
                for item in _extract_event_blocks(BeautifulSoup(html, "html.parser")):
                    key = (item["titulo"].lower(), item["url"])
                    if key in seen:
                        continue
                    seen.add(key)
                    events.append(item)
                    if len(events) >= MAX_GOOGLE_EVENTS:
                        break
            ctx.close()
            browser.close()
    except Exception as e:
        logger.warning("[Events] Playwright indisponível: %s", e)
        return []
    return events[:MAX_GOOGLE_EVENTS]


def _scrape_web_events():
    """Canal de busca web: Scrapling/Bing (HTTP stealth) -> Brave API -> Playwright.

    O Scrapling lê a SERP do Bing com fingerprint TLS de navegador, sem captcha e
    sem abrir browser - é a fonte primária. A Brave Search API entra se BRAVE_API_KEY
    existir; o Playwright (Chromium headless) é o fallback final contra bloqueios.
    """
    events = _scrape_bing_events()
    if events:
        return events
    api_key = os.getenv("BRAVE_API_KEY")
    if api_key:
        events = _scrape_brave_events(api_key)
        if events:
            return events
        logger.warning("[Events] Brave Search vazio/indisponível - fallback Playwright.")
    return _scrape_web_playwright()


SERPAPI_EVENTS_URL = "https://serpapi.com/search"

# Queries automotivas nacionais para a busca web estruturada da SerpApi.
SERPAPI_EVENT_QUERIES = [
    "eventos automotivos Brasil",
    "encontro de carros Brasil",
    "feira de autopeças Brasil",
    "salão do automóvel Brasil",
    "feira de carros Brasil",
    "expo automotiva Brasil",
    "leilão de carros Brasil",
    "encontro de motos Brasil",
    "rally de carros Brasil",
    "encontro de carros antigos Brasil",
]

# Paginação: quantas páginas de 10 resultados buscar por query.
SERPAPI_MAX_PAGES = 3


def _parse_google_events_date(date_obj):
    """Converte o campo date do google_events em (data_inicio, data_fim).

    O formato retornado pode ser:
      {"start_date": "3 de jun.", "when": "ter, 3 de jun., 09:00–18:00 BRT"}
      {"start_date": "Jun 3"}
    Retorna (ISO start, ISO end) ou (None, None).
    """
    if not date_obj or not isinstance(date_obj, dict):
        return None, None

    start_str = (date_obj.get("start_date") or "").strip()
    when_str = (date_obj.get("when") or "").strip()

    start_date = None
    end_date = None

    # tenta parsear start_date via _parse_br_dates (funciona com "3 de jun." etc.)
    if start_str:
        s, _ = _parse_br_dates(start_str)
        start_date = s

    # tenta extrair end_date do "when" (ex.: "ter, 3 de jun., 09:00–18:00 BRT")
    if when_str:
        # procura por padrão de hora final (HH:MM) após um "–" ou "-"
        m = re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", when_str)
        # se tem data de início mas não achou intervalo de datas no "when",
        # tenta extrair end_date de "3 de jun. a 5 de jun." no when
        if not start_date:
            s2, e2 = _parse_br_dates(when_str)
            if s2:
                start_date = s2
                end_date = e2
        # se o "when" contém dois range de datas (ex.: "3 de jun. a 5 de jun.")
        m_range = re.search(r"(\d{1,2}\s*(?:de\s+)?\w+(?:\.)?\s*a\s*\d{1,2}\s*(?:de\s+)?\w+(?:\.)?\s*(?:de\s+)?\d{4})", when_str)
        if m_range:
            s3, e3 = _parse_br_dates(m_range.group(1))
            if s3:
                start_date = s3
                end_date = e3

    return start_date, end_date


def _parse_google_events_address(address_list):
    """Extrai (cidade, uf, local_detalhe) de address = ['The Venue, 123 St', 'City, ST'].

    O Google Events retorna address como lista de strings.
    """
    if not address_list or not isinstance(address_list, list):
        return "", "", ""
    # junta tudo em uma string e tenta extrair
    full = ", ".join(str(a) for a in address_list if a)
    return _extract_city_uf(full)


def _scrape_serpapi_events():
    """Busca eventos via SerpApi (engine=google_events).

    Engine dedicado do Google para eventos: retorna dados estruturados
    (título, datas, venue, endereço, ingressos, imagem) em vez de snippets.
    Filtra por Brasil via gl=br + queries localizadas. Requer SERPAPI_KEY.
    """
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        logger.info("[Events] SERPAPI_KEY ausente - fonte SerpApi pulada.")
        return []

    def _search(query):
        all_results = []
        for page in range(SERPAPI_MAX_PAGES):
            try:
                resp = requests.get(
                    SERPAPI_EVENTS_URL,
                    params={
                        "api_key": api_key,
                        "engine": "google_events",
                        "q": query,
                        "hl": "pt-br",
                        "gl": "br",
                        "start": page * 10,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code != 200:
                    logger.warning("SerpApi status %s para '%s'", resp.status_code, query)
                    return []
                data = resp.json() or {}
            except Exception as e:
                logger.warning("SerpApi falhou (%s): %s", query, e)
                return []

            events_page = data.get("events_results") or []
            if not events_page:
                break

            for item in events_page:
                try:
                    url = (item.get("link") or "").strip()
                    if not url.startswith("http"):
                        continue
                    if _is_blocked_domain(url):
                        continue

                    titulo = _clean_text(item.get("title", ""))
                    if not titulo or len(titulo) < 3:
                        continue

                    if not _is_automotive(titulo):
                        continue

                    # datas estruturadas do google_events
                    inicio, fim = _parse_google_events_date(item.get("date"))

                    # endereço estruturado
                    cidade, uf, local = _parse_google_events_address(
                        item.get("address")
                    )

                    # venue
                    venue = item.get("venue") or {}
                    venue_name = _clean_text(venue.get("name", ""))

                    # descrição
                    descricao = _clean_text(item.get("description", ""))

                    # imagem
                    image_url = (item.get("thumbnail") or item.get("image") or "").strip()

                    # evento de verdade tem data; plataformas são isentas
                    if not _is_event_domain(url) and inicio is None:
                        continue

                    all_results.append(_make_event(
                        titulo=titulo,
                        url=url,
                        data_inicio=inicio,
                        data_fim=fim,
                        cidade=cidade,
                        uf=uf,
                        local=local or venue_name,
                        descricao=descricao,
                        venue_name=venue_name,
                        image_url=image_url,
                        fonte="serpapi",
                        fonte_nome="SerpApi (Google Events)",
                    ))
                except Exception:
                    continue

            # se retornou menos de 10, não há mais páginas
            if len(events_page) < 10:
                break

        return all_results

    events = []
    seen = set()
    with ThreadPoolExecutor(max_workers=min(len(SERPAPI_EVENT_QUERIES), 8)) as pool:
        futures = [pool.submit(_search, q) for q in SERPAPI_EVENT_QUERIES]
        for fut in as_completed(futures):
            for item in fut.result() or []:
                key = item["url"] or item["titulo"].lower()
                if key in seen:
                    continue
                seen.add(key)
                events.append(item)
                if len(events) >= MAX_GOOGLE_EVENTS:
                    break
    return events


# ─────────────────────────── orquestrador / API ───────────────────────────

SOURCE_RUNNERS = [
    ("nfeas", "NFeiras.com", _scrape_nfeiras),
    ("sindirepa", "Sindirepa Brasil", _scrape_sindirepa),
    ("diretriz", "Diretriz Feiras", _scrape_diretriz),
    ("interlagos", "Shopping Interlagos", _scrape_interlagos),
    ("serpapi", "SerpApi (Google Events)", _scrape_serpapi_events),
    ("web", "Busca Web", _scrape_web_events),
]


def _event_similarity(a, b):
    """Score 0-100 de similaridade entre dois eventos (deduplicação por score)."""
    score = 0
    ta, tb = a.get("normalized_title") or "", b.get("normalized_title") or ""
    if ta and tb:
        ratio = difflib.SequenceMatcher(None, ta, tb).ratio()
        if ratio >= 0.85:
            score += 30
        elif ratio >= 0.6:
            score += 20
    sd_a, sd_b = a.get("data_inicio"), b.get("data_inicio")
    if sd_a and sd_b and sd_a == sd_b:
        score += 30
    ca, cb = (a.get("cidade") or "").lower(), (b.get("cidade") or "").lower()
    if ca and cb and ca == cb:
        score += 20
    va, vb = (a.get("venue_name") or "").lower(), (b.get("venue_name") or "").lower()
    if va and vb and va == vb:
        score += 20
    oa, ob = (a.get("organizer") or "").lower(), (b.get("organizer") or "").lower()
    if oa and ob and oa == ob:
        score += 15
    return score


def _dedupe_events(events, threshold=60):
    """Remove duplicados mantendo o registro de MAIOR confiança (canônico)."""
    accepted = []
    for ev in events:
        is_dup = False
        for kept in accepted:
            if _event_similarity(ev, kept) >= threshold:
                is_dup = True
                if (ev.get("confidence") or 0) > (kept.get("confidence") or 0):
                    kept.clear()
                    kept.update(ev)
                break
        if not is_dup:
            accepted.append(ev)
    return accepted


def _geocode_event(ev):
    """Preenche latitude/longitude se faltarem (reuso do cache Nominatim)."""
    if ev.get("latitude") is not None and ev.get("longitude") is not None:
        return
    city = ev.get("cidade")
    uf = ev.get("uf")
    if not city:
        return
    try:
        from utils.geocode import geocode_address
        query = f"{city}, {uf}, Brasil" if uf else f"{city}, Brasil"
        lat, lng = geocode_address(query)
        if lat is not None and lng is not None:
            ev["latitude"], ev["longitude"] = lat, lng
    except Exception as exc:
        logger.debug("geocode falhou para %s: %s", city, exc)


_EVENT_COLUMNS = [
    "id", "title", "original_title", "normalized_title", "description", "category",
    "categoria_label", "start_date", "end_date", "start_time", "end_time", "venue_name",
    "address", "city", "state", "country", "latitude", "longitude", "organizer",
    "organizer_url", "event_url", "image_url", "source", "source_url", "status",
    "confidence", "last_verified_at",
]

_EVENT_INSERT_SQL = (
    "INSERT INTO events (" + ", ".join(_EVENT_COLUMNS) + ") VALUES ("
    + ", ".join(["%s"] * len(_EVENT_COLUMNS)) + ")"
)

_EVENT_UPSERT_SQL_MYSQL = _EVENT_INSERT_SQL + " ON DUPLICATE KEY UPDATE " + ", ".join(
    f"{c}=VALUES({c})" for c in _EVENT_COLUMNS if c != "id"
)

_EVENT_UPSERT_SQL_PG = _EVENT_INSERT_SQL + " ON CONFLICT (id) DO UPDATE SET " + ", ".join(
    f"{c}=EXCLUDED.{c}" for c in _EVENT_COLUMNS if c != "id"
)


def _event_upsert_sql():
    """ON DUPLICATE (MySQL) ou ON CONFLICT (Postgres/Neon)."""
    try:
        from routes.database import is_postgres
        if is_postgres():
            return _EVENT_UPSERT_SQL_PG
    except Exception:
        pass
    return _EVENT_UPSERT_SQL_MYSQL


# Alias legado (MySQL); prefira _event_upsert_sql().
_EVENT_UPSERT_SQL = _EVENT_UPSERT_SQL_MYSQL


def _event_db_row(ev):
    """Mapeia o evento normalizado para a tupla de colunas do MySQL."""
    return {
        "id": ev["id"],
        "title": ev.get("titulo") or "",
        "original_title": ev.get("original_title") or ev.get("titulo") or "",
        "normalized_title": ev.get("normalized_title") or "",
        "description": ev.get("descricao"),
        "category": ev.get("categoria"),
        "categoria_label": ev.get("categoria_label") or ev.get("categoria") or "",
        "start_date": ev.get("data_inicio"),
        "end_date": ev.get("data_fim"),
        "start_time": ev.get("start_time"),
        "end_time": ev.get("end_time"),
        "venue_name": ev.get("venue_name") or None,
        "address": ev.get("address") or None,
        "city": ev.get("cidade") or None,
        "state": ev.get("uf") or None,
        "country": ev.get("country") or "BR",
        "latitude": ev.get("latitude"),
        "longitude": ev.get("longitude"),
        "organizer": ev.get("organizer") or None,
        "organizer_url": ev.get("organizer_url") or None,
        "event_url": ev.get("event_url") or ev.get("url") or None,
        "image_url": ev.get("image_url") or None,
        "source": ev.get("fonte"),
        "source_url": ev.get("source_url") or ev.get("url") or None,
        "status": ev.get("status") or "unknown",
        "confidence": ev.get("confidence") or 0.5,
        "last_verified_at": datetime.now(),
    }


def persist_events(events):
    """Upsert em lote dos eventos no MySQL. Retorna (inseridos, atualizados)."""
    if not events:
        return 0, 0
    from routes.database import get_db
    # nunca persiste eventos internacionais
    events = [e for e in events if (e.get("country") or "BR").upper() == "BR"
              and (e.get("uf") or "").upper() != "INT"]
    if not events:
        return 0, 0
    rows = [_event_db_row(ev) for ev in events]
    ids = [r["id"] for r in rows]
    inserted = updated = 0
    with get_db() as (cursor, conn):
        existing = set()
        if ids:
            placeholders = ", ".join(["%s"] * len(ids))
            cursor.execute(f"SELECT id FROM events WHERE id IN ({placeholders})", ids)
            existing = {row[0] for row in cursor.fetchall()}
        to_insert = [r for r in rows if r["id"] not in existing]
        to_update = [r for r in rows if r["id"] in existing]
        if to_insert:
            cursor.executemany(
                _EVENT_INSERT_SQL,
                [tuple(r[c] for c in _EVENT_COLUMNS) for r in to_insert],
            )
            inserted = len(to_insert)
        if to_update:
            cursor.executemany(
                _event_upsert_sql(),
                [tuple(r[c] for c in _EVENT_COLUMNS) for r in to_update],
            )
            updated = len(to_update)
        conn.commit()
    return inserted, updated


def scan_automotive_events(force=False):
    """Executa toda a varredura de eventos automotivos.

    Retorna dict {events, sources, scanned_at, cache_ttl_seconds}.
    Resultado é cacheado por 6 horas (forçar com force=True).
    """
    cache_key = "automotive_events:v1"
    if not force:
        cached = cache_get_json(cache_key)
        if cached is not None:
            print("[Events] Cache hit — retornando eventos em cache", flush=True)
            return cached

    print("[Events] Iniciando varredura de eventos automotivos...", flush=True)
    scanned_at = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()
    sources_stats = []
    all_events = []

    def _run_one(slug, name, runner):
        start = datetime.now(timezone.utc)
        logger.info("[Events] Iniciando varredura da fonte %s (%s)", slug, name)
        print(f"[Events] Iniciando varredura da fonte {slug} ({name})", flush=True)
        try:
            found = runner() or []
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            return (slug, name, True, None, found)
        except Exception as e:
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            return (slug, name, False, str(e)[:200], [])

    with ThreadPoolExecutor(max_workers=len(SOURCE_RUNNERS)) as pool:
        futures = [pool.submit(_run_one, *cfg) for cfg in SOURCE_RUNNERS]
        for fut in as_completed(futures):
            try:
                slug, name, ok, err, found = fut.result()
            except Exception as e:
                logger.error("Erro interno na varredura de %s: %s", slug, e)
                continue
            sources_stats.append({
                "slug": slug,
                "nome": name,
                "ok": ok,
                "error": err,
                "count": len(found),
            })
            for ev in found:
                if ev.get("passado"):
                    continue
                all_events.append(ev)

    # remove eventos internacionais — o AutoAssist cobre apenas o Brasil
    all_events = [e for e in all_events if (e.get("country") or "BR").upper() == "BR"
                  and (e.get("uf") or "").upper() != "INT"]

    # deduplicação por score (fontes indexam o mesmo evento com URLs diferentes)
    deduped = _dedupe_events(all_events)

    # geocodifica eventos sem coordenadas (reuso do cache do Nominatim)
    for ev in deduped:
        _geocode_event(ev)

    # persiste no MySQL (histórico/status; mantém passados + futuros)
    try:
        persist_events(deduped)
    except Exception as exc:
        pass

    def _sort_key(ev):
        return (0, ev["data_inicio"] or "9999") if ev["data_inicio"] else (1, ev["titulo"].lower())

    deduped.sort(key=_sort_key)
    for ev in deduped:
        ev["categoria_label"] = CATEGORIA_LABELS.get(ev["categoria"], ev["categoria"])
    payload = {
        "success": True,
        "count": len(deduped[:MAX_EVENTS]),
        "events": deduped[:MAX_EVENTS],
        "sources": sources_stats,
        "scanned_at": scanned_at,
        "cache_ttl_seconds": EVENTS_CACHE_TTL,
    }
    cache_set_json(cache_key, payload, ttl=EVENTS_CACHE_TTL)
    print(f"[Events] Varredura concluída: {len(deduped[:MAX_EVENTS])} evento(s) final(is)", flush=True)
    return payload


def filter_events(events, uf=None, q=None, categoria=None, periodo=None,
                  lat=None, lng=None, radius_km=None):
    """Aplica os filtros da busca de eventos (usado pela rota /api/events/automotive).

    - uf       : UF (BR, maiúscula)
    - q        : termo livre no título/descrição/cidade/local
    - categoria: feira | encontro | competicao | exposicao | congresso | outros
    - periodo  : "30" | "90" | "ano" | "todos" (padrão: "todos" → futuros já
                 filtrados na varredura)
    - lat/lng/radius_km: filtro geográfico "perto de mim" (raio em km, padrão 50)
    Resultado é ordenado por data e cortado no limite global.
    """
    result = list(events)

    # remove eventos internacionais (camada de segurança adicional)
    result = [e for e in result if (e.get("country") or "BR").upper() == "BR"
              and (e.get("uf") or "").upper() != "INT"]

    if uf:
        result = [e for e in result if (e.get("uf") or "").upper() == uf.upper()]

    if q:
        q = q.lower()
        result = [
            e for e in result
            if q in (e.get("titulo") or "").lower()
            or q in (e.get("descricao") or "").lower()
            or q in (e.get("cidade") or "").lower()
            or q in (e.get("local") or "").lower()
        ]

    if categoria:
        result = [e for e in result if (e.get("categoria") or "") == categoria]

    if periodo and periodo != "todos":
        today = date.today()
        if periodo == "ano":
            cutoff_start, cutoff_end = today, date(today.year, 12, 31)
        else:
            try:
                cutoff_end = today + timedelta(days=int(periodo))
            except (TypeError, ValueError):
                cutoff_end = None
            cutoff_start = today
        if cutoff_end:
            result = [
                e for e in result
                if not e.get("data_inicio")
                or cutoff_start <= date.fromisoformat(e["data_inicio"]) <= cutoff_end
            ]

    result.sort(key=lambda ev: (
        0, ev["data_inicio"] or "9999"
    ) if ev["data_inicio"] else (1, ev["titulo"].lower()))

    if lat is not None and lng is not None:
        try:
            lat_f, lng_f = float(lat), float(lng)
        except (TypeError, ValueError):
            lat_f = lng_f = None
        if lat_f is not None:
            radius = float(radius_km) if radius_km else 50.0
            nearby = []
            for ev in result:
                ela, elng = ev.get("latitude"), ev.get("longitude")
                if ela is None or elng is None:
                    continue
                if _haversine(lat_f, lng_f, ela, elng) <= radius:
                    nearby.append(ev)
            result = nearby

    return result[:MAX_EVENTS]