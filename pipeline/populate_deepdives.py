#!/usr/bin/env python3
"""
Populate Deep Dive content for existing insights.
This adds detailed analysis based on the transcript content.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

# Database path
DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def create_deep_dive_content():
    """Create detailed Deep Dive content for each insight."""
    
    # Deep Dive content for each insight
    deepdives = [
        {
            "insight_title": "SpaceX/xAI $1.25T Super-Entity",
            "overview": "Elon Musk is consolidating Starlink's satellite network with xAI's Grok infrastructure, creating the first vertically integrated AI-to-orbit stack. This represents a fundamental shift in how AI compute is deployed and distributed.",
            "key_takeaways": [
                "First vertically integrated AI-to-orbit stack creates moats around infrastructure",
                "Starlink's satellite network provides distributed compute access globally",
                "xAI Grok infrastructure leverages orbital positioning for competitive advantage",
                "Combining launch capabilities with AI compute is unprecedented in the market"
            ],
            "investment_thesis": "The thesis centers on vertical integration creating durable competitive moats. Companies that control both the infrastructure layer (Starlink's orbital network) and the application layer (xAI's models) can extract more value than those operating at a single layer. This is particularly powerful in AI where compute access is the primary constraint.",
            "ticker_analysis": {
                "GOOGL": {
                    "rationale": "Defensive moat - Google's infrastructure becomes more valuable as competition intensifies",
                    "positioning": "Long-term hold, beneficiary of increased compute demand",
                    "risk": "Market share pressure from vertically integrated competitors"
                },
                "NVDA": {
                    "rationale": "Compute demand acceleration - more AI infrastructure requires more GPUs",
                    "positioning": "Core holding, demand driver intact",
                    "risk": "Cyclicality in data center spend, but structural growth intact"
                },
                "AVGO": {
                    "rationale": "Custom silicon opportunity - vertically integrated players need custom chips",
                    "positioning": "Beneficiary of custom silicon trend in AI infrastructure",
                    "risk": "Customer concentration, but diversified across hyperscalers"
                }
            },
            "positioning_guidance": "Focus on infrastructure plays that benefit from increased compute deployment. GOOGL as defensive moat, NVDA for compute demand, AVGO for custom silicon. Timeframe: 12-24 months for thesis to play out. Consider partial positions and add on weakness.",
            "risk_factors": [
                "Regulatory scrutiny on vertical integration (antitrust concerns)",
                "Technical execution risk in combining orbital and AI infrastructure",
                "Competitive response from other AI labs and infrastructure providers",
                "Capital intensity could strain cash flows in near term"
            ],
            "catalysts": [
                "Q2 2026: Expected update on Starlink-xAI integration progress",
                "H2 2026: Potential IPO of combined entity per management comments",
                "Ongoing: Monthly Starlink launch cadence and capacity additions"
            ]
        },
        {
            "insight_title": "Gold Climax Top Signal",
            "overview": "Milton Berg's institutional model has flipped net-short across major indices while retail remains 100% long. This divergence has historically preceded significant drawdowns (8% on average).",
            "key_takeaways": [
                "Institutional positioning vs retail positioning at extreme divergence",
                "Historical pattern suggests 8% average drawdown when this signal triggers",
                "Gold price action often marks sentiment extremes in risk assets",
                "Risk-off positioning warranted until VIX normalization"
            ],
            "investment_thesis": "The thesis is based on positioning divergence as a contrarian indicator. When institutions are net-short and retail is fully long, the marginal buyer is exhausted. Gold's parabolic move often coincides with this positioning extreme, serving as a canary in the coal mine for broader risk assets.",
            "ticker_analysis": {
                "VIX": {
                    "rationale": "Volatility expansion signal - watch for break above 25",
                    "positioning": "Consider VIX calls or long volatility strategies",
                    "risk": "Timing difficult, contango in VIX futures"
                },
                "SQQQ": {
                    "rationale": "Nasdaq inverse ETF for tactical downside protection",
                    "positioning": "Small position as portfolio hedge, scale in if VIX breaks 25",
                    "risk": "Decay over time, only for tactical use"
                },
                "TLT": {
                    "rationale": "Flight to quality, duration performs in risk-off",
                    "positioning": "Increase allocation to long-duration Treasuries",
                    "risk": "Inflation resurgence could pressure bonds"
                }
            },
            "positioning_guidance": "Reduce high-beta momentum exposure. Consider defensive positioning with increased cash/bond allocation. VIX >25 is the key trigger for more aggressive hedging. Timeframe: 1-3 months for potential drawdown. Not a long-term structural bear call, but tactical risk-off.",
            "risk_factors": [
                "Signal could be early - markets can remain irrational longer than expected",
                "Fed intervention could delay or prevent drawdown",
                "Retail capitulation could drive further melt-up before correction",
                "Gold could decouple from traditional risk-off correlations"
            ],
            "contrarian_signals": [
                "Institutional net-short while retail 100% long - classic contrarian setup",
                "Gold enthusiasm reaching retail mainstream media coverage",
                "Complacency in VIX pricing despite positioning extremes"
            ],
            "catalysts": [
                "Monthly: CFTC positioning reports to track institutional flows",
                "Weekly: VIX close above 25 confirms signal",
                "Earnings season: Guidance cuts could trigger repricing"
            ]
        },
        {
            "insight_title": "Bitcoin as Hard Asset",
            "overview": "New liquidity regime narrative gaining traction. BTC is decoupling from tech-correlation as the treasury reserve thesis resurfaces. Positioning shifts happening around DXY weakness and yen carry unwind scenarios.",
            "key_takeaways": [
                "Bitcoin correlation to tech stocks breaking down",
                "Treasury reserve thesis gaining institutional traction again",
                "DXY weakness creating tailwinds for BTC as non-correlated hard asset",
                "Yen carry unwind scenarios favor BTC as alternative store of value"
            ],
            "investment_thesis": "Bitcoin is transitioning from a risk-on tech asset to a macro hard asset. The treasury reserve thesis (companies/nations holding BTC on balance sheet) is resurfaces as fiat currency concerns mount. DXY weakness and potential yen carry unwind create favorable macro backdrop for BTC as non-correlated store of value.",
            "ticker_analysis": {
                "BTC": {
                    "rationale": "Direct exposure to digital hard asset thesis",
                    "positioning": "Core long-term position, accumulate on weakness",
                    "risk": "Regulatory, volatility, correlation regime could reverse"
                },
                "COIN": {
                    "rationale": "Infrastructure play for treasury reserve thesis",
                    "positioning": "Beneficiary of institutional custody demand",
                    "risk": "Fee compression, regulatory overhang"
                },
                "MSTR": {
                    "rationale": "Bitcoin treasury company with leverage to BTC price",
                    "positioning": "High-beta BTC exposure, but risky",
                    "risk": "Highly leveraged, premium/discount to NAV volatility"
                }
            },
            "positioning_guidance": "BTC as core allocation for treasury reserve thesis. COIN for infrastructure/custody exposure. MSTR only for high-risk tolerance. Watch DXY and yen for macro timing. Timeframe: 6-18 months for decoupling thesis to play out.",
            "risk_factors": [
                "Correlation to tech could reassert during broad risk-off",
                "Regulatory crackdown on treasury reserve thesis (accounting changes)",
                "DXY strength would reverse macro tailwinds",
                "Yen stabilization could reduce carry unwind pressure"
            ],
            "catalysts": [
                "Monthly: Treasury reserve adoption announcements",
                "Quarterly: DXY trend changes",
                "Ongoing: Yen/JPY policy shifts from BOJ"
            ]
        },
        {
            "insight_title": "Healthcare AI Moats",
            "overview": "Tennr and Camber are building operational infrastructure (referral automation, claims processing) rather than clinical AI. This represents first-mover advantage in regulatory capture of healthcare operations.",
            "key_takeaways": [
                "Operational AI (not clinical) has clearer regulatory path",
                "Referral automation and claims processing are high-ROI entry points",
                "First-movers can establish regulatory moats before competition",
                "Healthtech ops IPO pipeline building for 2026-2027"
            ],
            "investment_thesis": "Healthcare AI is bifurcating into clinical (high regulatory risk) and operational (clearer path to value). Companies building operational infrastructure (RPA for referrals, claims processing automation) can establish durable moats because once integrated into hospital workflows, switching costs are high.",
            "ticker_analysis": {
                "VEEV": {
                    "rationale": "Healthcare CRM incumbent, expanding into operations",
                    "positioning": "Defensive moat in healthcare data infrastructure",
                    "risk": "Valuation premium, growth deceleration"
                },
                "TDOC": {
                    "rationale": "Virtual care platform with operational scale",
                    "positioning": "Recovery play, operational leverage improving",
                    "risk": "Competition, post-pandemic demand normalization"
                },
                "DOCS": {
                    "rationale": "Professional network for physicians, data advantage",
                    "positioning": "Data moat for healthcare AI training",
                    "risk": "Platform dependency, regulatory changes"
                }
            },
            "positioning_guidance": "Watch for IPO pipeline in healthtech operations (Tennr, Camber, etc.). Public plays are indirect via VEEV, TDOC, DOCS. Focus on companies with existing operational scale. Timeframe: 12-36 months for IPO wave and operational AI adoption.",
            "risk_factors": [
                "Regulatory changes to healthcare reimbursement could impact demand",
                "Hospital budget constraints delaying operational AI adoption",
                "Big tech (AMZN, GOOGL) entering healthcare operations",
                "Clinical AI breakthrough could redirect investment focus"
            ],
            "catalysts": [
                "2026-2027: Expected IPO pipeline for healthtech operations",
                "Quarterly: Hospital IT spending surveys",
                "Ongoing: Regulatory clarity on operational AI vs clinical AI"
            ]
        },
        {
            "insight_title": "Machine-Native Money",
            "overview": "USDC co-founder Sean Neville discusses deterministic crypto meeting probabilistic AI. Identity systems for autonomous agents require new financial rails that traditional banking cannot provide.",
            "key_takeaways": [
                "AI agents require deterministic, programmable payment rails",
                "Traditional banking is too slow and manual for machine commerce",
                "Stablecoin infrastructure provides the settlement layer for AI economy",
                "Identity and verification for autonomous agents is the gating factor"
            ],
            "investment_thesis": "As AI agents proliferate, they will need financial infrastructure that can operate at machine speed. Traditional payment rails (ACH, wires) are too slow and require human intervention. Stablecoins provide instant, programmable settlement that AI agents can autonomously manage. This creates a long-term demand driver for stablecoin infrastructure.",
            "ticker_analysis": {
                "COIN": {
                    "rationale": "USDC issuer, primary beneficiary of stablecoin growth",
                    "positioning": "Core holding for AI-commerce thesis",
                    "risk": "Regulatory pressure on stablecoins, competition"
                },
                "PYPL": {
                    "rationale": "Payment infrastructure integrating crypto rails",
                    "positioning": "Legacy player adapting to new rails",
                    "risk": "Disruption by crypto-native competitors"
                },
                "SQ": {
                    "rationale": "Cash App crypto integration, merchant acceptance",
                    "positioning": "Consumer and merchant on-ramp for stablecoins",
                    "risk": "Consumer spending slowdown, bitcoin volatility"
                }
            },
            "positioning_guidance": "Long-term theme - machine-native money infrastructure. COIN as pure-play stablecoin exposure. PYPL and SQ as legacy adapters. Early stage - expect 3-5 year horizon for AI agent commerce to become material. DCA approach recommended.",
            "risk_factors": [
                "Regulatory crackdown on stablecoins (SEC/Congress)",
                "AI agent adoption slower than expected",
                "CBDCs could compete with private stablecoins",
                "Technical challenges in autonomous agent identity/verification"
            ],
            "catalysts": [
                "2026-2028: AI agent adoption inflection expected",
                "Ongoing: Stablecoin regulatory clarity",
                "Quarterly: Coinbase/USDC growth metrics"
            ]
        }
    ]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if deep_dive_content table exists
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='deep_dive_content'
    """)
    if not cursor.fetchone():
        print("Creating deep_dive_content table...")
        cursor.execute("""
            CREATE TABLE deep_dive_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                insight_id INTEGER NOT NULL,
                podcast_episode_id INTEGER,
                overview TEXT,
                key_takeaways_detailed TEXT,
                investment_thesis TEXT,
                ticker_analysis TEXT,
                positioning_guidance TEXT,
                risk_factors TEXT,
                contrarian_signals TEXT,
                catalysts TEXT,
                related_insights TEXT,
                audio_timestamp_start TEXT,
                audio_timestamp_end TEXT,
                transcript_excerpt TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (insight_id) REFERENCES latest_insights(id) ON DELETE CASCADE,
                FOREIGN KEY (podcast_episode_id) REFERENCES podcast_episodes(id)
            )
        """)
    
    # Clear existing deep dive content
    cursor.execute("DELETE FROM deep_dive_content")
    
    # Insert deep dive content
    for dd in deepdives:
        # Find the insight_id
        cursor.execute(
            "SELECT id FROM latest_insights WHERE title = ?",
            (dd["insight_title"],)
        )
        row = cursor.fetchone()
        if not row:
            print(f"⚠ Insight not found: {dd['insight_title']}")
            continue
        
        insight_id = row[0]
        
        cursor.execute("""
            INSERT INTO deep_dive_content (
                insight_id,
                overview,
                key_takeaways_detailed,
                investment_thesis,
                ticker_analysis,
                positioning_guidance,
                risk_factors,
                contrarian_signals,
                catalysts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            insight_id,
            dd.get("overview"),
            json.dumps(dd.get("key_takeaways", [])),
            dd.get("investment_thesis"),
            json.dumps(dd.get("ticker_analysis", {})),
            dd.get("positioning_guidance"),
            json.dumps(dd.get("risk_factors", [])),
            json.dumps(dd.get("contrarian_signals", [])) if dd.get("contrarian_signals") else None,
            json.dumps(dd.get("catalysts", []))
        ))
        
        print(f"✓ Added Deep Dive content for: {dd['insight_title']}")
    
    conn.commit()
    conn.close()
    print("\n✅ Deep Dive content populated successfully!")

def update_website_export():
    """Update the website export to include Deep Dive content."""
    # This will be handled by modifying db_manager.py
    print("\nNext step: Update db_manager.py to export Deep Dive content")
    print("Then regenerate data.js and redeploy")

if __name__ == "__main__":
    create_deep_dive_content()
    update_website_export()
