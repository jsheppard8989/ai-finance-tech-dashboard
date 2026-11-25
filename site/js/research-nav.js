/**
 * Shared Research + Trades dropdowns for the site nav.
 * Add research theses to RESEARCH_PAGES and trade write-ups / the
 * scoreboard to TRADES_PAGES. Every page with
 * <div class="nav-research" data-research-menu></div> and
 * <div class="nav-trades" data-trades-menu></div> in its nav picks them up.
 */
(function () {
  var RESEARCH_PAGES = [
    { label: 'Who Owns the Energized Megawatt?', href: 'power-bottleneck.html' },
    { label: 'Who Keeps the Profit from the AI Compute Shortage', href: 'compute-thesis.html' },
    { label: 'Healthcare Abundance', href: 'healthcare.html' },
    { label: 'The Nasdaq-100 Is a Filter, Not a Stock Picker', href: 'qqq-filter.html' },
    { label: 'SpaceX Model', href: 'https://jsheppard8989.github.io/spacex-path/' }
  ];

  var TRADES_PAGES = [
    { label: 'Live Paper-Trade Scoreboard', href: 'trades.html' },
    { label: 'Lam Research: Paid to Wait (closed Nov 5)', href: 'lrcx-paid-to-wait.html' },
    { label: 'Micron and the Memory Cycle', href: 'mu-memory-cycle.html' }
  ];

  var CSS =
    '.nav-research,.nav-trades{position:relative;display:inline-block}' +
    '.nav-research-btn,.nav-trades-btn{background:none;border:0;padding:0.25rem 0.1rem;min-height:44px;color:#00d4ff;font:inherit;font-size:0.95rem;font-weight:500;cursor:pointer}' +
    '.nav-research-btn:hover,.nav-trades-btn:hover{text-decoration:underline}' +
    '.nav-research-btn:focus-visible,.nav-trades-btn:focus-visible,.nav-research-menu a:focus-visible,.nav-trades-menu a:focus-visible{outline:2px solid #00d4ff;outline-offset:2px;border-radius:4px}' +
    '.nav-research-btn .caret,.nav-trades-btn .caret{display:inline-block;margin-left:0.3rem;font-size:0.7em;transition:transform .15s}' +
    '.nav-research-btn[aria-expanded="true"] .caret,.nav-trades-btn[aria-expanded="true"] .caret{transform:rotate(180deg)}' +
    '.nav-research-menu,.nav-trades-menu{position:absolute;top:100%;left:50%;transform:translateX(-50%);z-index:1000;min-width:12rem;max-width:calc(100vw - 2rem);margin:0.25rem 0 0;padding:0.35rem;list-style:none;background:#14182b;border:1px solid rgba(255,255,255,0.15);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.45);text-align:left}' +
    '.nav-research-menu[hidden],.nav-trades-menu[hidden]{display:none}' +
    '.nav-research-menu a,.nav-trades-menu a{display:block;padding:0.6rem 0.75rem;border-radius:6px;color:#00d4ff;text-decoration:none;white-space:nowrap}' +
    '.nav-research-menu a:hover,.nav-research-menu a:focus,.nav-trades-menu a:hover,.nav-trades-menu a:focus{background:rgba(0,212,255,0.12)}' +
    '@media(max-width:640px){.site-nav{position:relative}.nav-research,.nav-trades{position:static}.nav-research-menu,.nav-trades-menu{left:8px;right:8px;width:auto;min-width:0;max-width:calc(100vw - 16px);transform:none;box-sizing:border-box}.nav-research-menu a,.nav-trades-menu a{white-space:normal;overflow-wrap:anywhere}}';

  function build(root, idx, label, pages, prefix) {
    var menuId = prefix + '-menu-' + idx;
    var btnClass = prefix + '-btn';
    var menuClass = prefix + '-menu';
    root.innerHTML = '';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = btnClass;
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-controls', menuId);
    btn.innerHTML = label + '<span class="caret" aria-hidden="true">▾</span>';
    var menu = document.createElement('ul');
    menu.className = menuClass;
    menu.id = menuId;
    menu.hidden = true;
    pages.forEach(function (p) {
      var li = document.createElement('li');
      var a = document.createElement('a');
      a.href = p.href;
      a.textContent = p.label;
      li.appendChild(a);
      menu.appendChild(li);
    });
    root.appendChild(btn);
    root.appendChild(menu);

    function links() { return Array.prototype.slice.call(menu.querySelectorAll('a')); }
    function open(focusFirst) {
      menu.hidden = false;
      btn.setAttribute('aria-expanded', 'true');
      if (focusFirst && links()[0]) links()[0].focus();
    }
    function close(refocus) {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      if (refocus) btn.focus();
    }
    btn.addEventListener('click', function () { menu.hidden ? open(false) : close(false); });
    btn.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); open(true); }
      else if (e.key === 'Escape') { close(true); }
    });
    menu.addEventListener('keydown', function (e) {
      var ls = links(), i = ls.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.preventDefault(); close(true); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); ls[(i + 1) % ls.length].focus(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); ls[(i - 1 + ls.length) % ls.length].focus(); }
      else if (e.key === 'Home') { e.preventDefault(); ls[0].focus(); }
      else if (e.key === 'End') { e.preventDefault(); ls[ls.length - 1].focus(); }
    });
    root.addEventListener('focusout', function (e) {
      if (!root.contains(e.relatedTarget)) close(false);
    });
    document.addEventListener('click', function (e) { if (!root.contains(e.target)) close(false); });
  }

  function init() {
    var researchRoots = document.querySelectorAll('[data-research-menu]');
    var tradesRoots = document.querySelectorAll('[data-trades-menu]');
    if (!researchRoots.length && !tradesRoots.length) return;
    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);
    Array.prototype.forEach.call(researchRoots, function (root, idx) {
      build(root, idx, 'Research', RESEARCH_PAGES, 'nav-research');
    });
    Array.prototype.forEach.call(tradesRoots, function (root, idx) {
      build(root, idx, 'Trades', TRADES_PAGES, 'nav-trades');
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
