# Analise de Vulnerabilidades de Seguranca - AutoAssist

## Resumo Executivo

Este documento consolida vulnerabilidades identificadas no backend e frontend do AutoAssist, com priorizacao por impacto, explorabilidade e risco ao negocio.

Principais conclusoes:
- Existem falhas criticas em autenticacao, sessao e controle de acesso.
- Existem vetores reais de XSS persistente/DOM no frontend.
- O fluxo de pagamentos precisa de validacoes de negocio mais fortes no backend.

## Escopo da Analise

Backend:
- `backend/app.py`
- `backend/routes/auth.py`
- `backend/routes/pages.py`
- `backend/routes/payment.py`
- `backend/routes/gateway.py`
- `backend/routes/database.py`
- `backend/services/*`

Frontend:
- `frontend/index.html`
- `frontend/chat.html`
- `frontend/dashboard.html`
- `frontend/perfil.html`
- `frontend/videos.html`
- `frontend/static/js/auth.js`

Severidade:
- `P1` Critico (corrigir imediatamente)
- `P2` Alto (corrigir em seguida)
- `P3` Medio (proximo ciclo)

---

## P1 - Vulnerabilidades Criticas

### 1. Endpoint de reembolso sem autenticacao/autorizacao

**Local**: `backend/routes/gateway.py` (`/pagamentos/payments/<payment_id>/reembolso`)

**Descricao**: O endpoint de reembolso nao exige JWT e nao aplica RBAC.

**Impacto**:
- Risco financeiro direto.
- Possivel abuso automatizado de reembolsos.

**Correcao recomendada**:
- Exigir `@jwt_required()`.
- Permitir apenas perfil administrativo.
- Auditar toda acao de reembolso (usuario, payment_id, valor, timestamp, ip).

---

### 2. Bypass sistemico de premium/trial

**Locais**: `backend/routes/auth.py`, `backend/routes/pages.py`, `backend/routes/database.py`, `frontend/static/js/auth.js`

**Descricao**:
- `is_premium` retornado como `True` em varios fluxos.
- Trial hardcoded (`trial_expired=False`, `trial_days_remaining=9999`).
- Checks premium neutralizados (`ensure_premium_user` e `if True: User is always premium`).
- Frontend tambem forza `user.is_premium = true`.

**Impacto**:
- Quebra total de monetizacao.
- Exposicao de recursos premium para usuarios nao pagantes.

**Correcao recomendada**:
- Centralizar regra premium/trial no backend.
- Remover hardcodes no backend e frontend.
- Aplicar gate de premium no backend para toda rota sensivel.

---

### 3. Tokens JWT em query string no OAuth callback

**Local**: `backend/routes/auth.py` + `frontend/index.html`

**Descricao**:
- `access_token` e `refresh_token` sao enviados pela URL.
- Frontend consome da query string e persiste em `localStorage`.

**Impacto**:
- Vazamento por historico, logs, analytics e `Referer`.
- Sequestro de sessao.

**Correcao recomendada**:
- Nao trafegar token em URL.
- Usar cookie `HttpOnly + Secure + SameSite`.
- Usar codigo temporario (one-time) para troca segura no backend.

---

### 4. OAuth sem parametro `state` (login CSRF / account confusion)

**Local**: `backend/routes/auth.py`

**Descricao**:
- Fluxo Google OAuth nao valida `state`.

**Impacto**:
- Vinculacao de sessao/conta errada.
- Risco de ataques de login CSRF.

**Correcao recomendada**:
- Gerar `state` criptograficamente aleatorio.
- Armazenar e validar no callback.
- Expirar estado apos uso.

---

### 5. XSS persistente no historico de chat

**Local**: `backend/routes/pages.py` + `frontend/chat.html`

**Descricao**:
- Respostas sao salvas e depois renderizadas com `marked.parse` sem sanitizacao no carregamento de historico.

**Impacto**:
- Execucao de JavaScript no navegador do usuario.
- Roubo de token (especialmente por uso de `localStorage`).

**Correcao recomendada**:
- Sanitizar SEMPRE com DOMPurify antes de inserir HTML.
- Desabilitar HTML cru no parser markdown.
- Considerar sanitizacao adicional no backend.

---

### 6. Exposicao de laudos PDF em pasta estatica publica

**Local**: `backend/routes/pages.py` + `backend/app.py`

**Descricao**:
- Arquivos de laudo sao gravados em `frontend/reports` e expostos por URL previsivel.

**Impacto**:
- Possivel acesso indevido a dados de terceiros por enumeracao de URL.

**Correcao recomendada**:
- Armazenar fora de pasta estatica publica.
- Servir via endpoint autenticado com checagem de ownership.
- Usar nomes aleatorios nao previsiveis e expiracao de acesso.

---

## P2 - Vulnerabilidades Altas

### 7. XSS DOM em paginas de videos, dashboard, perfil e cards do chat

**Local**: `frontend/videos.html`, `frontend/dashboard.html`, `frontend/perfil.html`, `frontend/chat.html`, `frontend/static/js/auth.js`

**Descricao**:
- Uso extensivo de `innerHTML` com dados vindos da API/usuario (`url`, `titulo`, `descricao`, campos de veiculo).

**Impacto**:
- Execucao de scripts em contexto autenticado.
- Comprometimento da sessao e operacoes em nome do usuario.

**Correcao recomendada**:
- Trocar `innerHTML` por `textContent` sempre que possivel.
- Sanitizar estritamente campos que precisarem de HTML.
- Validar URLs no backend (`http/https`, dominio esperado quando aplicavel).

---

### 8. Validacao de pagamento insuficiente para upgrade premium

**Local**: `backend/routes/payment.py` e `backend/routes/gateway.py`

**Descricao**:
- O backend confia em partes do payload de criacao de pagamento e confirma upgrade principalmente por status/aprovacao.
- Nao ha validacao consolidada de plano/valor/moeda no fechamento.

**Impacto**:
- Risco de fraude de valor/plano.
- Inconsistencia comercial.

**Correcao recomendada**:
- Criar tabela de pedidos internos (valor esperado, plano, moeda, user_id).
- Confirmar upgrade apenas se pagamento casar com pedido interno.

---

### 9. Possivel Host Header Poisoning no reset de senha

**Local**: `backend/routes/auth.py`

**Descricao**:
- Fallback para `request.host_url` na composicao do link de redefinicao.

**Impacto**:
- Envio de links maliciosos se host header for manipulado no proxy/deploy.

**Correcao recomendada**:
- Exigir `FRONTEND_URL` fixo por ambiente.
- Nao usar `host_url` de requisicao para links de email.

---

### 10. Sessao em `localStorage` + refresh token longo

**Local**: `frontend/static/js/auth.js` + `backend/app.py`

**Descricao**:
- Tokens em `localStorage`.
- `JWT_REFRESH_TOKEN_EXPIRES=365 dias`.

**Impacto**:
- Em caso de XSS, comprometimento de longa duracao.

**Correcao recomendada**:
- Migrar para cookie `HttpOnly`.
- Reduzir janela de refresh token.
- Implementar rotacao e revogacao de refresh token.

---

### 11. Upload sem limite de tamanho (audio/imagem)

**Local**: `backend/routes/pages.py`, `backend/services/vision_ai.py`

**Descricao**:
- Processamento de audio e imagem sem `MAX_CONTENT_LENGTH` e sem validacao forte de tamanho.

**Impacto**:
- DoS por consumo de memoria/CPU.

**Correcao recomendada**:
- Definir `MAX_CONTENT_LENGTH`.
- Validar tamanho/tipo antes de processar.
- Rejeitar payloads acima do limite.

---

### 12. Rate limiting fraco e sem limite por endpoint critico

**Local**: `backend/app.py`

**Descricao**:
- Limites genericos e armazenamento em memoria.
- Falta rate limit especifico para login, 2FA, reset de senha e pagamento.

**Impacto**:
- Maior risco de brute force e abuso.

**Correcao recomendada**:
- Redis para limiter.
- Regras por endpoint sensivel.
- Bloqueio progressivo por falhas.

---

## P3 - Vulnerabilidades Medias

### 13. Ausencia de CSP

**Local**: `backend/app.py`

**Descricao**:
- `content_security_policy=None`.

**Impacto**:
- Reduz defesa em profundidade contra XSS.

**Correcao recomendada**:
- Definir CSP minima e evoluir para politica mais restritiva.

---

### 14. Exposicao de detalhes de erro ao cliente

**Local**: `backend/routes/gateway.py`

**Descricao**:
- Algumas respostas retornam `details` com erro bruto de integracao.

**Impacto**:
- Vazamento de informacao tecnica.

**Correcao recomendada**:
- Retorno generico ao cliente.
- Detalhe apenas em log interno.

---

### 15. Endpoint legado `/api/pay/mock` ativo

**Local**: `backend/routes/payment.py`

**Descricao**:
- Rota de mock ativa em fluxo de confirmacao.

**Impacto**:
- Superficie extra de ataque e confusao operacional.

**Correcao recomendada**:
- Remover em producao ou isolar por ambiente.

---

### 16. CORS com origens de dev e prod no mesmo bloco

**Local**: `backend/app.py`

**Descricao**:
- Lista unica mistura localhost com dominios de producao.

**Impacto**:
- Risco de configuracao incorreta em deploy.

**Correcao recomendada**:
- Separar CORS por ambiente.

---

### 17. `target="_blank"` sem `rel="noopener noreferrer"` em links dinamicos

**Local**: `frontend/chat.html`, `frontend/videos.html`

**Descricao**:
- Links externos abrem nova aba sem protecao consistente.

**Impacto**:
- Risco de tabnabbing.

**Correcao recomendada**:
- Adicionar `rel="noopener noreferrer"` em todos os links externos com `target="_blank"`.

---

### 18. Dependencias de CDN sem SRI

**Local**: paginas frontend com scripts/styles de terceiros

**Descricao**:
- Recursos externos carregados sem `integrity`/`crossorigin`.

**Impacto**:
- Maior risco de supply chain no cliente.

**Correcao recomendada**:
- Fixar versoes, usar SRI e preferir bundle local para libs criticas.

---

### 19. 2FA nao padrao + segredo curto

**Local**: `backend/routes/auth.py`

**Descricao**:
- Fluxo chamado de 2FA funciona como senha secundaria (bcrypt), com minimo de 4 caracteres.

**Impacto**:
- Seguranca inferior a TOTP.
- Maior chance de brute force sem limite especifico.

**Correcao recomendada**:
- Migrar para TOTP (`pyotp`) com codigos de recuperacao.
- Aumentar rigor de politica de senha secundaria durante migracao.

---

## Observacao Sobre IDOR

O risco de IDOR existe, mas nao e uma afirmacao universal para todas as rotas.
Ha endpoints com ownership-check correto (ex.: veiculos, videos e verificacao de `external_reference` em pagamento).

Recomendacao:
- Construir matriz `endpoint x ownership-check`.
- Corrigir apenas lacunas reais.

---

## Plano de Acao Priorizado

### Fase 0 - Contencao imediata (24-48h)
1. Proteger endpoint de reembolso com JWT + RBAC.
2. Remover bypass premium/trial (backend e frontend).
3. Remover JWT de query string no OAuth.
4. Implementar `state` no OAuth.
5. Corrigir XSS persistente do historico do chat.
6. Tirar laudos PDF da area estatica publica.

### Fase 1 - Hardening principal (Semana 1)
7. Corrigir XSS DOM nas telas com `innerHTML`.
8. Endurecer validacao de pagamentos (pedido interno + valor/plano/moeda).
9. Fixar `FRONTEND_URL` para reset de senha.
10. Adotar limite de upload e protecoes anti-DoS.
11. Reforcar rate limiting por endpoint critico.

### Fase 2 - Defesa em profundidade (Semanas 2-3)
12. Ativar CSP e evoluir politica.
13. Padronizar mensagens de erro sem vazamento tecnico.
14. Remover rota mock em producao.
15. Separar CORS por ambiente.
16. Adicionar `rel=noopener` e SRI.
17. Migrar 2FA para TOTP.

---

## Checklist de Verificacao Pos-Correcao

1. Reembolso rejeita chamadas sem autenticacao e sem permissao.
2. Usuario nao premium nao acessa recursos premium em nenhum fluxo.
3. OAuth nao trafega token em URL e valida `state`.
4. Historico de chat nao executa HTML/script injetado.
5. Telas de videos/dashboard/perfil/chat nao renderizam payload injetavel.
6. Pagamento so gera upgrade quando casar com pedido interno esperado.
7. Links de reset usam dominio fixo confiavel.
8. Tokens nao ficam expostos em `localStorage` (ou janela de risco foi reduzida com controles compensatorios).
9. Upload acima do limite e rejeitado.
10. Laudos so sao acessiveis pelo dono autenticado.
11. Rotas sensiveis respeitam rate limit especifico.

---

## Conclusao

As prioridades imediatas seguem sendo autenticacao/autorizacao, sessao segura e eliminacao de vetores reais de XSS.
Com as correcoes de Fase 0 e Fase 1, o risco tecnico e financeiro do produto cai de forma significativa e mensuravel.
