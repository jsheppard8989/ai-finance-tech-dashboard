#!/usr/bin/env python3
"""
Extraction Stop-list for Emerging Terms

Prevents generic, Wikipedia-level, or overly broad phrases from cluttering
the Emerging Terms inbox. These terms are filtered out during extraction,
not just during promotion.

Categories:
1. Generic AI/tech buzzwords that appear everywhere
2. Wikipedia-level concepts that aren't specific enough
3. Common phrases that get false-positive extracted
4. Overly broad market/economic terms
"""

from typing import Set
import re


# Terms that should never appear in Emerging Terms inbox.
# These are too generic or Wikipedia-level to represent "new ideas."
EXTRACTION_STOPLIST: Set[str] = {
    # Generic AI concepts (Wikipedia-level)
    "AI takeover",
    "AI Takeover",
    "Compute shortages",
    "Compute Shortages",
    "Computing power",
    "Computing Power",
    "Data centers",
    "Data Centers",
    "Cloud computing",
    "Cloud Computing",
    "Big data",
    "Big Data",
    "Internet of Things",
    "IoT",
    "Blockchain",
    "Cryptocurrency",
    "Digital transformation",
    "Digital Transformation",
    "Automation",
    "Digitization",
    "Digitalization",
    "Technology stack",
    "Tech stack",
    
    # Overly broad economic/market terms
    "Economic growth",
    "Economic Growth",
    "Market volatility",
    "Market Volatility",
    "Interest rates",
    "Interest Rates",
    "Inflation",
    "Recession",
    "Bull market",
    "Bull Market",
    "Bear market",
    "Bear Market",
    "Stock market",
    "Stock Market",
    "Market cap",
    "Market Cap",
    "Market capitalization",
    "Venture capital",
    "Venture Capital",
    "Private equity",
    "Private Equity",
    "IPO",
    "Initial Public Offering",
    "Earnings report",
    "Earnings Report",
    "Quarterly earnings",
    "Revenue growth",
    "Profit margin",
    "Cash flow",
    "Balance sheet",
    
    # Generic business terms
    "Business model",
    "Business Model",
    "Go to market",
    "Go-to-market",
    "Product market fit",
    "Product-market fit",
    "Scalability",
    "Disruption",
    "Innovation",
    "Startup",
    "Unicorn",
    "Decacorn",
    "Growth hacking",
    "Customer acquisition",
    "User engagement",
    "Retention rate",
    "Churn rate",
    "Unit economics",
    
    # Generic tech terms
    "Software",
    "Hardware",
    "Platform",
    "Ecosystem",
    "Infrastructure",
    "API",
    "APIs",
    "SDK",
    "Framework",
    "Architecture",
    "Algorithm",
    "Algorithms",
    "Data science",
    "Data Science",
    "Analytics",
    "Metrics",
    "KPIs",
    "Dashboard",
    
    # Common false-positive phrases
    "The Future",
    "The future",
    "Next generation",
    "Next Generation",
    "Next-gen",
    "State of the art",
    "State-of-the-art",
    "Cutting edge",
    "Cutting-edge",
    "Best practices",
    "Best Practices",
    "Industry standard",
    "Industry Standard",
    "Game changer",
    "Game-changer",
    "Paradigm shift",
    "Paradigm Shift",
    "Low hanging fruit",
    "Low-hanging fruit",
    "Moving the needle",
    "Value proposition",
    "Value Proposition",
    "Competitive advantage",
    "Competitive Advantage",
    "First mover",
    "First-mover advantage",
    
    # Generic research/academia terms
    "Research paper",
    "Research Paper",
    "White paper",
    "Peer review",
    "Peer-reviewed",
    "Published research",
    "Academic research",
    "Scientific method",
    
    # Overly broad AI safety terms (unless specific)
    "AI safety",
    "AI Safety",
    "AI alignment",
    "AI Alignment",
    "AI ethics",
    "AI Ethics",
    "Responsible AI",
    "Ethical AI",
    "AI governance",
    "AI Governance",
    "AI regulation",
    "AI Regulation",
}

# Lowercase set for quick lookups
_STOPLIST_LOWER: Set[str] = {t.lower() for t in EXTRACTION_STOPLIST}

# Patterns that should be filtered (regex)
_STOPLIST_PATTERNS = [
    r"^the\s+",  # Terms starting with "The "
    r"\s+report$",  # Terms ending with " report"
    r"\s+update$",  # Terms ending with " update"
    r"\s+news$",  # Terms ending with " news"
    r"^\d+",  # Terms starting with numbers
    r"^q[1-4]\s",  # Quarterly references (Q1, Q2, etc.)
]
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _STOPLIST_PATTERNS]


def is_stoplist_term(term: str) -> bool:
    """
    Check if a term should be filtered from Emerging Terms inbox.
    
    Returns True if the term is:
    - In the explicit stoplist
    - Matches a stoplist pattern
    - Too short or too generic
    """
    if not term:
        return True
    
    term_clean = term.strip()
    
    # Too short to be meaningful
    if len(term_clean) < 4:
        return True
    
    # Explicit stoplist (case-insensitive)
    if term_clean.lower() in _STOPLIST_LOWER:
        return True
    
    # Check patterns
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(term_clean):
            return True
    
    # Single common words (not compound terms)
    single_word_stops = {
        "technology", "software", "hardware", "data", "cloud",
        "market", "growth", "revenue", "profit", "loss",
        "increase", "decrease", "rise", "fall", "change",
        "new", "old", "big", "small", "fast", "slow",
        "good", "bad", "better", "worse", "best", "worst",
    }
    if term_clean.lower() in single_word_stops:
        return True
    
    return False


def filter_emerging_terms(terms: list) -> list:
    """
    Filter a list of term dictionaries, removing stoplist items.
    
    Args:
        terms: List of dicts with 'term' key
        
    Returns:
        Filtered list with stoplist terms removed
    """
    return [t for t in terms if not is_stoplist_term(t.get("term", ""))]


def get_stoplist_for_export() -> list:
    """Return the stoplist for documentation/transparency."""
    return sorted(EXTRACTION_STOPLIST)
