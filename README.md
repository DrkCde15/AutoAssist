# AutoAssist IA • Consultor Automotivo Inteligente 🚗🤖

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-4479A1?style=for-the-badge&logo=mysql&logoColor=white)
![Neura IA](https://img.shields.io/badge/AI_Local-Ollama-blue?style=for-the-badge&logo=openai&logoColor=white)

O **AutoAssist IA** é um ecossistema de inteligência artificial de última geração, desenvolvido especificamente para o mercado automotivo brasileiro. A plataforma integra Processamento de Linguagem Natural (NLP) e Visão Computacional para fornecer diagnósticos precisos, avaliações de mercado e consultoria técnica especializada, operando de forma **100% privada e local** através da integração com a **Neura IA**.

---

## ✨ Funcionalidades

### **Recursos Principais**

- **Consultoria Especializada (NOG):** O assistente "NOG" utiliza o modelo **Gemma 2 (2B)** para oferecer respostas focadas no mercado brasileiro, analisando modelos, versões, manutenção e custo-benefício.
- **Raio-X Mecânico:** Pipeline de visão computacional de dois estágios (**Moondream + Gemma 2**) para análise de fotos, identificando ferrugem, desalinhamentos e vazamentos.
- **Dashboard de Veículo:** Painel centralizado que monitora a saúde das principais peças do seu veículo e fornece alertas de manutenção preventiva.
- **Estimativa FIPE Inteligente:** Cálculo de depreciação e valor de mercado em tempo real, ajustado pelo estado de conservação do veículo.
- **Viva-Voz Inteligente:** Interação por voz em modo "mãos livres" com detecção automática de silêncio (Voice Activity Detection).

### **Segurança e Privacidade**

- **Autenticação em Duas Etapas (2FA):** Camada de segurança adicional utilizando uma senha secundária escolhida pelo usuário.
- **Privacidade Total:** Processamento local via **Ollama**. Nenhuma imagem ou dado de conversa sai do seu servidor privado.
- **Autenticação JWT:** Sistema robusto com tokens de acesso (24h) e refresh tokens (30 dias).
- **Trial Control:** Gestão automatizada de período de teste (30 dias) e benefícios para usuários **Premium**.

---

## 🛠️ Tecnologias Utilizadas

### **Backend & Inteligência Artificial**

| Tecnologia   | Função                                                           |
| :----------- | :--------------------------------------------------------------- |
| **Flask**    | Servidor robusto e orquestração de APIs REST.                    |
| **Neura IA** | Framework de integração para orquestração de modelos LLM locais. |
| **Ollama**   | Motor de execução local (Models: Gemma2:2b & Moondream).         |
| **PyMySQL**  | Driver de alta performance para banco de dados MySQL.            |
| **FPDF**     | Motor de geração de laudos técnicos em formato PDF.              |
| **Pydub**    | Processamento e conversão de áudio para transcrição.             |

### **Frontend**

| Tecnologia         | Função                                                        |
| :----------------- | :------------------------------------------------------------ |
| **UX Premium**     | Interface moderna com Dark Mode e Glassmorphism.              |
| **Vanilla JS**     | Lógica de estado e autenticação JWT (Sem frameworks pesados). |
| **Web Speech API** | Captura de áudio nativa com integração ao backend.            |
| **Marked.js**      | Renderização dinâmica de Markdown nas respostas da IA.        |
| **Inter Font**     | Tipografia moderna otimizada para legibilidade técnica.       |

---

## 🏗️ Estrutura do Projeto

```
AutoAssist/
├── backend/
│   ├── app.py                  # Servidor principal e API
│   ├── nogai.py                # Módulo de texto (Gemma 2)
│   ├── vision_ai.py            # Pipeline de visão (Moondream)
│   ├── report_generator.py     # Gerador de PDFs técnicos
│   └── requirements.txt        # Dependências Python
├── frontend/
│   ├── index.html              # Landing Page & Home
│   ├── chat.html               # Interface do Consultor NOG
│   ├── dashboard.html          # Painel de Saúde do Veículo
│   ├── perfil.html             # Gestão de Dados e Veículo
│   ├── login.html / cadastro.html
│   └── static/                 # CSS, JS (auth.js, config.js) e assets
└── README.md
```

---

## 🚀 Como Executar o Projeto

### 1. Pré-requisitos

- Python 3.10 ou superior
- **Ollama** instalado e configurado
- Servidor MySQL ativo

### 2. Configuração dos Modelos (Ollama)

Execute no terminal para baixar os pesos dos modelos otimizados:

```bash
ollama pull gemma2:2b
ollama pull moondream
```

### 3. Instalação e Execução

```bash
# Entre na pasta do backend
cd backend

# Instale as dependências
pip install -r requirements.txt

# Configure o arquivo .env manualmente conforme as variáveis necessárias
# Execute o servidor
python app.py
```

A plataforma estará acessível em `http://localhost:5000`

---

## 🔒 Segurança e Boas Práticas

- **Bcrypt**: Todas as senhas (primárias e secundárias) são armazenadas como hashes seguros.
- **JWT Protection**: Todos os endpoints `/api/` (exceto login/cadastro) exigem token válido.
- **Rate Limiting**: Proteção contra ataques de força bruta e sobrecarga do motor de IA.
- **CSP & Talisman**: Implementação de cabeçalhos de segurança HTTP.

---

## 📝 Licença e Autoria

Desenvolvido por **Júlio César** com o suporte da **Neura IA**.
Este projeto é proprietário e focado em demonstrar o poder da IA local no setor automotivo.
