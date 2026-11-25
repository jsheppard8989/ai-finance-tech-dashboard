"""The old Get in touch / Formspree contact card must stay off the site."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def test_get_in_touch_card_is_gone_from_every_page():
    for page in sorted(SITE.glob("*.html")):
        source = page.read_text(encoding="utf-8")
        assert "Get in touch" not in source, page.name
        assert "contactForm" not in source, page.name
        assert "contact-card" not in source, page.name
        assert "formspree.io" not in source, page.name
        assert "CONTACT_API_URL" not in source, page.name


def test_legacy_contact_backend_files_are_gone():
    for name in ("contacts.py", "contact_api.py", "check_contact_api.py"):
        assert not (ROOT / name).exists(), name
