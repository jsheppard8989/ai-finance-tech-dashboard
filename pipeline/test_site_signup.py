"""Regression checks for the home-page newsletter signup."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "site" / "index.html"
SITE = ROOT / "site"

KIT_ACTION = "https://app.kit.com/forms/10236979/subscriptions"
KIT_EMBED = "scarcity-abundance.kit.com"
KIT_SCRIPT = (
    '<script async data-uid="7ac38e24ff" '
    'src="https://scarcity-abundance.kit.com/7ac38e24ff/index.js"></script>'
)


def test_home_page_contains_kit_signup():
    source = HOME.read_text(encoding="utf-8")

    assert 'id="signup"' in source
    assert KIT_ACTION in source
    assert 'method="post"' in source
    assert 'name="email_address"' in source
    assert 'data-sv-form="10236979"' in source
    assert 'data-uid="7ac38e24ff"' in source
    assert "Get new research by email" in source
    assert "New pieces and trade updates. Email only, unsubscribe anytime." in source
    # Native form styled to the site, not the dropped-in Kit embed.
    assert KIT_SCRIPT not in source
    assert KIT_EMBED not in source


def test_kit_signup_follows_scoreboard_on_home():
    source = HOME.read_text(encoding="utf-8")
    assert source.find('id="latest-piece"') < source.find('id="scoreboard-summary"')
    assert source.find('id="scoreboard-summary"') < source.find('id="signup"')


def test_kit_signup_is_only_on_the_home_page():
    """Kit form stays on index.html; do not add it to other pages."""
    for page in SITE.glob("*.html"):
        if page.name == "index.html":
            continue
        source = page.read_text(encoding="utf-8")
        assert KIT_EMBED not in source, page.name
        assert "app.kit.com/forms/10236979" not in source, page.name
        assert 'id="signup"' not in source, page.name
        assert KIT_SCRIPT not in source, page.name
