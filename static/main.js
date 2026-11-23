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
