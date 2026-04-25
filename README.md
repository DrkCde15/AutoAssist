# AutoAssist IA 🚗💨

O **AutoAssist IA** é um ecossistema de inteligência artificial de última geração, desenvolvido especificamente para o mercado automotivo brasileiro. A plataforma integra Processamento de Linguagem Natural (NLP) e Visão Computacional para fornecer diagnósticos precisos, avaliações de mercado e consultoria técnica especializada, operando com alta performance através da integração com a API do **Google Gemini**.

---

## ✨ Funcionalidades

### **Recursos Inteligentes (NOG IA)**

- **Consultoria Especializada:** O assistente "NOG" utiliza o modelo **Gemini** para oferecer respostas focadas no mercado brasileiro, analisando modelos, manutenção e custo-benefício.
- **IA de Previsão de Manutenção:** Sistema que analisa descrições (ex: "Troquei o óleo hoje") e utiliza IA para prever a data e quilometragem da próxima revisão, mesmo quando não há dados manuais.
- **Raio-X Mecânico:** Análise visual avançada alimentada pelo **Gemini Vision** para identificação de ferrugem, desalinhamentos e vazamentos em fotos.

### **Dashboard e Gestão**

- **Histórico Proativo:** Painel que monitora a saúde das peças e indica o status de cada manutenção (Ok, Aviso ou Atrasado).
- **Notificações Instantâneas:** Sistema de e-mail que alerta o usuário **no mesmo dia** em que uma manutenção atinge o status crítico ou vence.
- **Tabela FIPE Real-Time:** Integração com a API FIPE para fornecer valores de mercado precisos e atualizados.
- **Biblioteca de Vídeos:** Recomendação automática de tutoriais baseados na conversa, salvos na galeria do usuário.

### **Segurança e Cloud**

- **Google OAuth 2.0:** Login simplificado e seguro utilizando contas Google.
- **Autenticação em Duas Etapas (2FA):** Camada de segurança adicional para proteção de dados sensíveis.
- **Cloud Resiliency:** Conectividade reforçada com suporte a SSL e timeouts otimizados para bancos de dados em nuvem (Aiven, RDS, etc).
- **Viva-Voz Inteligente:** Interação por voz nativa com detecção de silêncio (VAD).

---

## 🛠️ Tecnologias Utilizadas

### **Backend & Inteligência Artificial**

| Tecnologia            | Função                                                 |
| :-------------------- | :----------------------------------------------------- |
| **Flask**             | Servidor robusto e orquestração de APIs REST.          |
| **Google Gemini SDK** | Integração com Gemini 2.0 Flash (Texto e Visão).       |
| **PyMySQL + SSL**     | Conexão segura e resiliente com o banco de dados.      |
| **SMTP / Gmail**      | Motor de disparo de notificações proativas por e-mail. |
| **JWT**               | Autenticação moderna com Tokens de Acesso e Refresh.   |

### **Frontend**

| Tecnologia           | Função                                                     |
| :------------------- | :--------------------------------------------------------- |
| **Vanilla JS**       | Lógica de estado e consumo de APIs sem frameworks pesados. |
| **Glassmorphism UI** | Design moderno com transparências e animações dinâmicas.   |
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
DB_HOST=seu_host
DB_USER=seu_usuario
DB_PASSWORD=sua_senha
DB_NAME=seu_banco
GOOGLE_CLIENT_ID=seu_client_id_google
EMAIL_REMETENTE=seu_email@gmail.com
EMAIL_SENHA_APP=sua_senha_app_gmail
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
- **SSL Enforcement**: Todas as conexões de banco de dados utilizam criptografia SSL.
- **JWT Protection**: Endpoints protegidos garantem que apenas usuários autenticados acessem dados sensíveis.

---

## 📝 Licença e Autoria

Ideia original de **Clara Francisco**.
Desenvolvido por **Júlio César**, **Caio Lima**, **Eduardo Nishida** e **Caio Yugo** com suporte de **Antigravity AI**.
