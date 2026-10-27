"""NBA Jump Shot Tracker.

Pulls shooting-by-distance data from Basketball-Reference, ranks which shots
are most valuable league-wide (points per shot), and builds a personalized
breakdown for each All-NBA player (the 15 players across the three teams).

Usage:
    python main.py                      # latest season with All-NBA teams
    python main.py --season 2025        # 2024-25 season
    python main.py --player "Curry"     # breakdown for any player(s)
    python main.py --csv out/           # also export CSVs
    python main.py --refresh            # ignore the on-disk cache
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from analysis import league_zone_values, player_breakdown
from bbref import FetchError, get_all_nba, get_season_players


def season_label(season: int) -> str:
    return f"{season - 1}-{str(season)[-2:]}"


def print_league(league: list[dict], season: int) -> None:
    print(f"\n=== Most valuable shots league-wide, {season_label(season)} ===")
    print(f"{'Rank':<5}{'Zone':<24}{'Jumper':<8}{'FG%':>7}{'PPS':>7}{'Share':>8}{'Attempts':>10}")
    for i, r in enumerate(league, 1):
        print(f"{i:<5}{r['label']:<24}{'yes' if r['jumper'] else 'no':<8}"
              f"{r['fg_pct']:>7.1%}{r['pps']:>7.3f}{r['share']:>8.1%}{r['attempts']:>10,.0f}")
    jumpers = [r for r in league if r["jumper"]]
    print(f"\nBest jump shot: {jumpers[0]['label']} ({jumpers[0]['pps']:.3f} PPS). "
          f"Worst jump shot: {jumpers[-1]['label']} ({jumpers[-1]['pps']:.3f} PPS).")


def print_player(b: dict, header_suffix: str = "") -> None:
    p = b["player"]
    print(f"\n--- {p['name']} ({p['team']}, {p['pos']}){header_suffix} ---")
    print(f"{p['fga']:.0f} FGA | avg shot distance {p['avg_dist']:.1f} ft | "
          f"jumpers are {b['jumper_share']:.0%} of shots at {b['jumper_pps']:.3f} PPS "
          f"(league {b['league_jumper_pps']:.3f})")
    print(f"  {'Zone':<24}{'Att':>6}{'Share':>7}{'FG%':>7}{'PPS':>7}{'vs Lg':>8}{'Pts+':>8}")
    for z in sorted(b["zones"], key=lambda z: z["points_added"], reverse=True):
        flag = " *" if z["low_sample"] else ""
        print(f"  {z['label']:<24}{z['attempts']:>6.0f}{z['share']:>7.0%}{z['fg_pct']:>7.1%}"
              f"{z['pps']:>7.3f}{z['pps_diff']:>+8.3f}{z['points_added']:>+8.1f}{flag}")

    mv, best, weak = b["most_valuable_zone"], b["best_zone"], b["weakest_zone"]
    print(f"  Most valuable shot : {mv['label']} ({mv['points_added']:+.1f} pts vs. average shooter)")
    print(f"  Best place to score: {best['label']} ({best['pps']:.3f} PPS)")
    if b["best_jumper"]:
        j = b["best_jumper"]
        print(f"  Best jump shot     : {j['label']} ({j['pps']:.3f} PPS, {j['fg_pct']:.1%})")
    print(f"  Weakest zone       : {weak['label']} ({weak['pps_diff']:+.3f} PPS vs. league)")
    print(f"  Total shot value   : {b['total_points_added']:+.1f} pts above an average shooter")


def _rounded(row: dict) -> dict:
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in row.items()}


def write_csvs(out_dir: Path, league: list[dict], breakdowns: list[tuple[dict, str]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "league_zones.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(league[0].keys()))
        w.writeheader()
        w.writerows(_rounded(r) for r in league)

    with open(out_dir / "player_zones.csv", "w", newline="", encoding="utf-8") as f:
        fields = ["player_id", "player", "team", "all_nba", "zone", "label", "jumper",
                  "attempts", "makes", "share", "fg_pct", "pps", "league_pps",
                  "pps_diff", "points_added", "low_sample"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for b, all_nba in breakdowns:
            p = b["player"]
            for z in b["zones"]:
                w.writerow(_rounded({"player_id": p["id"], "player": p["name"], "team": p["team"],
                                     "all_nba": all_nba, **{k: z[k] for k in fields[4:]}}))
    print(f"\nCSV files written to {out_dir.resolve()}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NBA jump shot value tracker (Basketball-Reference data)")
    ap.add_argument("--season", type=int, help="Season end year, e.g. 2026 for 2025-26 "
                    "(default: latest season with All-NBA teams)")
    ap.add_argument("--player", action="append", default=[],
                    help="Also break down any player whose name contains this text (repeatable)")
    ap.add_argument("--min-attempts", type=int, default=25,
                    help="Minimum attempts for a zone to count as a player's best/worst (default 25)")
    ap.add_argument("--csv", type=Path, help="Directory to export CSV results")
    ap.add_argument("--refresh", action="store_true", help="Bypass the on-disk cache")
    args = ap.parse_args(argv)
    use_cache = not args.refresh

    try:
        all_nba = get_all_nba(use_cache)
        season = args.season or max(all_nba)
        players = get_season_players(season, use_cache)
    except FetchError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    league = league_zone_values(players)
    print_league(league, season)

    breakdowns: list[tuple[dict, str]] = []
    selections = all_nba.get(season, [])
    if not selections:
        print(f"\nNo All-NBA teams found for {season_label(season)} (not announced yet?).")
    else:
        print(f"\n=== All-NBA personalized breakdowns, {season_label(season)} ===")
        print("(PPS = points per shot; Pts+ = points added vs. a league-average shooter "
              "on the same attempts; * = low sample)")
        for sel in selections:
            p = players.get(sel["id"])
            if p is None:
                print(f"\n--- {sel['name']}: no shooting data found ---")
                continue
            b = player_breakdown(p, league, args.min_attempts)
            breakdowns.append((b, sel["all_nba_team"]))
            print_player(b, f" - All-NBA {sel['all_nba_team']} team")

        ranked = sorted(breakdowns, key=lambda x: x[0]["total_points_added"], reverse=True)
        print("\n=== All-NBA shot-value leaderboard ===")
        for i, (b, _) in enumerate(ranked, 1):
            print(f"{i:>2}. {b['player']['name']:<28}{b['total_points_added']:>+8.1f} pts   "
                  f"most valuable: {b['most_valuable_zone']['label']}")

    for query in args.player:
        matches = [p for p in players.values() if query.lower() in p["name"].lower()]
        if not matches:
            print(f"\nNo player matching '{query}' in {season_label(season)}.")
        for p in matches:
            b = player_breakdown(p, league, args.min_attempts)
            breakdowns.append((b, ""))
            print_player(b)

    if args.csv:
        write_csvs(args.csv, league, breakdowns)
    return 0


if __name__ == "__main__":
    sys.exit(main())
