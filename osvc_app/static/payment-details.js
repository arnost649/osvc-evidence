(() => {
  let active = null;
  let pinned = false;
  let closeTimer;

  function close() {
    clearTimeout(closeTimer);
    if (!active) return;
    active.panel.hidden = true;
    active.button.setAttribute('aria-expanded', 'false');
    active.button.removeAttribute('aria-describedby');
    active = null;
    pinned = false;
  }

  function position(entry) {
    const anchor = entry.button.getBoundingClientRect();
    const box = entry.panel.getBoundingClientRect();
    const margin = 12;
    const left = Math.max(margin, Math.min(anchor.right - box.width, innerWidth - box.width - margin));
    const above = anchor.top - box.height - 8;
    const below = anchor.bottom + 8;
    const preferred = above >= margin ? above : below;
    const top = Math.max(margin, Math.min(preferred, innerHeight - box.height - margin));
    entry.panel.style.left = `${left}px`;
    entry.panel.style.top = `${top}px`;
  }

  function open(entry, keepOpen = false) {
    clearTimeout(closeTimer);
    if (active !== entry) close();
    active = entry;
    pinned = keepOpen;
    entry.panel.hidden = false;
    entry.button.setAttribute('aria-expanded', 'true');
    entry.button.setAttribute('aria-describedby', entry.panel.id);
    position(entry);
  }

  function leave(entry) {
    if (active !== entry || pinned || document.activeElement === entry.button) return;
    closeTimer = setTimeout(close, 150);
  }

  document.querySelectorAll('[data-payment-details]').forEach(button => {
    const panel = document.getElementById(button.dataset.paymentDetails);
    if (!panel) return;
    // Keep the bubble outside the table's scroll/clipping container.
    document.body.appendChild(panel);
    const entry = {button, panel};
    // jen kliknutím (jako ikony (i)) – bez otevírání po najetí myší nebo fokusu
    button.addEventListener('click', () => {
      if (active === entry && pinned) close();
      else open(entry, true);
    });
  });
  document.addEventListener('pointerdown', event => {
    if (active && !active.button.contains(event.target) && !active.panel.contains(event.target)) close();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') close();
  });
  window.addEventListener('resize', () => { if (active) position(active); });
  window.addEventListener('scroll', event => {
    if (!active || active.panel.contains(event.target)) return;
    const anchor = active.button.getBoundingClientRect();
    if (anchor.bottom < 0 || anchor.top > innerHeight) close();
    else position(active);
  }, {capture: true, passive: true});
})();
