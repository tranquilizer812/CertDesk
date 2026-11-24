document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      const input = document.querySelector(button.dataset.copy);
      if (!input) return;
      await navigator.clipboard.writeText(input.value);
      const old = button.textContent;
      button.textContent = 'Copied!';
      setTimeout(() => { button.textContent = old; }, 1600);
    });
  });
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
  document.querySelectorAll('.toast').forEach((toast) => {
    setTimeout(() => toast.remove(), 4500);
  });
});
