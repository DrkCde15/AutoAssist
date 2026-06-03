<p align="center">
  <img src="frontend/public/static/logo2.png" alt="AutoAssist Logo" width="200">
</p>

# AutoAssist IA 🚗💨

O **AutoAssist IA** é um ecossistema de inteligência artificial de última geração, desenvolvido especificamente para o mercado automotivo brasileiro. A plataforma integra Processamento de Linguagem Natural (NLP) e Visão Computacional para fornecer diagnósticos precisos, avaliações de mercado e consultoria técnica especializada, operando com alta performance através da integração com a API do **Google Gemini**.

---

## ✨ Funcionalidades

### **Recursos Inteligentes (NOG IA)**

- **Consultoria Contextual:** O assistente "NOG" agora utiliza o **histórico da conversa** para oferecer respostas mais profundas e evitar resultados repetitivos.
- **E-commerce Automotivo Integrado:** Recomendação automática de links para compra de **veículos (WebMotors)** e **peças (Mercado Livre)** baseada na necessidade do usuário.
- **IA de Previsão de Manutenção:** Sistema que analisa descrições (ex: "Troquei o óleo hoje") e utiliza IA para prever a data e quilometragem da próxima revisão.
- **Raio-X Mecânico:** Análise visual avançada alimentada pelo **Gemini Vision** para identificação de ferrugem, desalinhamentos e vazamentos em fotos.

### **Dashboard e Gestão**

- **Histórico Proativo:** Painel que monitora a saúde das peças e indica o status de cada manutenção (Ok, Aviso ou Atrasado).
- **Galeria de Vídeos Otimizada:** Nova biblioteca de vídeos com redirecionamento direto para o YouTube, miniaturas em alta resolução e carregamento ultrarrápido.
- **Notificações Instantâneas:** Sistema de e-mail que alerta o usuário **no mesmo dia** em que uma manutenção atinge o status crítico ou vence.
- **Tabela FIPE Real-Time:** Integração com a API FIPE para fornecer valores de mercado precisos e atualizados.
- **Feedback Inteligente:** Sistema que coleta e organiza o feedback dos usuários para melhoria contínua do sistema.

### **Segurança e Cloud (Hardening de Produção)**

- **Proteção Avançada:** Implementação de **SRI (Subresource Integrity)**, **CSP (Content Security Policy)** e sanitização global contra XSS.
- **Google OAuth 2.0:** Login simplificado e seguro utilizando contas Google com propagação dinâmica de tokens.
- **Autenticação em Duas Etapas (2FA):** Camada de segurança adicional para proteção de dados sensíveis.
- **Cloud Resiliency:** Conectividade reforçada com suporte a SSL e timeouts otimizados para bancos de dados em nuvem.

---

## 🛠️ Tecnologias Utilizadas

### **Backend & Inteligência Artificial**

| Tecnologia            | Função                                                 |
| :-------------------- | :----------------------------------------------------- |
| **Flask**             | Servidor robusto e orquestração de APIs REST.          |
| **Google Gemini SDK** | Integração com Gemini 2.0 Flash (Texto e Visão).       |
| **PyMySQL + SSL**     | Conexão segura e resiliente com o banco de dados.      |
| **SMTP / Gmail API**  | Motor de disparo de notificações proativas por e-mail. |
| **JWT + Refresh**     | Autenticação moderna com Tokens de Acesso e Refresh.   |

### **Frontend**

| Tecnologia           | Função                                                     |
| :------------------- | :--------------------------------------------------------- |
| **Vanilla JS**       | Lógica de estado e consumo de APIs sem frameworks pesados. |
| **Glassmorphism UI** | Design moderno com transparências e animações dinâmicas.   |
| **DOMPurify + Marked**| Renderização segura de Markdown e sanitização de HTML.     |
| **Web Speech API**   | Captura e processamento de voz nativo no navegador.        |

---

## 🏗️ Estrutura do Projeto

```
AutoAssist/
├── backend/
│   ├── app.py                  # Entry-point (Servidor Flask)
│   ├── routes/                 # Módulos de API (Auth, Pages, Database)
│   ├── services/               # IA e Logica (NOG IA, Vision, Maintenance)
│   └── .env                    # Variáveis de ambiente
├── frontend/
│   ├── index.html              # Landing Page / Dashboard
│   ├── chat.html               # Consultor NOG IA
│   ├── library.html             # Galeria de Vídeos YouTube
│   ├── maintenance_history.html # Gestão de Manutenções
│   └── static/                 # CSS, JS (auth.js, config.js)
└── README.md
```

---

## 🚀 Como Executar o Projeto

### 1. Pré-requisitos

- Python 3.10 ou superior
- Servidor MySQL (Local ou Nuvem)
- Chave de API do Google Gemini

### 2. Configuração do Ambiente

Crie um arquivo `.env` na pasta `backend/` com:

```env
API_GEMINI=sua_chave_aqui
GEMINI_TEXT_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=gemini-2.0-flash,gemini-2.0-flash-lite
GEMINI_FALLBACK_ON_QUOTA=false
DB_HOST=seu_host
DB_USER=seu_usuario
DB_PASSWORD=sua_senha
DB_NAME=seu_banco
GOOGLE_CLIENT_ID=seu_client_id_google
EMAIL_REMETENTE=seu_email@gmail.com
EMAIL_SENHA_APP=sua_senha_app_gmail

# Opcao recomendada para Render Free: Gmail API via OAuth
EMAIL_PROVIDER=gmail_api
EMAIL_FROM=seu_email@gmail.com
EMAIL_FROM_NAME=AutoAssist
GMAIL_OAUTH_CLIENT_ID=seu_client_id_oauth
GMAIL_OAUTH_CLIENT_SECRET=seu_client_secret_oauth
GMAIL_OAUTH_REFRESH_TOKEN=seu_refresh_token_oauth

# Alertas de manutencao enviados pelo proprio backend
MAINTENANCE_EMAIL_AUTODISPATCH_ENABLED=true
MAINTENANCE_EMAIL_AUTODISPATCH_INTERVAL_SECONDS=1800
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

---

## 🔒 Segurança e Boas Práticas

- **Bcrypt Hashing**: Proteção de senhas com algoritmos de derivação de chave.
- **SRI & CSP**: Proteção contra injeção de scripts maliciosos e manipulação de recursos externos.
- **JWT Protection**: Endpoints protegidos garantem que apenas usuários autenticados acessem dados sensíveis.

---

## 📝 Licença e Autoria

Ideia original de **Clara Francisco**.
Desenvolvido por **Júlio César**, **Caio Lima**, **Eduardo Nishida** e **Caio Yugo**.