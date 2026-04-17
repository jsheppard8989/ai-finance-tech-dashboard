#!/usr/bin/env python3
"""
One-off: Populate suggested_terms (as approved), definitions, and overton_terms
with all current curated definitions as if they were pulled from episodes and promoted.
Run once to backfill the Overton Window and emerging-terms flow.
"""

import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db

# All 7 current definitions (formerly static on the Overton Window)
CURRENT_DEFINITIONS = [
    {
        "term": "Dyson Swarm",
        "definition": "A hypothetical megastructure consisting of a vast array of solar collectors (satellites) orbiting a star to capture its energy output. Unlike a solid Dyson Sphere, a swarm allows for gradual construction and doesn't require implausible engineering.",
        "investment_implications": "As space-based solar power becomes economically viable, companies developing launch capabilities and orbital infrastructure could benefit.",
        "source_context": "Curated definition (pre-promoted)",
    },
    {
        "term": "Jevon's Paradox",
        "definition": "An economic phenomenon where increased efficiency in using a resource leads to increased consumption of that resource rather than decreased consumption.",
        "investment_implications": "As AI makes computation cheaper, total compute demand may explode—benefiting chip makers, data centers, and power providers despite efficiency gains.",
        "source_context": "Curated definition (pre-promoted)",
    },
    {
        "term": "Yen Carry Trade",
        "definition": "A strategy where investors borrow in Japanese yen (low interest rates ~0.25%) and invest in higher-yielding assets (US Treasuries, tech stocks, emerging markets).",
        "investment_implications": "When the Bank of Japan hikes rates or yen strengthens, unwinds trigger forced selling. 2024 unwind caused 12% VIX spike—watch JPY/USD >150.",
        "source_context": "Curated definition (pre-promoted)",
    },
    {
        "term": "Neuralink Moment",
        "definition": "The inflection point when brain-computer interfaces shift from experimental to consumer-ready, triggering societal restructuring around cognitive enhancement.",
        "investment_implications": "BCI hardware, neurotech chips, cognitive enhancement platforms. Early stage - watch for FDA approvals and consumer product launches.",
        "source_context": "Detected in: The Network State Podcast • Feb 2026",
    },
    {
        "term": "Sovereign Individual Thesis",
        "definition": "The expectation that high-net-worth individuals will increasingly decouple from traditional jurisdictions, seeking digital-first citizenship and asset structures.",
        "investment_implications": "Digital banking, crypto custody, tax-advantaged jurisdictions, nomad infrastructure. Services enabling geographic arbitrage.",
        "source_context": "Detected in: Monetary Matters • Feb 2026",
    },
    {
        "term": "Compute Arbitrage",
        "definition": "Exploiting price differentials in AI compute across regions and providers—buying low in unregulated markets, deploying high in enterprise stacks.",
        "investment_implications": "GPU cloud providers, distributed compute networks, energy arbitrage plays. Infrastructure for AI training cost optimization.",
        "source_context": "Detected in: a16z Live • Jan 2026",
    },
    {
        "term": "Regulatory Moat",
        "definition": "Competitive advantage gained not through technology but through compliance complexity—incumbents weaponizing bureaucracy against nimble startups.",
        "investment_implications": "Incumbents with established compliance infrastructure. Banking, healthcare, defense contractors. Barrier to entry becomes the product.",
        "source_context": "Detected in: Jack Mallers Show • Feb 2026",
    },
]


def main():
    db = get_db()
    today = date.today().isoformat()

    with db._get_connection() as conn:
        # Ensure suggested_terms table exists
        schema_path = Path(__file__).parent / "schema_suggested_terms.sql"
        if schema_path.exists():
            conn.executescript(schema_path.read_text())
            conn.commit()

        added_suggested = 0
        added_definitions = 0
        added_overton = 0

        for d in CURRENT_DEFINITIONS:
            term = d["term"]
            definition = d["definition"]
            impl = d.get("investment_implications") or ""
            source_ctx = d.get("source_context") or "Curated definition (pre-promoted)"

            # 1. suggested_terms (as already approved / promoted)
            cursor = conn.execute(
                "SELECT id FROM suggested_terms WHERE term = ?", (term,)
            )
            if cursor.fetchone() is None:
                conn.execute(
                    """
                    INSERT INTO suggested_terms
                    (term, definition, investment_implications, source_type, source_context,
                     mention_count, source_diversity, relevance_score, last_mentioned_date, status,
                     reviewed_at, review_notes)
                    VALUES (?, ?, ?, 'manual_add', ?, 2, 1, 80, date('now'), 'approved',
                            CURRENT_TIMESTAMP, 'Seeded from curated definitions')
                    """,
                    (term, definition, impl, source_ctx),
                )
                added_suggested += 1

            # 2. definitions
            cursor = conn.execute("SELECT id FROM definitions WHERE term = ?", (term,))
            if cursor.fetchone() is None:
                conn.execute(
                    """
                    INSERT INTO definitions
                    (term, definition, investment_implications, added_date, vote_count, display_on_main, display_order)
                    VALUES (?, ?, ?, date('now'), 1, 1, 0)
                    """,
                    (term, definition, impl),
                )
                added_definitions += 1

            # 3. overton_terms (so they show in Overton Window)
            cursor = conn.execute("SELECT id FROM overton_terms WHERE term = ?", (term,))
            if cursor.fetchone() is None:
                conn.execute(
                    """
                    INSERT INTO overton_terms
                    (term, description, first_detected_date, last_mentioned_date, mention_count,
                     status, investment_implications, display_on_main)
                    VALUES (?, ?, date('now'), date('now'), 2, 'active', ?, 1)
                    """,
                    (term, definition, impl),
                )
                added_overton += 1
            else:
                # Ensure display_on_main and status so they show
                conn.execute(
                    """
                    UPDATE overton_terms
                    SET display_on_main = 1, status = 'active',
                        description = COALESCE(?, description),
                        investment_implications = COALESCE(?, investment_implications)
                    WHERE term = ?
                    """,
                    (definition, impl, term),
                )

        conn.commit()

    print("Seed complete:")
    print(f"  suggested_terms (approved): {added_suggested} new")
    print(f"  definitions:                 {added_definitions} new")
    print(f"  overton_terms:               {added_overton} new")
    print("\nRun export_data.py to refresh site data, then reload the site.")


if __name__ == "__main__":
    main()
