"""GICS sector labels for the Dragonfly universe (Jared 2026-09-28).

api.nasdaq.com's screener `sector` is Nasdaq's own ICB-style label: COST and
WMT come back as Consumer Discretionary, GOOGL/META as Technology, TSLA as
Industrials, PYPL as Industrials, and so on. The one-per-sector cap and the red
team's sector_lagging flag need standard GICS sectors, so every name gets its
GICS sector here:

  1. GICS_BY_TICKER (hand-maintained, reviewed 2026-09-28 against S&P/MSCI GICS
     for every Nasdaq-100 constituent and every pinned name), else
  2. ICB_TO_GICS renames Nasdaq's label to the GICS name where the two differ
     only in wording (Technology -> Information Technology, ...), else
  3. the screener label unchanged.

Each row records sector_source (gics_map | icb_label | screener) and the raw
screener_sector, so a surprise is visible. No gate logic lives here.
"""

from __future__ import annotations

from typing import Optional, Tuple

SCHEME = "GICS"

IT = "Information Technology"
CS_ = "Communication Services"
CD = "Consumer Discretionary"
ST = "Consumer Staples"
HC = "Health Care"
IND = "Industrials"
FIN = "Financials"
EN = "Energy"
UT = "Utilities"
MAT = "Materials"
RE = "Real Estate"

GICS_SECTORS = (EN, MAT, IND, CD, ST, HC, FIN, IT, CS_, UT, RE)

# Judgment calls (conflicting public classifications) are marked "# judgment".
GICS_BY_TICKER = {
    "AAPL": IT, "ABNB": CD, "ADBE": IT, "ADI": IT, "ADP": IND, "ADSK": IT, "AEP": UT, "ALAB": IT,
    "ALNY": HC, "AMAT": IT, "AMD": IT, "AMGN": HC, "AMZN": CD, "APP": IT, "ARM": IT, "ASML": IT,
    "AVGO": IT, "AXON": IND, "BKNG": CD, "BKR": EN, "CCEP": ST, "CDNS": IT, "CEG": UT, "CMCSA": CS_,
    "COST": ST, "CPRT": IND, "CRWD": IT, "CRWV": IT, "CSCO": IT, "CSX": IND, "CTAS": IND, "DASH": CD,
    "DDOG": IT, "DXCM": HC, "EXC": UT, "FANG": EN, "FAST": IND, "FER": IND, "FTNT": IT, "GEHC": HC,
    "GILD": HC, "GOOG": CS_, "GOOGL": CS_, "HON": IND, "HONA": IND, "IDXX": HC, "INTC": IT, "INTU": IT,
    "ISRG": HC, "KDP": ST, "KLAC": IT, "LIN": MAT, "LITE": IT, "LRCX": IT, "MAR": CD, "MCHP": IT,
    "MDLZ": ST, "MELI": CD, "META": CS_, "MNST": ST, "MPWR": IT, "MRVL": IT, "MSFT": IT, "MSTR": IT,
    "MU": IT, "NFLX": CS_, "NVDA": IT, "NXPI": IT, "ODFL": IND, "ORLY": CD, "PANW": IT, "PAYX": IND,
    "PCAR": IND, "PDD": CD, "PEP": ST, "PLTR": IT, "PYPL": FIN, "QCOM": IT, "REGN": HC, "RKLB": IND,
    "ROP": IT,  # judgment: GICS 45103010 Application Software after the 2025 divestitures
    "ROST": CD, "SBUX": CD, "SHOP": IT, "SNDK": IT, "SNPS": IT,
    "SPCX": CS_,  # judgment: MSCI Alternative Carriers (Starlink ~61% of revenue); some vendors say Industrials
    "STX": IT, "TER": IT, "TMUS": CS_,
    "TRI": IND,  # judgment: Research & Consulting Services
    "TSLA": CD, "TTWO": CS_, "TXN": IT, "VRTX": HC, "WBD": CS_, "WDAY": IT, "WDC": IT, "WMT": ST, "XEL": UT,
    # pinned names outside the Nasdaq-100
    "ORCL": IT,
    "NBIS": CS_,  # judgment: legacy GICS Interactive Media (ex-Yandex); some vendors say IT
    "IREN": IT,  # judgment: bitcoin miner / AI cloud, classed with IT peers
    "ASTS": CS_,  # Diversified Telecommunication Services
    "TWST": HC, "TEM": HC, "NTLA": HC,
}

ICB_TO_GICS = {
    "Technology": IT,
    "Telecommunications": CS_,
    "Basic Materials": MAT,
    "Finance": FIN,
    "Financial Services": FIN,
    "Consumer Services": CD,
}


def gics_sector(ticker: Optional[str], screener_sector: Optional[str]) -> Tuple[Optional[str], str]:
    """(GICS sector, source) for one name. A blank screener sector with no map
    entry stays None (the universe excludes it as sector_missing, fail closed)."""
    if ticker and ticker in GICS_BY_TICKER:
        return GICS_BY_TICKER[ticker], "gics_map"
    label = (screener_sector or "").strip() or None
    if label in ICB_TO_GICS:
        return ICB_TO_GICS[label], "icb_label"
    return label, "screener"
