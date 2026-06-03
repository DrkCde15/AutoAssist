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
      assert.match(html, /static\/js\/analytics-consent\.js/);
    });
  }

  it("home footer exposes legal links", () => {
    const html = readPublic("index.html");

    assert.match(html, /termos\.html/);
    assert.match(html, /privacidade\.html/);
    assert.match(html, /lgpd\.html/);
    assert.match(html, /analytics\.html/);
  });

  it("all public html pages load analytics consent script", () => {
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
      assert.match(
        readPublic(page),
        /static\/js\/analytics-consent\.js/,
        `${page} should include analytics consent script`
      );
    }
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
});
