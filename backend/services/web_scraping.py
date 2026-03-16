# backend/services/web_scrapping.py

import requests
from bs4 import BeautifulSoup

class WebScraper:
    def __init__(self, url: str):
        self.url = url
        self.soup = None

    def fetch_content(self):
        """Faz a requisição HTTP e inicializa o objeto BeautifulSoup"""
        response = requests.get(self.url)
        response.raise_for_status()  # lança erro se status != 200
        self.soup = BeautifulSoup(response.text, "html.parser")

    def get_headings(self, tag: str = "h2"):
        """Extrai todos os textos de um determinado tipo de tag"""
        if not self.soup:
            raise ValueError("O conteúdo ainda não foi carregado. Use fetch_content() primeiro.")
        return [item.get_text(strip=True) for item in self.soup.select(tag)]

if __name__ == "__main__":
    url = "https://example.com"
    scraper = WebScraper(url)
    scraper.fetch_content()
    headings = scraper.get_headings("h2")

    for h in headings:
        print(h)
