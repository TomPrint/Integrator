document.querySelectorAll("[data-delete-confirmation]").forEach((details) => {
  const button = details.querySelector("[data-delete-submit]");
  const status = details.querySelector("[data-delete-status]");
  const form = button.form;
  const cancel = details.querySelector("[data-delete-cancel]");
  const confirmLabel = details.dataset.confirmLabel;
  const waitLabel = details.dataset.waitLabel;
  const readyLabel = details.dataset.readyLabel;
  let timer;

  function reset() {
    clearInterval(timer);
    button.disabled = true;
    button.textContent = `${confirmLabel} (5 s)`;
    status.textContent = waitLabel;
  }

  details.addEventListener("toggle", () => {
    reset();
    if (!details.open) return;
    const deadline = performance.now() + 5000;
    timer = setInterval(() => {
      const remaining = Math.ceil((deadline - performance.now()) / 1000);
      if (remaining <= 0) {
        clearInterval(timer);
        button.textContent = confirmLabel;
        button.disabled = false;
        status.textContent = readyLabel;
      } else {
        button.textContent = `${confirmLabel} (${remaining} s)`;
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
