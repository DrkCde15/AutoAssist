# AutoAssist IA • Consultor Automotivo Inteligente 🚗🤖

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-4479A1?style=for-the-badge&logo=mysql&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini_AI-blue?style=for-the-badge&logo=google&logoColor=white)

O **AutoAssist IA** é um ecossistema de inteligência artificial de última geração, desenvolvido especificamente para o mercado automotivo brasileiro. A plataforma integra Processamento de Linguagem Natural (NLP) e Visão Computacional para fornecer diagnósticos precisos, avaliações de mercado e consultoria técnica especializada, operando com alta performance através da integração com a API do **Google Gemini**.

---

## ✨ Funcionalidades

### **Recursos Principais**

- **Consultoria Especializada (NOG):** O assistente "NOG" utiliza o modelo **Gemini 2.5 Flash** para oferecer respostas focadas no mercado brasileiro, analisando modelos, versões, manutenção e custo-benefício.
- **Raio-X Mecânico:** Análise visual avançada alimentada por **Gemini Vision** para identificação de ferrugem, desalinhamentos e vazamentos em fotos.
- **Dashboard de Veículo:** Painel centralizado que monitora a saúde das principais peças do seu veículo e fornece cotação em tempo real da Tabela FIPE.
- **Biblioteca de Vídeos Automática:** Integração com YouTube que recomenda tutoriais baseados na conversa e os salva automaticamente na biblioteca do usuário ("Meus Vídeos").
- **Tabela FIPE Real-Time:** Integração com a API FIPE (via Parallelum) para fornecer valores de mercado precisos e atualizados.
- **Viva-Voz Inteligente:** Interação por voz em modo "mãos livres" com detecção automática de silêncio (Voice Activity Detection).

### **Segurança e Cloud**

- **Autenticação em Duas Etapas (2FA):** Camada de segurança adicional utilizando uma senha secundária escolhida pelo usuário.
- **Performance Cloud:** Respostas rápidas e precisas via infraestrutura do Google Gemini 2.5 Flash.
- **Autenticação JWT:** Sistema robusto com tokens de acesso e refresh tokens.
- **Trial Control:** Gestão automatizada de período de teste (30 dias) e benefícios para usuários **Premium**.

---

## 🛠️ Tecnologias Utilizadas

### **Backend & Inteligência Artificial**

| Tecnologia                | Função                                                            |
| :------------------------ | :---------------------------------------------------------------- |
| **Flask**                 | Servidor robusto e orquestração de APIs REST.                     |
| **Gemini AI SDK**         | Novo SDK (`google-genai`) para texto e visão multimodal.          |
| **MySQL**                 | Armazenamento persistente de usuários, histórico e vídeos.        |
| **YouTube Search Python** | Motor de recomendação visual de tutoriais e manutenção.           |
| **FPDF**                  | Motor de geração de laudos técnicos em formato PDF.               |
| **SpeechRecognition**     | Processamento de áudio e transcrição de comandos de voz.          |

### **Frontend**

| Tecnologia         | Função                                                        |
| :----------------- | :------------------------------------------------------------ |
| **UX/UI Premium**  | Design moderno com Glassmorphism e animações dinâmicas.       |
| **Vanilla JS**     | Lógica de estado e consumo de API (Consumo de JWT).           |
| **Web Speech API** | Captura de áudio nativa com integração ao backend.            |
| **Marked.js**      | Renderização dinâmica de Markdown nas respostas da IA.        |

---

## 🏗️ Estrutura do Projeto

```
AutoAssist/
├── backend/
│   ├── app.py                  # Entry-point (Servidor Flask)
│   ├── routes/                 # Módulos de API (Auth, Pages, Database, Payment)
│   ├── services/               # Lógica de Integração (Gemini, Vision, YouTube, PDF)
│   └── requirements.txt        # Dependências do projeto
├── frontend/
│   ├── index.html              # Landing Page
│   ├── chat.html               # Consultor NOG com Video Cards
│   ├── dashboard.html          # Diagnóstico e Tabela FIPE
│   ├── videos.html             # Biblioteca Pessoal de Vídeos Salvos
│   ├── perfil.html             # Gestão de Perfil e Veículo
│   └── static/                 # CSS, assets e lógica global (auth.js)
└── README.md
```

---

## 🚀 Como Executar o Projeto

### 1. Pré-requisitos

- Python 3.10 ou superior
- Servidor MySQL ativo
- Chave de API do Google Gemini

### 2. Configuração do Ambiente

Crie um arquivo `.env` na pasta `backend/` com:

```env
API_GEMINI=sua_chave_aqui
DB_HOST=seu_host
DB_USER=seu_usuario
DB_PASSWORD=sua_senha
DB_NAME=seu_banco
JWT_SECRET_KEY=sua_chave_jwt
```

### 3. Instalação e Execução

```bash
# Entre na pasta do backend
cd backend

# Instale as dependências
pip install -r requirements.txt

# Execute o servidor
python app.py
```
### 3.1 Criando um ambiente virtual

```bash
# Entre na pasta do backend
cd backend

# Instale as dependências
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Execute o servidor
python app.py
```

A plataforma estará acessível em `http://localhost:5000`

---

## 🔒 Segurança e Boas Práticas

- **Monkey Patching**: Gerenciamento cirúrgico de compatibilidade entre o SDK do Gemini e a biblioteca de vídeos.
- **Bcrypt**: Todas as senhas (primárias e secundárias) são armazenadas como hashes seguros.
- **JWT Protection**: Todos os endpoints `/api/` (exceto login/cadastro) exigem token válido.
- **Rate Limiting**: Proteção contra abusos na API.
- **CSP & Talisman**: Implementação de cabeçalhos de segurança HTTP.

---

## 📝 Licença e Autoria

Ideia original de **Clara Francisco**.

Sistema desenvolvido por **Júlio César**, **Caio Lima**, **Eduardo Nishida** e **Caio Yugo** com o suporte de **Google Gemini API**.
