import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple

import pandas as pd

try:
    import kagglehub  # type: ignore
except ImportError:
    kagglehub = None  # lazy optional dependency


DATA_PATH = Path(__file__).resolve().parent / "data" / "nfl_scores_betting.csv"


@dataclass
class Game:
    season: int
    week: int
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    favorite_team: str
    spread: float  # points the favorite is laying

    @property
    def underdog_team(self) -> str:
        return self.away_team if self.favorite_team == self.home_team else self.home_team

    @property
    def underdog_spread(self) -> float:
        """Spread from the underdog's point of view (positive number = getting points)."""
        return abs(self.spread)

    def underdog_covers(self) -> bool:
        """Return True if the underdog covers the spread ATS."""
        # Favorite minus points must not beat underdog by more than spread.
        fav_score = self.home_score if self.favorite_team == self.home_team else self.away_score
        dog_score = self.away_score if self.favorite_team == self.home_team else self.home_score
        margin = fav_score - dog_score
        return margin <= self.spread


def approx_underdog_moneyline(spread_points: float) -> int:
    """
    Conservative mapping from underdog spread (positive points) to moneyline (American odds).
    We bucket spreads into ranges and return a bettor-unfriendly but realistic price.
    """
    s = abs(spread_points)
    # Small dogs
    if s <= 1.0:
        return 105
    if s <= 2.5:
        return 120
    if s <= 3.0:
        return 130
    if s <= 3.5:
        return 140
    if s <= 4.5:
        return 155
    if s <= 6.0:
        return 190
    if s <= 7.0:
        return 230
    if s <= 9.5:
        return 280
    if s <= 10.5:
        return 320
    if s <= 13.5:
        return 425
    # Very big dogs
    return 475


def american_to_decimal(ml: int) -> float:
    """Convert American moneyline odds to decimal odds."""
    if ml > 0:
        return 1.0 + ml / 100.0
    else:
        return 1.0 + 100.0 / abs(ml)


def _ensure_data_file(csv_path: Path = DATA_PATH) -> Path:
    """
    Ensure the local CSV exists. If missing and kagglehub is available + configured,
    download the Toby Crabtree NFL scores & betting dataset automatically and point
    to its main CSV file.
    """
    if csv_path.exists():
        return csv_path

    data_dir = csv_path.parent
    data_dir.mkdir(parents=True, exist_ok=True)

    if kagglehub is None:
        raise FileNotFoundError(
            f"Data file not found at {csv_path} and kagglehub is not installed.\n"
            f"Install dependencies and either:\n"
            f"  - Place a Kaggle-style NFL scores CSV at that path, or\n"
            f"  - Install kagglehub and configure Kaggle API credentials."
        )

    print("Data file missing; attempting Kaggle download via kagglehub...")
    try:
        ds_path = kagglehub.dataset_download("tobycrabtree/nfl-scores-and-betting-data")
    except Exception as e:
        raise FileNotFoundError(
            "Failed to download dataset via kagglehub. "
            "Check your Kaggle API credentials (kaggle.json or env vars)."
        ) from e

    ds_path = Path(ds_path)
    # Common main file name in this dataset.
    candidate = ds_path / "spreadspoke_scores.csv"
    if not candidate.exists():
        # Fallback: pick the first CSV in the dataset directory.
        csv_files = list(ds_path.glob("*.csv"))
        if not csv_files:
            raise FileNotFoundError(
                f"No CSV files found in downloaded dataset directory: {ds_path}"
            )
        candidate = csv_files[0]

    # Copy or symlink into our data directory for stability.
    target = csv_path
    if not target.exists():
        try:
            # Use a hard copy so future runs don't depend on cache layout.
            import shutil

            shutil.copy2(candidate, target)
            print(f"Copied dataset file to {target}")
        except Exception as e:
            raise FileNotFoundError(
                f"Downloaded dataset but failed to place CSV at {target}"
            ) from e

    return target


def load_games(csv_path: Path = DATA_PATH) -> List[Game]:
    csv_path = _ensure_data_file(csv_path)
    df = pd.read_csv(csv_path)

    # TODO: Adjust these column names to your actual CSV.
    # These are common for Kaggle-style datasets.
    season_col = "schedule_season"
    week_col = "schedule_week"
    home_col = "team_home"
    away_col = "team_away"
    home_score_col = "score_home"
    away_score_col = "score_away"
    fav_team_col = "team_favorite_id"
    spread_col = "spread_favorite"

    games: List[Game] = []
    for _, row in df.iterrows():
        try:
            season = int(row[season_col])
            week_raw = row[week_col]
            # Some datasets use 'Wildcard', 'Superbowl', etc. Skip non-regular-season for now.
            if isinstance(week_raw, str) and not week_raw.isdigit():
                continue
            week = int(week_raw)

            home_team = str(row[home_col])
            away_team = str(row[away_col])
            home_score = int(row[home_score_col])
            away_score = int(row[away_score_col])
            favorite_team = str(row[fav_team_col])
            spread = float(row[spread_col])

            games.append(
                Game(
                    season=season,
                    week=week,
                    home_team=home_team,
                    away_team=away_team,
                    home_score=home_score,
                    away_score=away_score,
                    favorite_team=favorite_team,
                    spread=spread,
                )
            )
        except Exception:
            # Skip malformed rows; we can log these later if needed.
            continue

    return games


def group_games_by_week(games: List[Game]) -> Dict[Tuple[int, int], List[Game]]:
    grouped: Dict[Tuple[int, int], List[Game]] = {}
    for g in games:
        key = (g.season, g.week)
        grouped.setdefault(key, []).append(g)
    return grouped


def simulate_week(games: List[Game], stake_per_parlay: float = 100.0) -> Dict[str, float]:
    if len(games) < 6:
        return {"parlays": 0.0, "winners": 0.0, "staked": 0.0, "profit": 0.0}

    # Rank by biggest underdog spread (largest positive points).
    sorted_games = sorted(games, key=lambda g: g.underdog_spread, reverse=True)
    top_six = sorted_games[:6]

    # All 3-leg combinations of these 6 underdogs.
    combos = list(itertools.combinations(top_six, 3))

    winners = 0
    profit = 0.0
    for combo in combos:
        if all(g.underdog_covers() for g in combo):
            winners += 1
            # Moneyline payout for 3-leg parlay of underdogs.
            dec_odds = 1.0
            for g in combo:
                ml = approx_underdog_moneyline(g.underdog_spread)
                dec_odds *= american_to_decimal(ml)
            profit += stake_per_parlay * (dec_odds - 1.0)
        else:
            profit -= stake_per_parlay

    return {
        "parlays": float(len(combos)),
        "winners": float(winners),
        "staked": float(len(combos)) * stake_per_parlay,
        "profit": profit,
    }


def run_backtest() -> None:
    games = load_games()
    by_week = group_games_by_week(games)

    total_parlays = 0.0
    total_winners = 0.0
    total_staked = 0.0
    total_profit = 0.0

    print("Season  Week  ParlayBets  Winners  Profit")
    print("-----------------------------------------------")
    for (season, week) in sorted(by_week.keys()):
        res = simulate_week(by_week[(season, week)])
        if res["parlays"] == 0.0:
            continue
        total_parlays += res["parlays"]
        total_winners += res["winners"]
        total_staked += res["staked"]
        total_profit += res["profit"]
        print(f"{season:<7}{week:<6}{int(res['parlays']):<11}{int(res['winners']):<8}{res['profit']:>10.2f}")

    print("\n=== Summary ===")
    print(f"Total parlays placed: {int(total_parlays)}")
    print(f"Total winning parlays (ATS): {int(total_winners)}")
    hit_rate = (total_winners / total_parlays) if total_parlays else 0.0
    print(f"Hit rate: {hit_rate:.4f}")
    print(f"Total staked (@ $100/parlay): ${total_staked:,.2f}")
    print(f"Total profit: ${total_profit:,.2f}")
    roi = (total_profit / total_staked) if total_staked else 0.0
    print(f"ROI: {roi:.4%}")


if __name__ == "__main__":
    run_backtest()

