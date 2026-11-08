document.querySelectorAll("[data-delete-confirmation]").forEach((details) => {
  const button = details.querySelector("[data-delete-submit]");
  const status = details.querySelector("[data-delete-status]");
  const form = button.form;
  const cancel = details.querySelector("[data-delete-cancel]");
  let timer;

  function reset() {
    clearInterval(timer);
    button.disabled = true;
    button.textContent = "Potwierdź usunięcie (5 s)";
    status.textContent = "Przycisk zostanie odblokowany po 5 sekundach.";
  }

  details.addEventListener("toggle", () => {
    reset();
    if (!details.open) return;
    const deadline = performance.now() + 5000;
    timer = setInterval(() => {
      const remaining = Math.ceil((deadline - performance.now()) / 1000);
      if (remaining <= 0) {
        clearInterval(timer);
        button.textContent = "Potwierdź usunięcie";
        button.disabled = false;
        status.textContent = "Możesz potwierdzić trwałe usunięcie.";
      } else {
        button.textContent = `Potwierdź usunięcie (${remaining} s)`;
      }
    }, 100);
  });

  cancel.addEventListener("click", () => {
    details.open = false;
    reset();
    details.querySelector("summary").focus();
  });

  form.addEventListener("submit", (event) => {
    if (button.disabled || !details.open) {
      event.preventDefault();
    } else {
      button.disabled = true;
    }
  });
});
