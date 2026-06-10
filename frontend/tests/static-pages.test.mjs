import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const publicDir = join(root, "public");

function readPublic(relativePath) {
  return readFileSync(join(publicDir, relativePath), "utf8");
}

describe("legal and analytics static pages", () => {
  const legalPages = ["termos.html", "privacidade.html", "lgpd.html", "analytics.html"];

  for (const page of legalPages) {
    it(`${page} is available and linked to the legal set`, () => {
      const html = readPublic(page);

      assert.match(html, /AutoAssist/);
      assert.match(html, /termos\.html/);
      assert.match(html, /privacidade\.html/);
      assert.match(html, /lgpd\.html/);
      assert.match(html, /analytics\.html/);
      assert.match(html, /data-legal-nav/);
      assert.match(html, /static\/js\/auth\.js/);
      assert.match(html, /static\/js\/legal-nav\.js/);
    });
  }

  it("home footer exposes legal links", () => {
    const html = readPublic("index.html");

    assert.match(html, /termos\.html/);
    assert.match(html, /privacidade\.html/);
    assert.match(html, /lgpd\.html/);
    assert.match(html, /analytics\.html/);
  });

  it("only the home page loads analytics consent script", () => {
    const pages = [
      "cadastro.html",
      "chat.html",
      "dashboard.html",
      "esqueci-senha.html",
      "feedback.html",
      "index.html",
      "library.html",
      "login.html",
      "maintenance_history.html",
      "pagamento-sucesso.html",
      "perfil.html",
      "redefinir-senha.html",
      ...legalPages,
    ];

    for (const page of pages) {
      const assertion = page === "index.html" ? assert.match : assert.doesNotMatch;
      assertion(
        readPublic(page),
        /static\/js\/analytics-consent\.js/,
        `${page} should ${page === "index.html" ? "include" : "not include"} analytics consent script`
      );
    }
  });

  it("signup confirms password before sending registration", () => {
    const html = readPublic("cadastro.html");
    const authScript = readPublic("static/js/auth.js");

    assert.match(html, /id="confirmSenha"/);
    assert.match(html, /id="toggleConfirmSenha"/);
    assert.match(html, /As senhas informadas .* conferem\./);
    assert.match(html, /Auth\.register\(nome, email, confirmEmail, senha, confirmSenha, veiculos\)/);
    assert.match(authScript, /confirm_password: confirmPassword/);
  });

  it("home page does not force login redirects for stale sessions", () => {
    const html = readPublic("index.html");
    const authScript = readPublic("static/js/auth.js");

    assert.match(authScript, /""/);
    assert.match(authScript, /"index\.html"/);
    assert.match(html, /Auth\.syncUser\(\{ redirectOnInvalid: false, force: true \}\)/);
    assert.doesNotMatch(html, /Auth\.authenticatedFetch\('\/api\/user'\)/);
  });

  it("analytics client blocks sensitive metadata and posts to the expected endpoint", () => {
    const script = readPublic("static/js/analytics-consent.js");
    const blockedKeys = ["password", "token", "email", "cpf", "placa", "message", "photo", "audio"];

    for (const key of blockedKeys) {
      assert.match(script, new RegExp(`"${key}"`));
    }

    assert.match(script, /\/api\/analytics\/events/);
    assert.match(script, /autoassist_analytics_consent/);
  });

  it("legal nav switches between public and authenticated links", () => {
    const script = readPublic("static/js/legal-nav.js");

    assert.match(script, /login\.html/);
    assert.match(script, /cadastro\.html/);
    assert.match(script, /chat\.html/);
    assert.match(script, /perfil\.html/);
    assert.match(script, /data-aa-logout/);
    assert.match(script, /Auth\.isAuthenticated/);
  });
});
