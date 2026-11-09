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

function wireQualityButtons(root) {
  root.querySelectorAll('.add-part').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.q;
      const block = root.querySelector(`.q-block[data-quality="${q}"] .q-parts`);
      if (!block) return;
      const n = block.querySelectorAll('input').length + 1;
      const lab = document.createElement('label');
      lab.textContent = `${q} · Part ${n}`;
      const inp = document.createElement('input');
      inp.type = 'text'; inp.className = 'link'; inp.name = q; inp.placeholder = 'https://…/{ep}.mkv';
      inp.inputMode = 'url'; inp.autocomplete = 'off'; inp.spellcheck = false;
      block.appendChild(lab); block.appendChild(inp);
      inp.focus();
    });
  });
  root.querySelectorAll('.add-mirror').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.q;
      const block = root.querySelector(`.q-block[data-quality="${q}"] .q-mirrors`);
      if (!block) return;
      block.style.display = 'block';
      const n = block.querySelectorAll('input').length + 1;
      const lab = document.createElement('label');
      lab.textContent = `${q} · Mirror ${n}`;
      const inp = document.createElement('input');
      inp.type = 'text'; inp.className = 'link'; inp.name = `${q}_mirror`; inp.placeholder = 'https://…/{ep}.mkv';
      inp.inputMode = 'url'; inp.autocomplete = 'off'; inp.spellcheck = false;
      block.appendChild(lab); block.appendChild(inp);
      inp.focus();
    });
  });
}

(function addepForm() {
  const form = document.getElementById('addep-form');
  if (!form) return;
  wireQualityButtons(form);
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
  form.addEventListener('submit', (ev) => {
    showErr('');
    const ep = (epEl && epEl.value || '').trim();
    if (!/^\d+$/.test(ep) || +ep < 1 || +ep > 9999) {
      ev.preventDefault(); showErr('Episode number required (1–9999)'); epEl && epEl.focus(); return;
    }
    const urls = [...form.querySelectorAll('.q-block input')].map(i => i.value.trim()).filter(Boolean);
    if (!urls.length) {
      ev.preventDefault(); showErr('At least one valid http(s) link is required'); return;
    }
    if (urls.find(u => !/^https?:\/\//i.test(u))) {
      ev.preventDefault(); showErr('Every link must start with http:// or https://'); return;
    }
  });
})();

(function addDramaForm() {
  const form = document.getElementById('add-drama-form');
  if (!form) return;
  wireQualityButtons(form);
  const totalEl = document.getElementById('add-total');
  const fromEl = document.getElementById('ep-from');
  const toEl = document.getElementById('ep-to');
  const errEl = document.getElementById('add-links-err');
  function showErr(msg) {
    if (!errEl) return;
    errEl.hidden = !msg;
    errEl.textContent = msg || '';
  }
  function syncTo() {
    if (!totalEl || !toEl) return;
    const t = (totalEl.value || '').trim();
    if (/^\d+$/.test(t)) toEl.value = t;
  }
  if (totalEl) {
    totalEl.addEventListener('input', syncTo);
    totalEl.addEventListener('change', syncTo);
    syncTo();
  }
  const preview = document.getElementById('ep-expand-preview');
  function updatePreview() {
    if (!preview) return;
    const urls = [...form.querySelectorAll('#add-links .q-block input')]
      .map(i => i.value.trim()).filter(Boolean);
    let fr = (fromEl && fromEl.value || '1').trim() || '1';
    let to = (toEl && toEl.value || '').trim();
    if (!to) {
      const t = (totalEl && totalEl.value || '').trim();
      to = /^\d+$/.test(t) ? t : fr;
    }
    if (!urls.length || !/^\d+$/.test(fr) || !/^\d+$/.test(to) || +to < +fr) {
      preview.textContent = '';
      return;
    }
    const n = +to - +fr + 1;
    const sample = urls[0].replace(/\{(episode|ep)\}/gi, fr);
    preview.textContent = n === 1
      ? `Will create episode ${fr}: ${sample}`
      : `Will create ${n} episodes (${fr}–${to}). Example: ${sample}`;
  }
  form.addEventListener('input', updatePreview);
  updatePreview();
  form.addEventListener('submit', (ev) => {
    showErr('');
    const urls = [...form.querySelectorAll('#add-links .q-block input')]
      .map(i => i.value.trim()).filter(Boolean);
    if (!urls.length) return; // drama with 0 episodes is fine
    if (urls.find(u => !/^https?:\/\//i.test(u))) {
      ev.preventDefault(); showErr('Every link must start with http:// or https://'); return;
    }
    let fr = (fromEl && fromEl.value || '1').trim() || '1';
    let to = (toEl && toEl.value || '').trim();
    if (!to) {
      const t = (totalEl && totalEl.value || '').trim();
      to = /^\d+$/.test(t) ? t : fr;
    }
    if (!/^\d+$/.test(fr) || !/^\d+$/.test(to) || +fr < 1 || +to < +fr || +to > 9999) {
      ev.preventDefault(); showErr('From/To range invalid (need 1 ≤ from ≤ to ≤ 9999)'); return;
    }
  });
})();
