/* One in-flight save; rapid selections are queued so the last choice wins. */
(() => {
  const picker = document.querySelector('[data-theme-picker]');
  if (!picker) return;
  const root = document.documentElement;
  const buttons = [...picker.querySelectorAll('[data-theme-choice]')];
  const message = document.querySelector('[data-theme-message]');
  let saved = root.dataset.theme, desired = saved, saving = false;
  function apply(theme) {
    root.classList.add('theme-changing');
    root.dataset.theme = theme;
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('theme-changing')));
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme)));
  }
  async function persist() {
    if (saving) return;
    saving = true;
    picker.setAttribute('aria-busy', 'true');
    while (saved !== desired) {
      const choice = desired;
      message.classList.remove('error');
      message.textContent = 'Ukládání…';
      try {
        const response = await fetch(picker.dataset.saveUrl, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': picker.dataset.csrf},
          body: JSON.stringify({theme: choice})
        });
        if (!response.ok || response.redirected) throw new Error('save');
        const result = await response.json();
        if (result.theme !== choice) throw new Error('save');
        saved = choice;
        message.textContent = 'Motiv uložen.';
      } catch (error) {
        desired = saved;
        apply(saved);
        message.classList.add('error');
        message.textContent = 'Motiv se nepodařilo uložit. Zkuste to znovu.';
        break;
      }
    }
    saving = false;
    picker.removeAttribute('aria-busy');
  }
  buttons.forEach(button => button.addEventListener('click', () => {
    desired = button.dataset.themeChoice;
    apply(desired);
    persist();
  }));
  window.addEventListener('beforeunload', event => {
    if (saving) { event.preventDefault(); event.returnValue = ''; }
  });
})();
