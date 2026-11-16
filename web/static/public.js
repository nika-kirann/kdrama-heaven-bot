/* kdrama_heaven public site — vanilla JS, progressive enhancement only. */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  // header search toggle
  const panel = $('#hdr-search'), openB = $('#search-open'), closeB = $('#search-close');
  if (panel && openB) {
    openB.addEventListener('click', () => { panel.hidden = !panel.hidden; if (!panel.hidden) $('input', panel).focus(); });
    closeB && closeB.addEventListener('click', () => { panel.hidden = true; });
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); panel.hidden = false; $('input', panel).focus(); }
      if (e.key === 'Escape') panel.hidden = true;
    });
  }

  // live suggestions
  $$('input[data-suggest]').forEach(inp => {
    const form = inp.closest('form'), box = $('.suggest', form);
    let timer, ctl, idx = -1, items = [];
    const hl = (t, q) => {
      const i = t.toLowerCase().indexOf(q.toLowerCase());
      return i < 0 || !q ? esc(t) : esc(t.slice(0, i)) + '<mark>' + esc(t.slice(i, i + q.length)) + '</mark>' + esc(t.slice(i + q.length));
    };
    const close = () => { box.hidden = true; idx = -1; };
    const render = (q, res) => {
      items = res;
      if (!res.length) { box.innerHTML = '<div class="sug-empty">No matches for “' + esc(q) + '”</div>'; box.hidden = false; return; }
      box.innerHTML = res.map((r, i) =>
        '<a class="sug" role="option" href="' + esc(r.url) + '" data-i="' + i + '">' +
          '<div class="pst" style="--h:' + (+r.h || 270) + '"><span class="pst-ph">' + esc(r.i || (r.title || '?')[0].toUpperCase()) + '</span>' +
          (r.poster ? '<img src="' + esc(r.poster) + '" alt="' + esc(r.title) + ' poster" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">' : '') + '</div>' +
          '<div><b>' + hl(r.title, q) + '</b><small>' + esc([r.year, r.eps].filter(Boolean).join(' · ')) + '</small></div>' +
          '<span class="spill ' + (r.status === 'Completed' ? 'done' : 'live') + '"><i></i>' + esc(r.status) + '</span></a>'
      ).join('') + '<a class="sug-all" href="/search?q=' + encodeURIComponent(q) + '">See all results for “' + esc(q) + '”</a>';
      box.hidden = false; idx = -1;
    };
    inp.addEventListener('input', () => {
      clearTimeout(timer);
      const q = inp.value.trim();
      if (q.length < 2) { close(); return; }
      timer = setTimeout(async () => {
        try {
          ctl && ctl.abort(); ctl = new AbortController();
          const r = await fetch('/api/search?q=' + encodeURIComponent(q), { signal: ctl.signal });
          if (!r.ok) return;
          const j = await r.json();
          if (inp.value.trim() === q) render(q, j.results || []);
        } catch (e) { /* aborted / offline */ }
      }, 180);
    });
    inp.addEventListener('keydown', (e) => {
      const opts = $$('.sug', box);
      if (box.hidden || !opts.length) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        idx = (idx + (e.key === 'ArrowDown' ? 1 : -1) + opts.length) % opts.length;
        opts.forEach((o, i) => o.classList.toggle('on', i === idx));
        opts[idx].scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter' && idx >= 0) { e.preventDefault(); location.href = opts[idx].href; }
      else if (e.key === 'Escape') close();
    });
    inp.addEventListener('focus', () => { if (box.innerHTML && inp.value.trim().length >= 2) box.hidden = false; });
    document.addEventListener('click', (e) => { if (!form.contains(e.target)) close(); });
  });

  // hero carousel
  const hero = $('#hero');
  if (hero) {
    const slides = $$('.slide', hero), dots = $$('.dot', hero);
    let cur = 0, t;
    const go = (n) => {
      slides[cur].classList.remove('on'); dots[cur] && dots[cur].classList.remove('on');
      cur = (n + slides.length) % slides.length;
      slides[cur].classList.add('on'); dots[cur] && dots[cur].classList.add('on');
    };
    const auto = () => { clearInterval(t); if (slides.length > 1) t = setInterval(() => go(cur + 1), 7000); };
    dots.forEach(d => d.addEventListener('click', () => { go(+d.dataset.go); auto(); }));
    hero.addEventListener('mouseenter', () => clearInterval(t)); hero.addEventListener('mouseleave', auto);
    auto();
  }

  // episode picker: no reload, URL stays shareable
  const grid = $('#ep-grid');
  if (grid) {
    const show = (chip, scroll) => {
      $$('.epc.on', grid).forEach(c => c.classList.remove('on'));
      chip.classList.add('on');
      $$('.ep-panel').forEach(p => { p.hidden = p.id !== chip.dataset.target; });
      const url = new URL(chip.href); history.replaceState(null, '', url.pathname + url.search + '#episodes');
      const p = document.getElementById(chip.dataset.target);
      if (scroll && p) p.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
    grid.addEventListener('click', (e) => {
      const chip = e.target.closest('a.epc');
      if (!chip) return;
      e.preventDefault(); show(chip, true);
    });
    $$('[data-jump]').forEach(b => b.addEventListener('click', () => {
      const chip = $('a.epc[data-target="' + b.dataset.jump + '"]', grid); if (chip) show(chip, false);
    }));
  }

  // Continue watching — localStorage only, last 10 dramas on this device.
  const CW_KEY = 'kdh-continue', CW_MAX = 10;
  const cwRead = () => {
    try {
      const v = JSON.parse(localStorage.getItem(CW_KEY) || '[]');
      return Array.isArray(v) ? v : [];
    } catch (e) { return []; }
  };
  const cwWrite = (items) => {
    try { localStorage.setItem(CW_KEY, JSON.stringify(items.slice(0, CW_MAX))); }
    catch (e) { /* private mode / full */ }
  };
  const cwSave = (entry) => {
    if (!entry || entry.id == null) return;
    const id = +entry.id;
    const items = cwRead().filter(x => +x.id !== id);
    items.unshift({
      id, title: String(entry.title || ''), url: String(entry.url || ('/drama/' + id)),
      ep: entry.ep == null || entry.ep === '' ? null : +entry.ep,
      season: entry.season == null || entry.season === '' ? 1 : +entry.season,
      poster: entry.poster || '', h: +entry.h || 270, i: entry.i || (entry.title || '?')[0],
      ts: Date.now()
    });
    cwWrite(items);
  };
  const cwHref = (it) => {
    const base = it.url || ('/drama/' + it.id);
    if (it.ep == null) return base;
    const s = it.season || 1;
    const join = base.includes('?') ? '&' : '?';
    return base + join + 's=' + s + '&ep=' + it.ep + '#episodes';
  };
  const cwRender = () => {
    const sec = $('#continue'), track = $('#continue-track');
    if (!sec || !track) return;
    const items = cwRead().slice(0, CW_MAX);
    if (!items.length) { sec.hidden = true; track.innerHTML = ''; return; }
    track.innerHTML = items.map(it => {
      const ep = it.ep != null ? 'Continue EP ' + it.ep : 'Continue';
      const img = it.poster
        ? '<img src="' + esc(it.poster) + '" alt="' + esc(it.title) + ' poster" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.remove()">'
        : '';
      const letter = esc(it.i || (it.title || '?')[0] || '?');
      return '<article class="card cw-card">' +
        '<a href="' + esc(cwHref(it)) + '">' +
          '<div class="pst" style="--h:' + (+it.h || 270) + '">' +
            '<span class="pst-ph" aria-hidden="true">' + letter + '</span>' +
            '<span class="pst-t">' + esc(it.title) + '</span>' + img + '</div>' +
          '<div class="card-badges"><span class="cont">' + esc(ep) + '</span></div>' +
          '<div class="card-body"><h3>' + esc(it.title) + '</h3><p>' + esc(ep) + '</p></div></a>' +
        '<button type="button" class="cw-x" data-id="' + (+it.id) + '" aria-label="Remove ' + esc(it.title) + ' from continue watching">' +
          '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button></article>';
    }).join('');
    sec.hidden = false;
  };
  const main = $('#main');
  if (main && main.dataset.watch) {
    try { cwSave(JSON.parse(main.dataset.watch)); } catch (e) { /* ignore bad payload */ }
  }
  document.addEventListener('click', (e) => {
    const go = e.target.closest('a[href^="/go/"]');
    if (go) {
      const panel = go.closest('.ep-panel');
      if (panel && main && main.dataset.watch) {
        try {
          const cur = JSON.parse(main.dataset.watch);
          const ep = panel.dataset.ep ? +panel.dataset.ep : cur.ep;
          cwSave(Object.assign({}, cur, { ep: ep }));
        } catch (err) { /* ignore */ }
      }
    }
  });
  if (grid) {
    grid.addEventListener('click', (e) => {
      const chip = e.target.closest('a.epc');
      if (!chip || !main || !main.dataset.watch) return;
      try {
        const cur = JSON.parse(main.dataset.watch);
        cwSave(Object.assign({}, cur, { ep: +chip.dataset.ep || cur.ep }));
      } catch (err) { /* ignore */ }
    });
  }
  const cwSec = $('#continue');
  if (cwSec) {
    cwRender();
    cwSec.addEventListener('click', (e) => {
      const x = e.target.closest('.cw-x');
      if (x) {
        e.preventDefault(); e.stopPropagation();
        cwWrite(cwRead().filter(it => +it.id !== +x.dataset.id));
        cwRender();
        return;
      }
      if (e.target.closest('.cw-clear')) {
        e.preventDefault();
        cwWrite([]);
        cwRender();
      }
    });
  }
})();
