(function () {
    const section = document.getElementById("scrolly-cars");
    const canvas = document.getElementById("autoassist-car-canvas");
    if (!section || !canvas) return;

    const context = canvas.getContext("2d");
    if (!context) {
        section.classList.add("car-scroll--fallback");
        return;
    }

    const navbar = document.querySelector(".navbar");
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const cycleDuration = 3000;
    const transitionDuration = prefersReducedMotion ? 0 : 900;

    const carSources = [
        "https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?q=80&w=1920",
        "https://images.unsplash.com/photo-1503376780353-7e6692767b70?q=80&w=1920",
        "https://images.unsplash.com/photo-1494976388531-d1058494cdd8?q=80&w=1920",
        "https://images.unsplash.com/photo-1583121274602-3e2820c69888?q=80&w=1920",
        "https://images.unsplash.com/photo-1544636331-e26879cd4d9b?q=80&w=1920",
    ];

    const accents = ["#38bdf8", "#f59e0b", "#34d399", "#a78bfa", "#60a5fa"];
    const loadedCars = carSources.map((src) => {
        const image = new Image();
        image.crossOrigin = "anonymous";
        image.decoding = "async";
        image.src = src;
        return image;
    });

    let width = 1;
    let height = 1;
    let dpr = 1;

    const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
    const lerp = (from, to, amount) => from + (to - from) * amount;
    const smoother = (value) => value * value * (3 - 2 * value);

    function updateHeaderOffset() {
        const headerHeight = navbar ? Math.ceil(navbar.getBoundingClientRect().height) : 0;
        if (headerHeight > 0) {
            section.style.setProperty("--car-scroll-header-offset", `${headerHeight}px`);
        }
    }

    function resize() {
        const bounds = canvas.getBoundingClientRect();
        width = Math.max(1, Math.floor(bounds.width || window.innerWidth));
        height = Math.max(1, Math.floor(bounds.height || window.innerHeight));
        dpr = Math.min(window.devicePixelRatio || 1, 1.8);
        canvas.width = Math.floor(width * dpr);
        canvas.height = Math.floor(height * dpr);
        context.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function roundedRect(ctx, x, y, w, h, radius) {
        const r = Math.min(radius, w / 2, h / 2);
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }

    function drawImageCover(ctx, image, x, y, w, h) {
        if (!image.complete || image.naturalWidth === 0) {
            const placeholder = ctx.createLinearGradient(x, y, x + w, y + h);
            placeholder.addColorStop(0, "#111827");
            placeholder.addColorStop(1, "#1d4ed8");
            ctx.fillStyle = placeholder;
            roundedRect(ctx, x, y, w, h, 20);
            ctx.fill();
            return;
        }

        const imageRatio = image.naturalWidth / image.naturalHeight;
        const targetRatio = w / h;
        let sx = 0;
        let sy = 0;
        let sw = image.naturalWidth;
        let sh = image.naturalHeight;

        if (imageRatio > targetRatio) {
            sw = image.naturalHeight * targetRatio;
            sx = (image.naturalWidth - sw) / 2;
        } else {
            sh = image.naturalWidth / targetRatio;
            sy = (image.naturalHeight - sh) / 2;
        }

        ctx.drawImage(image, sx, sy, sw, sh, x, y, w, h);
    }

    function drawBackground(ctx, carouselProgress, elapsed) {
        const sky = ctx.createLinearGradient(0, 0, 0, height);
        sky.addColorStop(0, "#080b12");
        sky.addColorStop(0.42, "#0f172a");
        sky.addColorStop(1, "#040507");
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, width, height);

        const glowX = width * (0.5 + Math.sin(elapsed * 0.00028) * 0.06);
        const glowY = height * 0.4;
        const glow = ctx.createRadialGradient(glowX, glowY, 0, glowX, glowY, Math.max(width, height) * 0.68);
        glow.addColorStop(0, "rgba(59, 130, 246, 0.2)");
        glow.addColorStop(0.35, "rgba(14, 165, 233, 0.08)");
        glow.addColorStop(1, "rgba(2, 6, 23, 0)");
        ctx.fillStyle = glow;
        ctx.fillRect(0, 0, width, height);

        const horizon = height * 0.56;
        const roadTop = width * 0.16;
        const roadBottom = width * 1.26;
        ctx.save();
        ctx.translate(width / 2, 0);

        const road = ctx.createLinearGradient(0, horizon, 0, height);
        road.addColorStop(0, "rgba(30, 41, 59, 0.22)");
        road.addColorStop(1, "rgba(2, 6, 23, 0.96)");
        ctx.fillStyle = road;
        ctx.beginPath();
        ctx.moveTo(-roadTop, horizon);
        ctx.lineTo(roadTop, horizon);
        ctx.lineTo(roadBottom, height + 30);
        ctx.lineTo(-roadBottom, height + 30);
        ctx.closePath();
        ctx.fill();

        ctx.strokeStyle = "rgba(96, 165, 250, 0.2)";
        ctx.lineWidth = 1;
        for (let i = -8; i <= 8; i += 1) {
            ctx.beginPath();
            ctx.moveTo(i * 34, horizon);
            ctx.lineTo(i * 152, height);
            ctx.stroke();
        }

        for (let i = 0; i < 18; i += 1) {
            const phase = (i / 18 + carouselProgress * 0.5 + elapsed * 0.00008) % 1;
            const y = lerp(horizon + 8, height + 24, phase * phase);
            const half = lerp(roadTop, roadBottom, phase);
            ctx.strokeStyle = `rgba(148, 163, 184, ${lerp(0.08, 0.24, phase)})`;
            ctx.lineWidth = lerp(0.4, 1.4, phase);
            ctx.beginPath();
            ctx.moveTo(-half, y);
            ctx.lineTo(half, y);
            ctx.stroke();
        }

        ctx.strokeStyle = "rgba(56, 189, 248, 0.38)";
        ctx.lineWidth = 2;
        [-0.12, 0.12].forEach((offset) => {
            ctx.beginPath();
            ctx.moveTo(roadTop * offset, horizon);
            ctx.lineTo(roadBottom * offset, height + 20);
            ctx.stroke();
        });

        ctx.restore();
    }

    function drawSpeedLines(ctx, elapsed) {
        const lineCount = width < 700 ? 20 : 32;
        ctx.save();
        ctx.globalCompositeOperation = "screen";
        for (let i = 0; i < lineCount; i += 1) {
            const seed = (i * 97.13) % 1;
            const phase = (seed + elapsed * 0.00016) % 1;
            const side = i % 2 === 0 ? -1 : 1;
            const x = width * 0.5 + side * lerp(width * 0.16, width * 0.54, phase);
            const y = lerp(height * 0.22, height * 0.88, phase);
            const length = lerp(22, 98, phase);
            ctx.strokeStyle = `rgba(125, 211, 252, ${lerp(0.035, 0.16, phase)})`;
            ctx.lineWidth = lerp(1, 2.2, phase);
            ctx.beginPath();
            ctx.moveTo(x, y);
            ctx.lineTo(x + side * length, y + length * 0.16);
            ctx.stroke();
        }
        ctx.restore();
    }

    function drawPanel(ctx, image, options) {
        const { x, y, w, h, rotation, skew, opacity, accent, highlight } = options;

        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(rotation);
        ctx.transform(1, skew, -skew * 0.55, 1, 0, 0);
        ctx.globalAlpha = opacity;

        ctx.shadowColor = "rgba(0, 0, 0, 0.62)";
        ctx.shadowBlur = highlight ? 34 : 20;
        ctx.shadowOffsetY = highlight ? 22 : 14;
        roundedRect(ctx, -w / 2, -h / 2, w, h, 20);
        ctx.fillStyle = "#0f172a";
        ctx.fill();
        ctx.clip();

        drawImageCover(ctx, image, -w / 2, -h / 2, w, h);

        const shade = ctx.createLinearGradient(-w / 2, -h / 2, w / 2, h / 2);
        shade.addColorStop(0, "rgba(255, 255, 255, 0.12)");
        shade.addColorStop(0.38, "rgba(255, 255, 255, 0)");
        shade.addColorStop(0.72, "rgba(2, 6, 23, 0.2)");
        shade.addColorStop(1, "rgba(2, 6, 23, 0.42)");
        ctx.fillStyle = shade;
        ctx.fillRect(-w / 2, -h / 2, w, h);
        ctx.restore();

        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(rotation);
        ctx.transform(1, skew, -skew * 0.55, 1, 0, 0);
        ctx.globalAlpha = opacity;
        roundedRect(ctx, -w / 2, -h / 2, w, h, 20);
        ctx.strokeStyle = highlight ? accent : "rgba(148, 163, 184, 0.28)";
        ctx.lineWidth = highlight ? 2 : 1;
        ctx.stroke();

        if (highlight) {
            ctx.globalCompositeOperation = "screen";
            ctx.strokeStyle = accent;
            ctx.globalAlpha = opacity * 0.42;
            ctx.lineWidth = 8;
            roundedRect(ctx, -w / 2 + 5, -h / 2 + 5, w - 10, h - 10, 16);
            ctx.stroke();
        }
        ctx.restore();
    }

    function drawReflection(ctx, image, x, y, w, h, opacity) {
        if (!image.complete || image.naturalWidth === 0) return;

        ctx.save();
        ctx.translate(x, y);
        ctx.scale(1, -1);
        ctx.globalAlpha = opacity;
        roundedRect(ctx, -w / 2, -h / 2, w, h, 18);
        ctx.clip();
        drawImageCover(ctx, image, -w / 2, -h / 2, w, h);

        const fade = ctx.createLinearGradient(0, -h / 2, 0, h / 2);
        fade.addColorStop(0, "rgba(4, 5, 7, 0.12)");
        fade.addColorStop(0.58, "rgba(4, 5, 7, 0.66)");
        fade.addColorStop(1, "rgba(4, 5, 7, 1)");
        ctx.fillStyle = fade;
        ctx.fillRect(-w / 2, -h / 2, w, h);
        ctx.restore();
    }

    function getCarouselProgress(elapsed) {
        const cycle = elapsed % cycleDuration;
        const currentIndex = Math.floor(elapsed / cycleDuration) % loadedCars.length;
        const nextIndex = (currentIndex + 1) % loadedCars.length;
        const transition = transitionDuration > 0
            ? smoother(clamp((cycle - (cycleDuration - transitionDuration)) / transitionDuration, 0, 1))
            : 0;

        if (currentIndex === loadedCars.length - 1 && nextIndex === 0 && transition > 0) {
            return currentIndex + transition;
        }

        return currentIndex + transition;
    }

    function drawCarCarousel(ctx, elapsed) {
        const carouselProgress = getCarouselProgress(elapsed);
        const activeIndex = Math.floor(carouselProgress) % loadedCars.length;
        const accent = accents[activeIndex] || accents[0];
        const baseX = width * 0.5;
        const baseY = height * (width < 700 ? 0.43 : 0.52);
        const baseW = Math.min(width * (width < 700 ? 1.08 : 0.78), 1120);
        const baseH = baseW * (width < 700 ? 0.62 : 0.54);

        const panels = loadedCars.map((image, index) => {
            let distance = index - carouselProgress;
            if (distance < -loadedCars.length / 2) distance += loadedCars.length;
            if (distance > loadedCars.length / 2) distance -= loadedCars.length;
            const abs = Math.abs(distance);
            const depth = 1 - clamp(abs, 0, 2.2) / 2.2;
            const activeBoost = smoother(depth);
            return {
                image,
                index,
                distance,
                abs,
                depth,
                activeBoost,
                scale: lerp(0.5, 1, activeBoost),
            };
        }).sort((a, b) => a.scale - b.scale);

        panels.forEach((panel) => {
            if (panel.abs > 2.4) return;
            const active = panel.abs < 0.54;
            const wave = prefersReducedMotion ? 0 : Math.sin(elapsed * 0.0012 + panel.index) * 0.012;
            const x = baseX + panel.distance * Math.min(width * 0.34, 480);
            const y = baseY + panel.abs * (width < 700 ? 36 : 58) - panel.activeBoost * 24;
            const w = baseW * panel.scale;
            const h = baseH * panel.scale;
            const rotation = panel.distance * -0.12 + wave;
            const skew = panel.distance * 0.03;
            const opacity = clamp(0.18 + panel.depth * 0.9, 0, 1);

            if (active) {
                drawReflection(ctx, panel.image, x, y + h * 0.82, w * 0.94, h * 0.52, 0.13);
            }

            drawPanel(ctx, panel.image, {
                x,
                y,
                w,
                h,
                rotation,
                skew,
                opacity,
                accent,
                highlight: active,
            });
        });

        ctx.save();
        ctx.globalCompositeOperation = "screen";
        const halo = ctx.createRadialGradient(baseX, baseY, 0, baseX, baseY, baseW * 0.68);
        halo.addColorStop(0, `${accent}3b`);
        halo.addColorStop(0.5, `${accent}12`);
        halo.addColorStop(1, "rgba(0, 0, 0, 0)");
        ctx.fillStyle = halo;
        ctx.fillRect(baseX - baseW, baseY - baseW * 0.55, baseW * 2, baseW * 1.1);
        ctx.restore();
    }

    function drawDataOverlays(ctx, elapsed) {
        const activeIndex = Math.floor(getCarouselProgress(elapsed)) % accents.length;
        const accent = accents[activeIndex] || accents[0];

        ctx.save();
        ctx.globalCompositeOperation = "screen";
        ctx.strokeStyle = accent;
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.48;

        const centerX = width * 0.5;
        const centerY = height * (width < 700 ? 0.34 : 0.48);
        for (let i = 0; i < 4; i += 1) {
            const radius = Math.min(width, height) * (0.12 + i * 0.045);
            const pulse = prefersReducedMotion ? 0 : Math.sin(elapsed * 0.0016 + i) * 8;
            ctx.beginPath();
            ctx.ellipse(centerX, centerY, radius + pulse, (radius + pulse) * 0.28, 0, 0, Math.PI * 2);
            ctx.stroke();
        }

        const nodes = width < 700 ? 5 : 8;
        for (let i = 0; i < nodes; i += 1) {
            const phase = (i / nodes + elapsed * 0.00018) % 1;
            const x = lerp(width * 0.16, width * 0.84, phase);
            const y = height * 0.18 + Math.sin(phase * Math.PI * 2 + elapsed * 0.001) * 22;
            ctx.fillStyle = accent;
            ctx.globalAlpha = 0.22 + phase * 0.26;
            ctx.beginPath();
            ctx.arc(x, y, 3 + phase * 3, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.restore();
    }

    function draw(elapsed) {
        const carouselProgress = getCarouselProgress(elapsed);
        context.clearRect(0, 0, width, height);
        drawBackground(context, carouselProgress, elapsed);
        drawSpeedLines(context, elapsed);
        drawDataOverlays(context, elapsed);
        drawCarCarousel(context, elapsed);

        const fade = context.createLinearGradient(0, 0, 0, height);
        fade.addColorStop(0, "rgba(0, 0, 0, 0.18)");
        fade.addColorStop(0.45, "rgba(0, 0, 0, 0)");
        fade.addColorStop(1, "rgba(0, 0, 0, 0.38)");
        context.fillStyle = fade;
        context.fillRect(0, 0, width, height);
    }

    function render(elapsed) {
        draw(elapsed);
        window.requestAnimationFrame(render);
    }

    window.addEventListener("resize", () => {
        updateHeaderOffset();
        resize();
    }, { passive: true });

    loadedCars.forEach((image) => {
        image.addEventListener("load", () => draw(performance.now()), { once: true });
    });

    if (navbar && "ResizeObserver" in window) {
        const headerObserver = new ResizeObserver(() => {
            updateHeaderOffset();
            resize();
        });
        headerObserver.observe(navbar);
    }

    updateHeaderOffset();
    resize();
    window.requestAnimationFrame(render);
})();
