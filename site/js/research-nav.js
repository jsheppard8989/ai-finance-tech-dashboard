/**
 * Shared "Research" dropdown for the site nav.
 * Add future research pages to RESEARCH_PAGES only; every page with
 * <div class="nav-research" data-research-menu></div> in its nav picks them up.
 */
(function () {
  var RESEARCH_PAGES = [
    { label: 'SpaceX Model', href: 'https://jsheppard8989.github.io/spacex-path/' },
    { label: 'Healthcare Abundance', href: 'healthcare.html' },
    { label: 'GPU Rental Prices and the AI Builders', href: 'compute-thesis.html' }
  ];

  var CSS =
    '.nav-research{position:relative;display:inline-block}' +
    '.nav-research-btn{background:none;border:0;padding:0.25rem 0.1rem;min-height:44px;color:#00d4ff;font:inherit;font-size:0.95rem;font-weight:500;cursor:pointer}' +
    '.nav-research-btn:hover{text-decoration:underline}' +
    '.nav-research-btn:focus-visible,.nav-research-menu a:focus-visible{outline:2px solid #00d4ff;outline-offset:2px;border-radius:4px}' +
    '.nav-research-btn .caret{display:inline-block;margin-left:0.3rem;font-size:0.7em;transition:transform .15s}' +
    '.nav-research-btn[aria-expanded="true"] .caret{transform:rotate(180deg)}' +
    '.nav-research-menu{position:absolute;top:100%;left:50%;transform:translateX(-50%);z-index:1000;min-width:12rem;max-width:calc(100vw - 2rem);margin:0.25rem 0 0;padding:0.35rem;list-style:none;background:#14182b;border:1px solid rgba(255,255,255,0.15);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.45);text-align:left}' +
    '.nav-research-menu[hidden]{display:none}' +
    '.nav-research-menu a{display:block;padding:0.6rem 0.75rem;border-radius:6px;color:#00d4ff;text-decoration:none;white-space:nowrap}' +
    '.nav-research-menu a:hover,.nav-research-menu a:focus{background:rgba(0,212,255,0.12)}';

  function build(root, idx) {
    var menuId = 'nav-research-menu-' + idx;
    root.innerHTML = '';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nav-research-btn';
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-controls', menuId);
    btn.innerHTML = 'Research<span class="caret" aria-hidden="true">▾</span>';
    var menu = document.createElement('ul');
    menu.className = 'nav-research-menu';
    menu.id = menuId;
    menu.hidden = true;
    RESEARCH_PAGES.forEach(function (p) {
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
    var roots = document.querySelectorAll('[data-research-menu]');
    if (!roots.length) return;
    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);
    Array.prototype.forEach.call(roots, build);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
