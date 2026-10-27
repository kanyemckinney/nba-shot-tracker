"""Offline tests: python -m unittest test_tracker"""

import unittest

from analysis import league_zone_values, player_breakdown, zone_counts
from bbref import _first_row_per_player, parse_table


def make_player(pid="p1", **overrides):
    p = {
        "id": pid, "name": "Test Player", "team": "TST", "pos": "G", "avg_dist": 15.0,
        "fga": 1000.0, "fg3a": 400.0, "fg3": 150.0,
        "pct_fga_00_03": 0.2, "pct_fga_03_10": 0.2, "pct_fga_10_16": 0.1, "pct_fga_16_xx": 0.1,
        "fg_pct_00_03": 0.7, "fg_pct_03_10": 0.45, "fg_pct_10_16": 0.45, "fg_pct_16_xx": 0.4,
        "pct_fg3a_corner3": 0.25, "fg_pct_corner3": 0.4, "fg3a_heave": 0.0, "fg3_heave": 0.0,
    }
    p.update(overrides)
    return p


class AnalysisTests(unittest.TestCase):
    def test_zone_counts_reconstruct_totals(self):
        c = zone_counts(make_player())
        self.assertAlmostEqual(sum(a for a, _ in c.values()), 1000.0)
        self.assertAlmostEqual(c["corner3"][0], 100.0)
        self.assertAlmostEqual(c["ab3"][0], 300.0)
        self.assertAlmostEqual(c["corner3"][1] + c["ab3"][1], 150.0)

    def test_heaves_removed_from_above_break(self):
        c = zone_counts(make_player(fg3a_heave=10.0, fg3_heave=1.0))
        self.assertAlmostEqual(c["ab3"][0], 290.0)
        self.assertAlmostEqual(c["ab3"][1], 109.0)

    def test_zero_attempts_is_safe(self):
        p = make_player(fga=0.0, fg3a=0.0, fg3=0.0)
        league = league_zone_values({"a": make_player("a"), "z": p})
        b = player_breakdown(p, league)
        self.assertEqual(b["total_points_added"], 0.0)

    def test_average_player_adds_nothing(self):
        p = make_player()
        league = league_zone_values({"p1": p})
        b = player_breakdown(p, league)
        self.assertAlmostEqual(b["total_points_added"], 0.0, places=6)
        self.assertEqual(league[0]["zone"], "rim")

    def test_better_shooter_adds_value(self):
        avg, good = make_player("a"), make_player("g", fg_pct_10_16=0.6)
        league = league_zone_values({"a": avg, "g": good})
        b = player_breakdown(good, league)
        self.assertGreater(b["total_points_added"], 0)
        self.assertEqual(b["most_valuable_zone"]["zone"], "mid")
        self.assertEqual(b["best_jumper"]["zone"], "mid")


class ParserTests(unittest.TestCase):
    HTML = """
    <!-- <table id="shooting"><tbody>
      <tr><td data-stat="name_display" data-append-csv="hardeja01"><a href="/players/h/hardeja01.html">James Harden</a></td>
          <td data-stat="team_name_abbr">2TM</td><td data-stat="fg_pct" csk="0.4123">.412</td></tr>
      <tr class="thead"><td data-stat="name_display">Player</td></tr>
      <tr><td data-stat="name_display" data-append-csv="hardeja01">James Harden</td>
          <td data-stat="team_name_abbr">LAC</td></tr>
    </tbody></table> -->
    """

    def test_parses_commented_table_and_keeps_combined_row(self):
        rows = parse_table(self.HTML, "shooting")
        self.assertEqual(len(rows), 2)
        players = _first_row_per_player(rows)
        self.assertEqual(players["hardeja01"]["team_name_abbr"]["text"], "2TM")
        self.assertEqual(players["hardeja01"]["fg_pct"]["csk"], "0.4123")


if __name__ == "__main__":
    unittest.main()
