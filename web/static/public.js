/* kdrama_heaven public site — vanilla JS, progressive enhancement only. */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // theme (dark is the default; choice lives in localStorage)
  const THEME_KEY = 'kdh-theme';
  const themeBtn = $('#theme-toggle'), themeMeta = $('#theme-color');
  const applyTheme = (t) => {
    if (t === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
      themeMeta && themeMeta.setAttribute('content', '#f3f0fa');
    } else {
      document.documentElement.removeAttribute('data-theme');
      themeMeta && themeMeta.setAttribute('content', '#0b0918');
    }
    if (themeBtn) {
      const light = t === 'light';
      themeBtn.setAttribute('aria-label', light ? 'Switch to dark theme' : 'Switch to light theme');
      themeBtn.setAttribute('aria-pressed', light ? 'true' : 'false');
    }
  };
  try { applyTheme(localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'); } catch (e) { applyTheme('dark'); }
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* private mode */ }
      applyTheme(next);
    });
  }

  // posters: fade in once the file has loaded (cached images included)
  $$('.pst img, .bgimg').forEach(img => {
    const on = () => img.classList.add('is-on');
    if (img.complete && img.naturalWidth) on();
    else img.addEventListener('load', on, { once: true });
  });

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

  // live suggestions — debounced /api/search, keyboard nav; Enter (no highlight) goes to /search
  $$('input[data-suggest]').forEach(inp => {
    const form = inp.closest('form'), box = $('.suggest', form);
    let timer, ctl, idx = -1, items = [];
    const hl = (t, q) => {
      const i = t.toLowerCase().indexOf(q.toLowerCase());
      return i < 0 || !q ? esc(t) : esc(t.slice(0, i)) + '<mark>' + esc(t.slice(i, i + q.length)) + '</mark>' + esc(t.slice(i + q.length));
    };
    const close = () => { box.hidden = true; idx = -1; };
    const skel = () => {
      box.innerHTML = Array.from({ length: 3 }, () =>
        '<div class="sug skel" aria-hidden="true"><div class="pst skel-box"></div><div class="skel-lines"><i></i><i></i></div></div>'
      ).join('');
      box.hidden = false; idx = -1;
    };
    const render = (q, res) => {
      items = res;
      if (!res.length) { box.innerHTML = '<div class="sug-empty">No matches for “' + esc(q) + '”</div>'; box.hidden = false; return; }
      box.innerHTML = res.map((r, i) =>
        '<a class="sug" role="option" href="' + esc(r.url) + '" data-i="' + i + '">' +
          '<div class="pst" style="--h:' + (+r.h || 270) + '"><span class="pst-ph">' + esc(r.i || (r.title || '?')[0].toUpperCase()) + '</span>' +
          (r.poster ? '<img src="' + esc(r.poster) + '" alt="' + esc(r.title) + ' poster" loading="lazy" referrerpolicy="no-referrer" onload="this.classList.add(\'is-on\')" onerror="this.remove()">' : '') + '</div>' +
          '<div><b>' + hl(r.title, q) + '</b><small>' + esc([r.year, r.eps].filter(Boolean).join(' · ')) + '</small></div>' +
          '<span class="spill ' + (r.status === 'Completed' ? 'done' : 'live') + '"><i></i>' + esc(r.status) + '</span></a>'
      ).join('') + '<a class="sug-all" href="/search?q=' + encodeURIComponent(q) + '">See all results for “' + esc(q) + '”</a>';
      box.hidden = false; idx = -1;
    };
    inp.addEventListener('input', () => {
      clearTimeout(timer);
      const q = inp.value.trim();
      if (q.length < 2) { close(); return; }
      skel();
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
      const opts = $$('.sug:not(.skel)', box);
      if (e.key === 'Enter' && (box.hidden || idx < 0)) {
        // no highlighted suggestion: let the form go to /search
        close();
        return;
      }
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

  // hero carousel: auto-advance, pause on hover, swipe, respect reduced motion
  const hero = $('#hero');
  if (hero) {
    const slides = $$('.slide', hero), dots = $$('.dot', hero);
    let cur = 0, t, startX = 0, startY = 0, swiping = false;
    const go = (n) => {
      if (!slides.length) return;
      slides[cur].classList.remove('on'); dots[cur] && dots[cur].classList.remove('on');
      cur = (n + slides.length) % slides.length;
      slides[cur].classList.add('on'); dots[cur] && dots[cur].classList.add('on');
    };
    const auto = () => {
      clearInterval(t);
      if (!reduceMotion() && slides.length > 1 && !document.hidden) t = setInterval(() => go(cur + 1), 7000);
    };
    dots.forEach(d => d.addEventListener('click', () => { go(+d.dataset.go); auto(); }));
    hero.addEventListener('mouseenter', () => clearInterval(t));
    hero.addEventListener('mouseleave', auto);
    document.addEventListener('visibilitychange', auto);
    hero.addEventListener('touchstart', (e) => {
      if (e.changedTouches.length !== 1) return;
      startX = e.changedTouches[0].clientX;
      startY = e.changedTouches[0].clientY;
      swiping = true;
    }, { passive: true });
    hero.addEventListener('touchend', (e) => {
      if (!swiping) return;
      swiping = false;
      const dx = e.changedTouches[0].clientX - startX;
      const dy = e.changedTouches[0].clientY - startY;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) { go(cur + (dx < 0 ? 1 : -1)); auto(); }
    }, { passive: true });
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
      if (scroll && p) p.scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'nearest' });
    };
    grid.addEventListener('click', (e) => {
      const chip = e.target.closest('a.epc');
      if (!chip) return;
      e.preventDefault(); show(chip, true);
    });
    $$('[data-jump]').forEach(b => b.addEventListener('click', (e) => {
      const chip = $('a.epc[data-target="' + b.dataset.jump + '"]', grid);
      if (chip) { e.preventDefault(); show(chip, true); }
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
        ? '<img src="' + esc(it.poster) + '" alt="' + esc(it.title) + ' poster" loading="lazy" decoding="async" referrerpolicy="no-referrer" onload="this.classList.add(\'is-on\')" onerror="this.remove()">'
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

  // card / row fade-in on scroll
  if (!reduceMotion() && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver((ents) => {
      ents.forEach(en => {
        if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
      });
    }, { rootMargin: '0px 0px -32px 0px', threshold: 0.06 });
    $$('.card, .rail, .cta-band, .browse, .search-band').forEach(el => {
      if (el.getBoundingClientRect().top < window.innerHeight - 24) {
        el.classList.add('reveal', 'in');
      } else {
        el.classList.add('reveal');
        io.observe(el);
      }
    });
  }
})();
