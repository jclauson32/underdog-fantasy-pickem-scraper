"""
Sleeper Picks NFL over/under lines with their payout multipliers.

Companion to underdog_scraper.py. Uses Sleeper's public but undocumented API -- no account or key needed.
URLs and headers live in config.json alongside the Underdog ones.

    from sleeper_scraper import SleeperScraper

    scraper = SleeperScraper().scrape()
    scraper.lines_for("D.J. Moore", "CHI")   # -> {"receiving_yds": {...}, "fantasy_points": {...}, ...}

Run directly to save every NFL line to CSV:

    python3 sleeper_scraper.py   # -> sleeper_props.csv
"""

import csv
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PLAYERS_CACHE = os.path.join(HERE, ".cache", "sleeper_players_nfl.json")
PLAYERS_CACHE_MAX_AGE = 24 * 3600  # Sleeper asks that the player list be fetched at most once a day

NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Sleeper wager types -> the stat keys Underdog uses, so the two sites line up
WAGER_TO_STAT = {
    "passing_yards": "passing_yds",
    "passing_touchdowns": "passing_tds",
    "interceptions": "passing_ints",
    "pass_completions": "passing_comps",
    "passing_attempts": "passing_att",
    "longest_passing_completion": "passing_long",
    "passing_and_rushing_yards": "passing_and_rushing_yds",
    "rushing_yards": "rushing_yds",
    "rushing_attempts": "rushing_att",
    "longest_rush": "rushing_long",
    "receptions": "receiving_rec",
    "receiving_yards": "receiving_yds",
    "longest_reception": "receiving_long",
    "rushing_and_receiving_yards": "rush_rec_yds",
    "anytime_touchdowns": "rush_rec_tds",
    "fantasy_points": "fantasy_points",
    "tackles": "tackles",
    "assists": "assists",
    "tackles_and_assists": "tackles_and_assists",
    "sacks": "sacks",
    "kicking_points": "kicking_points",
    "field_goal_made": "field_goals_made",
    "extra_point_made": "extra_points_made",
}


def normalize_name(name):
    """Normalise a player name so sources agree: 'D.J. Moore' == 'DJ Moore', 'James Cook III' == 'James Cook'."""
    cleaned = "".join(c for c in name.lower() if c.isalnum() or c.isspace() or c == "-")
    return " ".join(w for w in cleaned.replace("-", " ").split() if w not in NAME_SUFFIXES)


def multiplier_to_american(multiplier):
    """Sleeper payout multiplier (works like decimal odds) -> American odds string, e.g. 1.77 -> '-130'."""
    try:
        d = float(multiplier)
    except (TypeError, ValueError):
        return ""
    if d <= 1:
        return ""
    v = round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))
    return f"+{v}" if v > 0 else str(v)


def stats_row(raw):
    """One player's actual week from the stats feed -> compact dict, or None if he didn't play."""
    stats = raw.get("stats") or {}
    player = raw.get("player") or {}
    if not stats.get("gp") or not player.get("last_name"):
        return None
    return {
        "player_id": str(raw.get("player_id")),
        "name": f"{player.get('first_name', '')} {player['last_name']}".strip(),
        "position": player.get("position"),
        "team": raw.get("team") or player.get("team"),
        "opponent": raw.get("opponent"),
        "stats": {k: v for k, v in stats.items() if isinstance(v, (int, float))},
    }


class SleeperScraper:
    def __init__(self, timeout=30):
        self.config = None
        self.timeout = timeout
        self.players = {}               # player_id -> {"name", "position", "team", "injury_status"}
        self.sleeper_lines = []         # one dict per over/under line
        self._lines_by_id = {}          # player_id -> {stat key: line}
        self._by_name_team = {}         # (name, team) -> player_id
        self._by_name = {}              # name -> {player_ids}
        self._by_last_team = {}         # (last name, team) -> {player_ids}

        self.load_config()

    def load_config(self):
        with open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as json_file:
            self.config = json.load(json_file)

    # -- fetching -------------------------------------------------------------------
    def _get_json(self, url):
        req = urllib.request.Request(url, headers=self.config["headers"])
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)

    def fetch_data(self):
        """Raw Sleeper Picks lines (all sports; process_data keeps NFL)."""
        return self._get_json(self.config["sleeper_lines_url"])

    def fetch_state(self):
        """Current NFL season state: {"season", "week", "season_type", "season_start_date", ...}."""
        return self._get_json(self.config["sleeper_state_url"])

    def fetch_stats(self, season, week, season_type="regular"):
        """Actual box-score stats for a completed week (QB/RB/WR/TE), from Sleeper's public stats feed."""
        url = self.config["sleeper_stats_url"].format(season=season, week=week, season_type=season_type)
        return [stats_row(r) for r in self._get_json(url) if stats_row(r)]

    def fetch_players(self):
        """Sleeper's full NFL player list (~15 MB), cached on disk for a day. Lines only carry player ids."""
        try:
            if time.time() - os.path.getmtime(PLAYERS_CACHE) < PLAYERS_CACHE_MAX_AGE:
                with open(PLAYERS_CACHE, encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, ValueError):
            pass
        players = self._get_json(self.config["sleeper_players_url"])
        try:
            os.makedirs(os.path.dirname(PLAYERS_CACHE), exist_ok=True)
            with open(PLAYERS_CACHE, "w", encoding="utf-8") as f:
                json.dump(players, f)
        except OSError:
            pass  # caching is a nicety; never fail the run over it
        return players

    # -- processing (no network; testable on saved data) ---------------------------------
    def _add_player(self, player_id, name, position, team, injury_status=None):
        if not player_id or not name or player_id in self.players:
            return
        self.players[player_id] = {"name": name, "position": position, "team": team, "injury_status": injury_status}
        key = normalize_name(name)
        self._by_name_team[(key, team)] = player_id
        self._by_name.setdefault(key, set()).add(player_id)
        self._by_last_team.setdefault((key.split()[-1] if key else "", team), set()).add(player_id)

    def process_data(self, data, players):
        """Flatten NFL over/under lines. `players` is Sleeper's player list (id -> player)."""
        self.sleeper_lines, self._lines_by_id = [], {}
        for market in data:
            if market.get("sport") != "nfl" or market.get("subject_type") != "player":
                continue
            if market.get("status") not in (None, "active"):
                continue
            pid = str(market.get("subject_id"))
            sides = {o.get("outcome"): o for o in market.get("options", [])}
            over, under = sides.get("over"), sides.get("under")
            first = over or under
            if not first:
                continue
            p = players.get(pid) or {}
            name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            team = first.get("subject_team") or p.get("team")
            position = first.get("subject_position") or p.get("position")
            self._add_player(pid, name, position, team, p.get("injury_status"))

            wager = market.get("wager_type")
            counts = (market.get("pick_stats") or {}).get("counts") or {}
            recent = ((market.get("recent_performance") or {}).get("values")) or []
            line = {
                "player_id": pid,
                "name": name,
                "position": position,
                "team": team,
                "game_id": market.get("game_id"),
                "game_status": market.get("game_status"),
                "wager_type": wager,
                "stat_key": WAGER_TO_STAT.get(wager, wager),
                "line": float(first.get("outcome_value")),
                "over_multiplier": over.get("payout_multiplier") if over else "",
                "under_multiplier": under.get("payout_multiplier") if under else "",
                "over_american": multiplier_to_american(over.get("payout_multiplier")) if over else "",
                "under_american": multiplier_to_american(under.get("payout_multiplier")) if under else "",
                "popularity": (market.get("pick_stats") or {}).get("popularity"),
                "picks_total": counts.get("total", 0),
                "picks_over": counts.get("over", 0),
                "picks_under": counts.get("under", 0),
                "recent_values": [v.get("value") for v in recent],
                "updated_at": market.get("updated_at"),
            }
            self.sleeper_lines.append(line)
            self._lines_by_id.setdefault(pid, {})[line["stat_key"]] = line
        return self.sleeper_lines

    def scrape(self):
        """Fetch and index the lines. Returns self so calls can be chained."""
        self.process_data(self.fetch_data(), self.fetch_players())
        return self

    # -- matching -----------------------------------------------------------------------
    def player_id_for(self, name, team=None):
        """Sleeper player id for a name (+ team), or None. Tries, in order:
        1. exact normalised name + team
        2. name alone, if only one player has it (team abbreviations can differ between sites)
        3. last name + team, if unique (nicknames, e.g. 'Bam Knight' = 'Zonovan Knight')
        """
        key = normalize_name(name)
        if not key:
            return None
        pid = self._by_name_team.get((key, team))
        if pid:
            return pid
        same_name = self._by_name.get(key, set())
        if len(same_name) == 1:
            return next(iter(same_name))
        same_last = self._by_last_team.get((key.split()[-1], team), set())
        if len(same_last) == 1:
            return next(iter(same_last))
        return None

    def lines_for(self, name, team=None):
        """A player's lines as {stat key: line dict} (empty if none)."""
        return self.lines_for_id(self.player_id_for(name, team))

    def lines_for_id(self, player_id):
        return self._lines_by_id.get(player_id, {})

    # -- output -----------------------------------------------------------------------------
    def line_rows(self):
        """Lines as flat rows (recent results joined into one text column)."""
        rows = []
        for ln in sorted(self.sleeper_lines, key=lambda x: (x["team"] or "", x["name"], x["wager_type"])):
            row = {k: v for k, v in ln.items() if k != "recent_values"}
            row["recent_values"] = " ".join("" if v is None else f"{v:g}" for v in ln["recent_values"])
            rows.append(row)
        return rows

    @staticmethod
    def save_csv(rows, path):
        if not rows:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Data saved to {path}")


if __name__ == "__main__":
    scraper = SleeperScraper().scrape()
    print(f"Sleeper: {len(scraper.sleeper_lines)} NFL lines")
    scraper.save_csv(scraper.line_rows(), "sleeper_props.csv")
