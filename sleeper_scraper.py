"""
Sleeper weekly fantasy projections (supplied to Sleeper by RotoWire).

Companion to underdog_scraper.py. Uses Sleeper's public but undocumented API -- no account or key needed.
URLs and headers live in config.json alongside the Underdog ones.

    from sleeper_scraper import SleeperScraper

    scraper = SleeperScraper()            # current week
    scraper = SleeperScraper(week=11)     # a specific week
    scraper.scrape()
    proj = scraper.lookup("D.J. Moore", "CHI")   # -> {"ppr": 14.2, "half_ppr": ..., ...} or None

Run directly to save the projections to sleeper_projections.csv:

    python3 sleeper_scraper.py
"""

import csv
import json
import os
import urllib.request

NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name):
    """Normalise a player name so sources agree: 'D.J. Moore' == 'DJ Moore', 'James Cook III' == 'James Cook'."""
    cleaned = "".join(c for c in name.lower() if c.isalnum() or c.isspace() or c == "-")
    return " ".join(w for w in cleaned.replace("-", " ").split() if w not in NAME_SUFFIXES)


class SleeperScraper:
    def __init__(self, week=None, season=None, season_type=None, timeout=30):
        self.config = None
        self.week = week
        self.season = season
        self.season_type = season_type
        self.timeout = timeout
        self.sleeper_projections = []   # one dict per projected player
        self._by_name_team = {}         # (name, team) -> projection
        self._by_name = {}              # name -> [projections]
        self._by_last_team = {}         # (last name, team) -> [projections]

        self.load_config()

    def load_config(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
                  encoding="utf-8-sig") as json_file:
            self.config = json.load(json_file)

    def _get_json(self, url):
        req = urllib.request.Request(url, headers=self.config["headers"])
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)

    def fetch_data(self):
        """Download raw projections, filling in season/week/season type from Sleeper if not given."""
        if not (self.week and self.season and self.season_type):
            state = self._get_json(self.config["sleeper_state_url"])
            self.week = self.week or state["week"]
            self.season = self.season or state["season"]
            self.season_type = self.season_type or state.get("season_type") or "regular"
        url = self.config["sleeper_projections_url"].format(
            season=self.season, week=self.week, season_type=self.season_type)
        return self._get_json(url)

    def process_data(self, data):
        """Index raw projection rows. Separate from fetch_data() so it can run on saved data offline."""
        self.sleeper_projections, self._by_name_team, self._by_name, self._by_last_team = [], {}, {}, {}
        for row in data:
            stats = row.get("stats") or {}
            player = row.get("player") or {}
            if stats.get("pts_ppr") is None or not player.get("last_name"):
                continue  # no projection this week (bye, injured, inactive)
            proj = {
                "name": f"{player.get('first_name', '')} {player['last_name']}".strip(),
                "position": player.get("position"),
                "team": row.get("team") or player.get("team"),
                "opponent": row.get("opponent"),
                "ppr": stats["pts_ppr"],
                "half_ppr": stats.get("pts_half_ppr"),
                "standard": stats.get("pts_std"),
                "stats": stats,
            }
            key = normalize_name(proj["name"])
            self.sleeper_projections.append(proj)
            self._by_name_team[(key, proj["team"])] = proj
            self._by_name.setdefault(key, []).append(proj)
            self._by_last_team.setdefault((normalize_name(player["last_name"]), proj["team"]), []).append(proj)
        self.sleeper_projections.sort(key=lambda p: p["ppr"], reverse=True)
        return self.sleeper_projections

    def scrape(self):
        """Fetch and index projections. Returns self so calls can be chained."""
        self.process_data(self.fetch_data())
        return self

    def lookup(self, name, team=None):
        """Find a player's projection, or None. Tries, in order:
        1. exact normalised name + team
        2. name alone, if only one player has it (team abbreviations can differ between sites)
        3. last name + team, if unique (nicknames, e.g. 'Bam Knight' = 'Zonovan Knight')
        """
        key = normalize_name(name)
        if not key:
            return None
        proj = self._by_name_team.get((key, team))
        if proj:
            return proj
        same_name = self._by_name.get(key, [])
        if len(same_name) == 1:
            return same_name[0]
        same_last = self._by_last_team.get((key.split()[-1], team), [])
        if len(same_last) == 1:
            return same_last[0]
        return None

    def save_csv(self, path="sleeper_projections.csv"):
        fields = ["name", "position", "team", "opponent", "ppr", "half_ppr", "standard"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.sleeper_projections)
        print(f"Data saved to {path}")


if __name__ == "__main__":
    scraper = SleeperScraper().scrape()
    print(f"Sleeper {scraper.season} week {scraper.week}: {len(scraper.sleeper_projections)} projections")
    scraper.save_csv()
