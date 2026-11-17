/* kdrama_heaven admin — vanilla JS, no build step. */
(function shell() {
  const body = document.body;
  const btn = document.getElementById('menu-btn');
  const scrim = document.getElementById('scrim');
  const close = () => body.classList.remove('nav-open');
  if (btn) btn.addEventListener('click', () => body.classList.toggle('nav-open'));
  if (scrim) scrim.addEventListener('click', close);
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') close(); });
  // toasts: dismiss on click, auto-hide success after 5s
  document.querySelectorAll('.toast').forEach(t => {
    const hide = () => { t.classList.add('hide'); setTimeout(() => t.remove(), 320); };
    const x = t.querySelector('.toast-x');
    if (x) x.addEventListener('click', hide);
    if (t.classList.contains('ok')) setTimeout(hide, 5000);
  });
  // clickable table rows
  document.querySelectorAll('tr[data-href]').forEach(tr => {
    tr.addEventListener('click', (ev) => {
      if (ev.target.closest('a, button, input, select, form')) return;
      window.location.href = tr.getAttribute('data-href');
    });
  });
  // request replies: quick-reply chips fill the textarea
  document.querySelectorAll('.reply-form').forEach(form => {
    const ta = form.querySelector('textarea');
    form.querySelectorAll('.chip.quick').forEach(c => c.addEventListener('click', () => {
      ta.value = c.dataset.fill; ta.focus();
    }));
  });
  document.querySelectorAll('.reply-box').forEach(box => box.addEventListener('toggle', () => {
    if (box.open) { const ta = box.querySelector('textarea'); if (ta) ta.focus(); }
  }));
  // open the edit panel if a hash points inside it
  if (location.hash === '#edit') {
    const d = document.querySelector('details.collapsible'); if (d) d.open = true;
  }
})();

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
  function makeRow(q, name, kindLabel, n, removable) {
    const row = document.createElement('div');
    row.className = 'q-row';
    const rm = removable
      ? '<button type="button" class="btn ghost btn-sm q-remove" aria-label="Remove this link" title="Remove">×</button>'
      : '';
    row.innerHTML = `<label>${q} · ${kindLabel} ${n}</label><div class="q-input">`
      + `<input type="text" class="link" name="${name}" placeholder="https://…/{ep}.mkv" `
      + `inputmode="url" autocomplete="off" spellcheck="false">${rm}</div>`;
    return row;
  }
  function renumber(container, q, kindLabel) {
    const rows = [...container.querySelectorAll('.q-row')];
    rows.forEach((row, i) => {
      const lab = row.querySelector('label');
      if (lab) lab.textContent = `${q} · ${kindLabel} ${i + 1}`;
      const rm = row.querySelector('.q-remove');
      if (kindLabel === 'Part') {
        if (rows.length === 1) { if (rm) rm.remove(); }
        else if (!rm) {
          const btn = document.createElement('button');
          btn.type = 'button'; btn.className = 'btn ghost btn-sm q-remove';
          btn.setAttribute('aria-label', 'Remove this link'); btn.title = 'Remove';
          btn.textContent = '×';
          row.querySelector('.q-input').appendChild(btn);
        }
      }
    });
  }
  root.querySelectorAll('.add-part').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.q;
      const block = root.querySelector(`.q-block[data-quality="${q}"] .q-parts`);
      if (!block) return;
      const n = block.querySelectorAll('input').length + 1;
      const row = makeRow(q, q, 'Part', n, true);
      block.appendChild(row);
      renumber(block, q, 'Part');
      row.querySelector('input').focus();
    });
  });
  root.querySelectorAll('.add-mirror').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.q;
      const block = root.querySelector(`.q-block[data-quality="${q}"] .q-mirrors`);
      if (!block) return;
      block.style.display = 'block';
      const n = block.querySelectorAll('input').length + 1;
      const row = makeRow(q, `${q}_mirror`, 'Mirror', n, true);
      block.appendChild(row);
      row.querySelector('input').focus();
    });
  });
  root.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.q-remove');
    if (!btn || !root.contains(btn)) return;
    ev.preventDefault();
    const row = btn.closest('.q-row');
    const block = btn.closest('.q-block');
    const container = row && row.parentElement;
    if (!row || !container) return;
    row.remove();
    const q = block && block.getAttribute('data-quality');
    const kind = container.classList.contains('q-mirrors') ? 'Mirror' : 'Part';
    if (q) renumber(container, q, kind);
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

// Website poster URL: live thumbnail preview (browser loads the image; the server never fetches it)
(function () {
  document.querySelectorAll('[data-wp]').forEach((box) => {
    const inp = box.querySelector('input[name="web_poster_url"]');
    const prev = box.querySelector('[data-wp-prev]');
    const msg = box.querySelector('[data-wp-msg]');
    const base = msg ? msg.textContent : '';
    let t;
    const ok = (u) => /^https?:\/\/[^\s<>"'`\\]+$/i.test(u) && u.length <= 1000;
    const show = () => {
      const u = inp.value.trim();
      prev.classList.remove('on', 'bad');
      prev.querySelectorAll('img').forEach(i => i.remove());
      if (msg) msg.textContent = base;
      if (!u) return;
      if (!ok(u)) { prev.classList.add('bad'); if (msg) msg.textContent = 'Must start with http:// or https:// (no spaces or quotes).'; return; }
      const img = new Image();
      img.alt = ''; img.referrerPolicy = 'no-referrer';
      img.onload = () => prev.classList.add('on');
      img.onerror = () => { img.remove(); prev.classList.add('bad'); if (msg) msg.textContent = "Couldn't load that image. Check the link is a direct image URL."; };
      img.src = u;
      prev.prepend(img);
    };
    inp.addEventListener('input', () => { clearTimeout(t); t = setTimeout(show, 300); });
    const form = inp.closest('form');
    form && form.addEventListener('submit', (ev) => {
      const u = inp.value.trim();
      if (u && !ok(u)) { ev.preventDefault(); show(); inp.focus(); }
    });
  });
})();

// Live stats: render from embedded JSON, refresh /admin/api/stats every 30s
(function liveStats() {
  const root = document.getElementById('live-stats');
  const raw = document.getElementById('live-stats-data');
  if (!root || !raw) return;

  const METRICS = ['clicks', 'users', 'episodes', 'requests', 'reports'];
  const INTERVAL = 30000;
  let data;
  try { data = JSON.parse(raw.textContent); } catch (e) { return; }
  let metric = root.getAttribute('data-default-metric') || 'clicks';
  if (!METRICS.includes(metric)) metric = 'clicks';
  let fetchedAt = Date.now();

  function sparkline(values, w, h) {
    w = w || 120; h = h || 36;
    const vals = (values && values.length ? values : [0]).map(v => Math.max(0, +v || 0));
    const mx = Math.max.apply(null, vals.concat([1]));
    const n = vals.length;
    const pts = vals.map((v, i) => {
      const x = n === 1 ? 0 : i * w / (n - 1);
      const y = h - 2 - (v / mx) * (h - 4);
      return x.toFixed(1) + ',' + y.toFixed(1);
    });
    const line = pts.join(' ');
    const area = '0,' + h + ' ' + line + ' ' + w + ',' + h;
    return '<svg class="spark" viewBox="0 0 ' + w + ' ' + h + '" width="' + w + '" height="' + h +
      '" preserveAspectRatio="none" aria-hidden="true"><polygon class="spark-fill" points="' + area +
      '"/><polyline class="spark-line" fill="none" points="' + line + '"/></svg>';
  }

  function barChart(days, values, w, h) {
    w = w || 640; h = h || 148;
    const vals = (values || []).map(v => Math.max(0, +v || 0));
    const labels = days || [];
    const n = Math.max(vals.length, 1);
    const mx = Math.max.apply(null, vals.concat([1]));
    const padT = 8, padB = 22, padX = 2;
    const innerH = h - padT - padB;
    const gap = 2;
    const bw = Math.max(1.4, (w - 2 * padX - gap * (n - 1)) / n);
    let bars = '';
    for (let i = 0; i < n; i++) {
      const v = vals[i] || 0;
      const x = padX + i * (bw + gap);
      let bh = mx ? (v / mx) * innerH : 0;
      let y = padT + innerH - bh;
      let cls = 'on';
      let ht = v ? Math.max(bh, 1.5) : 1.2;
      if (!v) { y = padT + innerH - 1.2; cls = 'empty'; }
      const day = labels[i] || '';
      bars += '<rect class="' + cls + '" x="' + x.toFixed(2) + '" y="' + y.toFixed(2) +
        '" width="' + bw.toFixed(2) + '" height="' + ht.toFixed(2) + '" rx="1.4"><title>' +
        esc(day) + ': ' + v + '</title></rect>';
    }
    function lab(i) {
      if (!labels[i]) return '';
      const x = padX + i * (bw + gap) + bw / 2;
      const anchor = i === 0 ? 'start' : (i === n - 1 ? 'end' : 'middle');
      return '<text class="bar-lab" x="' + x.toFixed(1) + '" y="' + (h - 6) +
        '" text-anchor="' + anchor + '">' + esc((labels[i] || '').slice(5)) + '</text>';
    }
    const mid = Math.floor(n / 2);
    return '<svg class="bars" viewBox="0 0 ' + w + ' ' + h + '" width="100%" height="' + h +
      '" preserveAspectRatio="none" role="img" aria-label="Activity last 30 days">' +
      bars + lab(0) + lab(mid) + lab(n - 1) + '</svg>';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function fmtDelta(n, period) {
    n = +n || 0;
    const cls = n > 0 ? 'up' : (n < 0 ? 'down' : 'zero');
    const sign = n > 0 ? '+' + n : String(n);
    return '<div class="stat-delta ' + cls + '">' + sign + ' · ' + esc(period || '7d') + '</div>';
  }

  function rankList(rows, countKey, empty) {
    if (!rows || !rows.length) return '<p class="muted sm empty-mini">' + esc(empty) + '</p>';
    let mx = 1;
    rows.forEach(r => { mx = Math.max(mx, +r[countKey] || 0); });
    return '<ol class="rank-list">' + rows.map((r, i) => {
      const n = +r[countKey] || 0;
      const pct = Math.max(4, Math.round(n * 100 / mx));
      const title = esc(r.title || r.quality || '—');
      const label = r.id
        ? '<a href="/admin/drama/' + (+r.id) + '">' + title + '</a>'
        : '<span>' + title + '</span>';
      return '<li><span class="rank-i">' + (i + 1) + '</span><div class="rank-body">' + label +
        '<i class="rank-bar" style="width:' + pct + '%"></i></div><span class="rank-n">' + n + '</span></li>';
    }).join('') + '</ol>';
  }

  function upcomingList(rows) {
    if (!rows || !rows.length) return '<p class="muted sm empty-mini">No upcoming episode dates set.</p>';
    return '<ul class="air-list">' + rows.map(r => {
      const ep = r.season ? ('S' + r.season + ' Ep ' + r.episode) : ('Ep ' + r.episode);
      const extra = r.time ? ' · ' + esc(r.time) : '';
      return '<li><a href="/admin/drama/' + (+r.id) + '"><b>' + esc(r.title) + '</b></a>' +
        '<div class="muted sm">' + esc(ep) + ' · ' + esc(r.date) + extra + '</div></li>';
    }).join('') + '</ul>';
  }

  function periodPills(deltas, key) {
    return ['24h', '7d', '30d'].map(p => {
      const n = +((deltas[p] || {})[key] || 0);
      const sign = n > 0 ? '+' + n : String(n);
      return '<span class="period-pill" data-period="' + p + '"><b>' + sign + '</b> ' + p + '</span>';
    }).join('');
  }

  function agoText() {
    const s = Math.max(0, Math.round((Date.now() - fetchedAt) / 1000));
    if (s < 10) return 'Updated just now';
    if (s < 60) return 'Updated ' + s + 's ago';
    const m = Math.round(s / 60);
    return 'Updated ' + m + 'm ago';
  }

  function setText(sel, value) {
    root.querySelectorAll(sel).forEach(el => { el.textContent = value; });
  }

  function render(d) {
    data = d;
    const t = d.totals || {};
    const d7 = (d.deltas || {})['7d'] || {};
    const series = d.series || {};
    const numbers = {
      dramas: t.dramas, ongoing: t.ongoing, completed: t.completed, episodes: t.episodes,
      users: t.users, requests: t.requests, reports_open: t.reports_open, clicks: t.clicks
    };
    Object.keys(numbers).forEach(k => {
      const el = root.querySelector('[data-n="' + k + '"]');
      if (el && numbers[k] != null) el.textContent = numbers[k];
    });
    const reqSub = (t.requests_open || 0) + ' pending · ' + (t.requests_replied || 0) + ' replied';
    let userSub = (t.users_started || 0) + ' started';
    if (t.users_blocked) userSub += ' · ' + t.users_blocked + ' blocked';
    const subEl = root.querySelector('[data-sub="requests"]');
    if (subEl) subEl.textContent = reqSub;
    const uEl = root.querySelector('[data-sub="users"]');
    if (uEl) uEl.textContent = userSub;

    const deltaMap = {
      dramas: d7.dramas, episodes: d7.episodes, users: d7.users,
      requests: d7.requests, reports_open: d7.reports, clicks: d7.clicks
    };
    Object.keys(deltaMap).forEach(k => {
      const card = root.querySelector('[data-stat="' + k + '"] .stat-delta');
      if (card) card.outerHTML = fmtDelta(deltaMap[k], '7d');
    });
    const sparkMap = {
      dramas: series.dramas, episodes: series.episodes, users: series.users,
      requests: series.requests, reports_open: series.reports, clicks: series.clicks
    };
    Object.keys(sparkMap).forEach(k => {
      const box = root.querySelector('[data-spark="' + k + '"]');
      if (box && sparkMap[k]) box.innerHTML = sparkline(sparkMap[k]);
    });
    const chart = root.querySelector('[data-chart]');
    if (chart) chart.innerHTML = barChart(series.days || [], series[metric] || []);
    const periods = root.querySelector('[data-periods]');
    if (periods) periods.innerHTML = periodPills(d.deltas || {}, metric);
    const up = root.querySelector('[data-upcoming]');
    if (up) up.innerHTML = upcomingList(d.upcoming || []);
    const tc = root.querySelector('[data-top-clicked]');
    if (tc) tc.innerHTML = rankList(d.top_clicked_7d || [], 'clicks', 'No clicks in the last 7 days.');
    const tf = root.querySelector('[data-top-followed]');
    if (tf) tf.innerHTML = rankList(d.top_followed || [], 'followers', 'No followers yet.');
    const tq = root.querySelector('[data-top-qualities]');
    if (tq) tq.innerHTML = rankList(d.top_qualities_7d || [], 'clicks', 'No quality clicks in the last 7 days.');
    const extra = root.querySelector('.live-extra');
    if (extra) {
      extra.innerHTML = '<span>Posts today <b>' + (t.posts_today || 0) + '</b></span>' +
        '<span>Follows <b>' + (t.follows || 0) + '</b></span>' +
        '<span>Pending schedules <b>' + (t.pending_schedules || 0) + '</b></span>';
    }
    const ago = root.querySelector('[data-live-updated]');
    if (ago) ago.textContent = agoText();
  }

  function setMetric(next) {
    if (!METRICS.includes(next)) return;
    metric = next;
    root.querySelectorAll('.act-tab').forEach(btn => {
      btn.classList.toggle('on', btn.getAttribute('data-metric') === metric);
    });
    const series = (data && data.series) || {};
    const chart = root.querySelector('[data-chart]');
    if (chart) chart.innerHTML = barChart(series.days || [], series[metric] || []);
    const periods = root.querySelector('[data-periods]');
    if (periods) periods.innerHTML = periodPills((data && data.deltas) || {}, metric);
  }

  root.querySelectorAll('.act-tab').forEach(btn => {
    btn.addEventListener('click', () => setMetric(btn.getAttribute('data-metric')));
  });

  async function tick() {
    try {
      const r = await fetch('/admin/api/stats', { credentials: 'same-origin', headers: { 'Accept': 'application/json' } });
      if (!r.ok) throw new Error('status ' + r.status);
      const d = await r.json();
      if (!d || !d.ok) throw new Error('bad payload');
      fetchedAt = Date.now();
      root.classList.remove('stale');
      render(d);
    } catch (err) {
      root.classList.add('stale');
      const ago = root.querySelector('[data-live-updated]');
      if (ago) ago.textContent = 'Refresh failed · ' + agoText();
    }
  }

  setInterval(() => {
    const ago = root.querySelector('[data-live-updated]');
    if (ago && !root.classList.contains('stale')) ago.textContent = agoText();
  }, 5000);
  setInterval(tick, INTERVAL);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
})();

(function addDramaSilent() {
  const form = document.getElementById('add-drama-form');
  if (!form) return;
  const box = form.querySelector('input[name="silent"]');
  const hint = document.getElementById('add-post-hint');
  const btn = document.getElementById('add-submit');
  if (!box || !btn) return;
  const defaultHtml = btn.innerHTML;
  function sync() {
    if (box.checked) {
      if (hint) hint.textContent = "The drama is saved only — nothing is posted to the channel.";
      btn.innerHTML = 'Create without posting';
    } else {
      if (hint) hint.textContent = "The channel card is posted as soon as you create.";
      btn.innerHTML = defaultHtml;
    }
  }
  box.addEventListener('change', sync);
  sync();
})();

(function bulkForm() {
  const form = document.getElementById('bulk-form');
  if (!form) return;
  wireQualityButtons(form);
  const modeEl = document.getElementById('bulk-mode');
  const rangePane = document.getElementById('bulk-range');
  const pastePane = document.getElementById('bulk-paste');
  const live = document.getElementById('bulk-live-preview');
  const serverPrev = document.getElementById('bulk-server-preview');
  const errEl = document.getElementById('bulk-err');
  const existingMap = JSON.parse(form.getAttribute('data-existing') || '{}');
  const QUALITIES = ['480p', '720p', '1080p'];

  function showErr(msg) {
    if (!errEl) return;
    errEl.hidden = !msg;
    errEl.textContent = msg || '';
  }

  function setMode(mode) {
    if (modeEl) modeEl.value = mode;
    if (rangePane) rangePane.hidden = mode !== 'range';
    if (pastePane) pastePane.hidden = mode !== 'paste';
    form.querySelectorAll('[data-bulk-tab]').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-bulk-tab') === mode);
    });
    updateLive();
  }
  form.querySelectorAll('[data-bulk-tab]').forEach(btn => {
    btn.addEventListener('click', () => setMode(btn.getAttribute('data-bulk-tab')));
  });

  function existingNums() {
    const sn = (document.getElementById('bulk-season') || {}).value || '1';
    return new Set((existingMap[sn] || []).map(Number));
  }

  function onExisting() {
    const el = form.querySelector('input[name="on_existing"]:checked');
    return (el && el.value) || 'skip';
  }

  function fillEp(tmpl, n) {
    return tmpl.replace(/\{(episode|ep)\}/gi, String(n));
  }

  function parseRange() {
    const urls = [];
    form.querySelectorAll('#bulk-range .q-block').forEach(block => {
      const q = block.getAttribute('data-quality');
      block.querySelectorAll('.q-parts input').forEach(inp => {
        const v = inp.value.trim();
        if (v) urls.push({ q, url: v, kind: 'part' });
      });
      block.querySelectorAll('.q-mirrors input').forEach(inp => {
        const v = inp.value.trim();
        if (v) urls.push({ q, url: v, kind: 'mirror' });
      });
    });
    if (!urls.length) return { episodes: {}, error: null, empty: true };
    if (urls.find(u => !/^https?:\/\//i.test(u.url))) {
      return { episodes: {}, error: 'Every link must start with http:// or https://' };
    }
    let fr = (document.getElementById('bulk-from').value || '1').trim() || '1';
    let to = (document.getElementById('bulk-to').value || '').trim() || fr;
    if (!/^\d+$/.test(fr) || !/^\d+$/.test(to) || +fr < 1 || +to < +fr || +to > 9999) {
      return { episodes: {}, error: 'From/To range invalid (need 1 ≤ from ≤ to ≤ 9999)' };
    }
    const episodes = {};
    for (let n = +fr; n <= +to; n++) {
      episodes[n] = urls.map(u => ({ q: u.q, url: fillEp(u.url, n), kind: u.kind }));
    }
    return { episodes, error: null };
  }

  function parsePaste() {
    const text = (document.getElementById('bulk-paste-box') || {}).value || '';
    const episodes = {};
    const issues = [];
    const lines = text.split(/\r?\n/);
    const epCell = /^(?:ep|episode|#)?\s*[:#]?\s*(\d+)$/i;
    const labeled = /(480p|720p|1080p|hd|4k|2160p|540p)([\s_\-]*mirror)?\s*[:.\-]?\s*(https?:\/\/\S+)/i;
    const headers = { ep: 1, episode: 1, 'ep#': 1, '#': 1, num: 1, number: 1, '480p': 1, '720p': 1, '1080p': 1 };
    function splitRow(line) {
      if (line.includes('|')) return line.split('|').map(s => s.trim());
      if (line.includes('\t')) return line.split('\t').map(s => s.trim());
      const parts = line.split(',').map(s => s.trim());
      if (parts.length >= 2 && epCell.test(parts[0])) return parts;
      const toks = line.trim().split(/\s+/);
      if (toks.length >= 2 && epCell.test(toks[0]) && toks.slice(1).some(t => /^https?:\/\//i.test(t) || labeled.test(t))) {
        return [toks[0]].concat(toks.slice(1));
      }
      return [line.trim()];
    }
    function parseCell(cell, defaultQ) {
      const out = [];
      const raw = (cell || '').trim();
      if (!raw) return out;
      const re = /(480p|720p|1080p|hd|4k|2160p|540p)([\s_\-]*mirror)?\s*[:.\-]?\s*(https?:\/\/\S+)/ig;
      let leftover = raw, m;
      const spans = [];
      while ((m = re.exec(raw))) {
        const q = m[1].toLowerCase() === 'hd' ? 'HD' : (['4k', '2160p'].includes(m[1].toLowerCase()) ? '4K' : m[1].toLowerCase());
        out.push({ q, url: m[3], kind: m[2] ? 'mirror' : 'part' });
        spans.push([m.index, m.index + m[0].length]);
      }
      spans.reverse().forEach(([a, b]) => { leftover = leftover.slice(0, a) + ' ' + leftover.slice(b); });
      leftover.split(/[,\s]+/).filter(Boolean).forEach(tok => {
        if (!defaultQ) throw new Error('this column needs a quality or a labeled link');
        if (!/^https?:\/\//i.test(tok) || /\s/.test(tok)) throw new Error('not a valid http(s) link: ' + tok.slice(0, 60));
        out.push({ q: defaultQ, url: tok, kind: 'part' });
      });
      return out;
    }
    if (!text.trim()) return { episodes: {}, error: null, empty: true, issues };
    lines.forEach((raw, i) => {
      const line = raw.trim();
      if (!line || line.startsWith('#')) return;
      const cells = splitRow(line);
      const head = (cells[0] || '').trim().toLowerCase().replace(/[:#]+$/, '');
      if (headers[head] && !cells.some(c => c.includes('://'))) return;
      const m = epCell.exec(cells[0] || '');
      if (!m) { issues.push({ line: i + 1, kind: 'error', message: 'Line must start with an episode number', text: line }); return; }
      const ep = +m[1];
      if (ep < 1 || ep > 9999) { issues.push({ line: i + 1, kind: 'error', message: 'Episode number must be 1–9999', text: line }); return; }
      try {
        const rest = cells.slice(1);
        if (!rest.length) throw new Error('no links on this line');
        const links = [];
        rest.forEach((cell, idx) => {
          const dq = QUALITIES[idx] || '1080p';
          links.push(...parseCell(cell, dq));
        });
        if (!links.length) throw new Error('No valid http(s) links on this line');
        if (episodes[ep]) {
          episodes[ep] = episodes[ep].concat(links);
          issues.push({ line: i + 1, kind: 'warn', message: 'EP ' + ep + ' appears more than once — links were merged', text: line });
        } else episodes[ep] = links;
      } catch (e) {
        issues.push({ line: i + 1, kind: 'error', message: e.message, text: line });
      }
    });
    const errors = issues.filter(x => x.kind === 'error');
    return { episodes, issues, error: (!Object.keys(episodes).length && errors[0]) ? errors[0].message : null };
  }

  function planOf(episodes) {
    const exist = existingNums();
    const mode = onExisting();
    const add = {}, skip = [], overwrite = [];
    Object.keys(episodes).map(Number).sort((a, b) => a - b).forEach(n => {
      if (exist.has(n)) {
        if (mode === 'overwrite') { add[n] = episodes[n]; overwrite.push(n); }
        else skip.push(n);
      } else add[n] = episodes[n];
    });
    return { add, skip, overwrite };
  }

  function summary(links) {
    const quals = [];
    (links || []).forEach(l => { if (!quals.includes(l.q)) quals.push(l.q); });
    const n = (links || []).length;
    return quals.join(', ') + ' · ' + n + ' link' + (n === 1 ? '' : 's');
  }

  function renderLive(parsed) {
    if (!live) return;
    if (parsed.empty) { live.hidden = true; live.innerHTML = ''; return; }
    if (parsed.error && !Object.keys(parsed.episodes || {}).length) {
      live.hidden = false;
      live.innerHTML = '<div class="preview-head"><h3>Live preview</h3></div><p class="muted">' + escapeHtml(parsed.error) + '</p>';
      return;
    }
    const plan = planOf(parsed.episodes || {});
    const issues = parsed.issues || [];
    const rows = [];
    const all = [];
    Object.keys(plan.add).forEach(n => all.push([+n, plan.add[n], plan.overwrite.includes(+n) ? 'overwrite' : 'new']));
    plan.skip.forEach(n => all.push([n, null, 'skip']));
    all.sort((a, b) => a[0] - b[0]);
    const max = 40;
    const shown = all.length > max ? all.slice(0, max - 6).concat([[null, null, 'ellipsis']]).concat(all.slice(-6)) : all;
    const hidden = all.length > max ? all.length - (max - 6) - 6 : 0;
    shown.forEach(([n, links, status]) => {
      if (status === 'ellipsis') {
        rows.push('<tr class="preview-more"><td colspan="3">' + hidden + ' more episodes not shown here.</td></tr>');
        return;
      }
      const badge = status === 'new' ? '<span class="pill ok">new</span>'
        : status === 'overwrite' ? '<span class="pill warn">exists — will overwrite</span>'
        : '<span class="pill neutral">exists — will skip</span>';
      const url = links && links[0] ? escapeHtml(links[0].url) : '';
      const sum = links ? escapeHtml(summary(links)) : 'already in the database';
      rows.push('<tr class="st-' + status + '"><td><span class="ep-n">EP ' + n + '</span></td><td>' + sum
        + (url ? '<div class="preview-url" title="' + url + '">' + url + '</div>' : '') + '</td><td>' + badge + '</td></tr>');
    });
    const nNew = Object.keys(plan.add).length - plan.overwrite.length;
    const pills = [];
    if (nNew) pills.push('<span class="pill ok">' + nNew + ' new</span>');
    if (plan.overwrite.length) pills.push('<span class="pill warn">' + plan.overwrite.length + ' overwrite</span>');
    if (plan.skip.length) pills.push('<span class="pill neutral">' + plan.skip.length + ' skipped</span>');
    const errN = issues.filter(x => x.kind === 'error').length;
    if (errN) pills.push('<span class="pill err">' + errN + ' line error' + (errN === 1 ? '' : 's') + '</span>');
    const issueHtml = issues.length
      ? '<ul class="preview-issues">' + issues.slice(0, 8).map(x =>
          '<li class="' + x.kind + '">Line ' + x.line + ': ' + escapeHtml(x.message) + '</li>').join('') + '</ul>'
      : '';
    live.hidden = false;
    live.innerHTML = '<div class="preview-head"><h3>Live preview</h3><div class="pills">' + pills.join('')
      + '</div></div>' + issueHtml
      + '<div class="table-wrap"><table class="table compact preview-table"><thead><tr><th>Ep</th><th>Links</th><th>Status</th></tr></thead><tbody>'
      + (rows.join('') || '<tr><td colspan="3" class="muted">Nothing to import.</td></tr>')
      + '</tbody></table></div>';
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function currentParse() {
    const mode = (modeEl && modeEl.value) || 'range';
    return mode === 'paste' ? parsePaste() : parseRange();
  }

  function updateLive(fromUser) {
    if (fromUser && serverPrev) serverPrev.hidden = true;
    if (serverPrev && !serverPrev.hidden) {
      if (live) live.hidden = true;
      return;
    }
    renderLive(currentParse());
  }

  form.addEventListener('input', () => updateLive(true));
  form.addEventListener('change', () => updateLive(true));
  const rangeHint = document.getElementById('bulk-range-hint');
  function updateRangeHint() {
    if (!rangeHint) return;
    const parsed = parseRange();
    if (parsed.empty || parsed.error) { rangeHint.textContent = ''; return; }
    const keys = Object.keys(parsed.episodes).map(Number);
    const sample = parsed.episodes[keys[0]][0].url;
    const n = keys.length;
    rangeHint.textContent = n === 1
      ? 'Will create episode ' + keys[0] + ': ' + sample
      : 'Will create ' + n + ' episodes (' + keys[0] + '–' + keys[keys.length - 1] + '). Example: ' + sample;
  }
  form.addEventListener('input', updateRangeHint);
  updateRangeHint();
  updateLive();

  form.addEventListener('submit', (ev) => {
    showErr('');
    const parsed = currentParse();
    if (parsed.empty) {
      ev.preventDefault();
      showErr((modeEl && modeEl.value) === 'paste'
        ? 'Paste one episode per line, or use the range tab'
        : 'Add a from/to range and at least one http(s) link template');
      return;
    }
    if (parsed.error && !Object.keys(parsed.episodes || {}).length) {
      ev.preventDefault();
      showErr(parsed.error);
    }
  });
})();

(function editepForm() {
  const form = document.getElementById('editep-form');
  if (!form) return;
  wireQualityButtons(form);
  const epEl = document.getElementById('editep-ep');
  const errEl = document.getElementById('editep-err');
  function showErr(msg) {
    if (!errEl) return;
    errEl.hidden = !msg;
    errEl.textContent = msg || '';
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

(function bulkLinksForm() {
  const form = document.getElementById('bulk-links-form');
  if (!form) return;
  wireQualityButtons(form);
  const modeEl = document.getElementById('bulk-links-mode');
  const rangePane = document.getElementById('bulk-links-range');
  const pastePane = document.getElementById('bulk-links-paste');
  const live = document.getElementById('bulk-links-live-preview');
  const serverPrev = document.getElementById('bulk-server-preview');
  const errEl = document.getElementById('bulk-links-err');
  const existingMap = JSON.parse(form.getAttribute('data-existing-links') || '{}');
  const QUALITIES = ['480p', '720p', '1080p'];

  function showErr(msg) {
    if (!errEl) return;
    errEl.hidden = !msg;
    errEl.textContent = msg || '';
  }
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function setMode(mode) {
    if (modeEl) modeEl.value = mode;
    if (rangePane) rangePane.hidden = mode !== 'range';
    if (pastePane) pastePane.hidden = mode !== 'paste';
    form.querySelectorAll('[data-bulk-tab]').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-bulk-tab') === mode);
    });
    updateLive();
  }
  form.querySelectorAll('[data-bulk-tab]').forEach(btn => {
    btn.addEventListener('click', () => setMode(btn.getAttribute('data-bulk-tab')));
  });

  function existingForSeason() {
    const sn = (document.getElementById('bulk-links-season') || {}).value || '1';
    return existingMap[sn] || {};
  }
  function clearEmpty() {
    return !!(form.querySelector('input[name="clear_empty"]') || {}).checked;
  }
  function fillEp(tmpl, n) {
    return tmpl.replace(/\{(episode|ep)\}/gi, String(n));
  }

  function parseRange() {
    const urls = [];
    form.querySelectorAll('#bulk-links-range .q-block').forEach(block => {
      const q = block.getAttribute('data-quality');
      block.querySelectorAll('.q-parts input').forEach(inp => {
        const v = inp.value.trim();
        if (v) urls.push({ q, url: v, kind: 'part' });
      });
      block.querySelectorAll('.q-mirrors input').forEach(inp => {
        const v = inp.value.trim();
        if (v) urls.push({ q, url: v, kind: 'mirror' });
      });
    });
    if (!urls.length) return { episodes: {}, error: null, empty: true };
    if (urls.find(u => !/^https?:\/\//i.test(u.url))) {
      return { episodes: {}, error: 'Every link must start with http:// or https://' };
    }
    let fr = (document.getElementById('bulk-links-from').value || '1').trim() || '1';
    let to = (document.getElementById('bulk-links-to').value || '').trim() || fr;
    if (!/^\d+$/.test(fr) || !/^\d+$/.test(to) || +fr < 1 || +to < +fr || +to > 9999) {
      return { episodes: {}, error: 'From/To range invalid (need 1 ≤ from ≤ to ≤ 9999)' };
    }
    const episodes = {};
    for (let n = +fr; n <= +to; n++) {
      episodes[n] = urls.map(u => [u.q, fillEp(u.url, n), u.kind]);
    }
    return { episodes, error: null };
  }

  function parsePaste() {
    const text = (document.getElementById('bulk-links-paste-box') || {}).value || '';
    const episodes = {};
    const issues = [];
    const lines = text.split(/\r?\n/);
    const epCell = /^(?:ep|episode|#)?\s*[:#]?\s*(\d+)$/i;
    const labeled = /(480p|720p|1080p|hd|4k|2160p|540p)([\s_\-]*mirror)?\s*[:.\-]?\s*(https?:\/\/\S+)/i;
    const headers = { ep: 1, episode: 1, 'ep#': 1, '#': 1, num: 1, number: 1, '480p': 1, '720p': 1, '1080p': 1 };
    function splitRow(line) {
      if (line.includes('|')) return line.split('|').map(s => s.trim());
      if (line.includes('\t')) return line.split('\t').map(s => s.trim());
      const parts = line.split(',').map(s => s.trim());
      if (parts.length >= 2 && epCell.test(parts[0])) return parts;
      const toks = line.trim().split(/\s+/);
      if (toks.length >= 2 && epCell.test(toks[0]) && toks.slice(1).some(t => /^https?:\/\//i.test(t) || labeled.test(t))) {
        return [toks[0]].concat(toks.slice(1));
      }
      return [line.trim()];
    }
    function parseCell(cell, defaultQ) {
      const out = [];
      const raw = (cell || '').trim();
      if (!raw) return out;
      const re = /(480p|720p|1080p|hd|4k|2160p|540p)([\s_\-]*mirror)?\s*[:.\-]?\s*(https?:\/\/\S+)/ig;
      let leftover = raw, m;
      const spans = [];
      while ((m = re.exec(raw))) {
        const q = m[1].toLowerCase() === 'hd' ? 'HD' : (['4k', '2160p'].includes(m[1].toLowerCase()) ? '4K' : m[1].toLowerCase());
        out.push([q, m[3], m[2] ? 'mirror' : 'part']);
        spans.push([m.index, m.index + m[0].length]);
      }
      spans.reverse().forEach(([a, b]) => { leftover = leftover.slice(0, a) + ' ' + leftover.slice(b); });
      leftover.split(/[,\s]+/).filter(Boolean).forEach(tok => {
        if (!defaultQ) throw new Error('this column needs a quality or a labeled link');
        if (!/^https?:\/\//i.test(tok) || /\s/.test(tok)) throw new Error('not a valid http(s) link: ' + tok.slice(0, 60));
        out.push([defaultQ, tok, 'part']);
      });
      return out;
    }
    if (!text.trim()) return { episodes: {}, error: null, empty: true, issues };
    lines.forEach((raw, i) => {
      const line = raw.trim();
      if (!line || line.startsWith('#')) return;
      const cells = splitRow(line);
      const head = (cells[0] || '').trim().toLowerCase().replace(/[:#]+$/, '');
      if (headers[head] && !cells.some(c => c.includes('://'))) return;
      const m = epCell.exec(cells[0] || '');
      if (!m) { issues.push({ line: i + 1, kind: 'error', message: 'Line must start with an episode number', text: line }); return; }
      const ep = +m[1];
      if (ep < 1 || ep > 9999) { issues.push({ line: i + 1, kind: 'error', message: 'Episode number must be 1–9999', text: line }); return; }
      try {
        const rest = cells.slice(1);
        if (!rest.length) throw new Error('no links on this line');
        const links = [];
        rest.forEach((cell, idx) => {
          const dq = QUALITIES[idx] || '1080p';
          links.push(...parseCell(cell, dq));
        });
        if (!links.length) throw new Error('No valid http(s) links on this line');
        if (episodes[ep]) {
          episodes[ep] = episodes[ep].concat(links);
          issues.push({ line: i + 1, kind: 'warn', message: 'EP ' + ep + ' appears more than once — links were merged', text: line });
        } else episodes[ep] = links;
      } catch (e) {
        issues.push({ line: i + 1, kind: 'error', message: e.message, text: line });
      }
    });
    const errors = issues.filter(x => x.kind === 'error');
    return { episodes, issues, error: (!Object.keys(episodes).length && errors[0]) ? errors[0].message : null };
  }

  function groupLinks(links) {
    const out = {};
    (links || []).forEach(item => {
      const q = item[0], u = item[1], k = item[2] || 'part';
      (out[q] || (out[q] = [])).push([q, u, k]);
    });
    return out;
  }
  function sameList(a, b) {
    if ((a || []).length !== (b || []).length) return false;
    return (a || []).every((x, i) => x[0] === b[i][0] && x[1] === b[i][1] && (x[2] || 'part') === (b[i][2] || 'part'));
  }
  function planOf(incoming) {
    const exist = existingForSeason();
    const clear = clearEmpty();
    const update = {}, missing = [], unchanged = [], diffs = {};
    Object.keys(incoming).map(Number).sort((a, b) => a - b).forEach(n => {
      const cur = exist[String(n)];
      if (!cur) { missing.push(n); return; }
      const curG = groupLinks(cur);
      const newG = groupLinks(incoming[n]);
      const quals = QUALITIES.slice();
      Object.keys(curG).concat(Object.keys(newG)).forEach(q => { if (!quals.includes(q)) quals.push(q); });
      const final = [];
      const changed = [];
      quals.forEach(q => {
        let nxt;
        if (Object.prototype.hasOwnProperty.call(newG, q)) nxt = newG[q];
        else if (clear && QUALITIES.includes(q)) nxt = [];
        else nxt = curG[q] || [];
        if (!sameList(nxt, curG[q] || [])) changed.push(q);
        final.push.apply(final, nxt);
      });
      if (!changed.length) unchanged.push(n);
      else { update[n] = final; diffs[n] = { old: cur, neu: final, changed }; }
    });
    return { update, missing, unchanged, diffs };
  }

  function diffHtml(oldL, newL, changed) {
    const oldG = groupLinks(oldL), newG = groupLinks(newL);
    return '<div class="link-diff">' + changed.map(q => {
      const olds = (oldG[q] || []).map(x => escapeHtml(x[1]));
      const news = (newG[q] || []).map(x => escapeHtml(x[1]));
      const oldH = olds.length
        ? olds.map(u => '<span class="diff-old" title="' + u + '">' + u + '</span>').join('<br>')
        : '<span class="diff-old muted">—</span>';
      const newH = news.length
        ? news.map(u => '<span class="diff-new" title="' + u + '">' + u + '</span>').join('<br>')
        : '<span class="diff-removed">removed</span>';
      return '<div class="diff-q"><span class="pill q">' + escapeHtml(q) + '</span>'
        + '<div class="diff-urls">' + oldH + '<span class="diff-arrow">→</span>' + newH + '</div></div>';
    }).join('') + '</div>';
  }

  function renderLive(parsed) {
    if (!live) return;
    if (parsed.empty) { live.hidden = true; live.innerHTML = ''; return; }
    if (parsed.error && !Object.keys(parsed.episodes || {}).length) {
      live.hidden = false;
      live.innerHTML = '<div class="preview-head"><h3>Live preview</h3></div><p class="muted">' + escapeHtml(parsed.error) + '</p>';
      return;
    }
    const plan = planOf(parsed.episodes || {});
    const issues = parsed.issues || [];
    const all = [];
    Object.keys(plan.update).forEach(n => all.push([+n, 'update', plan.diffs[+n]]));
    plan.unchanged.forEach(n => all.push([n, 'unchanged', null]));
    plan.missing.forEach(n => all.push([n, 'missing', null]));
    all.sort((a, b) => a[0] - b[0]);
    const max = 40;
    const shown = all.length > max ? all.slice(0, max - 6).concat([[null, 'ellipsis', null]]).concat(all.slice(-6)) : all;
    const hidden = all.length > max ? all.length - (max - 6) - 6 : 0;
    const rows = [];
    shown.forEach(([n, status, payload]) => {
      if (status === 'ellipsis') {
        rows.push('<tr class="preview-more"><td colspan="3">' + hidden + ' more episodes not shown here.</td></tr>');
        return;
      }
      let badge, cell;
      if (status === 'update') {
        badge = '<span class="pill ok">will update</span>';
        cell = diffHtml(payload.old, payload.neu, payload.changed);
      } else if (status === 'unchanged') {
        badge = '<span class="pill neutral">no change</span>';
        cell = '<span class="muted">Links already match</span>';
      } else {
        badge = '<span class="pill neutral">not in the database — skipped</span>';
        cell = '<span class="muted">This episode is not in the season, so it will not be added.</span>';
      }
      rows.push('<tr class="st-' + status + '"><td><span class="ep-n">EP ' + n + '</span></td><td>' + cell + '</td><td>' + badge + '</td></tr>');
    });
    const pills = [];
    const nUp = Object.keys(plan.update).length;
    if (nUp) pills.push('<span class="pill ok">' + nUp + ' will update</span>');
    if (plan.unchanged.length) pills.push('<span class="pill neutral">' + plan.unchanged.length + ' no change</span>');
    if (plan.missing.length) pills.push('<span class="pill warn">' + plan.missing.length + ' not in database</span>');
    const errN = issues.filter(x => x.kind === 'error').length;
    if (errN) pills.push('<span class="pill err">' + errN + ' line error' + (errN === 1 ? '' : 's') + '</span>');
    const issueHtml = issues.length
      ? '<ul class="preview-issues">' + issues.slice(0, 8).map(x =>
          '<li class="' + x.kind + '">Line ' + x.line + ': ' + escapeHtml(x.message) + '</li>').join('') + '</ul>'
      : '';
    live.hidden = false;
    live.innerHTML = '<div class="preview-head"><h3>Live preview</h3><div class="pills">' + pills.join('')
      + '</div></div>' + issueHtml
      + '<div class="table-wrap"><table class="table compact preview-table"><thead><tr><th>Ep</th><th>Current → new</th><th>Status</th></tr></thead><tbody>'
      + (rows.join('') || '<tr><td colspan="3" class="muted">Nothing to update.</td></tr>')
      + '</tbody></table></div>';
  }

  function currentParse() {
    const mode = (modeEl && modeEl.value) || 'range';
    return mode === 'paste' ? parsePaste() : parseRange();
  }
  function updateLive(fromUser) {
    if (fromUser && serverPrev) serverPrev.hidden = true;
    if (serverPrev && !serverPrev.hidden) {
      if (live) live.hidden = true;
      return;
    }
    renderLive(currentParse());
  }
  form.addEventListener('input', () => updateLive(true));
  form.addEventListener('change', () => updateLive(true));
  const rangeHint = document.getElementById('bulk-links-range-hint');
  function updateRangeHint() {
    if (!rangeHint) return;
    const parsed = parseRange();
    if (parsed.empty || parsed.error) { rangeHint.textContent = ''; return; }
    const keys = Object.keys(parsed.episodes).map(Number);
    const exist = existingForSeason();
    const known = keys.filter(n => exist[String(n)]).length;
    const sample = parsed.episodes[keys[0]][0][1];
    rangeHint.textContent = 'Will update ' + known + ' existing episode' + (known === 1 ? '' : 's')
      + ' in ' + keys[0] + '–' + keys[keys.length - 1] + '. Example: ' + sample;
  }
  form.addEventListener('input', updateRangeHint);
  updateRangeHint();
  updateLive();

  form.addEventListener('submit', (ev) => {
    showErr('');
    const parsed = currentParse();
    if (parsed.empty) {
      ev.preventDefault();
      showErr((modeEl && modeEl.value) === 'paste'
        ? 'Paste one episode per line, or use the range tab'
        : 'Add a from/to range and at least one http(s) link template');
      return;
    }
    if (parsed.error && !Object.keys(parsed.episodes || {}).length) {
      ev.preventDefault();
      showErr(parsed.error);
    }
  });
})();
