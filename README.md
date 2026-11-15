# NFL PPR Rankings (with odds)

`ppr_rankings.py` pulls every live NFL prop from Underdog Fantasy and builds a spreadsheet of
players ranked by projected **full-PPR** fantasy points, with the line and over/under odds for each stat.

No installs needed (Python 3 standard library only):

```
python3 ppr_rankings.py                  # -> nfl_ppr_rankings.xlsx/.html/.csv + nfl_ppr_rankings_all_props.csv
python3 ppr_rankings.py --open           # same, then opens the interactive page in your browser
python3 ppr_rankings.py -o week11.xlsx   # custom file name
python3 ppr_rankings.py --no-csv         # xlsx only
```

**Interactive page** (`nfl_ppr_rankings.html`): a single offline file, no server needed. You can
- click any column header to sort by it (projected PPR, pass yds, TD %, any line or odds); click again to reverse
- filter by position (multi-select), team, game, or player name
- group by position, team, or game (collapsible, with group totals/averages); sorting applies inside each group
- show or hide the projection and lines/odds column sets

Odds columns sort by implied probability, so "descending" puts the most likely outcome first.
The page template lives in `templates/rankings.html`.

**Sheets**
- **PPR Rankings**: overall rank, positional rank (QB1, RB3, ...), team/opponent, kickoff, projected PPR,
  expected stat values, anytime-TD probability, and line + over/under American odds for pass yds, pass TDs,
  INTs, rush yds, receptions, rec yds, anytime TD, and Underdog's own Fantasy Points line.
- **All NFL Props**: every NFL prop Underdog has posted (including quarter/half lines, defense, kickers)
  with both sides' odds and the no-vig over probability.

**How projections work**
1. Each line's over/under odds are converted to a no-vig probability of the over.
2. Count stats (receptions, TDs, pass TDs, INTs, fumbles) use the Poisson mean that matches that probability;
   yardage stats shift the line by the odds-implied z-score.
3. Scoring: 0.04/pass yd, 4/pass TD, -2/INT, 0.1/rush or rec yd, 1/reception, 6/rush-rec TD, -2/fumble lost.
4. Missing rush yards are derived from Rush+Rec or Pass+Rush combo lines. If a player has no stat props,
   Underdog's Fantasy Points line (half-PPR) + 0.5 x expected receptions is used instead (see `Proj Source`).

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
