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
