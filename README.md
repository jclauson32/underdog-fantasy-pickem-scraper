# NFL PPR Rankings (with odds)

`ppr_rankings.py` pulls every live NFL prop from **Underdog Fantasy** and **Sleeper Picks**, plus
**FantasyPros**' weekly consensus projections, and lays them out side by side in a spreadsheet and an
interactive page. It makes **no projections of its own**: every number is a site's posted line and odds, a
straight conversion of those odds (no-vig probability), or FantasyPros' published projection.

No installs needed (Python 3 standard library only):

```
python3 ppr_rankings.py                  # -> nfl_ppr_rankings.xlsx, .html and one .csv per sheet
python3 ppr_rankings.py --open           # same, then opens the interactive page in your browser
python3 ppr_rankings.py --no-sleeper     # skip Sleeper
python3 ppr_rankings.py --no-fantasypros # skip FantasyPros
python3 ppr_rankings.py -o week11.xlsx   # custom file name
python3 ppr_rankings.py --no-csv         # skip the CSV copies
python3 ppr_rankings.py --no-history     # don't save a snapshot
python3 projected_vs_actual.py           # compare saved snapshots with actual results
```

**Sheets** (each also written as a CSV: `nfl_ppr_rankings.csv`, `nfl_ppr_rankings_odds_comparison.csv`, ...)
- **PPR Rankings**: one row per offensive player on any source: rank, team/opponent, kickoff, then for every
  stat (fantasy points, pass/rush/receiving yards, TDs, receptions, attempts, longest plays, ...) each site's
  line and over/under odds plus FantasyPros' projected value, e.g. `Pass Yds UD Line`, `Pass Yds SL Line`,
  `Pass Yds FP Proj`. Ranked by **Sleeper's Fantasy Points line** (full PPR); players without one are listed
  after, unranked. (Without Sleeper, FantasyPros' projection is used, then Underdog's half-PPR line.)
- **Odds Comparison**: every prop from both sites, one row per player + stat: each site's line, odds and no-vig
  over %, the differences (Sleeper − Underdog), and Sleeper's pick data (popularity, over/under pick counts,
  recent results and how often they beat the current line). Stats only one site offers are included too.
- **Underdog Props**: every NFL line on Underdog (including quarter/half lines, defense, kickers) with every
  price field: American and decimal odds, payout multipliers, Underdog's separate "fantasy" odds and
  probability, line type, last update.
- **Sleeper Props**: every NFL line on Sleeper Picks with payout multipliers (and their American-odds
  equivalent), pick counts, popularity and recent results.
- **FantasyPros Projections**: FantasyPros' consensus projection with every projected stat.

**FantasyPros coverage.** The script reads only FantasyPros' public projection pages (allowed by their
robots.txt), and those pages only embed the **top 10 players per position** (about 40 players); everyone else
is blank in the FantasyPros columns. The full tables come from FantasyPros' keyed API
(https://www.fantasypros.com/api-data/), which this doesn't use. FantasyPros numbers are expert projections, not
betting lines, so they have no odds.

**Odds on the two sites.** Underdog posts American odds. Sleeper posts a payout multiplier per side, which works
like decimal odds (1.78 = −128), so the script converts it to American odds and a no-vig probability to compare.
Note that the sites score **Fantasy Points** differently: Underdog's line is half-PPR, while Sleeper's matches
full PPR, so that stat is labelled with both and its line difference isn't apples to apples.

**Interactive page** (`nfl_ppr_rankings.html`): a single offline file with two tabs, **PPR Rankings** and
**Odds Comparison**. You can
- click any column header to sort by it; click again to reverse (odds sort by implied probability, so
  descending puts the most likely outcome first)
- pick the **sources** (Underdog, Sleeper, FantasyPros, any combination): every stat shows a top header (e.g.
  "Fantasy Pts", "Pass Yds") with a column group per selected source underneath
- **Rank by** Sleeper's Fantasy Points line (PPR), FantasyPros' projection (PPR) or Underdog's Fantasy Points
  line (half-PPR)
- pick which **stats** to show (Core / All / None shortcuts), and toggle the odds columns
- filter by position, team, game or player name (plus stat and "offered on both sites" in the comparison)
- group by position, team or game (and player or stat in the comparison); groups collapse and show totals

**Projected vs actual.** Every `ppr_rankings.py` run saves a snapshot of all lines, odds and FantasyPros
projections to `history/snapshots/`. Once a week's games are final (after Tuesday), `projected_vs_actual.py`
takes each player's last snapshot before his kickoff, downloads the actual box scores from Sleeper's public stats
feed (kept in `history/results/`), and writes `projected_vs_actual.xlsx`:
- **Summary**: per source and stat: players, average projected vs actual, average miss, over/under %, the
  odds-implied over %, and how often the side the odds favoured won
- **Fantasy Pts Rank**: per week and source, how well each fantasy-points number ordered players
  (rank correlation with actual points; 1 = perfect)
- **Details**: every player, stat and source
Actual fantasy points use each source's scoring (Underdog half-PPR; Sleeper and FantasyPros full PPR). Players
who didn't play are left out. Options: `--week N`, `--season YYYY`, `--refresh` (re-download stat corrections).

**Week by week.** The interactive page has a **Week** picker built from `history/`: each week shows every
player's last lines and projections before his kickoff. Once a week is final, each stat gets an **Actual**
column, "Actual fantasy points" becomes a Rank by option, and the **Projected vs Actual** tab shows the accuracy
summary for that week or the season to date. The Odds Comparison tab is always the live, current lines.

**Scheduled snapshots.** Claude cloud routines run before each game window: `scripts/pull_history.sh` (load the
saved history), `python3 ppr_rankings.py`, `scripts/push_history.sh` (push new snapshots and results to the
`history` branch; nothing is committed to `main`), then republish the page on claude.ai. To use the history
locally:
```
scripts/pull_history.sh
python3 projected_vs_actual.py
```

**Code layout**
- `ppr_rankings.py`: fetches Underdog, builds the rankings and comparison, writes the outputs
- `sleeper_scraper.py`: `SleeperScraper` (mirrors `UnderdogScraper`): Sleeper Picks lines, the player list
  (cached in `.cache/` for a day) and name matching. Run it alone with `python3 sleeper_scraper.py` to save
  `sleeper_props.csv`.
- `fantasypros_scraper.py`: `FantasyProsScraper`: reads the projections each public position page embeds.
  Run it alone with `python3 fantasypros_scraper.py` to save `fantasypros_projections.csv`.
- `projected_vs_actual.py` + `history.py`: snapshots, NFL week numbering, actual results and the comparison
- `weekly.py`: the week-by-week data embedded in the page
- `scripts/pull_history.sh`, `scripts/push_history.sh`: sync `history/` with the `history` branch
- `templates/rankings.html`: the interactive page
- `config.json`: API URLs and headers for both sites

Both sites' APIs are public but undocumented, so they can change without notice. If Sleeper is unreachable the
script still runs without the Sleeper columns.

**Tests**: `python3 -m unittest` runs 85 offline tests (odds conversions checked against hand calculations, parsing,
name matching, rankings, the comparison, the file writers, and a full run with the network replaced by sample
data in `tests/fixtures.py`).

Only players with lines currently posted show up, so run it close to kickoff for the fullest list.

---

# Underdog Fantasy Sports Scraper

This project provides a Python script to scrape and process pickem data from Underdog Fantasy Sports and output the results to a CSV file.

## Description

The Underdog Scraper is designed to:
1. Fetch data from Underdog Fantasy Sports API
2. Process and combine different data sets (players, appearances, over/under lines)
3. Apply name corrections if necessary
4. Filter and clean the data
5. Export the processed data to a CSV file

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/underdog-scraper.git
   cd underdog-scraper
   ```

2. Install the required Python packages:
   ```
   pip install requests pandas
   ```

3. Ensure you have a `config.json` file in the same directory as the script with the necessary configuration (API URL and headers). You should not have to edit this file, unless Underdog changes their API endpoints.

## Usage

1. Open the `underdog_scraper.py` file.

2. Uncomment the last two lines of the script:
   ```python
   scraper = UnderdogScraper()
   scraper.scrape()
   ```

3. Run the script:
   ```
   python underdog_scraper.py
   ```

4. The script will fetch data and save the results to `underdog_props.csv` in the same directory.

## FAQ

If you have comments or questions reach out to me on Twitter/X @tistonionwings

## Donation

If you find this project helpful and would like to support the developer, you can donate [by clicking here](https://www.paypal.com/paypalme/ultimateratings).

Thank you for your generosity!
