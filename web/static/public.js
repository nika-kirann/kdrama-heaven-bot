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
          (r.poster ? '<img src="' + esc(r.poster) + '" alt="" loading="lazy" onerror="this.remove()">' : '') + '</div>' +
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
})();
