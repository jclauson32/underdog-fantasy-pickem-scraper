"""Small, hand-built samples shaped like the real Underdog and Sleeper API responses and FantasyPros pages."""

import copy
import json

# --------------------------------------------------------------------------- #
# Underdog  (GET /v1/over_under_lines)
# --------------------------------------------------------------------------- #
TEAMS = {"BUF": "t-buf", "NYJ": "t-nyj", "JAX": "t-jax", "TEN": "t-ten", "ARI": "t-ari", "SF": "t-sf"}

_GAMES = [
    {"id": 1, "abbreviated_title": "BUF @ NYJ", "away_team_id": "t-buf", "home_team_id": "t-nyj",
     "scheduled_at": "2026-11-15T18:00:00Z"},
    {"id": 2, "abbreviated_title": "JAX @ TEN", "away_team_id": "t-jax", "home_team_id": "t-ten",
     "scheduled_at": "2026-11-15T18:00:00Z"},
    {"id": 3, "abbreviated_title": "ARI @ SF", "away_team_id": "t-ari", "home_team_id": "t-sf",
     "scheduled_at": "2026-11-15T21:25:00Z"},
]

# (appearance id, first, last, position, team, game id)
_PLAYERS = [
    ("a-allen", "Josh", "Allen", "QB", "BUF", 1),
    ("a-wilson", "Garrett", "Wilson", "WR", "NYJ", 1),
    ("a-thomas", "Brian", "Thomas", "WR", "JAX", 2),     # Sleeper calls him "Brian Thomas Jr."
    ("a-knight", "Bam", "Knight", "RB", "ARI", 3),       # Sleeper calls him "Zonovan Knight"
    ("a-warner", "Fred", "Warner", "LB", "SF", 3),       # defender: not ranked, but in the comparison
    ("a-kittle", "George", "Kittle", "TE", "SF", 3),     # only a Fantasy Points line + a 1Q line
    ("a-pearsall", "Ricky", "Pearsall", "WR", "SF", 3),  # only a 1Q line: nothing usable -> not ranked
]


def _option(choice, american, decimal=None, multiplier=None, fantasy_american=None, fantasy_prob=None):
    return {
        "choice": choice, "american_price": american, "decimal_price": decimal, "payout_multiplier": multiplier,
        "odds": {"fantasy": {"american": fantasy_american, "probability": fantasy_prob}},
        "updated_at": "2026-11-15T12:00:00Z",
    }


def _line(app_id, stat, value, over, under, display=None):
    options = []
    if over is not None:
        options.append(_option("higher", over, "1.91", "0.95", over, "50"))
    if under is not None:
        options.append(_option("lower", under, "1.91", "0.95", under, "50"))
    return {
        "id": f"{app_id}-{stat}-{value}", "status": "active", "stat_value": str(value), "line_type": "balanced",
        "updated_at": "2026-11-15T12:00:00Z", "options": options,
        "over_under": {"appearance_stat": {"appearance_id": app_id, "stat": stat, "display_stat": display or stat}},
    }


_LINES = [
    # Josh Allen
    _line("a-allen", "passing_yds", 250.5, "-110", "-110", "Pass Yards"),
    _line("a-allen", "passing_tds", 1.5, "-150", "+120", "Pass TDs"),
    _line("a-allen", "passing_ints", 0.5, "+130", "-160", "INTs Thrown"),
    _line("a-allen", "rushing_yds", 30.5, "-110", "-110", "Rush Yards"),
    _line("a-allen", "rush_rec_tds", 0.5, "+100", "-130", "Anytime TD"),
    _line("a-allen", "fantasy_points", 22.5, "-112", "-112", "Fantasy Points"),
    # Garrett Wilson -- two receiving-yards lines; the balanced 65.5 should win over the lopsided 70.5
    _line("a-wilson", "receiving_rec", 5.5, "-120", "-110", "Receptions"),
    _line("a-wilson", "receiving_yds", 70.5, "+150", "-200", "Receiving Yards"),
    _line("a-wilson", "receiving_yds", 65.5, "-110", "-110", "Receiving Yards"),
    _line("a-wilson", "rush_rec_tds", 0.5, "+200", "-260", "Anytime TD"),
    # Brian Thomas
    _line("a-thomas", "receiving_yds", 60.5, "-110", "-110", "Receiving Yards"),
    _line("a-thomas", "receiving_rec", 4.5, "-110", "-110", "Receptions"),
    # Bam Knight -- rushing yards must be derived from Rush + Rec minus Rec
    _line("a-knight", "rush_rec_yds", 50.5, "-110", "-110", "Rush + Rec Yards"),
    _line("a-knight", "receiving_yds", 10.5, "-110", "-110", "Receiving Yards"),
    # Fred Warner (defender)
    _line("a-warner", "tackles", 7.5, "-110", "-110", "Solo Tackles"),
    # George Kittle -- fantasy points only (+ a quarter line that isn't used)
    _line("a-kittle", "fantasy_points", 8.5, "-112", "-112", "Fantasy Points"),
    _line("a-kittle", "period_1_receiving_rec", 0.5, "-150", "+120", "1Q Receptions"),
    # Ricky Pearsall -- quarter line only
    _line("a-pearsall", "period_1_receiving_yds", 4.5, "-110", "-110", "1Q Rec Yards"),
]


def underdog_data():
    players, appearances = [], []
    for app_id, first, last, pos, team, game_id in _PLAYERS:
        pid = "p-" + app_id[2:]
        players.append({"id": pid, "first_name": first, "last_name": last, "position_name": pos,
                        "sport_id": "NFL", "team_id": TEAMS[team], "jersey_number": "1"})
        appearances.append({"id": app_id, "player_id": pid, "match_id": game_id, "team_id": TEAMS[team]})
    # a non-NFL player whose line must be ignored
    players.append({"id": "p-nba", "first_name": "Some", "last_name": "Guard", "position_name": "G",
                    "sport_id": "NBA", "team_id": "t-nba"})
    appearances.append({"id": "a-nba", "player_id": "p-nba", "match_id": 99, "team_id": "t-nba"})
    lines = _LINES + [_line("a-nba", "points", 20.5, "-110", "-110", "Points")]
    return copy.deepcopy({"players": players, "appearances": appearances, "games": _GAMES, "over_under_lines": lines})


# --------------------------------------------------------------------------- #
# Sleeper
# --------------------------------------------------------------------------- #
SLEEPER_PLAYERS = {
    "4984": {"full_name": "Josh Allen", "first_name": "Josh", "last_name": "Allen", "position": "QB", "team": "BUF"},
    "11631": {"full_name": "Brian Thomas Jr.", "first_name": "Brian", "last_name": "Thomas Jr.", "position": "WR", "team": "JAX"},
    "8122": {"full_name": "Zonovan Knight", "first_name": "Zonovan", "last_name": "Knight", "position": "RB", "team": "ARI"},
    "777": {"full_name": "Jake Moody", "first_name": "Jake", "last_name": "Moody", "position": "K", "team": "SF"},
    "501": {"full_name": "Jalen Smith", "first_name": "Jalen", "last_name": "Smith", "position": "WR", "team": "MIA"},
    "502": {"full_name": "Jaden Smith", "first_name": "Jaden", "last_name": "Smith", "position": "RB", "team": "MIA"},
}


def _sl_line(pid, wager, value, over_mult, under_mult, team, pos, sport="nfl", status="active", recent=None,
             popularity=0.5, counts=None):
    def opt(outcome, mult):
        return {"outcome": outcome, "outcome_value": value, "payout_multiplier": mult,
                "subject_team": team, "subject_position": pos}
    return {
        "sport": sport, "subject_type": "player", "subject_id": pid, "status": status, "wager_type": wager,
        "game_id": "g1", "game_status": "pre_game", "updated_at": 1794745891605,
        "options": [opt("over", over_mult), opt("under", under_mult)],
        "pick_stats": {"popularity": popularity, "counts": counts or {"total": 10, "over": 7, "under": 3}},
        "recent_performance": {"values": [{"value": v} for v in (recent or [])]},
    }


def sleeper_lines():
    return copy.deepcopy([
        _sl_line("4984", "passing_yards", 245.5, "1.78", "1.78", "BUF", "QB", recent=[300, 200, 250, 260]),
        _sl_line("4984", "fantasy_points", 24.5, "1.78", "1.78", "BUF", "QB"),
        _sl_line("11631", "receiving_yards", 62.5, "2.00", "1.50", "JAX", "WR", recent=[50, 70, 80]),
        _sl_line("8122", "rushing_attempts", 10.5, "1.78", "1.78", "ARI", "RB"),   # Underdog doesn't offer it
        _sl_line("777", "kicking_points", 7.5, "1.78", "1.78", "SF", "K"),         # player not on Underdog
        _sl_line("501", "receptions", 3.5, "1.78", "1.78", "MIA", "WR"),
        _sl_line("502", "rushing_yards", 40.5, "1.78", "1.78", "MIA", "RB"),
        _sl_line("4984", "points", 25.5, "1.78", "1.78", "BUF", "QB", sport="nba"),  # other sport: skipped
        _sl_line("4984", "rushing_yards", 30.5, "1.78", "1.78", "BUF", "QB", status="suspended"),  # skipped
    ])


# --------------------------------------------------------------------------- #
# FantasyPros  (public projection pages: /nfl/projections/{qb,rb,wr,te}.php?scoring=PPR)
# --------------------------------------------------------------------------- #
def _fp_page(position, rows):
    config = {
        "type": "nfl_projections", "title": "Fantasy Football Projections - Week 10",
        "subtitle": "Consensus last updated Nov 15, 2026",
        "table": {"fields": [], "rows": rows},
    }
    return ("<html><head><title>Week 10 %s Projections</title></head><body><script>\n"
            "  window.FP = window.FP || {};\n  window.FP.reportConfig = %s;\n  window.FP.isLoggedIn = false;\n"
            "</script></body></html>") % (position.upper(), json.dumps(config))


def _fp_row(pid, name, team, game, **stats):
    return {"id": pid, "player": {"id": pid, "name": name, "team": team, "url": "/x.php"}, "_filterGame": game, **stats}


def fantasypros_pages():
    return {
        "qb": _fp_page("qb", [_fp_row(1, "Josh Allen", "BUF", "BUFNYJ", pass_att=30.6, pass_cmp=20.1, pass_yds=250.7,
                                      pass_tds=1.8, pass_ints=0.6, rush_att=6.7, rush_yds=33.3, rush_tds=0.7,
                                      fumbles=0.2, fpts=24.1)]),
        "rb": _fp_page("rb", [_fp_row(2, "Jahmyr Gibbs", "DET", "NEDET", rush_att=20, rush_yds=92.2, rush_tds=1,
                                      rec_att=4.6, rec_yds=36.6, rec_tds=0.2, fumbles=0.1, fpts=24.4)]),
        "wr": _fp_page("wr", [_fp_row(3, "Brian Thomas Jr.", "JAC", "JACTEN", rec_att=5.0, rec_yds=70.0, rec_tds=0.4,
                                      rush_att=0.2, rush_yds=1.0, rush_tds=0, fumbles=0, fpts=14.5)]),
        "te": _fp_page("te", [_fp_row(4, "George Kittle", "SF", "ARISF", rec_att=5.4, rec_yds=70.8, rec_tds=0.6,
                                      fumbles=0, fpts=16.1),
                              _fp_row(5, "No Points", "SF", "ARISF", rec_att=1.0)]),   # no fpts -> skipped
    }


SLEEPER_STATE = {"week": 10, "season": "2026", "season_type": "regular", "season_start_date": "2026-09-09"}


def sleeper_stats_week():
    """Sleeper stats feed rows (actual box scores) for the sample players' week."""
    def row(pid, first, last, pos, team, opp, **stats):
        return {"player_id": pid, "team": team, "opponent": opp, "week": 10, "category": "stat",
                "player": {"first_name": first, "last_name": last, "position": pos, "team": team},
                "stats": {"gp": 1.0, **stats}}
    return [
        row("4984", "Josh", "Allen", "QB", "BUF", "NYJ", pass_yd=280.0, pass_td=2.0, pass_int=1.0, rush_yd=20.0,
            rush_td=1.0, pts_ppr=29.2, pts_half_ppr=29.2),
        row("5001", "Garrett", "Wilson", "WR", "NYJ", "BUF", rec=5.0, rec_yd=65.5, rec_td=0.0,
            pts_ppr=11.55, pts_half_ppr=9.05),
        row("11631", "Brian", "Thomas Jr.", "WR", "JAX", "TEN", rec=3.0, rec_yd=40.0, pts_ppr=7.0, pts_half_ppr=5.5),
        {"player_id": "8122", "team": "ARI", "player": {"first_name": "Zonovan", "last_name": "Knight"},
         "stats": {"gp": 0.0}},                                                           # inactive
    ]
