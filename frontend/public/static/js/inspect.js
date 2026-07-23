const { chromium } = require('playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');

const PUBLIC_DIR = path.join(__dirname, 'public');
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.svg': 'image/svg+xml',
};

// Simple static server
function startServer(port) {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      let filePath = path.join(PUBLIC_DIR, req.url === '/' ? '/chat.html' : req.url.split('?')[0]);
      const ext = path.extname(filePath);
      fs.readFile(filePath, (err, data) => {
        if (err) {
          res.writeHead(404); res.end('Not found');
        } else {
          res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
          res.end(data);
        }
      });
    });
    srv.listen(port, () => resolve(srv));
  });
}

(async () => {
  const server = await startServer(0);
  const port = server.address().port;
  const baseUrl = `http://localhost:${port}`;

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 375, height: 812 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();

  // Suppress service worker registration errors
  await page.addInitScript(() => {
    navigator.serviceWorker.register = () => Promise.resolve({});
    navigator.serviceWorker.ready = Promise.resolve({ active: {} });
  });

  console.log('=== NAVEGANDO PARA CHAT.HTML ===');
  await page.goto(baseUrl, { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(500);

  // 1. Check #btnNewChat existence
  const btnExists = await page.$('#btnNewChat');
  console.log(`\n1. #btnNewChat existe no DOM: ${!!btnExists}`);

  if (btnExists) {
    // Bounding rect
    const rect = await btnExists.boundingBox();
    console.log(`\n2. getBoundingClientRect:`);
    console.log(`   x: ${rect?.x}, y: ${rect?.y}, width: ${rect?.width}, height: ${rect?.height}`);

    // Computed styles
    const styles = await btnExists.evaluate(el => {
      const cs = getComputedStyle(el);
      return {
        display: cs.display,
        visibility: cs.visibility,
        opacity: cs.opacity,
        position: cs.position,
        top: cs.top,
        left: cs.left,
        width: cs.width,
        height: cs.height,
        zIndex: cs.zIndex,
        transform: cs.transform,
        overflow: cs.overflow,
        background: cs.background,
        color: cs.color,
      };
    });
    console.log(`\n3. Computed styles:`);
    for (const [k, v] of Object.entries(styles)) {
      console.log(`   ${k}: ${v}`);
    }

    // Check if within viewport
    const vp = page.viewportSize();
    const isInViewport = rect && rect.x < vp.width && rect.y < vp.height && rect.x + rect.width > 0 && rect.y + rect.height > 0;
    console.log(`\n4. Dentro da viewport (${vp.width}x${vp.height}): ${isInViewport}`);

    // Check for covering elements
    if (rect) {
      const centerX = rect.x + rect.width / 2;
      const centerY = rect.y + rect.height / 2;
      const topEl = await page.evaluate(({ x, y }) => {
        const el = document.elementFromPoint(x, y);
        return el ? { tag: el.tagName, id: el.id, className: el.className, text: (el.textContent || '').slice(0, 40) } : null;
      }, { x: centerX, y: centerY });
      console.log(`\n5. Elemento no centro do botão (elementFromPoint):`);
      console.log(`   ${JSON.stringify(topEl, null, 2)}`);
      if (topEl && topEl.id !== 'btnNewChat') {
        console.log(`   ⚠️ OUTRO elemento está cobrindo o #btnNewChat!`);
      }
    }
  }

  // 6. Sidebar structure
  console.log(`\n6. Estrutura da sidebar (#chatSidebar):`);
  const sidebarHTML = await page.evaluate(() => {
    const sidebar = document.getElementById('chatSidebar');
    if (!sidebar) return 'SIDEBAR NÃO ENCONTRADA';
    const children = [];
    sidebar.querySelectorAll(':scope > *').forEach(child => {
      const sub = [];
      child.querySelectorAll(':scope > *').forEach(subChild => {
        sub.push({
          tag: subChild.tagName,
          id: subChild.id,
          className: subChild.className,
          visible: getComputedStyle(subChild).display !== 'none' && getComputedStyle(subChild).visibility !== 'hidden',
        });
      });
      children.push({
        tag: child.tagName,
        id: child.id,
        className: child.className,
        children: sub,
      });
    });
    return children;
  });
  console.log(JSON.stringify(sidebarHTML, null, 2));

  // 7. Sidebar position
  const sidebarPos = await page.evaluate(() => {
    const sidebar = document.getElementById('chatSidebar');
    if (!sidebar) return null;
    const rect = sidebar.getBoundingClientRect();
    const cs = getComputedStyle(sidebar);
    return {
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      transform: cs.transform,
      position: cs.position,
      display: cs.display,
    };
  });
  console.log(`\n7. Posição da sidebar:`);
  console.log(JSON.stringify(sidebarPos, null, 2));

  // 8. Open sidebar and check again
  console.log(`\n8. Abrindo sidebar...`);
  const toggleBtn = await page.$('#btnSidebar');
  if (toggleBtn) {
    await toggleBtn.click();
    await page.waitForTimeout(500);
    
    const bodyClass = await page.evaluate(() => document.body.className);
    console.log(`   body classList: ${bodyClass}`);

    // Check btnNewChat after opening sidebar
    const btn2 = await page.$('#btnNewChat');
    if (btn2) {
      const rect2 = await btn2.boundingBox();
      console.log(`   #btnNewChat após abrir sidebar: x=${rect2?.x}, y=${rect2?.y}, w=${rect2?.width}, h=${rect2?.height}`);
      const vp2 = page.viewportSize();
      const visible2 = rect2 && rect2.x < vp2.width && rect2.y < vp2.height && rect2.x + rect2.width > 0 && rect2.y + rect2.height > 0;
      console.log(`   Visível na viewport: ${visible2}`);

      if (rect2) {
        const centerX2 = rect2.x + rect2.width / 2;
        const centerY2 = rect2.y + rect2.height / 2;
        const topEl2 = await page.evaluate(({ x, y }) => {
          const el = document.elementFromPoint(x, y);
          return el ? { tag: el.tagName, id: el.id, className: el.className, text: (el.textContent || '').slice(0, 40) } : null;
        }, { x: centerX2, y: centerY2 });
        console.log(`   elementFromPoint no centro: ${JSON.stringify(topEl2)}`);
      }

      // Computed styles after opening
      const styles2 = await btn2.evaluate(el => {
        const cs = getComputedStyle(el);
        return {
          display: cs.display,
          visibility: cs.visibility,
          opacity: cs.opacity,
          background: cs.background.slice(0, 80),
          color: cs.color,
        };
      });
      console.log(`   Computed styles: ${JSON.stringify(styles2)}`);
    }
  }

  // 9. Check for duplicate sidebars or hamburgers
  console.log(`\n9. Verificando duplicatas:`);
  const sidebarCount = await page.evaluate(() => document.querySelectorAll('.chat-sidebar, #chatSidebar, aside[aria-label*="Histórico"]').length);
  console.log(`   sidebars encontradas: ${sidebarCount}`);
  const hamburgerCount = await page.evaluate(() => document.querySelectorAll('#btnSidebar, [aria-label*="Abrir histórico"]').length);
  console.log(`   hamburgers encontrados: ${hamburgerCount}`);

  // 10. Check if btnNewChat is hidden by any script
  console.log(`\n10. JS que manipula btnNewChat:`);
  const jsRefs = await page.evaluate(() => {
    const scripts = document.querySelectorAll('script:not([src])');
    const results = [];
    scripts.forEach(s => {
      const text = s.textContent || '';
      if (text.includes('btnNewChat')) {
        const lines = text.split('\n').filter(l => l.includes('btnNewChat'));
        results.push(...lines.map(l => l.trim()).slice(0, 5));
      }
    });
    return results;
  });
  jsRefs.forEach(l => console.log(`   ${l}`));

  // 11. Screenshot
  await page.screenshot({ path: path.join(__dirname, 'inspect-chat.png'), fullPage: false });
  console.log(`\n11. Screenshot salva em inspect-chat.png`);

  await browser.close();
  server.close();
  console.log('\n=== FIM DA INSPEÇÃO ===');
})();
