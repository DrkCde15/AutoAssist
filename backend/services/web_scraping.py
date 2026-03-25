# backend/services/web_scrapping.py
import requests
from bs4 import BeautifulSoup

class WebScraper:
    def __init__(self, url: str = None):
        self.url = url
        self.soup = None

    def fetch_content(self):
        """Faz a requisição HTTP e inicializa o objeto BeautifulSoup"""
        if not self.url:
            raise ValueError("URL não definida.")
        response = requests.get(self.url)
        response.raise_for_status()  # lança erro se status != 200
        self.soup = BeautifulSoup(response.text, "html.parser")

    def get_headings(self, tag: str = "h2"):
        """Extrai todos os textos de um determinado tipo de tag"""
        if not self.soup:
            raise ValueError("O conteúdo ainda não foi carregado. Use fetch_content() primeiro.")
        return [item.get_text(strip=True) for item in self.soup.select(tag)]

    def search_car_stores(self, query: str):
        """Constrói links diretos para as principais lojas de veículos do Brasil com base na busca"""
        q_encoded = requests.utils.quote(query)
        q_plus = query.replace(' ', '+')
        q_dash = query.replace(' ', '-')
        
        results = [
            {'url': f"https://www.webmotors.com.br/carros/estoque?busca={q_plus}"},
            {'url': f"https://www.icarros.com.br/ache/listaanuncios.jsp?busca={q_encoded}"},
            {'url': f"https://lista.mercadolivre.com.br/veiculos/{q_dash}"},
            {'url': f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q={q_plus}"},
            {'url': f"https://www.google.com.br/search?q=concessionaria+oficial+{q_plus}&gl=br&hl=pt-BR"}
        ]
        return results

    def search_car_parts(self, query: str):
        """Constrói links diretos para compra de peças e acessórios automotivos"""
        q_plus = query.replace(' ', '+')
        q_dash = query.replace(' ', '-')
        
        results = [
            {'url': f"https://lista.mercadolivre.com.br/acessorios-veiculos/{q_dash}"},
            {'url': f"https://www.canaldapeca.com.br/busca?q={q_plus}"},
            {'url': f"https://www.google.com.br/search?tbm=shop&q={q_plus}"},
            {'url': f"https://www.olx.com.br/autos-e-pecas/pecas-e-acessorios?q={q_plus}"}
        ]
        return results