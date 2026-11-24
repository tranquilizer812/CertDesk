document.addEventListener('DOMContentLoaded', () => {
  const main = document.querySelector('main');
  if (main && !main.id) {
    main.id = 'main-content';
    main.setAttribute('tabindex', '-1');
  }

  const status = document.getElementById('ui-status');
  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      const input = document.querySelector(button.dataset.copy);
      if (!input) return;
      const old = button.textContent;
      try {
        if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error('Clipboard API unavailable');
        await navigator.clipboard.writeText(input.value);
        button.textContent = 'Copied!';
        if (status) status.textContent = 'Copied to clipboard.';
      } catch (error) {
        button.textContent = 'Copy failed';
        if (status) status.textContent = 'Could not copy to clipboard. Select the value and copy it manually.';
      }
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
