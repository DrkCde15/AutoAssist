// @ts-check
const { test, expect } = require("@playwright/test");

const BASE_URL = "http://127.0.0.1:5000";

test.describe("Responsividade da landing page", () => {
  test("CT-013: o hero nao deve vazar horizontalmente em telas pequenas", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 800 });
    await page.goto(`${BASE_URL}/index.html`);
    await page.waitForSelector(".brand-hero h1");

    const result = await page.evaluate(() => {
      const title = document.querySelector(".brand-hero h1");
      if (!title) {
        return { ok: false, clientWidth: 0, scrollWidth: 0 };
      }

      return {
        ok: title.scrollWidth <= title.clientWidth + 1,
        clientWidth: title.clientWidth,
        scrollWidth: title.scrollWidth,
      };
    });

    expect(result.ok).toBe(true);
  });
});
