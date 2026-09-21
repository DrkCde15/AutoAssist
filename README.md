<p align="center">
  <img src="frontend/public/logo2.png" alt="AutoAssist Logo" width="200">
</p>

# AutoAssist IA 🚗💨

O **AutoAssist IA** é um ecossistema de inteligência artificial de última geração, desenvolvido especificamente para o mercado automotivo brasileiro. A plataforma integra Processamento de Linguagem Natural (NLP) e Visão Computacional para fornecer diagnósticos precisos, avaliações de mercado e consultoria técnica especializada.

---

## ✨ Funcionalidades

### **Recursos Inteligentes (NOG IA)**

- **Consultoria Contextual:** O assistente "NOG" agora utiliza o **histórico da conversa** para oferecer respostas mais profundas e evitar resultados repetitivos.
- **E-commerce Automotivo Integrado:** Recomendação automática de links para compra de **veículos (WebMotors)** e **peças (Mercado Livre)** baseada na necessidade do usuário.
- **IA de Previsão de Manutenção:** Sistema que analisa descrições (ex: "Troquei o óleo hoje") e utiliza IA para prever a data e quilometragem da próxima revisão.
- **Raio-X Mecânico:** Análise visual avançada para identificação de ferrugem, desalinhamentos e vazamentos em fotos.
- **Busca Inteligente de Mecânicos:** Encontre oficinas reais próximas via OpenStreetMap + Google Search, com cache Redis (1h OSM, 24h web). Integrado ao chatbot - pergunte "preciso de um mecânico" e a IA responde com opções na região.

### **Dashboard e Gestão**

- **Histórico Proativo:** Painel que monitora a saúde das peças e indica o status de cada manutenção (Ok, Aviso ou Atrasado).
- **Agenda de Eventos Automotivos:** Varredura automática de feiras, encontros, competições e exposições do setor, exibidas em cards na página de eventos (`eventos.html`) com filtros por UF, categoria e período, mais **selo de status** (Agendado / Acontecendo / Cancelado / Encerrado / Data a confirmar) e a **fonte** de cada evento. As fontes de **alta confiança** são sites especializados estruturados (NFeiras, Sindirepa, Diretriz, Shopping Interlagos); a **busca web** (Bing via Scrapling, sem browser) entra como fallback de baixa confiança.
- **Galeria de Vídeos Otimizada:** Nova biblioteca de vídeos com redirecionamento direto para o YouTube, miniaturas em alta resolução e carregamento ultrarrápido.
- **Notificações Instantâneas:** Sistema de e-mail que alerta o usuário **no mesmo dia** em que uma manutenção atinge o status crítico ou vence.
- **Tabela FIPE Real-Time:** Integração com a API FIPE para fornecer valores de mercado precisos e atualizados.
- **Fotos dos Veículos:** Upload e exibição da foto de cada veículo no dashboard e no perfil (`foto_base64` na tabela `veiculos`). Envie/remova a foto via `POST /api/veiculos/<id>/foto`.
- **Feedback Inteligente:** Sistema que coleta e organiza o feedback dos usuários para melhoria contínua do sistema.

### **Programa de Indicação (Link de Convite)**

- Cada usuário recebe um **link de convite** próprio, obtido via `GET /api/referral` (JWT), que retorna `referral_code` e `referral_link` no formato `https://<dominio>/cadastro.html?ref=CODIGO`.
- Quem se cadastra informando um `referred_by` (o código do convite) **concede 1 mês de crédito/desconto na assinatura Premium a quem indicou** (aplicado na ativação da assinatura via `referral_credit_months` em `routes/auth.py`/`payment.py`).
- Proteções anti-fraude no backend: teto de **20 bônus por indicador**, máximo de **5 indicações/dia**, máximo de **5 contas por IP/dia** e bloqueio quando o IP do indicado é igual ao do indicador.

### **Mod Passport (recurso Premium)**

- Recurso **exclusivo para contas Premium** (validado por `_require_mod_passport` em `routes/pages.py`).
- Permite registrar **modificações/melhorias** do veículo (ex.: som, rodas, motor, preparação) e recalcula o **Valor estimado de mercado** (`fipe_ajustada`) com base nos upgrades aplicados.
- A **base do valor** é a **Tabela FIPE** (referência oficial) ou, quando há amostra confiável, a **mediana de anúncios reais** (Mercado Livre, via `get_market_price_estimate` em `services/web_scraping.py`).
- O ajuste por mods é **conservador e transparente**: pesos por categoria (turbo 5%, motor 4%, som 0,5%…) com teto de **12%**, mais qualquer valor em R$ informado por modificação (`_calcular_detalhe` em `routes/pages.py`).
- O painel exibe o valor FIPE base versus o valor estimado, a **fonte** utilizada e um **aviso** de que não é avaliação oficial (não substitui perícia para venda/seguro/financiamento).
- **Histórico e compartilhamento (lock-in de dados):** cada alteração de mods gera uma **versão** (`mod_passport_versions`) com snapshot do veículo, valor FIPE e valor estimado. O usuário pode ver o histórico (`GET /api/veiculos/<id>/modificacoes/history`, JWT), gerar um **link público** (`POST /api/veiculos/<id>/mod-passport/share`, JWT) e abrir/baixar o Mod Passport em **PDF** (`GET /api/public/mod-passport/<token>` e `.../pdf`) — sem login. Ações disponíveis no `dashboard.html` (Histórico / Compartilhar / Exportar PDF).

### **Diferenciais de Retenção e Experiência**

- **Diagnóstico Visual Assistido (memória visual):** no chat (`chat.html`), o usuário seleciona um veículo e a NOG **compara a foto enviada com a foto cadastrada** daquele veículo (`veiculos.foto_base64`), apontando o que é novo, piorou ou melhorou ao longo do tempo. Se o veículo ainda não tem foto, a própria imagem do diagnóstico vira o *baseline* de memória. Diferencial direto contra LLMs genéricos ("a IA lembra do seu carro"). Funciona tanto via REST (`/api/chat`) quanto via WebSocket (`/ws/chat`) — basta enviar `vehicle_id`.
- **Concierge de Oficinas:** botão flutuante "Oficinas" no `dashboard.html` e no `chat.html` que usa a geolocalização do navegador e lista oficinas reais próximas (`GET /api/mechanics/search?lat&lng`), com distância, cidade, especialidades e botão de ligar — fechando o ciclo diagnosticar → encontrar mecânico.
- **Badge de Confiança:** banner "Seu carro, lembrado pela IA" no topo do dashboard, reforçando o moat de dados do Mod Passport + FIPE + histórico.
- **Ativação e Retenção:** ao adicionar o primeiro veículo, o usuário recebe notificação in-app + push de boas-vindas (direcionando ao Mod Passport); quando o valor FIPE de um veículo é **atualizado** no dashboard, o dono é notificado + recebe push com o novo valor.

### **Dashboard - Modais de Detalhes do Veículo**

- O painel (`dashboard.html`) agora abre **modais interativos** com os detalhes completos de cada veículo - marca, modelo, ano de fabricação, quilometragem, valor FIPE base/ajustado e status de manutenção - além de ações rápidas como editar dados do veículo e acessar o **Mod Passport**.

### **Segurança e Cloud (Hardening de Produção)**

- **Proteção Avançada:** Implementação de **SRI (Subresource Integrity)**, **CSP (Content Security Policy)** e sanitização global contra XSS.
- **Google OAuth 2.0:** Login simplificado e seguro utilizando contas Google com propagação dinâmica de tokens.
- **Autenticação em Duas Etapas (2FA):** Camada de segurança adicional para proteção de dados sensíveis.
- **CAPTCHA Cloudflare Turnstile:** Proteção anti-bot no cadastro e login - validação server-side de `success`, `action` e `hostname`.
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
| **Overpass API (OSM)**| Consulta de oficinas mecânicas via OpenStreetMap.      |
| **Google Search**     | Scraping de resultados locais para mecanicas.           |
| **Scrapling (Bing)**  | Varredura web de eventos via TLS stealth (curl_cffi), sem browser; Brave Search API como fallback se `BRAVE_API_KEY`. |
| **OpenStreetMap Nominatim** | Geocodificação cidade→lat/lng dos eventos (cache 30d). |
| **MySQL `events`**    | Persistência estruturada dos eventos (upsert, status, confiança, coords). |
| **Redis**             | Cache distribuído de IA, dashboard e mechanics (OSM/Web).|

### **Frontend**

| Tecnologia           | Função                                                     |
| :------------------- | :--------------------------------------------------------- |
| **HTML/CSS/JS**      | Frontend estático vanilla servido pelo Flask.              |
| **Tailwind CSS**     | Utility-first CSS com design system customizado.           |
| **Lucide Icons**     | Ícones leves via SVG inline.                               |
| **Web Speech API**   | Captura e processamento de voz nativo no navegador.        |
| **DOMPurify**        | Sanitização de HTML contra XSS.                            |

---

## 🏗️ Estrutura do Projeto

```
AutoAssist/
├── backend/
│   ├── models/                    # Modelos de ML para treinamento
│   ├── routes/                    # Módulos de API (Auth, Pages, Database, Mechanics, Events, Payment)
│   ├── scripts/                   # Treinamento do ML
│   ├── services/                  # IA e Lógica (NOG IA, Vision, Maintenance, Web Scraping, Automotive Events)
│   ├── utils/                     # Cache Redis, e-mail, tasks assíncronas e cron auth
│   ├── tests/                     # Testes unitários (unittest) — 17 arquivos, 3.645 linhas
│   ├── app.py                     # Entry-point (Servidor Flask)
│   ├── gunicorn.conf.py           # Configuração Gunicorn (produção)
│   ├── build.sh                   # Instala dependências Python
│   └── .env                       # Variáveis de ambiente (NÃO commitar — ver Checklist de Segurança)
├── frontend/
│   └── public/                    # Frontend estático (HTML/CSS/JS)
│       ├── index.html             # Landing page
│       ├── login.html             # Login (Google OAuth + Turnstile)
│       ├── cadastro.html          # Cadastro com referral
│       ├── chat.html              # Chat com NOG IA
│       ├── dashboard.html         # Dashboard do veículo
│       ├── perfil.html            # Perfil do usuário
│       ├── planos.html            # Planos e preços (checkout Cakto)
│       ├── eventos.html           # Agenda de eventos automotivos
│       ├── maps.html              # Mapa de oficinas
│       ├── biblioteca.html        # Biblioteca de vídeos
│       ├── anotacoes.html         # Anotações do usuário
│       ├── feedback.html          # Feedback
│       ├── duvidas.html           # Perguntas frequentes
│       ├── b2b.html               # B2B (diagnóstico por foto)
│       ├── docs.html              # Documentação da API B2B
│       ├── 404.html               # Página de erro
│       ├── css/
│       │   └── styles.css         # Tailwind CSS compilado
│       ├── js/
│       │   ├── api.js             # Cliente API
│       │   ├── auth.js            # Autenticação (login, cadastro, OAuth)
│       │   ├── nav.js             # Navbar + drawer mobile
│       │   ├── payment.js         # Integração Cakto
│       │   ├── premium-modal.js   # Modal de upsell premium
│       │   ├── notifications.js   # Notificações in-app
│       │   ├── sw.js              # Service Worker (push notifications)
│       │   └── pages/
│       │       ├── chat.js        # Chat com NOG IA
│       │       ├── dashboard.js   # Dashboard do veículo
│       │       ├── perfil.js      # Perfil do usuário
│       │       ├── maps.js        # Mapa de oficinas
│       │       ├── eventos.js     # Eventos automotivos (com modal de detalhes)
│       │       ├── biblioteca.js  # Biblioteca de vídeos
│       │       ├── anotacoes.js   # Anotações
│       │       ├── b2b.js         # B2B
│       │       ├── planos-checkout.js # Checkout premium
│       │       └── ...
│       ├── sw.js                  # Service Worker
│       ├── manifest.json          # PWA manifest
│       ├── robots.txt             # SEO
│       ├── sitemap.xml            # SEO
│       └── logo.png, logo2.png    # Logos
├── render.yaml                    # Blueprint de deploy (Render)
├── docker-compose.yml             # Redis local para desenvolvimento
├── requirements.txt               # 37 dependências Python
├── runtime.txt                    # python-3.12
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
# Groq (IA)
API_GROQ=sua_chave_aqui
GROQ_PRIMARY_MODEL=groq/compound-mini
GROQ_UTILITY_MODEL=openai/gpt-oss-20b
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
GROQ_FALLBACK_MODELS=groq/compound

# Busca web de eventos (fallback de baixa confiança)
# Scrapling/Bing nao exige chave. Brave Search API eleva a qualidade se configurada:
BRAVE_API_KEY=

# Redis (cache de IA, dashboard, filas RQ e rate limit)
# Local (docker-compose): redis://localhost:6379/0
# Upstash (producao): rediss://default:<token>@<host>.upstash.io:6379
REDIS_URL=redis://localhost:6379/0
RATELIMIT_STORAGE_URI=redis://localhost:6379/0

# TTL dos caches de IA (segundos)
GROQ_CACHE_TTL_SECONDS=3600
GROQ_VISION_CACHE_TTL_SECONDS=86400
GROQ_PDF_CACHE_TTL_SECONDS=86400
DASHBOARD_CACHE_TTL_SECONDS=30

# Banco de dados
DB_HOST=seu_host
DB_USER=seu_usuario
DB_PASSWORD=sua_senha
DB_NAME=seu_banco
AUTO_INIT_DB=1

# E-mail (provedor google_script usa Google Apps Script)
EMAIL_REMETENTE=seu_email@gmail.com
EMAIL_SENHA_APP=sua_senha_app_gmail
EMAIL_FROM_NAME=AutoAssist
EMAIL_PROVIDER=google_script
GOOGLE_SCRIPT_URL=https://script.google.com/macros/s/xxx/exec
GOOGLE_SCRIPT_SECRET=xxx

# Google OAuth
GOOGLE_CLIENT_ID=seu_client_id
GOOGLE_CLIENT_SECRET=seu_client_secret
GOOGLE_REDIRECT_URI=https://seu-dominio/api/auth/google/callback

# URLs do frontend (CORS/WebSocket e links de e-mail)
URL_DEV=http://127.0.0.1:5000/
URL_PROD=https://seu-dominio

# Seguranca / producao
FLASK_ENV=production
JWT_SECRET_KEY=gere_um_segredo_forte
DEMO_LOGIN_ENABLED=0
CSP_ALLOW_UNSAFE_EVAL=0
HEALTHCHECK_EXTERNAL_CHECKS=1
MAINTENANCE_EMAIL_CRON_SECRET=gere_um_segredo_forte

# Pagamentos (Cakto)
CAKTO_CHECKOUT_URL=https://pay.cakto.com.br/xxx
BASE_URL=https://api.cakto.com.br/
CAKTO_WEBHOOK_SECRET=xxx

# Cloudflare Turnstile (CAPTCHA anti-bot)
# Criar widget: https://dash.cloudflare.com -> Turnstile -> Create Widget
# (ou via API, veja a seção "Segurança e Boas Práticas")
TURNSTILE_SITE_KEY=0x4AAAAAAA...
TURNSTILE_SECRET_KEY=segredo_do_widget
# Frontends autorizados a emitir token, separados por vírgula, SEM protocolo
# (produção: só o domínio real; dev: localhost,127.0.0.1)
TURNSTILE_HOSTNAMES=seu-dominio.com,localhost,127.0.0.1

# API B2B (diagnóstico por foto como serviço assinável)
# Segredo para criar API keys de clientes corporativos (POST /api/b2b/keys).
# OBS: obrigatório - sem ele, a criação de chave retorna 500.
B2B_ADMIN_SECRET=gere_um_segredo_forte

```

### 3. Instalação e Execução

```bash
# Backend
cd backend
pip install -r requirements.txt
python app.py

# Frontend é servido automaticamente pelo Flask em http://localhost:5000
# Não é necessário Node.js ou npm
```

### 4. Build para Produção

O `build.sh` apenas instala as dependências Python. O frontend é estático e não precisa de build:

```bash
cd backend
bash build.sh
# Flask serve frontend/public/ em http://localhost:5000
```

### 5. Deploy no Render

O `render.yaml` configura automaticamente:
- `rootDir: backend`
- `buildCommand: bash build.sh` (instala dependências Python)
- `startCommand: gunicorn app:app -c gunicorn.conf.py --bind 0.0.0.0:$PORT`

### 6. Redis para desenvolvimento local

O cache de IA, o cache do dashboard (FIPE + predições de manutenção), as filas RQ (e-mails/manutenção) e o rate limit usam Redis. Para subir um Redis local:

```bash
docker compose up -d   # sobe redis:7-alpine em localhost:6379
```

Defina no `.env`:

```env
REDIS_URL=redis://localhost:6379/0
RATELIMIT_STORAGE_URI=redis://localhost:6379/0
```

Sem Redis, o cache recai sobre memória local (por processo) e as filas RQ não processam jobs.

---

## 💳 Planos e Monetização

- **Plano Premium recorrente:** assinatura **R$ 19,90/mês** (via Cakto, `PREMIUM_PLANS` em `routes/payment.py`).
- **Camada gratuita:** até **30 consultas/mês** com a IA NOG (`FREE_MONTHLY_CHAT_LIMIT` em `routes/pages.py`); estourar o limite retorna `403 code=free_limit_reached`. Em manutenções, o free pode registrar até **3 por veículo** (`FREE_MAINTENANCE_LIMIT`), com alertas gratuitos.
- **Indicação:** quem se cadastra com um código de convite concede **1 mês de crédito** na assinatura de quem indicou (`referral_credit_months`).
- **B2B:** diagnóstico por foto como serviço, com tiers e cota por API key (ver seção abaixo).

---

## 🤝 API B2B (Diagnóstico por Foto como Serviço)

API assinável para clientes corporativos enviarem fotos de defeitos e receberem um laudo técnico (JSON ou PDF) gerado por IA. Autenticação via header `X-API-Key` (chave criada em `POST /api/b2b/keys`, protegido por `B2B_ADMIN_SECRET`). A chave é exibida **uma vez**; no banco fica só o hash SHA-256, com comparação em tempo constante. Rate limit por cliente (Redis, com fallback local). Planos/tiers (`B2B_PLANS`: **trial (grátis), pro_1k (R$ 99/mês), pro_5k (R$ 399/mês), pro_20k (R$ 999/mês)**) definem a cota de requisições (`requests_limit`/`requests_used` na tabela `api_clients`); ultrapassar retorna `429`. Clientes podem gerar sua própria chave via `POST /api/b2b/self-serve/keys` (JWT do usuário logado) e acompanhar o consumo em `GET /api/b2b/usage`. Webhook `POST /api/b2b/webhook/usage` permite a AutoAssist marcar uso apócrifo/externo (idempotente por par `client_key_hash`+`evento_ref`). SDK/Postman e exemplos (Python/JS/cURL) em `frontend/public/docs.html` + collection em `frontend/public/static/b2b-postman.json`.

### Endpoints

| Método | Rota | Auth | Descrição |
| :----- | :--- | :--- | :-------- |
| `POST` | `/api/b2b/keys` | `X-Admin-Secret` = `B2B_ADMIN_SECRET` | Cria um cliente e retorna a `api_key` (uso único). Body: `{ "nome", "rate_limit_per_min"? }`. |
| `POST` | `/api/b2b/self-serve/keys` | JWT (usuário logado) | Usuário cria sua própria API key B2B (plano/tier definido por `B2B_PLANS`). |
| `POST` | `/api/b2b/diagnosis` | `X-API-Key` | Diagnóstico por foto. Body: `{ "image": <base64>, "pergunta"?, "formato"?: "json"\|"pdf" }`. |
| `GET`  | `/api/b2b/usage` | `X-API-Key` | Consumo da cota do cliente (usado/restante, janela de rate). |
| `POST` | `/api/b2b/webhook/usage` | `X-API-Key` | Registra uso externo/idempotente (body: `{ "evento_ref", "increment"?: 1 }`). |
| `POST` | `/api/b2b/leads` | público | Captura lead do formulário B2B. Body: `{ "nome", "email", "empresa"?, "telefone"?, "mensagem"? }`. |
| `GET`  | `/api/admin/b2b/leads` | JWT admin | Lista os leads capturados. |

### Exemplo de fluxo

```bash
# 1) Criar chave (admin)
curl -X POST http://localhost:5000/api/b2b/keys \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: $B2B_ADMIN_SECRET" \
  -d '{"nome":"Cliente Teste","rate_limit_per_min":30}'

# 2) Diagnóstico por foto (use a api_key retornada)
IMG=$(base64 -w0 foto.jpg)
curl -X POST http://localhost:5000/api/b2b/diagnosis \
  -H "Content-Type: application/json" \
  -H "X-API-Key: aa_xxxxxxxxxxxxxxxxxxxx" \
  -d "{\"image\":\"$IMG\",\"pergunta\":\"Qual o problema?\"}"
```

> O laudo é gerado por IA e **não substitui inspeção mecânica presencial**.

---

## 📅 Agenda de Eventos Automotivos

Pipeline de coleta de eventos tratado como **dado estruturado** (não scraping genérico):

1. **Provedores de alta confiança** (HTML estável e curado): `nfeiras.com` (automobilismo), `sindirepabrasil.org.br/eventos` (reparação), `diretriz.com.br` (Autopar, Minasparts…) e `interlagos.com.br` (itens automotivos).
2. **Busca web (fallback, baixa confiança):** Bing via **Scrapling** (`Fetcher`, TLS stealth com `curl_cffi`, sem abrir browser); **Brave Search API** entra se `BRAVE_API_KEY` estiver configurado; Playwright como último recurso.
3. **Normalização:** título normalizado (minúsculo, sem acento), `confidence` por fonte (fontes oficiais `0.90`, web `0.40`) e `status` (`upcoming` / `ongoing` / `finished` / `cancelled` / `unknown`).
4. **Deduplicação por score:** similaridade ponderada (título + data + cidade + venue + organizador); mantém o registro de **maior confiança** como canônico.
5. **Geocodificação:** cidade→lat/lng via Nominatim/OSM (cache 30d), reutilizando o cache de geocoding.
6. **Persistência:** upsert na tabela MySQL `events` (id estável via `sha1`), preservando eventos passados e o `status` (não são apagados).
7. **API:** `GET /api/events/automotive` (filtros `uf`, `q`, `categoria`, `periodo`, `lat`/`lng`/`radius` para "perto de mim") e `GET /api/events/<id>`.
8. **Frontend:** `eventos.html` renderiza cards com badge de `status` e selo de fonte; a lista mostra apenas eventos futuros.

> Eventos de comunidade (Facebook/Instagram/WhatsApp) e plataformas fechadas (Sympla/Eventbrite sem token) não são cobertos - ficam como fontes futuras. Nenhuma área protegida/CAPTCHA é contornada.

### Endpoints

| Método | Rota | Auth | Descrição |
| :----- | :--- | :--- | :-------- |
| `GET`  | `/api/events/automotive` | Página exige Premium | Lista eventos (filtros `uf`, `q`, `categoria`, `periodo`, `lat`, `lng`, `radius`). `?force=1` refaz a varredura. |
| `GET`  | `/api/events/<id>` | Página exige Premium | Detalhe de um evento (cache da varredura + MySQL). |
| `POST` | `/api/cron/events-notifications` | `X-Cron-Secret` | Notifica usuários sobre novos eventos (via RQ/thread). |

---

## 🔒 Segurança e Boas Práticas

- **Bcrypt Hashing**: Proteção de senhas com algoritmos de derivação de chave.
- **CSP (Content Security Policy)**: `unsafe-eval` deve ser removido (configurar `CSP_ALLOW_UNSAFE_EVAL=0`); `unsafe-inline` mantido para frontend estático (migração para nonce recomendada). Scripts inline nos HTMLs devem ser extraídos para arquivos `.js` externos.
- **JWT Protection**: Endpoints protegidos garantem que apenas usuários autenticados acessem dados sensíveis. Tokens de acesso expiram em 30 dias; implementar blocklist para revogação.
- **Cron Auth**: rotas agendadas exigem `X-Cron-Secret` (veja `utils/cron_auth.require_cron_secret` e `MAINTENANCE_EMAIL_CRON_SECRET`).
- **Cloudflare Turnstile**: CAPTCHA anti-bot em `/api/cadastro` (action `signup`) e `/api/login` (action `login`). O siteverify é feito server-side validando `success`, `action` e `hostname`. Sem `TURNSTILE_SECRET_KEY`, o decorator é no-op (dev/testes).
- **Webhook Secret**: Cakto webhook validado apenas via header (nunca via query string). Usar `secrets.compare_digest()` para comparação em tempo constante.
- **Segredos**: o `.env` **não deve ser commitado**. Em produção, configure os segredos no Render via dashboard/Environment Group. Se `.env` já foi commitado no git, rotacionar TODAS as chaves imediatamente.

---

## 🧪 Testes

Os testes ficam em `backend/tests/` (estilo `unittest`). Mockam banco, Redis e visão por IA, então rodam sem Groq/DB externo.

```bash
cd backend
python -m unittest tests.test_b2b -v     # ou: python tests/test_b2b.py
```

Cobertura de `test_b2b.py` (11 testes, todos passando):
- `POST /api/b2b/keys` - sucesso (201, hash gravado == SHA-256 da chave), secret errado (403), `B2B_ADMIN_SECRET` ausente (500)
- `POST /api/b2b/diagnosis` - sem key (401), sem imagem (400), JSON (200), **PDF** (200, `%PDF`)
- `POST /api/b2b/leads` - sucesso (201), campos faltando (400)
- `GET /api/admin/b2b/leads` - sem admin (403), com admin (200)

> O endpoint de PDF usa `fpdf2`; `_build_laudo_pdf` retorna `bytes`. A criação de chaves exige `B2B_ADMIN_SECRET` definido no `.env`.

---

## 📋 Alterações Recentes

Registro das mudanças feitas nesta sessão de desenvolvimento:

### Correções de Bugs Críticos
- **`pages.py`**: adicionado `send_file` ao import do Flask (PDF do Mod Passport agora funciona).
- **`pages.py:3323`**: corrigida variável `image_b64` → `img_b64` (chat de voz crashava após gerar resposta).
- **`mechanics.py`**: endpoint `POST /api/mechanics` protegido com `@jwt_required()` (antes era público e podia ser abusado para spam).
- **CSP compliance**: removidos todos os `onclick="..."` inline de `notifications.js`, `dashboard.js`, `perfil.js`, `anotacoes.js` e `eventos.js` — substituídos por `addEventListener`.

### Segurança e Hardening
- **CAKTO_ACCEPT_QUERY_SECRET** forçado como `False` em `cakto.py` — webhook secret aceito apenas via header, nunca via query string (que vaza em logs).
- **Logs removidos** de cache do chat (`nogai.py`, `vision_ai.py`, `attachment_ai.py`), busca de eventos (`events.py`, `automotive_events.py`, `tasks.py`) e geolocalização (`geocode.py`, `mechanics.py`). Nenhum segredo ou dado sensível é mais impresso em logs.
- **Prompt do chat** atualizado: respostas agora são em **texto simples** (sem markdown). Adicionada função `_strip_markdown()` em `nogai.py` que remove headers, bold, tabelas e blockquotes que escapem do prompt.
- **Referência a mecânicos** no prompt do chat atualizada: de "ícone 🔧 no chat" para "página de Mapas (`/maps`)".

### Correções de UI/UX
- **Favicon** corrigido em `cadastro.html`, `login.html`, `verificacao.html` e `redefinir-senha.html` (removidas referências quebradas a `/favicon.ico`).
- **Link "Assinar Premium"** no `index.html` agora aponta para `/planos` (antes ia para `/cadastro?plan=premium`).
- **Botão "Assinar Premium"** em `planos.html` reescrito como `<button>` puro (sem `<a>`) com script externo `planos-checkout.js` — funciona com CSP, redireciona para login se não autenticado, vai para Cakto checkout se autenticado.
- **Modal de detalhes do evento** adicionado em `eventos.js`: ao clicar em um card, abre modal com imagem, categoria, título, datas, localização, descrição e botão "Abrir site do evento". Cards são `<button>` em vez de `<a>`.
- **Biblioteca de vídeos** (`biblioteca.js` v3): cards redesenhados com estilos inline (compatível com Tailwind CSS compilado), play button sempre visível, fallback com gradiente, título uma única vez na seção `.video-info`.
- **Página de eventos** (`eventos.js`): removido `onclick="window.__eventosRetry()"` do botão de retry (CSP compliance), retry agora usa `addEventListener`.
- **Service Worker** (`sw.js`): handler de fetch atualizado para não retornar `undefined`.
- **Página de dúvidas**: todos os links `/dúvidas` corrigidos para `/duvidas` (sem acento) em 14 arquivos HTML + canonical/JSON-LD.

### Busca de Mecânicos
- **Overpass API**: queries combinadas em 2 union queries (antes eram 6 separadas), timeout aumentado de 25s para 45s — resolveu o problema de retornar 0 resultados.
- **`maps.js`**: adicionada função `isLoggedIn()` que faltava (causava crash).
- **Perfil de mecânico `serpapi_`**: tratamento adicionado para prefixo `serpapi_` no ID, com cache individual.

### Fluxo de Pagamento
- **`premium-modal.js`**: adicionada verificação `isAuthenticated()` antes de chamar `goToCheckout()` — redireciona para `/login?redirect={currentPage}` se não autenticado.
- **`planos-checkout.js`**: novo script externo que gerencia o clique no botão "Assinar Premium" com fallback para login.

### Infraestrutura e Qualidade
- **`.env`**: o arquivo contém todos os secrets em plaintext — **não deve ser commitado**. Verificar `git log` para confirmar se já foi; se sim, rotacionar TODAS as chaves.
- **Testes**: 17 arquivos de teste em `backend/tests/` (3.645 linhas) cobrindo auth, dashboard, payment, database, events, chat, marketing, B2B, analytics, geocode, maintenance, Mod Passport, AI cache, cron/webhook e Turnstile.

---

## 📝 Licença e Autoria

Ideia original de **Clara Francisco**.
Desenvolvido por **Júlio César**, **Caio Lima**, **Eduardo Nishida** e **Caio Yugo**.
