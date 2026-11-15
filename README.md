# NFL PPR Rankings (with odds)

`ppr_rankings.py` pulls every live NFL prop from **Underdog Fantasy** and **Sleeper Picks**, plus
**FantasyPros**' weekly consensus projections, and builds a spreadsheet and an interactive page of players ranked by projected
**full-PPR** fantasy points, with both sites' lines and odds side by side.

No installs needed (Python 3 standard library only):

```
python3 ppr_rankings.py                  # -> nfl_ppr_rankings.xlsx, .html and one .csv per sheet
python3 ppr_rankings.py --open           # same, then opens the interactive page in your browser
python3 ppr_rankings.py --no-sleeper     # skip Sleeper
python3 ppr_rankings.py --no-fantasypros # skip FantasyPros
python3 ppr_rankings.py -o week11.xlsx   # custom file name
python3 ppr_rankings.py --no-csv         # skip the CSV copies
```

**Sheets** (each also written as a CSV: `nfl_ppr_rankings.csv`, `nfl_ppr_rankings_odds_comparison.csv`, ...)
- **PPR Rankings**: one row per player on any source: rank, team/opponent, kickoff, a full-PPR projection per
  source (`UD Proj PPR` and `SL Proj PPR` built from each site's own lines, `FP Proj PPR` = FantasyPros
  consensus) and their average (used for the rank), then for every stat (fantasy points, pass/rush/receiving
  yards, TDs, receptions, attempts, longest plays, ...) each site's line, over/under odds and expected value,
  plus FantasyPros' projected value, e.g. `Pass Yds UD Line`, `Pass Yds SL Line`, `Pass Yds FP Proj`.
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
  "PPR projection", "Pass Yds") with a column group per selected source underneath; the rank follows the
  selected source's projection (the average of the selected sources when several are on)
- pick which **stats** to show (Core / All / None shortcuts), and toggle the odds and expected-value columns
- filter by position, team, game or player name (plus stat and "offered on both sites" in the comparison)
- group by position, team or game (and player or stat in the comparison); groups collapse and show totals

**Code layout**
- `ppr_rankings.py`: fetches Underdog, builds the projections, rankings and comparison, writes the outputs
- `sleeper_scraper.py`: `SleeperScraper` (mirrors `UnderdogScraper`): Sleeper Picks lines, the player list
  (cached in `.cache/` for a day) and name matching. Run it alone with `python3 sleeper_scraper.py` to save
  `sleeper_props.csv`.
- `fantasypros_scraper.py`: `FantasyProsScraper`: reads the projections each public position page embeds.
  Run it alone with `python3 fantasypros_scraper.py` to save `fantasypros_projections.csv`.
- `templates/rankings.html`: the interactive page
- `config.json`: API URLs and headers for both sites

Both sites' APIs are public but undocumented, so they can change without notice. If Sleeper is unreachable the
script still runs without the Sleeper columns.

**Tests**: `python3 -m unittest` runs 76 offline tests (odds math checked against hand calculations, parsing,
name matching, rankings, the comparison, the file writers, and a full run with the network replaced by sample
data in `tests/fixtures.py`).

**How projections work**
1. Each line's over/under odds are converted to a no-vig probability of the over.
2. Count stats (receptions, TDs, pass TDs, INTs, fumbles) use the Poisson mean that matches that probability;
   yardage stats shift the line by the odds-implied z-score.
3. Scoring: 0.04/pass yd, 4/pass TD, -2/INT, 0.1/rush or rec yd, 1/reception, 6/rush-rec TD, -2/fumble lost.
4. Missing rush yards are derived from Rush+Rec or Pass+Rush combo lines. If a player has no stat props, the
   site's Fantasy Points line is used instead (Underdog's is half-PPR, so + 0.5 x expected receptions).
5. Each site is projected from its own lines only. Sleeper posts anytime-TD lines for far fewer players than
   Underdog; without one, a projection has no touchdown points and runs low (about 1 point). Those are
   marked `Props, no TD line` in `Proj Source` and with `*` on the page.

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
