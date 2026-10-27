# NBA Jump Shot Tracker

Previous project that was lost and reuploaded.

Ranks which shots are most valuable league-wide (points per shot by zone) and
builds a personalized shot-value breakdown for every All-NBA player, using data
from [Basketball-Reference](https://www.basketball-reference.com).

Requires Python 3.10+; no third-party packages.

## Usage

```bash
python main.py                      # latest season with All-NBA teams
python main.py --season 2025        # 2024-25 season
python main.py --player "Curry"     # break down any player(s)
python main.py --csv out/           # export league and player CSVs
python main.py --refresh            # ignore the local cache
python -m unittest test_tracker     # run tests (offline)
```

## How it works

- **Zones**: at rim (0-3 ft), short (3-10 ft), mid-range (10-16 ft), long two
  (16 ft-3P), corner three, above-break three. Jump shots are 10 ft and beyond.
- **PPS** (points per shot) = FG% x shot value. League PPS is attempt-weighted.
- **Points added** = (player PPS - league PPS) x attempts: points produced above
  a league-average shooter taking the same shots.
- Zone attempts are reconstructed from Basketball-Reference's shot-distribution
  percentages and season totals; half-court heaves are excluded from threes.
- Zones under `--min-attempts` (default 25) are flagged as low sample and are
  not used to pick a player's best/worst zone.

## Data and rate limits

Pages are cached in `.cache/` for 24 hours and requests are throttled
(~3.5 s apart) to respect Basketball-Reference's rate limit of about 20 requests
per minute. The cache is git-ignored: data belongs to Sports Reference and is
subject to their [terms of use](https://www.sports-reference.com/termsofuse.html).
