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
