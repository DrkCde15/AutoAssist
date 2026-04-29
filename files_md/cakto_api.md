# Documentacao Consolidada da API Cakto

## 1) Visao geral da API

- Plataforma: Cakto API (REST)
- URL base: `https://api.cakto.com.br/`
- Autenticacao: OAuth2 com `client_id` e `client_secret`
- Formato comum:
  - Header: `Authorization: Bearer <access_token>`
  - Header: `Content-Type: application/json` (para endpoints JSON)
- Listagens seguem paginação padrao (`count`, `next`, `previous`, `results`)

## 2) Credenciais e token

### Credenciais
- `client_id`: identifica sua aplicacao
- `client_secret`: autentica sua aplicacao

### Endpoint de token
- `POST /public_api/token/`
- URL completa: `https://api.cakto.com.br/public_api/token/`
- Content-Type: `application/x-www-form-urlencoded`
- Campos esperados (conforme exemplos oficiais):
  - `client_id`
  - `client_secret`

### Exemplo de resposta de sucesso
- `access_token`
- `expires_in` (ex.: 36000 = 10h)
- `token_type` (Bearer)
- `scope` (ex.: `read write products offers orders`)

## 3) Escopos (scopes)

A documentacao indica uso de escopos por recurso e acao, por exemplo:
- `read webhooks`
- `write webhooks`
- `read` / `write` (base)
- outros escopos por recurso (products, offers, orders etc.)

Boas praticas destacadas na docs:
- guardar `client_secret` em variavel de ambiente
- nao expor credenciais no frontend
- usar principio do menor privilegio

## 4) Endpoints de Webhooks

### 4.1) Listar webhooks
- `GET /public_api/webhook/`
- Escopo: leitura de webhooks
- Suporta filtro/paginacao/busca/ordenacao

### 4.2) Criar webhook
- `POST /public_api/webhook/`
- Escopo: `write webhooks`
- Campos principais no body:
  - `name`
  - `url`
  - `products` (lista)
  - `events` (lista de `custom_id`)
  - `status` (ex.: `active`)

### 4.3) Obter webhook
- `GET /public_api/webhook/{id}/`
- Escopo: `read webhooks`

### 4.4) Atualizar webhook
- `PUT /public_api/webhook/{id}/`
- Escopo: `write webhooks`

### 4.5) Deletar webhook
- `DELETE /public_api/webhook/{id}/`
- Escopo: `write webhooks`

### 4.6) Historico de eventos do webhook
- `GET /public_api/webhook/event_history/`
- Escopo: `read webhooks`
- Query de paginacao:
  - `limit`
  - `page`
- Filtros documentados:
  - `id`
  - `app_id`
  - `event_id`
  - `event_status` (+ operadores `__gt`, `__gte`, `__lt`, `__lte`)
  - `sentAt` (+ operadores `__gt`, `__gte`, `__lt`, `__lte`)

### 4.7) Reenviar evento do historico
- `POST /public_api/webhook/event_resend/{id}/`
- Escopo: `write webhooks`
- Resposta esperada: `{"detail": "Evento reenviado com sucesso"}`

### 4.8) Enviar evento de teste para webhook
- `POST /public_api/webhook/event_test/{id}/`
- Escopo: `write webhooks`
- Query param:
  - `event_id` (tipo de evento que deseja testar)

## 5) Eventos de webhook mapeados

Eventos observados na docs:
- `initiate_checkout`
- `checkout_abandonment`
- `purchase_approved`
- `purchase_refused`
- `pix_gerado`
- `boleto_gerado`
- `picpay_gerado`
- `openfinance_nubank_gerado`
- `chargeback`
- `refund`
- `subscription_created`
- `subscription_renewed`
- `subscription_canceled`
- `subscription_renewal_refused`

## 6) Estrutura de payload de evento (amostra real da docs)

No historico de eventos de webhook, aparece payload com estrutura:
- `event` (ex.: `purchase_approved`)
- `secret`
- `data` com campos como:
  - `id`
  - `refId`
  - `status` (ex.: `paid`)
  - `amount`
  - `paidAt`
  - `paymentMethod`, `paymentMethodName`
  - `customer` (`name`, `email`, `phone`, `docType`, `docNumber`)
  - `product` e `offer`
  - `checkoutUrl`
  - `subscription` (quando aplicavel)

## 7) Outros grupos de endpoints existentes na docs (menu)

A navegacao oficial mostra tambem:
- Pedidos:
  - `GET` Listar Pedidos
  - `GET` Obter Pedido
  - `POST` Reembolsar Pedido
  - `POST` Reenviar Email de Aprovacao
  - `POST` Reenviar Acesso
- Produtos:
  - `GET` Listar Produtos
  - `GET` Obter Produto
  - `PUT` Atualizar Produto
- Ofertas:
  - `GET` Listar Ofertas
  - `POST` Criar Oferta
  - `GET` Obter Oferta
  - `PUT` Atualizar Oferta
  - `DELETE` Deletar Oferta

Observacao: os detalhes completos desses grupos (body, filtros e respostas) nao foram todos extraidos nesta consolidacao, mas os endpoints constam no menu oficial.

## 8) Como isso conversa com o AutoAssist (estado atual)

No projeto AutoAssist, o fluxo atual esta assim:
- Checkout do usuario: via `CAKTO_CHECKOUT_URL` (link de pagamento)
- Ativacao premium: via webhook recebido no backend
- Seguranca webhook: validacao de `CAKTO_WEBHOOK_SECRET`

Campos de ambiente usados no projeto:
- `CLIENT_ID`
- `CLIENT_SECRET`
- `CAKTO_CHECKOUT_URL`
- `CAKTO_WEBHOOK_SECRET`
- `CAKTO_APPEND_REF`
- `CAKTO_ACCEPT_QUERY_SECRET`
- `BASE_URL` (quando necessario para chamadas da API)

## 9) Recomendacao de hardening (proximo passo)

Para confirmacao ativa antes de liberar premium:
1. Receber webhook
2. Obter `access_token` com `CLIENT_ID/CLIENT_SECRET`
3. Consultar pedido/assinatura na API Cakto
4. Validar status final (`paid`/`approved`/assinatura ativa)
5. So entao atualizar `users.is_premium`

## 10) Links oficiais usados nesta consolidacao

- Introducao: https://docs.cakto.com.br/
- Introducao (slug): https://docs.cakto.com.br/introduction
- Autenticacao: https://docs.cakto.com.br/authentication
- Listar Webhooks: https://docs.cakto.com.br/api-reference/webhooks/list
- Criar Webhook: https://docs.cakto.com.br/api-reference/webhooks/create
- Obter Webhook: https://docs.cakto.com.br/api-reference/webhooks/retrieve
- Atualizar Webhook: https://docs.cakto.com.br/api-reference/webhooks/update
- Deletar Webhook: https://docs.cakto.com.br/api-reference/webhooks/delete
- Historico de Eventos: https://docs.cakto.com.br/api-reference/webhooks/event-history
- Reenviar Evento: https://docs.cakto.com.br/api-reference/webhooks/resend-event
- Evento de Teste: https://docs.cakto.com.br/api-reference/webhooks/test-webhook
