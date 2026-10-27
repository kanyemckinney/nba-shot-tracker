"""Shot-value analysis: points per shot by zone, league baselines, player breakdowns."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    key: str
    label: str
    points: int
    is_jumper: bool


ZONES = [
    Zone("rim", "At rim (0-3 ft)", 2, False),
    # 3-10 ft is mostly floaters, hooks and post moves, so it isn't treated as a jumper.
    Zone("short", "Short (3-10 ft)", 2, False),
    Zone("mid", "Mid-range (10-16 ft)", 2, True),
    Zone("long2", "Long two (16 ft-3P)", 2, True),
    Zone("corner3", "Corner three", 3, True),
    Zone("ab3", "Above-break three", 3, True),
]
ZONE_BY_KEY = {z.key: z for z in ZONES}

_TWO_PT_FIELDS = {
    "rim": ("pct_fga_00_03", "fg_pct_00_03"),
    "short": ("pct_fga_03_10", "fg_pct_03_10"),
    "mid": ("pct_fga_10_16", "fg_pct_10_16"),
    "long2": ("pct_fga_16_xx", "fg_pct_16_xx"),
}


def zone_counts(p: dict) -> dict[str, tuple[float, float]]:
    """Return {zone_key: (attempts, makes)} for a player.

    Basketball-Reference publishes zone shares/percentages; combining them with
    season totals reconstructs attempt and make counts. Heaves are removed from
    above-the-break threes so end-of-quarter prayers don't distort the numbers.
    """
    fga = p.get("fga", 0.0)
    out: dict[str, tuple[float, float]] = {}
    for key, (share_f, pct_f) in _TWO_PT_FIELDS.items():
        att = fga * p.get(share_f, 0.0)
        out[key] = (att, att * p.get(pct_f, 0.0))

    fg3a, fg3 = p.get("fg3a", 0.0), p.get("fg3", 0.0)
    c3a = fg3a * p.get("pct_fg3a_corner3", 0.0)
    c3m = c3a * p.get("fg_pct_corner3", 0.0)
    ab3a = max(fg3a - c3a - p.get("fg3a_heave", 0.0), 0.0)
    ab3m = max(fg3 - c3m - p.get("fg3_heave", 0.0), 0.0)
    out["corner3"] = (c3a, c3m)
    out["ab3"] = (ab3a, min(ab3m, ab3a))
    return out


def pps(att: float, made: float, points: int) -> float:
    return points * made / att if att > 0 else 0.0


def league_zone_values(players: dict[str, dict]) -> list[dict]:
    """Attempt-weighted league-wide value of each zone, sorted best first."""
    totals = {z.key: [0.0, 0.0] for z in ZONES}
    for p in players.values():
        for key, (att, made) in zone_counts(p).items():
            totals[key][0] += att
            totals[key][1] += made

    all_att = sum(a for a, _ in totals.values()) or 1.0
    rows = []
    for z in ZONES:
        att, made = totals[z.key]
        rows.append({
            "zone": z.key,
            "label": z.label,
            "jumper": z.is_jumper,
            "attempts": att,
            "fg_pct": made / att if att else 0.0,
            "pps": pps(att, made, z.points),
            "share": att / all_att,
        })
    rows.sort(key=lambda r: r["pps"], reverse=True)
    return rows


def player_breakdown(p: dict, league: list[dict], min_attempts: int = 25) -> dict:
    """Per-zone efficiency vs. league average and value added for one player.

    points_added = (player PPS - league PPS) * attempts: how many points the
    player produced in that zone above an average shooter taking the same shots.
    Zones with fewer than `min_attempts` are reported but flagged as low sample.
    """
    league_pps = {r["zone"]: r["pps"] for r in league}
    counts = zone_counts(p)
    fga = sum(a for a, _ in counts.values()) or 1.0

    zones = []
    for z in ZONES:
        att, made = counts[z.key]
        player_pps = pps(att, made, z.points)
        zones.append({
            "zone": z.key,
            "label": z.label,
            "jumper": z.is_jumper,
            "attempts": att,
            "makes": made,
            "share": att / fga,
            "fg_pct": made / att if att else 0.0,
            "pps": player_pps,
            "league_pps": league_pps[z.key],
            "pps_diff": player_pps - league_pps[z.key] if att else 0.0,
            "points_added": (player_pps - league_pps[z.key]) * att if att else 0.0,
            "low_sample": att < min_attempts,
        })

    qualified = [z for z in zones if not z["low_sample"]] or zones
    jumpers = [z for z in qualified if z["jumper"]]

    jump_att = sum(z["attempts"] for z in zones if z["jumper"])
    jump_pts = sum(z["makes"] * ZONE_BY_KEY[z["zone"]].points for z in zones if z["jumper"])
    lg_jump_att = sum(r["attempts"] for r in league if r["jumper"])
    lg_jump_pts = sum(r["pps"] * r["attempts"] for r in league if r["jumper"])

    return {
        "player": p,
        "zones": zones,
        "best_zone": max(qualified, key=lambda z: z["pps"]),
        "most_valuable_zone": max(qualified, key=lambda z: z["points_added"]),
        "best_jumper": max(jumpers, key=lambda z: z["pps"]) if jumpers else None,
        "weakest_zone": min(qualified, key=lambda z: z["pps_diff"]),
        "jumper_share": jump_att / fga,
        "jumper_pps": jump_pts / jump_att if jump_att else 0.0,
        "league_jumper_pps": lg_jump_pts / lg_jump_att if lg_jump_att else 0.0,
        "total_points_added": sum(z["points_added"] for z in zones),
    }
