# AutoAssist Mobile

Esta branch (`feat/react-native`) concentra a conversao do AutoAssist para aplicativo mobile com Expo/React Native. O site permanece na branch `main`; nao use `git merge` desta branch para a `main`.

## Estrutura

```text
AutoAssist/
├── backend/   # API Flask, MySQL, Gemini, Cakto e rotas do produto
└── mobile/    # App Expo/React Native
```

## Backend

O backend continua sendo a API Flask usada pelo app mobile.

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Variaveis principais ficam em `backend/.env`:

```env
JWT_SECRET_KEY=...
DB_HOST=...
DB_PORT=3306
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
API_GEMINI=...
CAKTO_CHECKOUT_URL=...
CAKTO_WEBHOOK_SECRET=...
```

Nesta branch, o Flask nao depende mais de `frontend/public`. Se a pasta estatica nao existir, `/` responde como API mobile.

## Mobile

```bash
cd mobile
npm install
npm run start
```

Por padrao o app usa a API publicada em `https://autoassist-l9lr.onrender.com`.

Para usar o backend local, defina antes de iniciar o Expo:

```bash
# Android emulator
set EXPO_PUBLIC_API_URL=http://10.0.2.2:5000

# iOS simulator ou web
set EXPO_PUBLIC_API_URL=http://localhost:5000
```

## Funcionalidades Mobile

- Login, cadastro e verificacao 2FA.
- Sessao persistida com `expo-secure-store`.
- Dashboard com status da conta, veiculos e alertas.
- Chat NOG com texto e imagem via `expo-image-picker`.
- Garagem mobile com cadastro e exclusao de veiculos.
- Historico de manutencao premium e checkout Cakto.

## Verificacoes

```bash
cd mobile
npx tsc --noEmit

cd ..
python -m compileall backend
```
