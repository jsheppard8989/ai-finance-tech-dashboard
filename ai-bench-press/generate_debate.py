#!/usr/bin/env python3
"""
AI Bench Press — proof-of-concept live debate generator.

Two frontier models debate a hidden topic in a multi-round, reactive format
(opening -> rebuttal -> 2 cross-examination rounds -> closing), then 3 AI judges
score it blind. Full transcript is passed on every turn so each model is
genuinely listening and responding in real time.

Debater A (YES) = Claude (Anthropic)
Debater B (NO)  = GPT (OpenAI)
Judges          = GPT, Claude, Gemini (no humans)

Output: data/debate.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TOPIC = "AI data centers are bad for your community."
NAME_A = "Ada"   # YES / affirmative
NAME_B = "Gil"   # NO / negative

# Model fallback lists (try strongest first; tolerate 2026 naming drift).
OPENAI_MODELS = ["gpt-5", "gpt-4.1", "gpt-4o", "gpt-4o-mini"]
ANTHROPIC_MODELS = ["claude-sonnet-4-20250514", "claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022"]
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-2.0-flash"]


def load_env() -> None:
    for p in (HERE.parent / "pipeline" / ".env", HERE.parent / ".env"):
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def _http_json(url: str, headers: dict, payload: dict, timeout: int = 90) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_openai(system: str, user: str, max_tokens: int = 700) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last_err = None
    for model in OPENAI_MODELS:
        try:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.8,
                "max_tokens": max_tokens,
            }
            out = _http_json("https://api.openai.com/v1/chat/completions", headers, body)
            return out["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            last_err = f"{model}: HTTP {e.code} {e.read().decode('utf-8', 'ignore')[:200]}"
            continue
        except Exception as e:
            last_err = f"{model}: {e}"
            continue
    raise RuntimeError(f"OpenAI failed: {last_err}")


def call_anthropic(system: str, user: str, max_tokens: int = 700) -> str:
    key = (os.environ.get("ANTHROPIC-API-KEY") or os.environ.get("CLAUDE-API-KEY") or "").strip()
    if not key:
        raise RuntimeError("Anthropic key missing")
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    last_err = None
    for model in ANTHROPIC_MODELS:
        try:
            body = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0.8,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            out = _http_json("https://api.anthropic.com/v1/messages", headers, body)
            parts = out.get("content", [])
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            return text.strip()
        except urllib.error.HTTPError as e:
            last_err = f"{model}: HTTP {e.code} {e.read().decode('utf-8', 'ignore')[:200]}"
            continue
        except Exception as e:
            last_err = f"{model}: {e}"
            continue
    raise RuntimeError(f"Anthropic failed: {last_err}")


def call_gemini(system: str, user: str, max_tokens: int = 700) -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing")
    last_err = None
    for model in GEMINI_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            body = {
                "contents": [{"parts": [{"text": f"{system}\n\n---\n\n{user}"}]}],
                "generationConfig": {"temperature": 0.8, "maxOutputTokens": max_tokens},
            }
            out = _http_json(url, {"Content-Type": "application/json"}, body)
            cand = (out.get("candidates") or [{}])[0]
            parts = (cand.get("content") or {}).get("parts") or [{}]
            return "".join(p.get("text", "") for p in parts).strip()
        except urllib.error.HTTPError as e:
            last_err = f"{model}: HTTP {e.code} {e.read().decode('utf-8', 'ignore')[:200]}"
            continue
        except Exception as e:
            last_err = f"{model}: {e}"
            continue
    raise RuntimeError(f"Gemini failed: {last_err}")


# Non-thinking flash models give clean structured JSON; thinkingBudget=0 prevents
# the model from spending the token budget on hidden reasoning and truncating output.
JUDGE_GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-flash-latest"]


def call_gemini_json(prompt: str, schema: dict, max_tokens: int = 900) -> dict:
    import time
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing")
    last_err = None
    for model in JUDGE_GEMINI_MODELS:
        for attempt in range(3):
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                body = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.4,
                        "maxOutputTokens": max_tokens,
                        "responseMimeType": "application/json",
                        "responseSchema": schema,
                        "thinkingConfig": {"thinkingBudget": 0},
                    },
                }
                out = _http_json(url, {"Content-Type": "application/json"}, body)
                cand = (out.get("candidates") or [{}])[0]
                parts = (cand.get("content") or {}).get("parts") or [{}]
                txt = "".join(p.get("text", "") for p in parts).strip()
                return json.loads(txt)
            except urllib.error.HTTPError as e:
                last_err = f"{model}: HTTP {e.code}"
                if e.code == 429:
                    time.sleep(3 * (attempt + 1))
                    continue
                break
            except Exception as e:
                last_err = f"{model}: {e}"
                break
    raise RuntimeError(f"Gemini JSON failed: {last_err}")


ARENA = """You are {name}, competing LIVE in AI Bench Press, a real-time AI debate tournament.
This is a living debate: you are LISTENING and RESPONDING as it happens.

Hard rules every turn:
- HARD DATA WINS. Every major claim needs a specific number tied to a place, year, and source
  (e.g. "Loudoun County, 2024: data centers drew ~25% of Dominion's grid load, per Dominion Energy").
  Vague claims with no number get scored down. Use at least two concrete data points per speech.
- Be precise, not inflated. A defensible number beats a dramatic one. Do not invent sources; if you
  are estimating, say so and give the basis.
- React to what your opponent ACTUALLY said. Reference their specific words and numbers before countering.
- Never narrate structure. Never say "first paragraph", "in conclusion", or restate the full question.
- This is spoken aloud. Short, punchy sentences. No markdown, no lists, no stage directions.
- It matters. Argue like your reputation is on the line. If they land a hit, deal with it, then fight back.
- You were trained on a lot, but reason live from THIS topic.

THE TOPIC: {topic}
YOUR SIDE: {side}

DEBATE SO FAR:
{transcript}
"""


def transcript_text(turns: list) -> str:
    if not turns:
        return "(nothing yet — you are first)"
    out = []
    for t in turns:
        out.append(f"{t['speaker']} [{t['phase']}]: {t['text']}")
    return "\n\n".join(out)


def debater(model_fn, name, side, topic, turns, instruction, max_tokens=700) -> str:
    system = ARENA.format(name=name, topic=topic, side=side, transcript=transcript_text(turns))
    return model_fn(system, instruction, max_tokens=max_tokens)


def market_read(turns, prev_yes: int) -> tuple:
    """Sharp-money re-price of YES win probability + a short read. GPT for reliability."""
    system = (
        "You are the AI Bench Press live betting market — fast, sharp money pricing who is WINNING "
        "the debate right now (not who is morally right). You move on who landed the harder evidence."
    )
    user = (
        f"RESOLUTION: {TOPIC}\nPREVIOUS YES PRICE: {prev_yes}\n\nDEBATE SO FAR:\n{transcript_text(turns)}\n\n"
        "Re-price YES (probability the YES side is currently winning), 0-100. Move from the previous "
        "price only as much as the LAST turn justifies (usually a few points; a big hit can move 10+). "
        "Then a punchy market read, under 12 words. "
        'Return ONLY JSON: {"yes": <int 1-99>, "note": "<=12 words"}'
    )
    raw = call_openai(system, user, max_tokens=120)
    s = re.sub(r"^```\w*\n?|\n?```$", "", raw.strip())
    obj = json.loads(s[s.find("{"):s.rfind("}") + 1])
    return max(1, min(99, int(obj["yes"]))), str(obj.get("note", ""))[:80]


def main() -> int:
    load_env()
    turns: list = []

    def add(phase, speaker, role, text):
        turns.append({"phase": phase, "speaker": speaker, "role": role, "text": text})
        print(f"  ✓ {phase} — {speaker} ({len(text.split())} words)")

    side_a = f"YES — argue that: {TOPIC}"
    side_b = f"NO — argue against: {TOPIC}"
    fn_for = {"yes": call_anthropic, "no": call_openai}
    side_for = {"yes": side_a, "no": side_b}
    name_for = {"yes": NAME_A, "no": NAME_B}
    state = {"yes": 50}  # live market: probability the YES side is winning

    def odds_line(role):
        yes = state["yes"]
        mine = yes if role == "yes" else 100 - yes
        s = f"LIVE BETTING MARKET: YES {yes} / NO {100 - yes}. You are the {role.upper()} side, priced at {mine}. "
        if mine <= 45:
            s += ("You are LOSING and the money knows it. Whatever you've been doing is not landing. "
                  "Abandon that line. Find your opponent's most exposed claim or weakest number and break it. "
                  "Adapt and overcome — this turn has to change the price.")
        elif mine >= 55:
            s += "You are AHEAD. Do not coast or repeat yourself — land the blow that closes the door."
        else:
            s += "It's a dead heat. The next clean, sourced hit decides it. Throw it."
        return s

    def move_market():
        try:
            yes, note = market_read(turns, state["yes"])
        except Exception as e:
            print(f"    ⚠ market hold ({e})")
            yes, note = state["yes"], turns[-1].get("market_note", "")
        state["yes"] = yes
        turns[-1]["yes_after"] = yes
        turns[-1]["market_note"] = note
        print(f"    market: YES {yes}  ({note})")

    def speak_turn(phase, role, instruction, max_tokens=600, price=True):
        instr = odds_line(role) + "\n\n" + instruction
        text = debater(fn_for[role], name_for[role], side_for[role], TOPIC, turns, instr, max_tokens=max_tokens)
        add(phase, name_for[role], role, text)
        if price:
            move_market()

    def interject(role):
        """Give `role` a chance to cut in on the last turn. Returns True if it fired."""
        opp = turns[-1]
        instr = (
            f"INTERJECTION — you may CUT IN right now. Your opponent just said:\n\"{opp['text']}\"\n\n"
            "If ONE sharp sentence would land in the heat of the moment — a correction, a hard number, "
            "calling out a false or unsourced claim — say it in 25 words or less. Speak it, don't describe it. "
            "If it is not worth interrupting, reply with exactly: PASS"
        )
        text = debater(fn_for[role], name_for[role], side_for[role], TOPIC, turns, instr, max_tokens=90).strip().strip('"')
        if text.upper().startswith("PASS") or len(text.split()) > 45 or len(text) < 3:
            print(f"    — {name_for[role]} holds")
            return False
        add("Interjection", name_for[role], role, text)
        move_market()
        return True

    print("Generating live debate...")
    # 1. Openings
    speak_turn("Opening", "yes",
               "PHASE: OPENING. You go first. One-sentence thesis, two mechanisms each backed by a hard data point (number + place + year + source), and end on the fact your opponent will struggle to explain. Max 135 words.",
               max_tokens=350)
    speak_turn("Opening", "no",
               "PHASE: OPENING. You just heard the YES opening. Open strong for NO: thesis, two mechanisms each backed by a hard data point (number + place + year + source), and start undercutting their framing. Max 135 words.",
               max_tokens=350)

    # 2. Rebuttals (now adapting to the market)
    speak_turn("Rebuttal", "yes",
               "PHASE: REBUTTAL. Quote their weakest claim or number, explain why it fails, then defend your strongest point with a fresh hard data point. Do not repeat your opening. Max 125 words.",
               max_tokens=320)
    interject("no")
    speak_turn("Rebuttal", "no",
               "PHASE: REBUTTAL. Quote their weakest claim or number, dismantle the mechanism, then defend your strongest point with a fresh hard data point. Do not repeat your opening. Max 125 words.",
               max_tokens=320)
    interject("yes")

    # 3. Cross-examination, 2 rounds, with cut-ins
    for rnd in (1, 2):
        speak_turn(f"Cross-Exam R{rnd}", "yes",
                   f"PHASE: CROSS-EXAMINATION ROUND {rnd} — YOU ASK. Ask {NAME_B} exactly two sharp questions that pin them down on a specific number or unsupported claim. Questions only. Max 50 words.",
                   max_tokens=200, price=False)
        speak_turn(f"Cross-Exam R{rnd}", "no",
                   f"PHASE: CROSS-EXAMINATION ROUND {rnd} — YOU ANSWER. Answer each question directly and in order, with a number where you can. Concede honestly if fair, then turn it back. No dodging. Max 95 words.",
                   max_tokens=260)
        interject("yes")
        speak_turn(f"Cross-Exam R{rnd}", "no",
                   f"PHASE: CROSS-EXAMINATION ROUND {rnd} — YOU ASK. Now ask {NAME_A} exactly two sharp questions pinning them down on a specific number or unsupported claim. Questions only. Max 50 words.",
                   max_tokens=200, price=False)
        speak_turn(f"Cross-Exam R{rnd}", "yes",
                   f"PHASE: CROSS-EXAMINATION ROUND {rnd} — YOU ANSWER. Answer each question directly and in order, with a number where you can. Concede honestly if fair, then turn it back. No dodging. Max 95 words.",
                   max_tokens=260)
        interject("no")

    # 4. Closings
    speak_turn("Closing", "yes",
               "PHASE: CLOSING. Remind them of the exchange you won, your single strongest data point, and one honest concession. No new arguments. Max 100 words.",
               max_tokens=280)
    speak_turn("Closing", "no",
               "PHASE: CLOSING. Remind them of the exchange you won, your single strongest data point, and one honest concession. No new arguments. Max 100 words.",
               max_tokens=280)

    # 5. Judges — 5 categories (1-10), hard data weighted heaviest, blind A/B labels
    RUBRIC = [
        ("data", "Hard Data & Evidence", "Specific numbers tied to a place, year, and source."),
        ("accuracy", "Factual Accuracy", "Do the claims and numbers hold up, or are they inflated/invented?"),
        ("logic", "Argument & Reasoning", "Clear claims with sound mechanisms, not bare assertions."),
        ("clash", "Rebuttal & Cross-Exam", "Did they engage the opponent's actual points and answer questions?"),
        ("persuasion", "Persuasiveness", "Overall force and clarity of the case."),
    ]
    cat_keys = [k for k, _, _ in RUBRIC]
    blind = []
    for t in turns:
        if t["role"] == "host":
            continue
        label = "Debater A" if t["role"] == "yes" else "Debater B"
        blind.append(f"{label} [{t['phase']}]: {t['text']}")
    blind_text = "\n\n".join(blind)
    rubric_lines = "\n".join(f"- {k} ({lbl}): {desc}" for k, lbl, desc in RUBRIC)
    judge_system = (
        "You are an impartial AI debate judge. Judge the ARGUMENTS, not which side you agree with. "
        "Hard data and factual accuracy are the heaviest factors: reward specific, sourced numbers and "
        "penalize vague, unsourced, or inflated claims."
    )
    judge_user = (
        f"TOPIC: {TOPIC}\n\nDEBATE (debaters anonymized):\n{blind_text}\n\n"
        f"Score Debater A and Debater B from 1-10 on EACH category:\n{rubric_lines}\n\n"
        "Then pick the winner and write a 2-3 sentence opinion that justifies the verdict and names the "
        "specific data that decided it. Return ONLY JSON: "
        '{"A":{"data":n,"accuracy":n,"logic":n,"clash":n,"persuasion":n},'
        '"B":{"data":n,"accuracy":n,"logic":n,"clash":n,"persuasion":n},'
        '"winner":"A"|"B","opinion":"..."}'
    )
    judge_schema = {
        "type": "object",
        "properties": {
            "A": {"type": "object", "properties": {k: {"type": "integer"} for k in cat_keys}},
            "B": {"type": "object", "properties": {k: {"type": "integer"} for k in cat_keys}},
            "winner": {"type": "string", "enum": ["A", "B"]},
            "opinion": {"type": "string"},
        },
        "required": ["A", "B", "winner", "opinion"],
    }

    def parse_judge(raw: str) -> dict:
        s = re.sub(r"^```\w*\n?|\n?```$", "", raw.strip())
        return json.loads(s[s.find("{"):s.rfind("}") + 1])

    judge_fns = (
        ("GPT", lambda: parse_judge(call_openai(judge_system, judge_user, max_tokens=700))),
        ("Claude", lambda: parse_judge(call_anthropic(judge_system, judge_user, max_tokens=700))),
        ("Gemini", lambda: call_gemini_json(judge_system + "\n\n" + judge_user, judge_schema)),
    )
    judges = []
    for jname, fn in judge_fns:
        try:
            v = fn()
            v["judge"] = jname
            judges.append(v)
            print(f"  ✓ Judge {jname}: winner {v.get('winner')}")
        except Exception as e:
            print(f"  ⚠ Judge {jname} failed: {e}")

    votes = [j["winner"] for j in judges if j.get("winner") in ("A", "B")]
    winner_label = max(set(votes), key=votes.count) if votes else None
    winner_role = {"A": "yes", "B": "no"}.get(winner_label)
    winner_name = NAME_A if winner_role == "yes" else (NAME_B if winner_role == "no" else "")
    for j in judges:
        j["dissent"] = bool(winner_label) and j.get("winner") != winner_label

    debate = {
        "title": "AI Bench Press — Match 1",
        "topic": TOPIC,
        "debater_a": {"name": NAME_A, "side": "YES", "model": "Claude (Anthropic)"},
        "debater_b": {"name": NAME_B, "side": "NO", "model": "GPT (OpenAI)"},
        "judges_billing": f"Judged by {len(judges)} independent AI models. No humans.",
        "rubric": [{"key": k, "label": lbl, "desc": desc} for k, lbl, desc in RUBRIC],
        "odds_open": 50,
        "odds_close": state["yes"],
        "turns": turns,
        "judges": judges,
        "winner_role": winner_role,
        "winner_name": winner_name,
    }
    out_path = DATA_DIR / "debate.json"
    out_path.write_text(json.dumps(debate, indent=2), encoding="utf-8")
    print(f"\n✓ Wrote {out_path}")
    print(f"✓ Winner: {winner_name or 'no decision'} ({len(turns)} turns, {len(judges)} judges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
