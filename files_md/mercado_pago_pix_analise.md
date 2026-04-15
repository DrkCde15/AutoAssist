# Análise Completa: Integração de Pagamento Pix com a API do Mercado Pago

Com base nas informações mais atualizadas da documentação oficial do Mercado Pago e da web, elaborei um dossiê completo sobre como funciona a integração de pagamentos via **Pix** utilizando a respectiva API.

---

## 1. Visão Geral da Integração

A integração de pagamentos Pix no Mercado Pago permite que você gere cobranças instantâneas (representadas por um QR Code e um código "Copia e Cola") a partir do seu backend, exiba-as ao usuário final e, em seguida, receba confirmações em tempo real assim que o pagamento for consumado pelo cliente.

Existem diferentes rotas de integração, sendo as duas principais:
- **Checkout Bricks (Frontend + Backend):** Solução baseada em componentes visuais prontos oferecidos pelo Mercado Pago para montar a  tela de checkout em seu frontend e consumir a API pelo backend.
- **Integração via API (Apenas Backend):** Processo totalmente flexível e invisível onde seu software lida diretamente com os endpoints REST do Mercado Pago, processa o retorno e constrói sua própria interface no frontend.

## 2. Requisitos Iniciais

Antes de escrever qualquer código, sua conta de desenvolvedor precisa ter os seguintes itens:
1. **Credenciais da Aplicação:** É necessário criar uma aplicação no site `Mercado Pago Developers` e gerar um **Access Token** (Token de acesso). Você terá um token para o ambiente de testes (Test) e um para produção (Production).
2. **Chave Pix Cadastrada:** Para receber pagamentos Pix no modo produção (dinheiro real), a conta do Mercado Pago da sua empresa/projeto precisa obrigatoriamente ter uma chave Pix cadastrada.

---

## 3. Criação do Pagamento (Endpoint e Payload)

Para gerar uma cobrança, o seu backend deve realizar uma requisição HTTP `POST` ao endpoint principal de cobranças. 

- **Endpoint:** `POST https://api.mercadopago.com/v1/payments`
- **Headers Obrigatórios:**
  - `Authorization: Bearer <SEU_ACCESS_TOKEN>`
  - `X-Idempotency-Key` (Altamente recomendado): Um identificador único gerado pelo seu sistema para cada intenção de compra. Impede que, caso ocorra uma falha de rede e seu sistema faça um *retry*, o cliente seja cobrado duas vezes.

### Exemplo de Payload (Corpo da Requisição JSON)

A estrutura mínima exigida para realizar a cobrança:

```json
{
  "transaction_amount": 150.50,
  "description": "Pagamento de Assinatura - Plano Premium",
  "payment_method_id": "pix",
  "payer": {
    "email": "cliente.exemplo@dominio.com.br",
    "first_name": "João",
    "last_name": "Silva",
    "identification": {
      "type": "CPF",
      "number": "12345678909"
    }
  }
}
```

> [!NOTE]
> O campo `"payment_method_id"` deve ser obrigatoriamente definido como `"pix"`. Diferente de cartões de crédito, pagamentos por Pix não exigem o envio de dados sensíveis na requisição, tornando todo o fluxo bem mais simples e protegido.

---

## 4. O Retorno da API (Resposta JSON)

Assim que o Mercado Pago recebe a sua requisição `POST`, ele processa a solicitação e devolve uma resposta HTTP 201 (Created).

Dentro desta resposta JSON, o local mais importante para integrações via Pix é a chave `point_of_interaction`. Nela estarão os dados de que o cliente precisa para efetuar o pagamento bancário.

### Exemplo de Resposta:

```json
{
  "id": 1234567890,
  "status": "pending",
  ...
  "point_of_interaction": {
    "transaction_data": {
      "qr_code": "00020126580014BR.GOV.BCB.PIX...",
      "qr_code_base64": "iVBORw0KGgoAAAANSUhEUgAAAJYAAA...",
      "ticket_url": "https://www.mercadopago.com.br/payments/1234567890/ticket"
    }
  }
}
```

### O que fazer com estes dados no Frontend?
1. **`qr_code` (O Pix Copia e Cola):** Você exibe essa string alfanumérica juntamente com um botão "Copiar". Esta rota permite que indivíduos paguem usando o smartphone sem precisarem ler um código com a câmera celular.
2. **`qr_code_base64` (A imagem)**: Esta é a representação visual codificada em Base64 do QR Code, para exibição nas telas web. Você coloca ela diretamente no HTML de uma tag de imagem (ex: `<img src="data:image/jpeg;base64,...(STRING)..." />`).
3. **`ticket_url`:** É o link para o ambiente de checkout do próprio Mercado Pago, com layout pronto deles. Inclui as instruções para pagar, o QR e o código numérico.

---

## 5. Webhooks e Confirmação de Pagamento

O Pix é assíncrono. Na hora em que a API retorna o QR Code (no passo 4), o pagamento `status` é `"pending"`. Quando o cliente de fato levanta o celular no aplicativo bancário e paga, como seu sistema descobre isso?

Através dos **Webhooks** (Notificações).

### Fluxo de Confirmação:
1. Você cadastra uma URL pública do seu servidor no painel de desenvolvedor do Mercado Pago (exemplo: `https://sua-api.com.br/webhooks/mercadopago`).
2. Assim que o respectivo status do pagamento mudar (ex: aprovado), o Mercado Pago fará uma requisição POST na sua URL para te avisar, enviando os dados de notificação.
3. No recebimento da notificação, seu código não deve confiar cegamente no payload (medida de proteção). Você deve pegar o `id` da notificação e fazer um `GET` restrito no Mercado Pago:
   `GET https://api.mercadopago.com/v1/payments/{ID}`
4. Com a resposta autêntica de que o `status` está como `"approved"`, aí sim o seu sistema dá baixa no banco de dados e libera o serviço ao cliente.

---

## 6. Bibliotecas Oficiais e SDKs

Como vi você configurando arquivos Python localmente (`gateway.py`, `payment.py`), recomendo fortemente usar o SDK oficial do Mercado Pago para sua linguagem.

No **Python** (usando o SDK `mercadopago`):

```python
import mercadopago

# Inicializa o SDK
sdk = mercadopago.SDK("SEU_ACCESS_TOKEN")

payment_data = {
    "transaction_amount": 100.00,
    "description": "Serviço Mensal Premium",
    "payment_method_id": "pix",
    "payer": {
        "email": "test@test.com",
        "first_name": "Fulano",
        "last_name": "Silva",
        "identification": {
            "type": "CPF",
            "number": "19119119100"
        }
    }
}

# Realiza a requisição
payment_response = sdk.payment().create(payment_data)
payment = payment_response["response"]

# Acessa as propriedades geradas 
qr_code_copia_e_cola = payment["point_of_interaction"]["transaction_data"]["qr_code"]
status_pagamento = payment["status"]
```

## Considerações Finais e Dicas
- **Segurança primeiro:** A transação Pix pela API Mercado Pago exige apenas chaves do backend, portanto jamais exponha seu Access Token de Produção ou Teste a nível client-side (Frontend Vue, React, Angular). Toda a logística ocorre Server-side.
- **Ambiente de Sandbox:** Enquanto estiver construindo seu `gateway.py`, use as credenciais de **Teste** de sua conta do Mercado Pago para simulações completas de pagamento no painel "Contas de Teste" e valide todas as respostas (201 do POST e as notificações em Webhook).
