import logging
from youtubesearchpython import VideosSearch

logger = logging.getLogger(__name__)

def buscar_videos_youtube(termo, limite=3):
    """
    Busca vídeos no YouTube com base em um termo de pesquisa e retorna
    uma lista de dicionários contendo titulo, url e thumbnail.
    """
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
        return videos
    
    except Exception as e:
        logger.error(f"❌ Erro ao buscar vídeos no YouTube para o termo '{termo}': {e}")
        return []
