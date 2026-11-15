"""
Local history for comparing what was projected (lines, odds, FantasyPros) with what actually happened.

    history/
      snapshots/2026-11-15T14-25-31Z.json   one per ppr_rankings.py run: every player's lines, odds, FantasyPros values
      results/2026_week10.json              actual stats for a completed week (projected_vs_actual.py)

Weeks are worked out from each game's kickoff: NFL weeks run Wednesday-Tuesday from the season start date
Sleeper reports (e.g. 2026-09-09), so Thursday through Monday night games of one week share a number.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(HERE, "history")


def _dir(kind, root=None):
    path = os.path.join(root or HISTORY_DIR, kind)
    os.makedirs(path, exist_ok=True)
    return path


def parse_time(iso):
    """'2026-11-15T18:00:00Z' -> aware datetime (None for blanks)."""
    if not iso:
        return None
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))


def nfl_week(kickoff, season_start_date):
    """Week number of a game, from its kickoff and the season start date ('2026-09-09')."""
    kick = parse_time(kickoff) if isinstance(kickoff, str) else kickoff
    if not kick or not season_start_date:
        return None
    # Kickoffs are in UTC; US evening games fall on the next UTC day, so judge the date in US Eastern (~UTC-5)
    local_day = (kick - timedelta(hours=5)).date()
    days = (local_day - date.fromisoformat(season_start_date)).days
    return days // 7 + 1 if days >= 0 else None


def week_complete(season_start_date, week, now=None):
    """True once a week's Tuesday has passed (all its games, including Monday night, are final)."""
    end = date.fromisoformat(season_start_date) + timedelta(days=7 * week)   # the following Wednesday
    return (now or datetime.now(timezone.utc)).date() >= end


# --------------------------------------------------------------------------- #
# Snapshots
# --------------------------------------------------------------------------- #
def save_snapshot(rankings, state, taken_at=None, root=None):
    """Save one run's rankings rows. `state` is Sleeper's season state (may be {} if unavailable)."""
    taken_at = taken_at or datetime.now(timezone.utc)
    snap = {
        "taken_at": taken_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": state.get("season"),
        "season_type": state.get("season_type"),
        "season_start_date": state.get("season_start_date"),
        "week": state.get("week"),
        "rows": rankings,
    }
    path = os.path.join(_dir("snapshots", root), taken_at.strftime("%Y-%m-%dT%H-%M-%SZ") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f)
    return path


def load_snapshots(root=None):
    folder = _dir("snapshots", root)
    snaps = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(".json"):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                snaps.append(json.load(f))
    return snaps


# --------------------------------------------------------------------------- #
# Actual results
# --------------------------------------------------------------------------- #
def _week_path(kind, season, week, root=None):
    return os.path.join(_dir(kind, root), f"{season}_week{int(week):02d}.json")


def save_week(kind, season, week, data, root=None):
    path = _week_path(kind, season, week, root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def load_week(kind, season, week, root=None):
    path = _week_path(kind, season, week, root)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def has_week(kind, season, week, root=None):
    return os.path.exists(_week_path(kind, season, week, root))


def stored_weeks(kind, root=None):
    """[(season, week)] stored for a kind, e.g. 'results'."""
    out = []
    for name in sorted(os.listdir(_dir(kind, root))):
        if name.endswith(".json") and "_week" in name:
            season, week = name[:-5].split("_week")
            out.append((season, int(week)))
    return out
