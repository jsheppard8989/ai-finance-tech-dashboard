"""Regression checks for the Kit newsletter signup card."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

KIT_ACTION = "https://app.kit.com/forms/10236979/subscriptions"
KIT_EMBED = "scarcity-abundance.kit.com"
KIT_SCRIPT = (
    '<script async data-uid="7ac38e24ff" '
    'src="https://scarcity-abundance.kit.com/7ac38e24ff/index.js"></script>'
)
CSS_HREF = "./css/signup-card.css"
SIGNUP_COPY = "Get new research by email"

# Home + in-repo Research menu pages. trades.html is required only once it exists
# (added on the Research/Trades split branch).
ALWAYS_PAGES = [
    "index.html",
    "power-bottleneck.html",
    "compute-thesis.html",
    "healthcare.html",
    "qqq-filter.html",
    "lrcx-paid-to-wait.html",
    "mu-memory-cycle.html",
    "tlt-call-spread.html",
    "googl-call-spread.html",
]
SKIP_PAGES = [
    "dc-buildout.html",  # live but out of nav (WIP hold)
    "archive.html",
    "debait.html",
]


def _required_pages():
    pages = list(ALWAYS_PAGES)
    if (SITE / "trades.html").is_file():
        pages.append("trades.html")
    return pages


TRADES_COPY = "Trade alerts by email"
TRADES_DEK = "Every paper trade we open or close"


def _assert_native_kit_card(source: str, name: str) -> None:
    assert 'id="signup"' in source, name
    assert CSS_HREF in source, name
    assert KIT_ACTION in source, name
    assert 'method="post"' in source, name
    assert 'name="email_address"' in source, name
    assert 'data-sv-form="10236979"' in source, name
    assert 'data-uid="7ac38e24ff"' in source, name
    if name == "trades.html":
        # Trades page: trade-alert copy, and every Kit form carries the "trades" tag hook.
        assert TRADES_COPY in source and TRADES_DEK in source, name
        assert source.count('data-kit-tag="trades"') == source.count(KIT_ACTION) == 2, name
    else:
        assert SIGNUP_COPY in source, name
        assert "New pieces and trade updates. Email only, unsubscribe anytime." in source, name
    assert KIT_SCRIPT not in source, name
    assert KIT_EMBED not in source, name


def test_shared_signup_stylesheet_exists():
    css = (SITE / "css" / "signup-card.css").read_text(encoding="utf-8")
    assert "#signup.signup-card" in css
    assert ".signup-submit" in css
    assert ".signup-form" in css


def test_required_pages_have_native_kit_signup():
    for name in _required_pages():
        _assert_native_kit_card((SITE / name).read_text(encoding="utf-8"), name)


def test_home_signup_follows_plumbing_or_scoreboard():
    source = (SITE / "index.html").read_text(encoding="utf-8")
    signup_at = source.find('id="signup"')
    assert signup_at != -1
    if 'id="scoreboard-summary"' in source:
        assert source.find('id="scoreboard-summary"') < signup_at
    elif 'id="latest-piece"' in source:
        assert source.find('id="latest-piece"') < signup_at
    else:
        assert source.find("plumbing-widgets") < signup_at < source.find('<div class="grid">')


def test_research_signup_sits_at_end_of_the_piece():
    for name in ALWAYS_PAGES:
        if name == "index.html":
            continue
        source = (SITE / name).read_text(encoding="utf-8")
        assert source.find("</main>") < source.find('id="signup"') < source.find("<footer>"), name


def test_signup_is_not_on_held_or_archive_pages():
    for name in SKIP_PAGES:
        source = (SITE / name).read_text(encoding="utf-8")
        assert 'id="signup"' not in source, name
        assert KIT_EMBED not in source, name
        assert "app.kit.com/forms/10236979" not in source, name
        assert CSS_HREF not in source, name


def test_no_kit_embed_script_on_any_site_page():
    for page in SITE.glob("*.html"):
        source = page.read_text(encoding="utf-8")
        assert KIT_SCRIPT not in source, page.name
        assert KIT_EMBED not in source, page.name


def test_page_shell_includes_signup_for_new_research_pages():
    shell = (ROOT / "docs" / "research" / "mu" / "page_shell.html").read_text(encoding="utf-8")
    _assert_native_kit_card(shell, "page_shell.html")
    assert shell.find("</main>") < shell.find('id="signup"') < shell.find("<footer>")
