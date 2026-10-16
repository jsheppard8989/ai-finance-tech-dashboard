"""OpenAI Flex processing for the scheduled podcast pipeline (cost fix 2026-10-16, Jared yes 2:57 PM CT).

create_chat(client, **kwargs) sends the chat.completions request with service_tier="flex" (half price,
Batch rates) and a 15-minute timeout. On a Flex "resource unavailable" 429 or a timeout it backs off and
retries Flex, then retries ONCE on the standard tier with the SAME model (never a different/bigger model).
If the model/endpoint rejects service_tier, it goes straight to standard. Credit/quota/auth errors are
raised unchanged (callers fail fast). OPENAI_FLEX=0 turns Flex off.

price(model, in, out, tier) uses the table below (USD per 1M tokens, standard tier; checked against
developers.openai.com/api/docs/pricing on 2026-10-16). Flex = 50% of standard.
"""
from __future__ import annotations

import os
import time

PRICES = {  # model: (input, output) per 1M tokens, standard tier
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.5": (5.00, 30.00),
}
FLEX_DISCOUNT = 0.5
FLEX_TIMEOUT_S = 900.0
FLEX_BACKOFF_S = (20, 60)

LEDGER: list = []  # (model, input_tokens, output_tokens, tier) for the current run; callers may reset


def flex_enabled() -> bool:
    return os.environ.get("OPENAI_FLEX", "1").strip().lower() not in ("0", "false", "no", "off")


def price(model: str, input_tokens: int, output_tokens: int, tier: str = "default") -> float:
    m = str(model or "")
    base = next((v for k, v in sorted(PRICES.items(), key=lambda kv: -len(kv[0])) if m.startswith(k)), None)
    if base is None:
        return 0.0
    mult = FLEX_DISCOUNT if str(tier or "").lower() == "flex" else 1.0
    return (input_tokens / 1_000_000 * base[0] + output_tokens / 1_000_000 * base[1]) * mult


def is_quota_or_auth_error(e) -> bool:
    t = str(e).lower()
    return any(k in t for k in ("insufficient_quota", "credit_balance", "no credits", "billing",
                                "invalid_api_key", "incorrect api key", "authentication", "unauthorized"))


def is_flex_unavailable(e) -> bool:
    """Flex capacity 429 (not billed) or a request timeout."""
    if is_quota_or_auth_error(e):
        return False
    t = str(e).lower()
    name = type(e).__name__.lower()
    return ("resource unavailable" in t or "resource_unavailable" in t or "resources unavailable" in t
            or "timeout" in name or "timed out" in t or "408" in t)


def is_tier_unsupported(e) -> bool:
    t = str(e).lower()
    return "service_tier" in t or ("flex" in t and ("not supported" in t or "unsupported" in t or "invalid" in t))


def _tier_of(resp, requested: str) -> str:
    t = getattr(resp, "service_tier", None)
    return str(t) if t else requested


def create_chat(client, *, sleep=time.sleep, **kwargs):
    """Returns (response, tier_used). Records usage in LEDGER."""
    def _record(resp, tier):
        u = getattr(resp, "usage", None)
        LEDGER.append((kwargs.get("model"), getattr(u, "prompt_tokens", 0) or 0,
                       getattr(u, "completion_tokens", 0) or 0, tier))
        return resp, tier

    if flex_enabled():
        api = client.with_options(timeout=FLEX_TIMEOUT_S) if hasattr(client, "with_options") else client
        for i in range(len(FLEX_BACKOFF_S) + 1):
            try:
                resp = api.chat.completions.create(service_tier="flex", **kwargs)
                return _record(resp, _tier_of(resp, "flex"))
            except Exception as e:  # noqa: BLE001
                if is_tier_unsupported(e):
                    print(f"    ⓘ Flex not accepted for {kwargs.get('model')}; using standard tier", flush=True)
                    break
                if not is_flex_unavailable(e):
                    raise
                if i < len(FLEX_BACKOFF_S):
                    print(f"    ⓘ Flex unavailable ({type(e).__name__}); retrying in {FLEX_BACKOFF_S[i]}s", flush=True)
                    sleep(FLEX_BACKOFF_S[i])
                else:
                    print(f"    ⓘ Flex still unavailable; one standard-tier call on {kwargs.get('model')}", flush=True)
    resp = client.chat.completions.create(**kwargs)
    return _record(resp, _tier_of(resp, "default"))


def ledger_cost(start: int = 0) -> float:
    return sum(price(m, i, o, t) for m, i, o, t in LEDGER[start:])
