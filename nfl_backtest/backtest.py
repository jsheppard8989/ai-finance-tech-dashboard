import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple

import pandas as pd


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


def load_games(csv_path: Path = DATA_PATH) -> List[Game]:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Data file not found at {csv_path}. "
            f"Place your Kaggle-style NFL scores & betting CSV there."
        )

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


def simulate_week(games: List[Game]) -> Dict[str, int]:
    if len(games) < 6:
        return {"parlays": 0, "winners": 0}

    # Rank by biggest underdog spread (largest positive points).
    sorted_games = sorted(games, key=lambda g: g.underdog_spread, reverse=True)
    top_six = sorted_games[:6]

    # All 3-leg combinations of these 6 underdogs.
    combos = list(itertools.combinations(top_six, 3))

    winners = 0
    for combo in combos:
        if all(g.underdog_covers() for g in combo):
            winners += 1

    return {"parlays": len(combos), "winners": winners}


def run_backtest() -> None:
    games = load_games()
    by_week = group_games_by_week(games)

    total_parlays = 0
    total_winners = 0

    print("Season  Week  ParlayBets  WinningParlays")
    print("----------------------------------------")
    for (season, week) in sorted(by_week.keys()):
        res = simulate_week(by_week[(season, week)])
        if res["parlays"] == 0:
            continue
        total_parlays += res["parlays"]
        total_winners += res["winners"]
        print(f"{season:<7}{week:<6}{res['parlays']:<11}{res['winners']}")

    print("\n=== Summary ===")
    print(f"Total parlays placed: {total_parlays}")
    print(f"Total winning parlays (ATS): {total_winners}")
    hit_rate = (total_winners / total_parlays) if total_parlays else 0.0
    print(f"Hit rate: {hit_rate:.4f}")


if __name__ == "__main__":
    run_backtest()

