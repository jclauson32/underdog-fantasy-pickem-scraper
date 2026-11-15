"""
FantasyPros weekly consensus PPR projections, read from the public projection pages.

Companion to underdog_scraper.py and sleeper_scraper.py. No account or key: it reads only the data each
public page embeds, which is the TOP 10 PLAYERS PER POSITION (QB, RB, WR, TE). The rest of each table is
loaded from FantasyPros' keyed API (https://www.fantasypros.com/api-data/), which this does not use.
URLs and headers live in config.json.

    from fantasypros_scraper import FantasyProsScraper

    scraper = FantasyProsScraper().scrape()
    scraper.lookup("Ja'Marr Chase", "CIN")   # -> {"fpts": 20.8, "stats": {"receiving_rec": 7.3, ...}, ...} or None

Run directly to save the projections to CSV:

    python3 fantasypros_scraper.py   # -> fantasypros_projections.csv
"""

import csv
import json
import os
import re
import time
import urllib.request

from sleeper_scraper import normalize_name

HERE = os.path.dirname(os.path.abspath(__file__))
POSITIONS = ("qb", "rb", "wr", "te")
TEAM_ALIASES = {"JAC": "JAX", "WSH": "WAS", "LA": "LAR"}   # FantasyPros code -> Underdog code

# FantasyPros fields -> the stat keys Underdog uses (sums for combined stats)
FIELD_TO_STAT = {
    "passing_att": ("pass_att",),
    "passing_comps": ("pass_cmp",),
    "passing_yds": ("pass_yds",),
    "passing_tds": ("pass_tds",),
    "passing_ints": ("pass_ints",),
    "rushing_att": ("rush_att",),
    "rushing_yds": ("rush_yds",),
    "receiving_rec": ("rec_att",),
    "receiving_yds": ("rec_yds",),
    "rush_rec_tds": ("rush_tds", "rec_tds"),
    "rush_rec_yds": ("rush_yds", "rec_yds"),
    "passing_and_rushing_yds": ("pass_yds", "rush_yds"),
    "fumbles_lost": ("fumbles",),
    "fantasy_points": ("fpts",),
}
STATS = set(FIELD_TO_STAT)
REQUIRED_FIELD = {"passing_and_rushing_yds": "pass_yds"}   # only meaningful for players projected to pass


def opponent_from_game(game_code, team):
    """FantasyPros game codes join the two teams' codes, e.g. 'NEDET' for NE vs DET."""
    if not game_code or not team:
        return ""
    if game_code.startswith(team):
        opp = game_code[len(team):]
    elif game_code.endswith(team):
        opp = game_code[:-len(team)]
    else:
        return ""
    return TEAM_ALIASES.get(opp, opp)


class FantasyProsScraper:
    def __init__(self, timeout=30, pause=1.0):
        self.config = None
        self.timeout = timeout
        self.pause = pause                      # seconds between page requests, to be polite
        self.week = None
        self.updated = None
        self.fantasypros_projections = []       # one dict per player
        self._by_name_team = {}
        self._by_name = {}

        self.load_config()

    def load_config(self):
        with open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as json_file:
            self.config = json.load(json_file)

    # -- fetching -------------------------------------------------------------------
    def _get_html(self, url):
        req = urllib.request.Request(url, headers={**self.config["headers"], "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def fetch_data(self):
        """{position: page html} for QB, RB, WR, TE."""
        pages = {}
        for i, pos in enumerate(POSITIONS):
            if i and self.pause:
                time.sleep(self.pause)
            pages[pos] = self._get_html(self.config["fantasypros_projections_url"].format(position=pos))
        return pages

    # -- processing (no network; testable on saved pages) ------------------------------
    @staticmethod
    def parse_page(html):
        """The report config JSON a projections page embeds (window.FP.reportConfig = {...})."""
        m = re.search(r"window\.FP\.reportConfig\s*=\s*", html)
        if not m:
            raise ValueError("FantasyPros page layout changed: no reportConfig found")
        config, _ = json.JSONDecoder().raw_decode(html, m.end())
        return config

    def process_data(self, pages):
        self.fantasypros_projections, self._by_name_team, self._by_name = [], {}, {}
        for pos, html in pages.items():
            config = self.parse_page(html)
            week = re.search(r"Week (\d+)", config.get("title", ""))
            if week:
                self.week = int(week.group(1))
            updated = re.search(r"updated (.+)$", config.get("subtitle", ""))
            if updated:
                self.updated = updated.group(1)
            for row in config.get("table", {}).get("rows", []):
                player = row.get("player") or {}
                if not player.get("name") or row.get("fpts") is None:
                    continue
                team = TEAM_ALIASES.get(player.get("team"), player.get("team"))
                stats = {}
                for key, fields in FIELD_TO_STAT.items():
                    # a position's page omits fields it doesn't project (no rec TDs for QBs, no rush TDs for TEs)
                    vals = [row[f] for f in fields if isinstance(row.get(f), (int, float))]
                    required = REQUIRED_FIELD.get(key)
                    if vals and (required is None or isinstance(row.get(required), (int, float))):
                        stats[key] = round(sum(vals), 4)
                proj = {"name": player["name"], "position": pos.upper(), "team": team,
                        "opp": opponent_from_game(row.get("_filterGame"), player.get("team")),
                        "fpts": row["fpts"], "stats": stats, "raw": {k: v for k, v in row.items() if k != "player"}}
                self.fantasypros_projections.append(proj)
                key = normalize_name(proj["name"])
                self._by_name_team[(key, team)] = proj
                self._by_name.setdefault(key, []).append(proj)
        self.fantasypros_projections.sort(key=lambda p: p["fpts"], reverse=True)
        return self.fantasypros_projections

    def scrape(self):
        """Fetch and parse all four position pages. Returns self."""
        self.process_data(self.fetch_data())
        return self

    # -- matching / output ---------------------------------------------------------------
    def lookup(self, name, team=None):
        """A player's projection by name (+ team), or None."""
        key = normalize_name(name)
        if not key:
            return None
        proj = self._by_name_team.get((key, TEAM_ALIASES.get(team, team)))
        if proj:
            return proj
        same = self._by_name.get(key, [])
        return same[0] if len(same) == 1 else None

    def projection_rows(self):
        """One row per player with every FantasyPros field (blank where a position has none)."""
        fields = list(dict.fromkeys(k for p in self.fantasypros_projections for k in p["raw"]
                                    if k not in ("id", "_filterGame", "fpts")))
        rows = []
        for p in self.fantasypros_projections:
            row = {"Player": p["name"], "Pos": p["position"], "Team": p["team"], "Opp": p["opp"], "PPR": p["fpts"]}
            row.update({f: p["raw"].get(f, "") for f in fields})
            rows.append(row)
        return rows

    @staticmethod
    def save_csv(rows, path):
        if not rows:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Data saved to {path}")


if __name__ == "__main__":
    scraper = FantasyProsScraper().scrape()
    print(f"FantasyPros week {scraper.week} (updated {scraper.updated}): "
          f"{len(scraper.fantasypros_projections)} projections (top 10 per position)")
    scraper.save_csv(scraper.projection_rows(), "fantasypros_projections.csv")
