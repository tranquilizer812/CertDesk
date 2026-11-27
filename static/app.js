document.addEventListener('DOMContentLoaded', () => {
  const main = document.querySelector('main');
  if (main && !main.id) {
    main.id = 'main-content';
    main.setAttribute('tabindex', '-1');
  }

  // Mobile navigation toggle
  const navToggle = document.querySelector('.nav-toggle');
  const navLinks = document.querySelector('.nav-links');
  if (navToggle && navLinks) {
    navToggle.addEventListener('click', () => {
      const isOpen = navLinks.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', isOpen);
    });
    // Close menu when clicking a link
    navLinks.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => {
        navLinks.classList.remove('open');
        navToggle.setAttribute('aria-expanded', 'false');
      });
    });
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

  // Loading indicator for file upload forms
  document.querySelectorAll('form[enctype="multipart/form-data"]').forEach((form) => {
    form.addEventListener('submit', () => {
      const btn = form.querySelector('button[type="submit"]');
      if (btn) {
        btn.dataset.origText = btn.textContent;
        btn.textContent = 'Uploading…';
        btn.disabled = true;
      }
      const status = document.getElementById('ui-status');
      if (status) status.textContent = 'Uploading file…';
    });
  });

  // Accessibility: mark fields with errors
  document.querySelectorAll('.field .error-message').forEach((errorSpan) => {
    const fieldId = errorSpan.id.replace('error-', '');
    const input = document.getElementById(fieldId);
    if (input) {
      input.setAttribute('aria-invalid', 'true');
      input.setAttribute('aria-describedby', errorSpan.id);
    }
  });

  // Accessibility: aria-label for icon-only links in sidebar
  document.querySelectorAll('.sidebar a i[aria-hidden="true"]').forEach((icon) => {
    const link = icon.closest('a');
    if (link && !link.getAttribute('aria-label')) {
      const text = link.textContent.trim();
      if (text) link.setAttribute('aria-label', text);
    }
  });

  // Global network error handler for fetch requests
  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    try {
      const response = await originalFetch(...args);
      if (!response.ok && response.status >= 500) {
        const status = document.getElementById('ui-status');
        if (status) status.textContent = 'Server error. Please try again later.';
      }
      return response;
    } catch (error) {
      const status = document.getElementById('ui-status');
      if (status) status.textContent = 'Network error. Please check your connection and try again.';
      throw error;
    }
  };

  // AJAX filtering for document list
  const filterForm = document.querySelector('form.filter-bar');
  let tableBody = document.querySelector('table tbody');
  if (filterForm && tableBody) {
    const searchInput = filterForm.querySelector('input[name="q"]');
    const statusSelect = filterForm.querySelector('select[name="status"]');

    async function loadFilteredResults() {
      const params = new URLSearchParams();
      if (searchInput && searchInput.value.trim()) params.set('q', searchInput.value.trim());
      if (statusSelect && statusSelect.value) params.set('status', statusSelect.value);

      const tableWrap = tableBody.closest('.table-wrap');
      const originalHtml = tableWrap ? tableWrap.innerHTML : '';

      try {
        if (status) status.textContent = 'Loading filtered results…';
        const csrfToken = document.cookie.match('(?:^|; )csrftoken=([^;]*)');
        const headers = { 'X-Requested-With': 'XMLHttpRequest' };
        if (csrfToken && csrfToken[1]) headers['X-CSRFToken'] = csrfToken[1];
        const response = await fetch(`/documents/filter/?${params.toString()}`, {
          headers,
        });
        if (!response.ok) throw new Error(`Server responded ${response.status}`);
        const data = await response.json();

        // Rebuild table rows from JSON
        const thead = tableBody.closest('table').querySelector('thead');
        let rowsHtml = '';
        if (data.results.length === 0) {
          rowsHtml = '<tr><td colspan="5"><div class="empty-state compact"><h3>No matching requests</h3><p>Try another filter or search term.</p></div></td></tr>';
        } else {
          for (const item of data.results) {
            const statusClass = `status-${item.status}`;
            const expiresDisplay = item.expires_on ? new Date(item.expires_on).toLocaleDateString() : '—';
            rowsHtml += `
              <tr>
                <td><strong>${escapeHtml(item.vendor)}</strong><small>${item.property ? item.property : 'All properties'}</small></td>
                <td>${escapeHtml(item.document_type)}</td>
                <td><span class="status ${statusClass}">${item.status}</span></td>
                <td>${expiresDisplay}</td>
                <td><a class="row-link" href="${item.url}">View →</a></td>
              </tr>`;
          }
        }
        tableBody.innerHTML = rowsHtml;
        if (status) status.textContent = `Found ${data.count} result${data.count !== 1 ? 's' : ''}.`;
      } catch (error) {
        if (status) status.textContent = 'Filter failed. Please try again.';
        if (tableWrap) {
          tableWrap.innerHTML = originalHtml;
          tableBody = tableWrap.querySelector('tbody') || tableBody;
        }
        console.error('AJAX filter error:', error);
      }
    }

    const debounce = (fn, delay) => {
      let timer;
      return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
      };
    };

    if (searchInput) {
      searchInput.addEventListener('input', debounce(loadFilteredResults, 300));
    }
    if (statusSelect) {
      statusSelect.addEventListener('change', loadFilteredResults);
    }
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
});
