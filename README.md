<p align="center">
  <img src="frontend/public/static/logo2.png" alt="AutoAssist Logo" width="200">
</p>

# AutoAssist IA 🚗💨

O **AutoAssist IA** é um ecossistema de inteligência artificial de última geração, desenvolvido especificamente para o mercado automotivo brasileiro. A plataforma integra Processamento de Linguagem Natural (NLP) e Visão Computacional para fornecer diagnósticos precisos, avaliações de mercado e consultoria técnica especializada.

---

## ✨ Funcionalidades

### **Landing Page e Apresentação**

- **Carrossel 3D imersivo:** Seção heróica com animação de carros em perspectiva 3D (Canvas 2D), cards com highlight dinâmico e efeito de estrada em movimento.
- **Design responsivo:** Layout adaptável a qualquer viewport com navbar fixa isolada via `body.home`, escalonamento visual consistente entre zoom 80%–100%.

### **Recursos Inteligentes (NOG IA)**

- **Consultoria Contextual:** O assistente "NOG" agora utiliza o **histórico da conversa** para oferecer respostas mais profundas e evitar resultados repetitivos.
- **E-commerce Automotivo Integrado:** Recomendação automática de links para compra de **veículos (WebMotors)** e **peças (Mercado Livre)** baseada na necessidade do usuário.
- **IA de Previsão de Manutenção:** Sistema que analisa descrições (ex: "Troquei o óleo hoje") e utiliza IA para prever a data e quilometragem da próxima revisão.
- **Raio-X Mecânico:** Análise visual avançada para identificação de ferrugem, desalinhamentos e vazamentos em fotos.

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
| **Groq API**         | Modelos de linguagem (LLaMA, Groq Compound) para texto e visão. |
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
│   ├── app.py                     # Entry-point (Servidor Flask)
│   ├── routes/                    # Módulos de API (Auth, Pages, Database)
│   ├── services/                  # IA e Lógica (NOG IA, Vision, Maintenance)
│   └── .env                       # Variáveis de ambiente
├── frontend/
│   ├── index.html                 # Landing Page / Dashboard
│   ├── chat.html                  # Consultor NOG IA
│   ├── library.html               # Galeria de Vídeos YouTube
│   ├── maintenance_history.html   # Gestão de Manutenções
│   ├── profile.html               # Perfil do Usuário
│   └── static/
│       ├── css/
│       │   ├── car-scrollytelling.css   # Estilos do carrossel 3D e hero
│       │   ├── shared.css               # Estilos compartilhados (navbar, footer)
│       │   ├── responsive.css           # Media queries globais
│       │   ├── chat.css                 # Estilos do consultor NOG IA
│       │   ├── dashboard.css            # Estilos do dashboard
│       │   └── profile.css              # Estilos do perfil
│       ├── js/
│       │   ├── car-scrollytelling.js    # Canvas 2D carousel com física de perspectiva
│       │   ├── auth.js                  # Autenticação Google OAuth 2.0
│       │   └── config.js                # Configurações do frontend
│       └── logo2.png                    # Logotipo do projeto
└── README.md
```

---

## 🚀 Como Executar o Projeto

### 1. Pré-requisitos

- Python 3.10 ou superior
- Servidor MySQL (Local ou Nuvem)
- Chave de API do Groq (https://console.groq.com)

### 2. Configuração do Ambiente

Crie um arquivo `.env` na pasta `backend/` com:

```env
API_GROQ=sua_chave_aqui
GROQ_PRIMARY_MODEL=groq/compound-mini
GROQ_UTILITY_MODEL=gpt-oss-20b
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
GROQ_FALLBACK_MODELS=groq/compound

# Cache de respostas (segundos). 0 desativa o cache.
AI_CACHE_TTL_SECONDS=300
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
