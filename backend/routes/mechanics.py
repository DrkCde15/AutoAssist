"""
Mecânicos API - Busca e gestão de mecânicos
Fontes: OpenStreetMap (Overpass API) + Web Scraping (Google)
"""
import logging
import math
import json
import re
import time
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from routes.database import get_db
from utils.cache import cache_get_json, cache_set_json
from services.web_scraping import search_mechanics_serpapi

mechanics_bp = Blueprint('mechanics', __name__)
logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371
OVERPASS_URLS = [
    "https://overpass.osm.ch/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
OVERPASS_TIMEOUT = 45
OVERPASS_TOTAL_BUDGET = 40  # segundos máximos gastos em tentativas contra os mirrors
OSM_MIN_ELEMENTS_BEFORE_STOP = 40  # para de consultar após esse volume de resultados
OSM_CACHE_TTL = 3600  # 1 hora (área realmente vazia)
OSM_FAILURE_CACHE_TTL = 60  # falha transitória: cache curto p/ não suprimir fontes por 5 min
PHOTON_REVERSE_URL = "https://photon.komoot.io/reverse"
REVGEO_CACHE_TTL = 30 * 86400  # 30 dias (endereços mudam pouco)
REVGEO_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")


def _sanitize_phone(value):
    """Normaliza telefone para dígitos (WhatsApp exige DDI+DDD+número)."""
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    if len(digits) == 10 or len(digits) == 11:
        digits = "55" + digits  # Brasil como padrão
    return digits if PHONE_RE.match("+" + digits) else ""


def calculate_distance(lat1, lng1, lat2, lng2):
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = math.sin(delta_lat / 2) ** 2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * \
        math.sin(delta_lng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def _build_overpass_queries(user_lat, user_lng, radius_m, osm_tags):
    """Gera uma query union por tipo de elemento (node, way) para minimizar chamadas à API.

    Enviar queries separadas por tag dispara rate-limiting do Overpass.
    Unir todas as tags em uma query por elemento reduz chamadas de 6 para 2,
    evitando o rate-limiting que retorna 0 elementos.
    """
    around = f"(around:{radius_m},{user_lat},{user_lng})"
    queries = []
    for elem in ("node", "way"):
        tag_clauses = ";".join(f'{elem}[{tag}]{around}' for tag in osm_tags)
        query = f'[out:json][timeout:60];({tag_clauses};);out center;'
        queries.append((elem, query))
    return queries


def _overpass_request(query, deadline):
    """Executa a query no primeiro mirror Overpass que responder com sucesso."""
    last_error = None
    for url in OVERPASS_URLS:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        timeout = max(5, min(OVERPASS_TIMEOUT, int(remaining)))
        try:
            resp = requests.post(
                url,
                data={'data': query},
                timeout=timeout,
                headers={
                    'Accept': 'application/json',
                    'User-Agent': 'AutoAssist/1.0 (vehicle maintenance assistant)'
                },
            )
            if resp.status_code == 200:
                return resp.json()
            last_error = f"HTTP {resp.status_code} de {url}"
            logger.warning("Overpass %s falhou: HTTP %s", url, resp.status_code)
        except Exception as e:
            last_error = f"{e} de {url}"
            logger.warning("Overpass %s falhou: %s", url, e)
        time.sleep(2)  # pequena pausa para aliviar rate-limit dos mirrors
    logger.error("Todos os mirrors Overpass falharam: %s", last_error)
    return None


def _reverse_geocode(lat, lng, osm_id):
    """Endereço aproximado via Photon (reverse geocoding), com cache por mecânico."""
    cache_key = f"revgeo:{osm_id}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return cached if cached else None
    try:
        resp = requests.get(
            PHOTON_REVERSE_URL,
            params={'lat': lat, 'lon': lng},
            headers={'User-Agent': REVGEO_BROWSER_UA},
            timeout=4,
        )
        resp.raise_for_status()
        props = resp.json().get('features', [{}])[0].get('properties', {})
        parts = []
        street = props.get('street') or props.get('name')
        if street:
            number = props.get('housenumber', '')
            parts.append(f"{street} {number}".strip())
        if props.get('postcode'):
            parts.append(props['postcode'])
        if not parts:
            return None
        result = {
            'endereco': ', '.join(parts),
            'cidade': props.get('city') or props.get('district') or '',
            'estado': props.get('state') or '',
        }
        cache_set_json(cache_key, result, ttl=REVGEO_CACHE_TTL)
        return result
    except Exception as e:
        cache_set_json(cache_key, {}, ttl=REVGEO_CACHE_TTL)
        return None


def enrich_missing_addresses(mechanics, max_items=10, time_budget=8):
    """Preenche endereco/cidade/estado de mecânicos OSM sem endereço.

    Usa reverse geocoding (Photon) com cache de 30 dias por mecânico.
    Respeita um teto de requisições e de tempo para não travar a resposta.
    """
    start = time.time()
    enriched = 0
    for m in mechanics:
        if enriched >= max_items or (time.time() - start) > time_budget:
            break
        sid = str(m.get('id', ''))
        if not sid.startswith('osm_'):
            continue
        if m.get('endereco'):
            continue
        lat, lng = m.get('latitude'), m.get('longitude')
        if lat is None or lng is None:
            continue
        addr = _reverse_geocode(lat, lng, sid)
        if addr:
            m['endereco'] = addr['endereco']
            if addr.get('cidade'):
                m['cidade'] = addr['cidade']
            if addr.get('estado'):
                m['estado'] = addr['estado']
            enriched += 1
    return mechanics


def search_osm(user_lat, user_lng, radius, service_type=None):
    """Busca oficinas mecânicas via Overpass API (OpenStreetMap). Retorna GeoJSON Features."""
    cache_key = f"osm_mechanics:{user_lat:.4f}:{user_lng:.4f}:{radius}:{service_type or ''}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return cached

    osm_tags = ['"shop"="car_repair"', '"craft"="auto_mechanic"']
    if service_type and service_type in ('eletrica',):
        osm_tags.append('"craft"="auto_electrician"')

    radius_m = int(radius * 1000)

    try:
        logger.debug("Overpass: %d queries x %d mirrors", 2, len(OVERPASS_URLS))
        deadline = time.time() + OVERPASS_TOTAL_BUDGET
        elements = []
        seen_qids = set()
        got_success = False
        for elem, query in _build_overpass_queries(user_lat, user_lng, radius_m, osm_tags):
            if time.time() > deadline:
                break
            # Já temos o suficiente para responder; evita requests extras (rate-limit)
            if len(elements) >= OSM_MIN_ELEMENTS_BEFORE_STOP:
                logger.debug("Encerrando buscas Overpass cedo (%d elementos)", len(elements))
                break
            raw = _overpass_request(query, deadline)
            if not isinstance(raw, dict):
                continue
            got_success = True
            for el in raw.get('elements', []):
                qid = f"{elem}_{el.get('id')}"
                if qid in seen_qids:
                    continue
                seen_qids.add(qid)
                elements.append(el)

        if not elements:
            # Distinguir "área realmente vazia" (resposta OK, 0 elementos) de
            # "todos os mirrors falharam" (transitório): só a 2ª deve ser cacheada
            # por muito tempo, para não suprimir a fonte por minutos após um erro.
            if got_success:
                cache_set_json(cache_key, [], ttl=OSM_CACHE_TTL)
            else:
                cache_set_json(cache_key, [], ttl=OSM_FAILURE_CACHE_TTL)
            return []

        features = _elements_to_geojson(elements)
    except Exception as e:
        logger.error(f"Erro Overpass API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error("Overpass response body: %s", e.response.text[:500])
        return []
    results = []
    seen = set()

    for feature in features:
        props = feature.get('properties', {}) or {}
        geom = feature.get('geometry', {})
        if geom.get('type') != 'Point':
            coords = _extract_center(geom)
            if coords:
                geom = {"type": "Point", "coordinates": coords}
            else:
                continue
        lng, lat = geom['coordinates']

        nome = (props.get('name') or '').strip()
        if not nome:
            nome = 'Oficina Mecânica'

        # Endereço: suporta variantes comuns do OSM brasileiro (addr:full, addr:place)
        endereco_parts = []
        if props.get('addr:full'):
            endereco_parts.append(props['addr:full'])
        elif props.get('addr:street'):
            number = props.get('addr:housenumber', '')
            endereco_parts.append(f"{props['addr:street']} {number}".strip())
        elif props.get('addr:place'):
            number = props.get('addr:housenumber', '')
            endereco_parts.append(f"{props['addr:place']} {number}".strip())
        if props.get('addr:city') or props.get('addr:district'):
            endereco_parts.append(props.get('addr:city') or props.get('addr:district'))
        if props.get('addr:postcode'):
            endereco_parts.append(props['addr:postcode'])
        endereco = ', '.join(endereco_parts) if endereco_parts else props.get('display_name', '')

        cidade = props.get('addr:city') or props.get('is_in:city', '')
        estado = props.get('addr:state') or props.get('is_in:state', '')
        telefone = (props.get('phone')
                    or props.get('contact:phone')
                    or props.get('contact:mobile')
                    or props.get('phone:mobile')
                    or props.get('tel')
                    or '')
        website = (props.get('website')
                   or props.get('contact:website')
                   or props.get('contact:url')
                   or props.get('url')
                   or '')
        email = props.get('contact:email') or props.get('email') or ''

        descricao_parts = []
        if props.get('description'):
            descricao_parts.append(props['description'])
        if props.get('opening_hours'):
            descricao_parts.append(f"Horários: {props['opening_hours']}")
        descricao = '. '.join(descricao_parts)

        especialidades = _derive_specialties(props)

        horarios = None
        if props.get('opening_hours'):
            try:
                horarios = parse_opening_hours(props['opening_hours'])
            except Exception:
                pass

        osm_id = feature.get('id', 0)
        uid = f"osm_{osm_id}"
        if uid in seen:
            continue
        seen.add(uid)

        distance = round(calculate_distance(user_lat, user_lng, lat, lng), 1)
        if distance > radius:
            continue

        results.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "id": uid,
            "nome": nome,
            "endereco": endereco,
            "cidade": cidade,
            "estado": estado,
            "latitude": lat,
            "longitude": lng,
            "telefone": telefone,
            "website": website,
            "email": email,
            "descricao": descricao,
            "especialidades": sorted(especialidades) or ['troca_oleo'],
            "servicos": [],
            "horario_funcionamento": horarios,
            "avaliacao_media": None,
            "total_avaliacoes": 0,
            "foto_url": None,
            "is_verified": False,
            "distance_km": distance,
            "_source": "osm"
        })

    results.sort(key=lambda m: m['distance_km'])
    enrich_missing_addresses(results, max_items=10, time_budget=8)
    cache_set_json(cache_key, results, ttl=OSM_CACHE_TTL)
    return results


def _elements_to_geojson(elements):
    """Converte elements[] do Overpass para lista de Features GeoJSON (Point)."""
    features = []
    for el in elements:
        lat = el.get('lat')
        lng = el.get('lon')
        if lat is None or lng is None:
            center = el.get('center')
            if center:
                lat = center.get('lat')
                lng = center.get('lon')
        if lat is None or lng is None:
            continue
        tags = el.get('tags', {}) or {}
        feat = {
            "type": "Feature",
            "id": el.get('id'),
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": tags
        }
        features.append(feat)
    return features


def _extract_center(geom):
    """Extrai centro aproximado de geometria não-Point."""
    try:
        if geom['type'] == 'Polygon':
            coords = geom['coordinates'][0]
            lats = [c[1] for c in coords]
            lngs = [c[0] for c in coords]
            return [sum(lngs) / len(lngs), sum(lats) / len(lats)]
        if geom['type'] == 'LineString':
            coords = geom['coordinates']
            lats = [c[1] for c in coords]
            lngs = [c[0] for c in coords]
            return [sum(lngs) / len(lngs), sum(lats) / len(lats)]
    except Exception:
        pass
    return None


def _derive_specialties(tags):
    """Deriva especialidades das tags OSM."""
    especialidades = set()
    tag_map = {
        'shop': {'car_repair': 'troca_oleo'},
        'craft': {'auto_mechanic': 'motor', 'auto_electrician': 'eletrica'},
        'service': {'dealer': 'suspensao'},
    }
    for key, val_map in tag_map.items():
        val = tags.get(key)
        if val in val_map:
            especialidades.add(val_map[val])
    return sorted(especialidades)


def parse_opening_hours(oh_string):
    """Converte string de horário OSM para formato do app (dias da semana)."""
    day_map = {
        'mo': 'seg', 'tu': 'ter', 'we': 'qua',
        'th': 'qui', 'fr': 'sex', 'sa': 'sab', 'su': 'dom'
    }
    result = {}

    # Padrão simples: "Mo-Fr 08:00-18:00; Sa 09:00-13:00"
    parts = re.split(r';\s*', oh_string)
    for part in parts:
        part = part.strip()
        match = re.match(
            r'([A-Za-z]{2})(?:-([A-Za-z]{2}))?\s+([0-9]{2}:[0-9]{2})-([0-9]{2}:[0-9]{2})',
            part
        )
        if match:
            start_day = match.group(1).lower()
            end_day = match.group(2)
            open_time = match.group(3)
            close_time = match.group(4)

            days = list(day_map.keys())
            if start_day in day_map:
                if end_day:
                    end_day = end_day.lower()
                    if end_day in day_map:
                        start_idx = days.index(start_day)
                        end_idx = days.index(end_day)
                        for i in range(start_idx, end_idx + 1):
                            result[day_map[days[i]]] = f"{open_time}-{close_time}"
                else:
                    result[day_map[start_day]] = f"{open_time}-{close_time}"

    # Preenche dias não definidos como fechado
    for d in ['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom']:
        if d not in result:
            result[d] = 'fechado'

    return result


@mechanics_bp.route('/api/mechanics/search', methods=['GET'])
def search_mechanics():
    """
    Busca mecânicos próximos.
    Fontes: MySQL (mecânicos salvos) + OpenStreetMap + Web Scraping
    """
    try:
        user_lat = request.args.get('lat', type=float)
        user_lng = request.args.get('lng', type=float)

        if user_lat is None or user_lng is None:
            return jsonify(error="Coordenadas lat e lng são obrigatórias"), 400

        radius = request.args.get('radius', default=10, type=float)
        service_type = request.args.get('service_type', default=None)
        min_rating = request.args.get('min_rating', default=0, type=float)
        sort_by = request.args.get('sort_by', default='distance')
        limit = request.args.get('limit', default=20, type=int)

        mechanics = []

        # 1. MySQL - mecânicos já salvos (favoritados, cadastrados)
        db_count = 0
        try:
            with get_db() as (cursor, conn):
                cursor.execute("""
                    SELECT id, nome, endereco, cidade, estado, cep,
                           latitude, longitude, telefone, email, website,
                           descricao, especialidades, servicos,
                           horario_funcionamento, avaliacao_media,
                           total_avaliacoes, foto_url, is_verified,
                           (
                               %s * ACOS(
                                   COS(RADIANS(%s)) * COS(RADIANS(latitude)) *
                                   COS(RADIANS(longitude) - RADIANS(%s)) +
                                   SIN(RADIANS(%s)) * SIN(RADIANS(latitude))
                               )
                           ) AS distance_km
                    FROM mechanics
                    WHERE is_active = TRUE
                      AND latitude IS NOT NULL
                      AND longitude IS NOT NULL
                    HAVING distance_km <= %s
                    ORDER BY distance_km ASC
                    LIMIT %s
                """, (EARTH_RADIUS_KM, user_lat, user_lng, user_lat, radius, limit))

                for m in cursor.fetchall():
                    if m.get('especialidades'):
                        m['especialidades'] = json.loads(m['especialidades'])
                    if m.get('servicos'):
                        m['servicos'] = json.loads(m['servicos'])
                    if m.get('horario_funcionamento'):
                        m['horario_funcionamento'] = json.loads(m['horario_funcionamento'])
                    m['distance_km'] = round(m['distance_km'], 1)
                    m['_source'] = 'db'
                    m['geometry'] = {
                        "type": "Point",
                        "coordinates": [float(m['longitude']), float(m['latitude'])]
                    }
                    mechanics.append(m)
        except Exception as e:
            logger.error(f"Erro na busca MySQL: {e}")

        db_count = len(mechanics)
        existing_ids = {m.get('id') for m in mechanics}

        # 2. OpenStreetMap (Overpass API)
        if len(mechanics) < limit:
            try:
                osm_results = search_osm(user_lat, user_lng, radius, service_type)
                for osm_m in osm_results:
                    if osm_m['id'] not in existing_ids:
                        mechanics.append(osm_m)
                        existing_ids.add(osm_m['id'])
                        if len(mechanics) >= limit:
                            break
            except Exception as e:
                logger.error(f"Erro na busca OSM: {e}")

        osm_count = len(mechanics) - db_count

        # 3. SerpApi (Google Maps) — fonte confiável em produção (datacenter).
        # Substitui o antigo scraping do Google, que gerava coordenadas falsas
        # e falhava em IPs de servidor.
        if len(mechanics) < limit:
            try:
                serp_results = search_mechanics_serpapi(user_lat, user_lng, radius, service_type)
                for serp_m in serp_results:
                    if serp_m['id'] not in existing_ids:
                        mechanics.append(serp_m)
                        existing_ids.add(serp_m['id'])
                        if len(mechanics) >= limit:
                            break
            except Exception as e:
                logger.error(f"Erro na busca SerpApi: {e}")

        serpapi_count = len(mechanics) - db_count - osm_count

        # Filtro por avaliação mínima
        if min_rating > 0:
            mechanics = [m for m in mechanics if (m.get('avaliacao_media') or 0) >= min_rating]

        # Ordenação final
        if sort_by == 'rating':
            mechanics.sort(key=lambda m: (m.get('avaliacao_media') or 0, -m['distance_km']), reverse=True)
        elif sort_by == 'name':
            mechanics.sort(key=lambda m: (m.get('nome', '').lower(), m['distance_km']))
        else:
            mechanics.sort(key=lambda m: m['distance_km'])

        mechanics = mechanics[:limit]

        for m in mechanics:
            if m.get('id'):
                cache_set_json(f"mech:{m['id']}", m, ttl=OSM_CACHE_TTL)

        return jsonify({
            "success": True,
            "count": len(mechanics),
            "counts": {"db": db_count, "osm": osm_count, "serpapi": serpapi_count},
            "mechanics": mechanics
        }), 200

    except Exception as e:
        logger.error(f"Erro na busca de mecânicos: {e}")
        return jsonify(error="Erro interno na busca"), 500


@mechanics_bp.route('/api/mechanics/<mechanic_id>', methods=['GET'])
def get_mechanic_profile(mechanic_id):
    """
    Retorna perfil completo de um mecânico.
    Suporta IDs do MySQL (int), OSM ("osm_...") e Web ("web_...").
    """
    try:
        sid = str(mechanic_id)
        if sid.startswith('osm_') or sid.startswith('web_') or sid.startswith('serpapi_'):
            cached = cache_get_json(f"mech:{sid}")
            if cached:
                return jsonify({"success": True, "mechanic": cached}), 200
            return jsonify({
                "success": True,
                "mechanic": {
                    "id": mechanic_id,
                    "nome": "",
                    "endereco": "",
                    "avaliacao_media": None,
                    "total_avaliacoes": 0,
                    "reviews": [],
                    "servicos": [],
                    "horario_funcionamento": None,
                    "_source": "serpapi" if sid.startswith('serpapi_') else "osm" if sid.startswith('osm_') else "web"
                }
            }), 200

        # ID do MySQL
        mechanic_id = int(mechanic_id)

        with get_db() as (cursor, conn):
            cursor.execute("""
                SELECT * FROM mechanics
                WHERE id = %s AND is_active = TRUE
            """, (mechanic_id,))

            mechanic = cursor.fetchone()

            if not mechanic:
                return jsonify(error="Mecânico não encontrado"), 404

            if mechanic.get('especialidades'):
                mechanic['especialidades'] = json.loads(mechanic['especialidades'])
            if mechanic.get('servicos'):
                mechanic['servicos'] = json.loads(mechanic['servicos'])
            if mechanic.get('horario_funcionamento'):
                mechanic['horario_funcionamento'] = json.loads(mechanic['horario_funcionamento'])

            cursor.execute("""
                SELECT r.*, u.nome as user_nome, u.profile_pic
                FROM mechanic_reviews r
                LEFT JOIN users u ON u.id = r.user_id
                WHERE r.mechanic_id = %s
                ORDER BY r.created_at DESC
                LIMIT 10
            """, (mechanic_id,))
            mechanic['reviews'] = cursor.fetchall()

            return jsonify({
                "success": True,
                "mechanic": mechanic
            }), 200

    except Exception as e:
        logger.error(f"Erro ao buscar perfil do mecânico: {e}")
        return jsonify(error="Erro interno"), 500


@mechanics_bp.route('/api/mechanics/<int:mechanic_id>/reviews', methods=['POST'])
@jwt_required()
def add_mechanic_review(mechanic_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        avaliacao = data.get('avaliacao')
        comentario = data.get('comentario', '')
        service_type = data.get('service_type', '')

        if not avaliacao or avaliacao < 1 or avaliacao > 5:
            return jsonify(error="Avaliação deve ser entre 1 e 5"), 400

        with get_db() as (cursor, conn):
            cursor.execute("SELECT id FROM mechanics WHERE id = %s", (mechanic_id,))
            if not cursor.fetchone():
                return jsonify(error="Mecânico não encontrado"), 404

            cursor.execute("""
                INSERT INTO mechanic_reviews
                (mechanic_id, user_id, avaliacao, comentario, service_type)
                VALUES (%s, %s, %s, %s, %s)
            """, (mechanic_id, user_id, avaliacao, comentario, service_type))

            cursor.execute("""
                UPDATE mechanics
                SET avaliacao_media = (
                    SELECT AVG(avaliacao) FROM mechanic_reviews
                    WHERE mechanic_id = %s
                ),
                total_avaliacoes = (
                    SELECT COUNT(*) FROM mechanic_reviews
                    WHERE mechanic_id = %s
                )
                WHERE id = %s
            """, (mechanic_id, mechanic_id, mechanic_id))

            return jsonify({
                "success": True,
                "message": "Avaliação adicionada com sucesso"
            }), 201

    except Exception as e:
        logger.error(f"Erro ao adicionar avaliação: {e}")
        return jsonify(error="Erro interno"), 500


@mechanics_bp.route('/api/mechanics', methods=['POST'])
@jwt_required()
def create_mechanic():
    """
    Cadastro público de oficina/mecânico (dono da oficina).
    O registro fica ativo e verificável depois por um admin.
    """
    try:
        data = request.get_json(silent=True) or {}
        nome = (data.get('nome') or '').strip()
        cidade = (data.get('cidade') or '').strip()[:50]
        estado = (data.get('estado') or '').strip().upper()[:2]
        telefone_raw = data.get('telefone') or data.get('whatsapp') or ''
        endereco = (data.get('endereco') or '').strip()
        lat = data.get('latitude')
        lng = data.get('longitude')

        if not nome:
            return jsonify(error="Informe o nome da oficina."), 400
        if not endereco:
            return jsonify(error="Informe o endereço da oficina."), 400

        try:
            lat = float(lat) if lat not in (None, "") else None
            lng = float(lng) if lng not in (None, "") else None
        except (TypeError, ValueError):
            return jsonify(error="Coordenadas inválidas."), 400
        if lat is None or lng is None:
            return jsonify(error="Informe a localização da oficina no mapa."), 400
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return jsonify(error="Coordenadas fora do intervalo válido."), 400

        telefone = _sanitize_phone(telefone_raw)

        payload = {
            'nome': nome,
            'endereco': endereco[:512],
            'cidade': cidade,
            'estado': estado,
            'latitude': lat,
            'longitude': lng,
            'telefone': telefone,
            'website': (data.get('website') or '').strip()[:200],
            'descricao': (data.get('descricao') or '').strip()[:1000],
            'especialidades': [s.strip() for s in (data.get('especialidades') or []) if str(s).strip()][:10],
        }

        mechanic_id = upsert_mechanic(payload)
        if not mechanic_id:
            return jsonify(error="Não foi possível cadastrar a oficina."), 500

        return jsonify({
            "success": True,
            "message": "Oficina cadastrada com sucesso!",
            "mechanic_id": mechanic_id,
            "telefone_whatsapp": telefone,
        }), 201

    except Exception as e:
        logger.error(f"Erro ao cadastrar oficina: {e}")
        return jsonify(error="Erro interno ao cadastrar oficina."), 500


def upsert_mechanic(data):
    """Insere ou atualiza um mecânico no MySQL.

    Usa nome + latitude + longitude como chave de unicidade.
    Retorna o id do mecânico no MySQL.
    """
    nome = (data.get('nome') or '').strip()
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    if not nome or latitude is None or longitude is None:
        return None

    with get_db() as (cursor, conn):
        cursor.execute(
            "SELECT id FROM mechanics WHERE nome = %s AND latitude = %s AND longitude = %s",
            (nome, latitude, longitude)
        )
        existing = cursor.fetchone()
        if existing:
            mechanic_id = existing['id']
            cursor.execute("""
                UPDATE mechanics SET
                    endereco = COALESCE(%s, endereco),
                    cidade = COALESCE(%s, cidade),
                    estado = COALESCE(%s, estado),
                    telefone = COALESCE(%s, telefone),
                    website = COALESCE(%s, website),
                    descricao = COALESCE(%s, descricao)
                WHERE id = %s
            """, (
                data.get('endereco'), data.get('cidade'), data.get('estado'),
                data.get('telefone'), data.get('website'), data.get('descricao'),
                mechanic_id
            ))
        else:
            cursor.execute("""
                INSERT INTO mechanics
                    (nome, endereco, cidade, estado, latitude, longitude, telefone,
                     website, descricao, especialidades, is_active, is_verified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, FALSE)
            """, (
                nome, data.get('endereco', ''), data.get('cidade', ''),
                data.get('estado', ''), latitude, longitude,
                data.get('telefone', ''), data.get('website', ''),
                data.get('descricao', ''),
                json.dumps(data.get('especialidades', ['troca_oleo']))
            ))
            mechanic_id = cursor.lastrowid
        return mechanic_id


@mechanics_bp.route('/api/mechanics/<mechanic_id>/favorite', methods=['POST', 'DELETE'])
@jwt_required()
def toggle_favorite(mechanic_id):
    try:
        user_id = get_jwt_identity()
        is_external = not mechanic_id.isdigit()

        if is_external and request.method == 'POST':
            data = request.get_json() or {}
            data['latitude'] = data.get('latitude') or data.get('lat')
            data['longitude'] = data.get('longitude') or data.get('lng')
            new_id = upsert_mechanic(data)
            if not new_id:
                return jsonify(error="Dados insuficientes para salvar mecânico"), 400
            mechanic_id = str(new_id)

        if not mechanic_id.isdigit():
            return jsonify(error="ID inválido. Favoritos só podem ser gerenciados para mecânicos salvos no banco."), 400

        mid = int(mechanic_id)
        with get_db() as (cursor, conn):
            if request.method == 'POST':
                cursor.execute("""
                    INSERT IGNORE INTO mechanic_favorites (user_id, mechanic_id)
                    VALUES (%s, %s)
                """, (user_id, mid))
                return jsonify({
                    "success": True,
                    "message": "Mecânico favoritado",
                    "mechanic_id": mid
                }), 200
            else:
                cursor.execute("""
                    DELETE FROM mechanic_favorites
                    WHERE user_id = %s AND mechanic_id = %s
                """, (user_id, mid))
                return jsonify({"success": True, "message": "Mecânico removido dos favoritos"}), 200

    except Exception as e:
        logger.error(f"Erro ao gerenciar favorito: {e}")
        return jsonify(error="Erro interno"), 500


@mechanics_bp.route('/api/mechanics/favorites', methods=['GET'])
@jwt_required()
def get_favorites():
    try:
        user_id = get_jwt_identity()

        with get_db() as (cursor, conn):
            cursor.execute("""
                SELECT m.* FROM mechanics m
                INNER JOIN mechanic_favorites f ON f.mechanic_id = m.id
                WHERE f.user_id = %s AND m.is_active = TRUE
                ORDER BY f.created_at DESC
            """, (user_id,))

            favorites = cursor.fetchall()

            for mechanic in favorites:
                if mechanic.get('especialidades'):
                    mechanic['especialidades'] = json.loads(mechanic['especialidades'])

            return jsonify({
                "success": True,
                "favorites": favorites
            }), 200

    except Exception as e:
        logger.error(f"Erro ao buscar favoritos: {e}")
        return jsonify(error="Erro interno"), 500
