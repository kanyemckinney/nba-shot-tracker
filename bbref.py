"""Fetching and parsing Basketball-Reference pages (stdlib only).

Pages are cached on disk and requests are throttled to stay well under
Basketball-Reference's rate limit (~20 requests/minute).
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = "https://www.basketball-reference.com"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
CACHE_TTL_SECONDS = 24 * 60 * 60
MIN_SECONDS_BETWEEN_REQUESTS = 3.5
USER_AGENT = "Mozilla/5.0 (jump-shot-tracker; educational project)"

_last_request_time = 0.0


class FetchError(RuntimeError):
    pass


def fetch(path: str, use_cache: bool = True, retries: int = 3) -> str:
    """Return the HTML for a Basketball-Reference path, using a disk cache."""
    global _last_request_time
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / path.strip("/").replace("/", "_")

    if use_cache and cache_file.exists():
        if time.time() - cache_file.stat().st_mtime < CACHE_TTL_SECONDS:
            return cache_file.read_text(encoding="utf-8")

    url = BASE_URL + path
    last_error: Exception | None = None
    for attempt in range(retries):
        wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.time() - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            cache_file.write_text(html, encoding="utf-8")
            return html
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 404:
                raise FetchError(f"Page not found: {url}") from e
            if e.code == 429:
                retry_after = e.headers.get("Retry-After", "")
                time.sleep(int(retry_after) if retry_after.isdigit() else 60)
                continue
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = e
        time.sleep(2 ** attempt)

    # Fall back to a stale cache entry rather than failing outright.
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    raise FetchError(f"Failed to fetch {url}: {last_error}")


class _TableParser(HTMLParser):
    """Collects the <tbody> rows of a table with the given id.

    Each row becomes {data-stat: cell}, where a cell is a dict with
    'text', 'csk' (precise sort value), 'id' (data-append-csv) and 'hrefs'.
    """

    def __init__(self, table_id: str):
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.rows: list[dict[str, dict]] = []
        self._in_table = False
        self._in_tbody = False
        self._row: dict[str, dict] | None = None
        self._cell: dict | None = None
        self._cell_key: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and a.get("id") == self.table_id:
            self._in_table = True
        elif not self._in_table:
            return
        elif tag == "tbody":
            self._in_tbody = True
        elif tag == "tr" and self._in_tbody:
            is_header = "thead" in (a.get("class") or "")
            self._row = None if is_header else {}
        elif tag in ("td", "th") and self._row is not None:
            self._cell_key = a.get("data-stat")
            self._cell = {
                "text": "",
                "csk": a.get("csk"),
                "id": a.get("data-append-csv"),
                "hrefs": [],
            }
        elif tag == "a" and self._cell is not None and a.get("href"):
            self._cell["hrefs"].append(a["href"])

    def handle_endtag(self, tag):
        if not self._in_table:
            return
        if tag in ("td", "th") and self._cell is not None:
            if self._row is not None and self._cell_key:
                self._cell["text"] = self._cell["text"].strip()
                self._row[self._cell_key] = self._cell
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "tbody":
            self._in_tbody = False
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data


def parse_table(html: str, table_id: str) -> list[dict[str, dict]]:
    # Some Basketball-Reference tables are shipped inside HTML comments.
    html = html.replace("<!--", "").replace("-->", "")
    parser = _TableParser(table_id)
    parser.feed(html)
    return parser.rows


def _num(cell: dict | None) -> float:
    if not cell:
        return 0.0
    for raw in (cell.get("csk"), cell.get("text")):
        if raw:
            try:
                return float(raw)
            except ValueError:
                continue
    return 0.0


def _player_id_from_href(href: str) -> str | None:
    # /players/j/jokicni01.html -> jokicni01
    if href.startswith("/players/") and href.endswith(".html"):
        return href.rsplit("/", 1)[-1][:-5]
    return None


def _first_row_per_player(rows: list[dict]) -> dict[str, dict]:
    """Traded players have a combined row (e.g. '2TM') listed first; keep it."""
    out: dict[str, dict] = {}
    for row in rows:
        name_cell = row.get("name_display")
        if not name_cell or not name_cell.get("id"):
            continue
        out.setdefault(name_cell["id"], row)
    return out


SHOOTING_FIELDS = [
    "fg_pct", "avg_dist",
    "pct_fga_00_03", "pct_fga_03_10", "pct_fga_10_16", "pct_fga_16_xx", "pct_fga_fg3a",
    "fg_pct_00_03", "fg_pct_03_10", "fg_pct_10_16", "fg_pct_16_xx", "fg_pct_fg3a",
    "pct_fg3a_corner3", "fg_pct_corner3", "fg3a_heave", "fg3_heave",
]
TOTALS_FIELDS = ["games", "mp", "fg", "fga", "fg3", "fg3a", "fg2", "fg2a", "ft", "fta", "pts"]


def get_season_players(season: int, use_cache: bool = True) -> dict[str, dict]:
    """Merge the shooting-by-distance and totals tables for a season.

    `season` is the year the season ends (2026 -> 2025-26).
    Returns {player_id: {name, team, pos, <numeric fields>...}}.
    """
    shooting_html = fetch(f"/leagues/NBA_{season}_shooting.html", use_cache)
    totals_html = fetch(f"/leagues/NBA_{season}_totals.html", use_cache)

    shooting = _first_row_per_player(parse_table(shooting_html, "shooting"))
    totals = _first_row_per_player(parse_table(totals_html, "totals_stats"))
    if not shooting or not totals:
        raise FetchError(f"Could not parse shooting/totals tables for {season}")

    players: dict[str, dict] = {}
    for pid, srow in shooting.items():
        trow = totals.get(pid)
        if trow is None:
            continue
        p = {
            "id": pid,
            "name": srow["name_display"]["text"],
            "team": srow.get("team_name_abbr", {}).get("text", ""),
            "pos": srow.get("pos", {}).get("text", ""),
        }
        for f in SHOOTING_FIELDS:
            p[f] = _num(srow.get(f))
        for f in TOTALS_FIELDS:
            p[f] = _num(trow.get(f))
        players[pid] = p
    return players


def get_all_nba(use_cache: bool = True) -> dict[int, list[dict]]:
    """Return {season_end_year: [{id, name, team: '1st'|'2nd'|'3rd'}...]} for the NBA."""
    html = fetch("/awards/all_league.html", use_cache)
    result: dict[int, list[dict]] = {}
    for row in parse_table(html, "awards_all_league"):
        if row.get("lg_id", {}).get("text") != "NBA":
            continue
        season_text = row.get("season", {}).get("text", "")  # e.g. "2025-26"
        try:
            start_year = int(season_text.split("-")[0])
        except ValueError:
            continue
        end_year = start_year + 1
        team = row.get("all_team", {}).get("text", "")
        for key, cell in row.items():
            if not key.isdigit():
                continue
            for href in cell["hrefs"]:
                pid = _player_id_from_href(href)
                if pid:
                    name = cell["text"].rsplit(" ", 1)[0] if cell["text"] else pid
                    result.setdefault(end_year, []).append(
                        {"id": pid, "name": name, "all_nba_team": team}
                    )
    return result
