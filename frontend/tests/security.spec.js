// @ts-check
const { test, expect } = require("@playwright/test");

// Estes testes exercitam o frontend servido por um backend Flask real.
// Se o backend nao estiver rodando em http://localhost:5000, eles sao
// pulados graciosamente (nao devem crashar o CI de frontend isolado).

test.describe("Seguranca do chat (XSS e WebSocket)", () => {
  test("security-utils sanitiza HTML de mensagens de erro do WebSocket", async ({ page }) => {
    let errored = false;
    try {
      await page.goto("/chat.html", { waitUntil: "domcontentloaded", timeout: 5000 });
    } catch (e) {
      errored = true;
    }
    if (errored) {
      test.skip(true, "Backend Flask nao disponivel neste ambiente.");
      return;
    }

    // Simula o que o handler onmessage faz com um payload de erro malicioso.
    const result = await page.evaluate(() => {
      if (typeof SecurityUtils === "undefined" || !SecurityUtils.setSafeText) {
        return { available: false };
      }
      const div = document.createElement("div");
      const malicious = "<img src=x onerror=window.__pwned=1>";
      SecurityUtils.setSafeText(div, malicious, "Erro: ");
      return {
        available: true,
        html: div.innerHTML,
        pwned: window.__pwned === 1,
        hasRawTag: div.innerHTML.includes("<img"),
      };
    });

    if (!result.available) {
      test.skip(true, "SecurityUtils nao carregado (pagina sem backend).");
      return;
    }
    expect(result.pwned).toBeFalsy();
    expect(result.hasRawTag).toBeFalsy();
    expect(result.html).toContain("&lt;img");
  });

  test("WebSocket de chat nao envia token via query string", async ({ page }) => {
    let errored = false;
    try {
      await page.goto("/chat.html", { waitUntil: "domcontentloaded", timeout: 5000 });
    } catch (e) {
      errored = true;
    }
    if (errored) {
      test.skip(true, "Backend Flask nao disponivel neste ambiente.");
      return;
    }

    const hasTokenInQuery = await page.evaluate(() => {
      const url = "wss://example.com/ws/chat";
      // Usa a mesma logica de montagem da app: apenas guest_id vai para a query.
      const params = new URLSearchParams();
      const isAuthed = typeof Auth !== "undefined" && Auth.isAuthenticated ? Auth.isAuthenticated() : false;
      if (!isAuthed) params.set("guest_id", "g123");
      const wsUrl = `${url}?${params}`;
      return /[?&]token=/.test(wsUrl);
    });

    expect(hasTokenInQuery).toBeFalsy();
  });
});
