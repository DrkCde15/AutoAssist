# AutoAssist Mobile

Aplicativo Expo/React Native do AutoAssist. Esta branch transforma a experiencia do site em app nativo consumindo a API Flask do backend.

## Get Started

Instale as dependencias:

```bash
npm install
```

Configure a URL da API se quiser usar o backend local:

```bash
# Android emulator
set EXPO_PUBLIC_API_URL=http://10.0.2.2:5000

# iOS simulator ou web
set EXPO_PUBLIC_API_URL=http://localhost:5000
```

Sem essa variavel, o app usa `https://autoassist-l9lr.onrender.com`.

Inicie o Expo para abrir no Expo Go:

```bash
npx expo start --tunnel
```

## Implementado

- Login, cadastro e 2FA.
- Persistencia de sessao com `expo-secure-store`.
- Dashboard, chat NOG, envio de imagem para analise, garagem, manutencoes premium e perfil.
- Checkout premium pela mesma rota Cakto do backend.
- QR Code para Expo Go, sem development build.

## Backend

O backend Flask continua em `../backend`. A pasta `frontend` nao e necessaria para rodar o app mobile nativo.

## Observacoes

- Esta branch nao deve ser mergeada na `main`.
- Use `npm` neste projeto; `bun.lock` foi removido porque o ambiente nao possui Bun.
