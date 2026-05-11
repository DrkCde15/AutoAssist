import logging
import os
import time
from youtubesearchpython import VideosSearch
import httpx

# Monkey Patch para corrigir a biblioteca youtube-search-python
original_post = httpx.post
def patched_post(*args, **kwargs):
    if 'proxies' in kwargs:
        proxies = kwargs.pop('proxies')
        if proxies and 'proxy' not in kwargs:
            kwargs['proxy'] = proxies.get('http') or proxies.get('https') if isinstance(proxies, dict) else proxies
    return original_post(*args, **kwargs)
httpx.post = patched_post

logger = logging.getLogger(__name__)

YOUTUBE_CACHE_TTL_SECONDS = max(30, int(os.getenv("YOUTUBE_CACHE_TTL_SECONDS", "900")))
YOUTUBE_CACHE_MAX_ITEMS = max(16, int(os.getenv("YOUTUBE_CACHE_MAX_ITEMS", "128")))
_youtube_cache = {}


def _clone_videos(videos):
    return [dict(video) for video in videos]

def buscar_videos_youtube(termo, limite=3):
    """
    Busca vídeos no YouTube com base em um termo de pesquisa e retorna
    uma lista de dicionários contendo titulo, url e thumbnail.
    """
    termo = str(termo or "").strip()
    try:
        limite = max(1, min(int(limite), 5))
    except (TypeError, ValueError):
        limite = 3
    if not termo:
        return []

    cache_key = (termo.lower(), limite)
    now = time.monotonic()
    cached = _youtube_cache.get(cache_key)
    if cached and cached["expires_at"] > now:
        return _clone_videos(cached["videos"])

    try:
        videosSearch = VideosSearch(termo, limit=limite)
        resultados = videosSearch.result()
        
        videos = []
        if resultados and 'result' in resultados:
            for v in resultados['result']:
                # Selecionar a melhor thumbnail disponível (frequentemente a última é a de maior resolução, mas a primeira funciona bem)
                thumbs = v.get('thumbnails', [])
                thumbnail_url = thumbs[0]['url'] if thumbs else None
                
                videos.append({
                    'titulo': v.get('title'),
                    'url': v.get('link'),
                    'thumbnail': thumbnail_url,
                    'canal': v.get('channel', {}).get('name')
                })
        
        logger.info(f"YOUTUBE SEARCH: Encontrados {len(videos)} vídeos para '{termo}'")
        if len(_youtube_cache) >= YOUTUBE_CACHE_MAX_ITEMS:
            oldest_key = min(_youtube_cache, key=lambda key: _youtube_cache[key]["expires_at"])
            _youtube_cache.pop(oldest_key, None)
        _youtube_cache[cache_key] = {
            "expires_at": now + YOUTUBE_CACHE_TTL_SECONDS,
            "videos": _clone_videos(videos),
        }
        return videos
    
    except Exception as e:
        logger.error(f"❌ Erro ao buscar vídeos no YouTube para o termo '{termo}': {e}")
        return []
