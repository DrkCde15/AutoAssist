from fpdf import FPDF
from datetime import datetime

class AutoAssistReport(FPDF):
    def header(self):
        # Logo placeholder (pode ser texto estilizado se não tiver imagem)
        self.set_font('Arial', 'B', 15)
        self.set_text_color(59, 130, 246) # Blue-500
        self.cell(0, 10, 'AutoAssist IA - Relatório Técnico', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def criar_relatorio_pdf(usuario, dados_analise, nome_arquivo_saida):
    """
    Gera um PDF com a análise do veículo.
    :param usuario: Dict com dados do user (nome, email)
    :param dados_analise: Dict ou Texto com o conteúdo da análise
    :param nome_arquivo_saida: Caminho absoluto para salvar
    """
    pdf = AutoAssistReport()
    pdf.add_page()
    
    # 1. Informações do Cliente
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(0)
    pdf.cell(0, 10, 'Dados do Solicitante:', 0, 1)
    pdf.set_font('Arial', '', 11)
    pdf.cell(0, 7, f"Nome: {usuario.get('nome')}", 0, 1)
    pdf.cell(0, 7, f"Email: {usuario.get('email')}", 0, 1)
    pdf.cell(0, 7, f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}", 0, 1)
    pdf.ln(5)
    
    # 2. Análise Técnica (Conteúdo do Chat)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, 'Laudo Técnico (IA):', 0, 1)
    pdf.ln(2)
    
    pdf.set_font('Arial', '', 11)
    # Limpa caracteres incompatíveis (emoji básico)
    texto_limpo = dados_analise.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 7, texto_limpo)
    
    # 3. Aviso Legal
    pdf.ln(10)
    pdf.set_font('Arial', 'I', 9)
    pdf.set_text_color(200, 50, 50)
    pdf.multi_cell(0, 5, "AVISO: Este relatório é gerado por Inteligência Artificial e serve apenas como estimativa. Não substitui uma inspeção mecânica presencial.")

    # Salva
    pdf.output(nome_arquivo_saida)
    return True
