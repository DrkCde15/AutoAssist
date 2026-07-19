// Testes unitarios para security-utils.js (roda com node, sem browser).
const assert = require("assert");
const { escapeHTML, setSafeText } = require("../../public/static/js/security-utils.js");

// 1) escapeHTML neutraliza tags e atributos perigosos
const payload = '<img src=x onerror=alert(1)>';
const escaped = escapeHTML(payload);
assert.ok(!escaped.includes("<img"), "tags devem ser escapadas");
assert.ok(escaped.includes("&lt;img"), "esperado &lt;img");
// Apos o escape, nao deve restar NENHUMA tag HTML crua (apenas entidades &lt; ...).
assert.ok(!/<[a-z][\s\S]*>/i.test(escaped), "nenhuma tag HTML crua deve restar apos escape");

// 2) aspas e apostrofos escapados
assert.strictEqual(escapeHTML('a"b\'c'), "a&quot;b&#039;c");

// 3) setSafeText usa textContent (nao innerHTML) -> simula via jsdom-free stub
function FakeEl() {
  this.children = [];
  this._textContent = "";
  Object.defineProperty(this, "textContent", {
    get() { return this._textContent; },
    set(v) { this._textContent = v; this.children = []; },
  });
  this.appendChild = function (node) { this.children.push(node); };
  this._text = function () {
    return this._textContent + this.children.map((c) => c.text || c.textContent || "").join("");
  };
}
global.document = {
  createElement: function (tag) {
    return { tag: tag, text: "", set textContent(v) { this.text = v; }, get textContent() { return this.text; } };
  },
  createTextNode: function (txt) {
    return { text: String(txt) };
  },
};
const el = new FakeEl();
setSafeText(el, '<b>hack</b>', "Erro: ");
const rendered = el._text();
// O texto malicioso deve aparecer COMO TEXTO (nao como elemento interpretado).
// Se fosse interpretado, nao haveria a string literal '<b>hack</b>' no texto.
assert.ok(rendered.includes("<b>hack</b>"), "texto bruto deve estar presente como texto (nao interpretado)");
assert.ok(rendered.includes("Erro: "), "prefixo deve estar presente");
assert.strictEqual(el.children.length, 2, "deve ter prefixo + no de texto, sem tags filhas");

console.log("OK: security-utils passou em todos os asserts");
