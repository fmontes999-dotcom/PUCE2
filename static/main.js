document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
        const target = document.querySelector(link.getAttribute("href"));
        if (!target) return;
        event.preventDefault();
        target.scrollIntoView({ behavior: "smooth" });
    });

    const toggleOrderForm = document.querySelector("#toggle-order-form");
    const orderForm = document.querySelector("#order-form");
    if (toggleOrderForm && orderForm) {
        toggleOrderForm.addEventListener("click", () => {
            orderForm.classList.toggle("hidden");
        });
    }

});

(() => {
    const tip = document.createElement("div");
    tip.className = "viz-tip";
    tip.hidden = true;
    document.body.appendChild(tip);

    const place = (x, y) => {
        const pad = 14;
        const { width, height } = tip.getBoundingClientRect();
        tip.style.left = Math.min(x + pad, window.innerWidth - width - 8) + "px";
        tip.style.top = Math.max(8, y - height - pad) + "px";
    };
    const open = (el, x, y) => {
        tip.textContent = el.dataset.tip;
        tip.hidden = false;
        place(x, y);
    };

    document.addEventListener("mouseover", (event) => {
        const el = event.target.closest("[data-tip]");
        if (el) open(el, event.clientX, event.clientY);
    });
    document.addEventListener("mousemove", (event) => {
        if (!tip.hidden && event.target.closest("[data-tip]")) place(event.clientX, event.clientY);
    });
    document.addEventListener("mouseout", (event) => {
        if (event.target.closest("[data-tip]")) tip.hidden = true;
    });
    document.addEventListener("focusin", (event) => {
        const el = event.target.closest("[data-tip]");
        if (!el) return;
        const box = el.getBoundingClientRect();
        open(el, box.left + box.width / 2, box.top);
    });
    document.addEventListener("focusout", () => { tip.hidden = true; });
})();

/* ===== Smart Order: tablero en vivo, tema, mapa e instalación ===== */
(() => {
    const $ = (sel, root = document) => root.querySelector(sel);
    const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
    const SWAP = ["#metrics", "#asistente", "#board-wrap", "#reportes", "#menu", "#notificaciones", "#bell"];
    let map = null;
    let dragging = false;
    let dragCard = null;
    let busy = false;
    let audio = null;

    // ----- Tema claro / oscuro -----
    const themeBtn = $("#theme-toggle");
    if (themeBtn) {
        themeBtn.addEventListener("click", () => {
            const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
            document.documentElement.dataset.theme = next;
            localStorage.setItem("theme", next);
        });
    }

    // ----- Avisos y sonido -----
    const toasts = document.createElement("div");
    toasts.className = "toasts";
    document.body.appendChild(toasts);

    function toast(title, body) {
        const el = document.createElement("div");
        el.className = "toast";
        const strong = document.createElement("strong");
        strong.textContent = title;
        const small = document.createElement("small");
        small.textContent = body || "";
        el.append(strong, small);
        toasts.appendChild(el);
        setTimeout(() => el.remove(), 5000);
    }

    document.addEventListener("click", () => {
        if (!audio && window.AudioContext) audio = new AudioContext();
    }, { once: true });

    function beep() {
        if (!audio) return;
        const osc = audio.createOscillator();
        const gain = audio.createGain();
        osc.frequency.value = 880;
        gain.gain.value = 0.05;
        osc.connect(gain).connect(audio.destination);
        osc.start();
        osc.stop(audio.currentTime + 0.12);
    }

    // ----- Peticiones -----
    async function post(url, data) {
        const body = new FormData();
        Object.entries(data || {}).forEach(([key, value]) => body.append(key, value));
        const res = await fetch(url, {
            method: "POST", body, credentials: "same-origin",
            headers: { "X-Requested-With": "fetch" },
        });
        if (res.redirected && res.url.includes("/login")) location.href = "/login";
        return res;
    }

    // ----- Tiempo transcurrido por pedido -----
    function updateTimers() {
        const now = Date.now();
        $$(".kcard[data-created]").forEach((card) => {
            const timer = $("[data-timer]", card);
            const created = Date.parse(card.dataset.created);
            if (!timer || Number.isNaN(created)) return;
            const minutes = Math.max(0, Math.floor((now - created) / 60000));
            timer.textContent = minutes < 1 ? "ahora"
                : minutes < 60 ? `hace ${minutes} min` : `hace ${Math.floor(minutes / 60)} h`;
            const active = ["nuevo", "preparando"].includes(card.dataset.status);
            timer.classList.toggle("late", active && minutes >= 15);
        });
    }

    // ----- Búsqueda y filtro -----
    function applyFilters() {
        const query = (($("#order-search") || {}).value || "").trim().toLowerCase();
        const platform = ($("#order-platform") || {}).value || "";
        $$(".kcard").forEach((card) => {
            const okQuery = !query || card.dataset.search.includes(query);
            const okPlatform = !platform || card.dataset.platform === platform;
            card.hidden = !(okQuery && okPlatform);
        });
    }
    const search = $("#order-search");
    const platformSelect = $("#order-platform");
    if (search) search.addEventListener("input", applyFilters);
    if (platformSelect) platformSelect.addEventListener("change", applyFilters);

    // ----- Actualización en vivo (sin recargar la página) -----
    async function refresh(force = false) {
        if (busy || (!force && (dragging || document.hidden))) return;
        busy = true;
        try {
            const res = await fetch("/", {
                credentials: "same-origin", headers: { "X-Requested-With": "fetch" },
            });
            if (res.redirected && res.url.includes("/login")) { location.href = "/login"; return; }
            if (!res.ok) return;
            const doc = new DOMParser().parseFromString(await res.text(), "text/html");
            if (!$("#board-wrap", doc)) { location.href = "/login"; return; }
            const before = new Set($$("#board-wrap .kcard").map((card) => card.dataset.id));
            SWAP.forEach((sel) => {
                const current = $(sel);
                const next = $(sel, doc);
                if (current && next) current.replaceWith(next);
            });
            const fresh = $$("#board-wrap .kcol[data-status='nuevo'] .kcard")
                .filter((card) => !before.has(card.dataset.id));
            fresh.slice(0, 3).forEach((card) => {
                toast(`Nuevo pedido · ${card.dataset.platform}`,
                    `${($("strong", card) || {}).textContent || ""} — ${($("b", card) || {}).textContent || ""}`);
            });
            fresh.forEach((card) => card.classList.add("is-new"));
            if (fresh.length) beep();
            updateTimers();
            applyFilters();
            updateDeliveries();
        } catch (error) {
            // sin conexión: se reintenta en el siguiente ciclo
        } finally {
            busy = false;
        }
    }

    // ----- Botones de las tarjetas (avanzar, plato agotado, respuesta del cliente) -----
    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-act]");
        if (!button) return;
        button.disabled = true;
        try {
            const data = button.dataset.status ? { status: button.dataset.status }
                : button.dataset.dish ? { dish: button.dataset.dish } : {};
            await post(button.dataset.act, data);
        } finally {
            busy = false;
            await refresh(true);
        }
    });

    // ----- Arrastrar y soltar entre columnas -----
    document.addEventListener("dragstart", (event) => {
        const card = event.target.closest(".kcard[draggable='true']");
        if (!card) return;
        dragging = true;
        dragCard = card;
        card.classList.add("dragging");
        event.dataTransfer.setData("text/plain", card.dataset.id);
        event.dataTransfer.effectAllowed = "move";
    });
    document.addEventListener("dragend", () => {
        dragging = false;
        if (dragCard) dragCard.classList.remove("dragging");
        $$(".kcol.drop").forEach((col) => col.classList.remove("drop"));
        dragCard = null;
    });
    document.addEventListener("dragover", (event) => {
        const col = event.target.closest(".kcol");
        if (col && dragCard) { event.preventDefault(); col.classList.add("drop"); }
    });
    document.addEventListener("dragleave", (event) => {
        const col = event.target.closest(".kcol");
        if (col && !col.contains(event.relatedTarget)) col.classList.remove("drop");
    });
    document.addEventListener("drop", async (event) => {
        const col = event.target.closest(".kcol");
        if (!col || !dragCard) return;
        event.preventDefault();
        const card = dragCard;
        const status = col.dataset.status;
        col.classList.remove("drop");
        dragging = false;
        if (card.dataset.status !== status) await post(card.dataset.urlEstado, { status });
        await refresh(true);
    });

    // ----- Simulación en vivo (entra un pedido cada 15 s) -----
    const liveBtn = $("#live-toggle");
    let liveTimer = null;

    async function tick() {
        const connected = (($("#pedidos") || {}).dataset.connected || "").split(",").filter(Boolean);
        if (!connected.length) {
            toast("Conecta una plataforma", "Conecta Uber Eats, Rappi o PedidosYa para simular pedidos.");
            setLive(false);
            return;
        }
        const platform = connected[Math.floor(Math.random() * connected.length)];
        await post(`/demo/pedido-entrante/${platform}`);
        await post("/demo/avanzar");
        await refresh(true);
    }

    function setLive(on, immediate = true) {
        if (!liveBtn) return;
        liveBtn.classList.toggle("on", on);
        liveBtn.setAttribute("aria-pressed", String(on));
        liveBtn.textContent = on ? "⏸ Detener simulación" : "▶ Simulación en vivo";
        localStorage.setItem("live", on ? "1" : "0");
        clearInterval(liveTimer);
        if (on) {
            liveTimer = setInterval(tick, 15000);
            if (immediate) tick();
        }
    }
    if (liveBtn) {
        liveBtn.addEventListener("click", () => setLive(!liveBtn.classList.contains("on")));
        if (localStorage.getItem("live") === "1") setLive(true, false);
    }

    // ----- Imprimir / PDF -----
    const printBtn = $("#print-btn");
    if (printBtn) printBtn.addEventListener("click", () => window.print());

    // ----- Mapa de Quito -----
    function initMap() {
        const el = $("#map");
        if (!el) return;
        if (!window.L) {
            el.innerHTML = '<p class="map-fallback">No se pudo cargar el mapa (se necesita internet).</p>';
            return;
        }
        el.innerHTML = "";
        map = L.map(el, { scrollWheelZoom: false }).setView([-0.1807, -78.4678], 12);
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19, attribution: "&copy; OpenStreetMap",
        }).addTo(map);
        let points = [];
        try { points = JSON.parse(el.dataset.points || "[]"); } catch (error) { points = []; }
        points.forEach((point) => {
            const marker = L.circleMarker([point.lat, point.lng], {
                radius: 9 + Math.min(point.orders, 12), color: "#fff", weight: 2,
                fillColor: "#ef5a2a", fillOpacity: 0.9,
            }).addTo(map);
            const box = document.createElement("div");
            const name = document.createElement("strong");
            name.textContent = `${point.icon || "🍴"} ${point.name}`;
            const lines = document.createElement("div");
            lines.textContent = `${point.address} · ${point.orders} pedidos · $${point.sales.toFixed(2)}`;
            box.append(name, lines);
            marker.bindPopup(box);
        });
        if (points.length) {
            map.fitBounds(points.map((p) => [p.lat, p.lng]), { padding: [40, 40], maxZoom: 13 });
        }
    }
    initMap();

    // ----- Repartidores en el mapa -----
    let deliveryLayer = null;
    let couriers = [];

    const textNode = (value) => {
        const span = document.createElement("span");
        span.textContent = value;
        return span;
    };

    async function updateDeliveries() {
        if (!map || !window.L) return;
        let data;
        try {
            const res = await fetch("/api/entregas", { credentials: "same-origin" });
            if (!res.ok) return;
            data = await res.json();
        } catch (error) {
            return;
        }
        if (!deliveryLayer) deliveryLayer = L.layerGroup().addTo(map);
        deliveryLayer.clearLayers();
        couriers = [];
        data.deliveries.forEach((delivery) => {
            L.polyline([delivery.from, delivery.to], { color: "#2a78d6", weight: 3, dashArray: "6 8" })
                .addTo(deliveryLayer);
            L.circleMarker(delivery.to, {
                radius: 6, color: "#fff", weight: 2, fillColor: "#2a78d6", fillOpacity: 1,
            }).bindTooltip(textNode(`Entrega: ${delivery.who}`)).addTo(deliveryLayer);
            const icon = L.divIcon({ className: "courier-pin", html: "🛵", iconSize: [28, 28] });
            const marker = L.marker(delivery.from, { icon })
                .bindTooltip(textNode(`${delivery.courier} · ~${delivery.eta} min`))
                .addTo(deliveryLayer);
            couriers.push({ marker, delivery });
        });
    }

    function animateCouriers(now) {
        couriers.forEach(({ marker, delivery }) => {
            const t = ((now / 1000 + delivery.id * 3) % 30) / 30;
            marker.setLatLng([
                delivery.from[0] + (delivery.to[0] - delivery.from[0]) * t,
                delivery.from[1] + (delivery.to[1] - delivery.from[1]) * t,
            ]);
        });
        requestAnimationFrame(animateCouriers);
    }
    if (map) {
        updateDeliveries();
        requestAnimationFrame(animateCouriers);
    }

    // ----- Instalación como app -----
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

    updateTimers();
    applyFilters();
    setInterval(updateTimers, 30000);
    setInterval(refresh, 5000);
})();

/* ===== Animaciones de entrada, QR y copiar enlace ===== */
(() => {
    const $ = (sel, root = document) => root.querySelector(sel);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Las animaciones de entrada solo corren al abrir la página, no en cada actualización en vivo.
    setTimeout(() => document.documentElement.classList.remove("intro"), 2400);

    function countUp(el) {
        const match = el.textContent.trim().match(/^(\$?)(\d+(?:\.\d+)?)$/);
        if (!match) return;
        const prefix = match[1];
        const target = parseFloat(match[2]);
        const decimals = (match[2].split(".")[1] || "").length;
        const start = performance.now();
        const duration = 900;
        el.textContent = prefix + (0).toFixed(decimals);
        const step = (now) => {
            const t = Math.min(1, (now - start) / duration);
            el.textContent = prefix + (target * (1 - Math.pow(1 - t, 3))).toFixed(decimals);
            if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    }
    if (!reduced) document.querySelectorAll("#metrics .metric-card strong").forEach(countUp);

    // Ventana con el código QR
    const dialog = $("#qr-dialog");
    const open = $("#qr-open");
    if (dialog && open) {
        open.addEventListener("click", () => {
            if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
        });
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) dialog.close();
        });
    }

    // Copiar el enlace
    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-copy]");
        if (!button) return;
        const original = button.textContent;
        try {
            await navigator.clipboard.writeText(button.dataset.copy);
            button.textContent = "¡Copiado!";
        } catch (error) {
            button.textContent = "Copia el enlace de arriba";
        }
        setTimeout(() => { button.textContent = original; }, 1600);
    });
})();
