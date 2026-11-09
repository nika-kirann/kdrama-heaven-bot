document.querySelectorAll('.tabs button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const tab = btn.dataset.tab;
    const code = document.getElementById('tab-code');
    const pass = document.getElementById('tab-password');
    if (code) code.hidden = tab !== 'code';
    if (pass) pass.hidden = tab !== 'password';
  });
});
document.querySelectorAll('[data-confirm]').forEach(el => {
  el.addEventListener('click', (ev) => {
    if (!confirm(el.getAttribute('data-confirm'))) ev.preventDefault();
  });
});

(function addepForm() {
  const form = document.getElementById('addep-form');
  if (!form) return;
  const nextMap = JSON.parse(form.getAttribute('data-next') || '{}');
  const seasonEl = document.getElementById('addep-season');
  const epEl = document.getElementById('addep-ep');
  const errEl = document.getElementById('addep-err');

  function showErr(msg) {
    if (!errEl) return;
    errEl.hidden = !msg;
    errEl.textContent = msg || '';
  }

  function syncEp() {
    if (!epEl || !seasonEl) return;
    const sn = seasonEl.value || '1';
    if (nextMap[sn] != null) epEl.value = nextMap[sn];
  }
  if (seasonEl && seasonEl.tagName === 'SELECT') {
    seasonEl.addEventListener('change', syncEp);
  }

  form.querySelectorAll('.add-part').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.q;
      const block = form.querySelector(`.q-block[data-quality="${q}"] .q-parts`);
      const n = block.querySelectorAll('input').length + 1;
      const lab = document.createElement('label');
      lab.textContent = `${q} · Part ${n}`;
      const inp = document.createElement('input');
      inp.type = 'url'; inp.name = q; inp.placeholder = 'https://…';
      inp.inputMode = 'url'; inp.autocomplete = 'off';
      block.appendChild(lab); block.appendChild(inp);
      inp.focus();
    });
  });
  form.querySelectorAll('.add-mirror').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.q;
      const block = form.querySelector(`.q-block[data-quality="${q}"] .q-mirrors`);
      block.style.display = 'block';
      const n = block.querySelectorAll('input').length + 1;
      const lab = document.createElement('label');
      lab.textContent = `${q} · Mirror ${n}`;
      const inp = document.createElement('input');
      inp.type = 'url'; inp.name = `${q}_mirror`; inp.placeholder = 'https://…';
      inp.inputMode = 'url'; inp.autocomplete = 'off';
      block.appendChild(lab); block.appendChild(inp);
      inp.focus();
    });
  });

  form.addEventListener('submit', (ev) => {
    showErr('');
    const ep = (epEl && epEl.value || '').trim();
    if (!/^\d+$/.test(ep) || +ep < 1 || +ep > 9999) {
      ev.preventDefault(); showErr('Episode number required (1–9999)'); epEl && epEl.focus(); return;
    }
    const urls = [...form.querySelectorAll('input[type=url]')]
      .map(i => i.value.trim()).filter(Boolean);
    if (!urls.length) {
      ev.preventDefault(); showErr('At least one valid http(s) link is required'); return;
    }
    const bad = urls.find(u => !/^https?:\/\//i.test(u));
    if (bad) {
      ev.preventDefault(); showErr('Every link must start with http:// or https://'); return;
    }
  });
})();
