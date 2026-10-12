"""
Builds dark_mode.svg for the GitHub profile README.

Runs daily from .github/workflows/build.yaml. It:
  - calculates "Uptime" from the date of birth
  - fetches GitHub stats (repos, stars, commits, followers, lines of code)

Token: uses ACCESS_TOKEN (a personal access token, includes private repos)
if set, otherwise GITHUB_TOKEN (public data only).

Run locally without a token:  python today.py --offline
"""

import datetime as dt
import html
import json
import os
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Profile details — edit these to change what the card shows
# ---------------------------------------------------------------------------
USER = "Tanay-42"
TITLE = "Tanay Verma"
BIRTHDAY = dt.date(2004, 2, 4)

ABOUT = [
    ("OS", "Windows 11, Android 15"),
    ("Uptime", None),  # filled in automatically
    ("Host", "Learning & Building"),
    ("Role", "AI Engineer"),
    ("IDE", "VS Code"),
    ("Currently", "Exploring LLMs & agents"),
    ("Ask Me About", "Python, C++, RAG, LLMs"),
    None,  # blank line
    ("Languages.Programming", "C++, Python"),
    ("Languages.Real", "English, Hindi, Marathi"),
]

CONTACT = [
    ("Email.Personal", "tanayverma42004@gmail.com"),
    ("LinkedIn", "tanay-verma-41482b259"),
    ("GitHub", "Tanay-42"),
]

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent
ART_FILES = {"dark_mode.svg": ROOT / "ascii_art.txt"}
CACHE_FILE = ROOT / "cache" / "loc_cache.json"

PANEL_WIDTH = 58      # characters in each info line
FONT_SIZE = 16
CHAR_W = 9.63         # width of one monospace character at FONT_SIZE
LINE_H = 20
PAD = 15

THEMES = {
    "dark_mode.svg": {
        "bg": "#0d1117", "border": "#30363d", "art": "#c9d1d9", "key": "#ffa657",
        "value": "#a5d6ff", "cc": "#616e7f", "add": "#3fb950", "del": "#f85149",
    },
}

API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Uptime
# ---------------------------------------------------------------------------
def uptime(born: dt.date, today: dt.date) -> str:
    years = today.year - born.year
    months = today.month - born.month
    days = today.day - born.day
    if days < 0:
        months -= 1
        prev_month_end = today.replace(day=1) - dt.timedelta(days=1)
        days += prev_month_end.day
    if months < 0:
        years -= 1
        months += 12

    def unit(n, word):
        return f"{n} {word}{'' if n == 1 else 's'}"

    text = f"{unit(years, 'year')}, {unit(months, 'month')}, {unit(days, 'day')}"
    if (today.month, today.day) == (born.month, born.day):
        text += " 🎂"
    return text


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------
class GitHub:
    def __init__(self, token: str):
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def graphql(self, query: str, variables: dict) -> dict:
        r = self.s.post(f"{API}/graphql", json={"query": query, "variables": variables}, timeout=30)
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"GraphQL error: {body['errors']}")
        return body["data"]

    def contributor_stats(self, full_name: str):
        """Weekly additions/deletions per author. GitHub returns 202 while it builds the stats."""
        for attempt in range(8):
            r = self.s.get(f"{API}/repos/{full_name}/stats/contributors", timeout=30)
            if r.status_code == 200:
                return r.json() or []
            if r.status_code == 204:          # empty repository
                return []
            if r.status_code == 202:
                time.sleep(min(2 ** attempt, 20))
                continue
            print(f"  skip {full_name}: HTTP {r.status_code}", file=sys.stderr)
            return None
        print(f"  skip {full_name}: stats still being computed", file=sys.stderr)
        return None


REPO_QUERY = """
query($login: String!, $aff: [RepositoryAffiliation], $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: $aff) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { nameWithOwner stargazerCount isFork defaultBranchRef { target { ... on Commit { oid } } } }
    }
  }
}"""

USER_QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection { contributionYears }
  }
}"""

YEAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
    }
  }
}"""


def all_repos(gh: GitHub, affiliations):
    repos, cursor, total = [], None, 0
    while True:
        data = gh.graphql(REPO_QUERY, {"login": USER, "aff": affiliations, "cursor": cursor})
        page = data["user"]["repositories"]
        total = page["totalCount"]
        repos.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return total, repos
        cursor = page["pageInfo"]["endCursor"]


def lines_of_code(gh: GitHub, repos) -> tuple:
    """Sum additions/deletions by USER across repos. Cached by each repo's latest commit."""
    cache = {}
    if CACHE_FILE.exists():
        cache = json.loads(CACHE_FILE.read_text())

    added = deleted = 0
    new_cache = {}
    for repo in repos:
        name = repo["nameWithOwner"]
        ref = repo.get("defaultBranchRef") or {}
        head = (ref.get("target") or {}).get("oid")
        if head is None:
            continue
        old = cache.get(name)
        if old and old["head"] == head:
            entry = old
        else:
            stats = gh.contributor_stats(name)
            if stats is None:
                if old:
                    new_cache[name] = old
                    added += old["added"]
                    deleted += old["deleted"]
                continue
            a = d = 0
            for person in stats:
                if (person.get("author") or {}).get("login", "").lower() == USER.lower():
                    a = sum(w["a"] for w in person["weeks"])
                    d = sum(w["d"] for w in person["weeks"])
            entry = {"head": head, "added": a, "deleted": d}
        new_cache[name] = entry
        added += entry["added"]
        deleted += entry["deleted"]

    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(new_cache, indent=2, sort_keys=True) + "\n")
    return added, deleted


def fetch_stats(token: str) -> dict:
    gh = GitHub(token)

    owned_count, owned = all_repos(gh, ["OWNER"])
    all_count, every = all_repos(gh, ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"])
    stars = sum(r["stargazerCount"] for r in owned)

    info = gh.graphql(USER_QUERY, {"login": USER})["user"]
    followers = info["followers"]["totalCount"]

    commits = 0
    for year in info["contributionsCollection"]["contributionYears"]:
        data = gh.graphql(YEAR_QUERY, {
            "login": USER,
            "from": f"{year}-01-01T00:00:00Z",
            "to": f"{year}-12-31T23:59:59Z",
        })["user"]["contributionsCollection"]
        commits += data["totalCommitContributions"]

    added, deleted = lines_of_code(gh, [r for r in every if not r["isFork"]])

    return {
        "repos": owned_count,
        "contributed": all_count,
        "stars": stars,
        "commits": commits,
        "followers": followers,
        "loc_added": added,
        "loc_deleted": deleted,
    }


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------
def esc(s: str) -> str:
    return html.escape(s, quote=False)


def kv_line(key: str, value: str, width: int = PANEL_WIDTH):
    """'. Key: ....... value' padded with dots to the full panel width."""
    left = f"{key}:"
    dots = width - 2 - len(left) - 2 - len(value)
    dots = max(dots, 1)
    return [("cc", ". "), ("key", left), ("cc", " " + "." * dots + " "), ("value", value)]


def header_line(text: str, width: int = PANEL_WIDTH):
    return [("plain", text), ("cc", " " + "—" * (width - len(text) - 1))]


def section_line(text: str, width: int = PANEL_WIDTH):
    label = f"- {text} "
    return [("plain", label), ("cc", "—" * (width - len(label)))]


def stat_pair(k1, v1, k2, v2, width: int = PANEL_WIDTH):
    """Two key/values on one line split by ' | ', like the reference card."""
    right_w = 20
    left = kv_line(k1, v1, width - right_w - 3)
    right_key = f"{k2}:"
    dots = max(right_w - len(right_key) - 2 - len(v2), 1)
    right = [("key", right_key), ("cc", " " + "." * dots + " "), ("value", v2)]
    return left + [("cc", " | ")] + right


def build_panel(stats: dict, today: dt.date):
    lines = [header_line(TITLE)]
    for item in ABOUT:
        if item is None:
            lines.append([("cc", ".")])
            continue
        key, value = item
        if key == "Uptime":
            value = uptime(BIRTHDAY, today)
        lines.append(kv_line(key, value))

    lines.append([("cc", ".")])
    lines.append(section_line("Contact"))
    for key, value in CONTACT:
        lines.append(kv_line(key, value))

    lines.append([("cc", ".")])
    lines.append(section_line("GitHub Stats"))

    def num(n):
        return "—" if n is None else f"{n:,}"

    contributed = stats.get("contributed")
    repos_val = num(stats.get("repos"))
    if contributed is not None:
        repos_val += f" {{Contributed: {contributed:,}}}"
    lines.append(stat_pair("Repos", repos_val, "Stars", num(stats.get("stars"))))
    lines.append(stat_pair("Commits", num(stats.get("commits")), "Followers", num(stats.get("followers"))))

    added, deleted = stats.get("loc_added"), stats.get("loc_deleted")
    if added is None:
        lines.append(kv_line("Lines of Code", "—"))
    else:
        total = f"{added - deleted:,}"
        a, d = f"{added:,}++", f"{deleted:,}--"
        tail_len = len(total) + 2 + len(a) + 2 + len(d) + 1   # "total (a, d)"
        key = "Lines of Code:"
        dots = max(PANEL_WIDTH - 2 - len(key) - 2 - tail_len, 1)
        lines.append([
            ("cc", ". "), ("key", key), ("cc", " " + "." * dots + " "),
            ("value", total), ("cc", " ("), ("add", a), ("cc", ", "), ("del", d), ("cc", ")"),
        ])
    return lines


def render_svg(theme: dict, art: list, panel: list) -> str:
    art_cols = max(len(l) for l in art)
    panel_x = PAD + art_cols * CHAR_W + 25
    width = round(panel_x + PANEL_WIDTH * CHAR_W + PAD + 10)
    rows = max(len(art), len(panel))
    height = PAD * 2 + rows * LINE_H + 10

    # vertically centre the shorter column
    # (whole rows only, so art and panel lines sit on one grid and slices never cut a character)
    art_y = PAD + 20 + (rows - len(art)) // 2 * LINE_H
    panel_y = PAD + 20 + (rows - len(panel)) // 2 * LINE_H

    t = theme
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,\'Courier New\',monospace" '
        f'width="{width}px" height="{height}px" font-size="{FONT_SIZE}px">',
        "<style>",
        "@font-face { src: local('Consolas'), local('Consolas Bold'); font-family: 'ConsolasFallback'; "
        "font-display: swap; -webkit-size-adjust: 109%; size-adjust: 109%; }",
        f".key {{fill: {t['key']};}}",
        f".value {{fill: {t['value']};}}",
        f".add {{fill: {t['add']};}}",
        f".del {{fill: {t['del']};}}",
        f".cc {{fill: {t['cc']};}}",
        f"text, tspan {{white-space: pre;}}",
        "</style>",
        f'<rect width="{width}px" height="{height}px" fill="{t["bg"]}" stroke="{t["border"]}" rx="15"/>',
        f'<text x="{PAD}" y="{art_y}" fill="{t["art"]}" class="ascii">',
    ]
    for i, line in enumerate(art):
        out.append(f'<tspan x="{PAD}" y="{art_y + i * LINE_H}">{esc(line)}</tspan>')
    out.append("</text>")

    out.append(f'<text x="{panel_x:.1f}" y="{panel_y}" fill="{t["art"]}">')
    for i, segs in enumerate(panel):
        y = panel_y + i * LINE_H
        parts = []
        for cls, text in segs:
            if cls == "plain":
                parts.append(esc(text))
            else:
                parts.append(f'<tspan class="{cls}">{esc(text)}</tspan>')
        out.append(f'<tspan x="{panel_x:.1f}" y="{y}">{"".join(parts)}</tspan>')
    out.append("</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n", {"width": width, "height": height, "panel_y": panel_y}


# ---------------------------------------------------------------------------
# Clickable rows: the card is cut into horizontal slices, and the slices for
# these rows are wrapped in links in README.md (GitHub can't link inside an image).
# ---------------------------------------------------------------------------
LINKS = {
    "Email.Personal": "mailto:tanayverma42004@gmail.com",
    "LinkedIn": "https://www.linkedin.com/in/tanay-verma-41482b259/",
    "GitHub": "https://github.com/Tanay-42",
}
SLICE_DIR = ROOT / "cards"
ROW_ASCENT = 15   # distance from a text baseline up to the top of its row


def slice_svg(svg: str, geo: dict, panel: list):
    """Return [(svg_text, link_or_None), ...] covering the whole card top to bottom."""
    row_of = {}
    for i, segs in enumerate(panel):
        for cls, text in segs:
            if cls == "key":
                row_of[text.rstrip(":")] = i

    cuts = []
    for key, url in LINKS.items():
        top = geo["panel_y"] + row_of[key] * LINE_H - ROW_ASCENT
        cuts.append((top, top + LINE_H, url))
    cuts.sort()

    pieces, prev = [], 0
    for top, bottom, url in cuts:
        if top > prev:
            pieces.append((prev, top, None))
        pieces.append((top, bottom, url))
        prev = bottom
    pieces.append((prev, geo["height"], None))

    head = f'width="{geo["width"]}px" height="{geo["height"]}px" font-size'
    assert head in svg
    out = []
    for top, bottom, url in pieces:
        h = bottom - top
        part = svg.replace(
            head,
            f'viewBox="0 {top} {geo["width"]} {h}" width="{geo["width"]}px" height="{h}px" font-size',
            1,
        )
        out.append((part, url))
    return out


def write_readme(names_and_links):
    """README made of the slices stacked with no whitespace between them."""
    parts = []
    for name, url in names_and_links:
        img = f'<img src="cards/{name}" alt="">'
        parts.append(f'<a href="{url}">{img}</a>' if url else img)
    (ROOT / "README.md").write_text(
        "<!-- Generated by today.py. Edit LINKS in today.py instead of this file. -->\n"
        "<p>" + "".join(parts) + "</p>\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
def main():
    offline = "--offline" in sys.argv
    token = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")

    if offline or not token:
        if not offline:
            print("No ACCESS_TOKEN or GITHUB_TOKEN set — writing card without stats.", file=sys.stderr)
        stats = {}
    else:
        stats = fetch_stats(token)
        print(json.dumps(stats, indent=2))

    ist_today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()
    panel = build_panel(stats, ist_today)

    for filename, theme in THEMES.items():
        art = ART_FILES[filename].read_text(encoding="utf-8").rstrip("\n").split("\n")
        svg, geo = render_svg(theme, art, panel)
        (ROOT / filename).write_text(svg, encoding="utf-8")
        print(f"wrote {filename}")

    # slices of the dark card for the README
    SLICE_DIR.mkdir(exist_ok=True)
    for old in SLICE_DIR.glob("part_*.svg"):
        old.unlink()
    names = []
    for n, (part, url) in enumerate(slice_svg(svg, geo, panel), start=1):
        name = f"part_{n}.svg"
        (SLICE_DIR / name).write_text(part, encoding="utf-8")
        names.append((name, url))
    write_readme(names)
    print(f"wrote {len(names)} slices and README.md")


if __name__ == "__main__":
    main()
