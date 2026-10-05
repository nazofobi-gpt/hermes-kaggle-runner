(() => {
  "use strict";
  const form = document.getElementById("lead-form");
  const status = document.getElementById("form-status");

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const email = document.getElementById("email");
    if (!email.checkValidity()) {
      status.textContent = "Enter a valid email address.";
      email.focus();
      return;
    }
    status.textContent = "Demo fixture validated locally; no data was sent.";
    form.reset();
  });
})();
