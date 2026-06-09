#!/usr/bin/env python3
"""
update_maze.py — Cat Heist game engine
Triggered by GitHub Actions on every new issue.

Workflow
--------
1. Read issue title to extract direction (UP / DOWN / LEFT / RIGHT)
2. Load game_state.json
3. Check rate limit for the issuer (15-min cooldown per account)
4. Attempt the move — validate against walls
5. Check win condition
6. Update game_state.json
7. Regenerate README.md
8. Post a comment on the issue via GitHub API
9. Close the issue

Environment variables (set by GitHub Actions)
----------------------------------------------
  ISSUE_NUMBER      : int
  ISSUE_AUTHOR      : str  (GitHub username of person who opened the issue)
  ISSUE_TITLE       : str  (raw issue title)
  GITHUB_TOKEN      : str  (automatically available in Actions)
  GITHUB_REPOSITORY : str  e.g. "chilli-garlic-momo/chilli-garlic-momo"

Usage (Actions)
---------------
  python3 scripts/update_maze.py

Usage (local testing)
---------------------
  ISSUE_NUMBER=1 ISSUE_AUTHOR=testuser ISSUE_TITLE="Move: UP" \
  GITHUB_TOKEN=ghp_xxx GITHUB_REPOSITORY=chilli-garlic-momo/chilli-garlic-momo \
  python3 scripts/update_maze.py
"""

import json
import os
import sys
import random
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT   = Path(__file__).parent.parent
STATE_FILE  = REPO_ROOT / "game_state.json"
README_FILE = REPO_ROOT / "README.md"
ASSETS_BASE = "assets"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COOLDOWN_MINUTES = 15
MAZE_SIZE        = 11
WALL             = 1
PATH             = 0
REPO_OWNER       = "chilli-garlic-momo"

CAT_CYCLE = ["white", "orange", "black", "siamese", "tuxedo", "brown"]

CAT_NAMES = [
    "Mochi", "Soot", "Nori", "Boba", "Chai", "Miso",
    "Tofu", "Pepper", "Gizmo", "Binx", "Pebble", "Fig",
    "Wren", "Cleo", "Salem", "Jinx", "Pixel", "Remy",
    "Mango", "Rue", "Mittens", "Dumpling", "Pretzel", "Latte",
    "Sesame", "Waffle", "Biscuit", "Pudding", "Noodle", "Maple",
]

DIRECTION_MAP = {
    "UP":    (-1,  0),
    "DOWN":  ( 1,  0),
    "LEFT":  ( 0, -1),
    "RIGHT": ( 0,  1),
}

MOVE_PREFIX  = "Move:"
RESET_PREFIX = "[RESET]"

# ---------------------------------------------------------------------------
# Maze generation (inline — keeps this script self-contained)
# ---------------------------------------------------------------------------

def generate_maze(seed=None):
    """Recursive backtracking. Returns (grid, player_pos, exit_pos)."""
    rng  = random.Random(seed)
    size = MAZE_SIZE
    grid = [[WALL] * size for _ in range(size)]

    def carve(sr, sc):
        stack = [(sr, sc)]
        grid[sr][sc] = PATH
        while stack:
            r, c = stack[-1]
            neighbours = []
            for dr, dc in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                nr, nc = r + dr, c + dc
                if 1 <= nr < size - 1 and 1 <= nc < size - 1 and grid[nr][nc] == WALL:
                    neighbours.append((nr, nc, dr, dc))
            if neighbours:
                nr, nc, dr, dc = rng.choice(neighbours)
                grid[r + dr // 2][c + dc // 2] = PATH
                grid[nr][nc] = PATH
                stack.append((nr, nc))
            else:
                stack.pop()

    carve(1, 1)

    for i in range(size):
        grid[0][i] = grid[size - 1][i] = WALL
        grid[i][0] = grid[i][size - 1] = WALL

    grid[1][1] = grid[size - 2][size - 2] = PATH
    return grid, [1, 1], [size - 2, size - 2]


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def gh_api(method: str, path: str, body: dict = None) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    url   = f"https://api.github.com{path}"
    data  = json.dumps(body).encode() if body else None
    req   = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization":        f"Bearer {token}",
            "Accept":               "application/vnd.github+json",
            "Content-Type":         "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"GitHub API error {e.code}: {e.read().decode()}", file=sys.stderr)
        return {}


def post_comment(issue_number: int, body: str):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    gh_api("POST", f"/repos/{repo}/issues/{issue_number}/comments", {"body": body})


def close_issue(issue_number: int):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    gh_api("PATCH", f"/repos/{repo}/issues/{issue_number}",
           {"state": "closed", "state_reason": "completed"})


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_on_cooldown(state: dict, author: str) -> tuple:
    """Returns (on_cooldown, minutes_remaining)."""
    last = state.get("last_movers", {}).get(author)
    if not last:
        return False, 0
    elapsed  = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    cooldown = timedelta(minutes=COOLDOWN_MINUTES)
    if elapsed < cooldown:
        remaining = int((cooldown - elapsed).total_seconds() // 60) + 1
        return True, remaining
    return False, 0


def pick_cat_name(maze_number: int, used_names: list) -> str:
    pool = [n for n in CAT_NAMES if n not in used_names] or CAT_NAMES[:]
    return pool[(maze_number - 1) % len(pool)]


def init_new_maze(state: dict) -> dict:
    """Generate a new maze and update state. Returns updated state."""
    maze_number = state.get("maze_number", 0) + 1
    seed        = random.randint(0, 2 ** 31)
    grid, player_pos, exit_pos = generate_maze(seed=seed)
    used_names  = [e["maze"] for e in state.get("hall_of_fame", [])]

    state.update({
        "maze_number":  maze_number,
        "maze_name":    pick_cat_name(maze_number, used_names),
        "cat_colour":   CAT_CYCLE[(maze_number - 1) % len(CAT_CYCLE)],
        "seed":         seed,
        "grid":         grid,
        "player_pos":   player_pos,
        "exit_pos":     exit_pos,
        "move_count":   0,
        "last_movers":  {},
        "completed_by": None,
    })
    return state


# ---------------------------------------------------------------------------
# README generation
# ---------------------------------------------------------------------------

TILE = {
    "wall_topleft":     f"{ASSETS_BASE}/tiles/wall_topleft.png",
    "wall_top":         f"{ASSETS_BASE}/tiles/wall_top.png",
    "wall_topright":    f"{ASSETS_BASE}/tiles/wall_topright.png",
    "wall_left":        f"{ASSETS_BASE}/tiles/wall_left.png",
    "wall_right":       f"{ASSETS_BASE}/tiles/wall_right.png",
    "wall_bottomleft":  f"{ASSETS_BASE}/tiles/wall_bottomleft.png",
    "wall_bottomright": f"{ASSETS_BASE}/tiles/wall_bottomright.png",
    "wall_inner":       f"{ASSETS_BASE}/tiles/wall_top.png",
    "floor":            f"{ASSETS_BASE}/tiles/floor.png",
    "floor_tex_a":      f"{ASSETS_BASE}/tiles/floor_textured_a.png",
    "floor_tex_b":      f"{ASSETS_BASE}/tiles/floor_textured_b.png",
    "exit":             f"{ASSETS_BASE}/tiles/exit.png",
}

CELL_SIZE      = 48
TEXTURED_CELLS = {(3, 3), (7, 7), (5, 5)}


def tile_for_cell(grid, r, c, player_pos, exit_pos, cat_colour):
    """Return the <img> tag for a single grid cell."""
    size   = MAZE_SIZE
    pr, pc = player_pos
    er, ec = exit_pos

    if r == pr and c == pc:
        return f'<img src="{ASSETS_BASE}/cats/{cat_colour}_run.gif" width="{CELL_SIZE}" height="{CELL_SIZE}">'

    if r == er and c == ec:
        return f'<img src="{TILE["exit"]}" width="{CELL_SIZE}" height="{CELL_SIZE}">'

    if grid[r][c] == WALL:
        if   r == 0        and c == 0:        src = TILE["wall_topleft"]
        elif r == 0        and c == size - 1: src = TILE["wall_topright"]
        elif r == size - 1 and c == 0:        src = TILE["wall_bottomleft"]
        elif r == size - 1 and c == size - 1: src = TILE["wall_bottomright"]
        elif r == 0:                           src = TILE["wall_top"]
        elif r == size - 1:                    src = TILE["wall_top"]
        elif c == 0:                           src = TILE["wall_left"]
        elif c == size - 1:                    src = TILE["wall_right"]
        else:                                  src = TILE["wall_inner"]
        return f'<img src="{src}" width="{CELL_SIZE}" height="{CELL_SIZE}">'

    if (c, r) in TEXTURED_CELLS and grid[r][c] == PATH:
        src = TILE["floor_tex_a"] if (c + r) % 2 == 0 else TILE["floor_tex_b"]
        return f'<img src="{src}" width="{CELL_SIZE}" height="{CELL_SIZE}">'

    return f'<img src="{TILE["floor"]}" width="{CELL_SIZE}" height="{CELL_SIZE}">'


def build_maze_table(state: dict) -> str:
    """Render the maze as an HTML table."""
    grid       = state["grid"]
    player_pos = state["player_pos"]
    exit_pos   = state["exit_pos"]
    cat_colour = state["cat_colour"]

    lines = ['<table><tbody>']
    for r in range(MAZE_SIZE):
        lines.append('<tr>')
        for c in range(MAZE_SIZE):
            lines.append(f'<td>{tile_for_cell(grid, r, c, player_pos, exit_pos, cat_colour)}</td>')
        lines.append('</tr>')
    lines.append('</tbody></table>')
    return "\n".join(lines)


def build_win_banner(state: dict) -> str:
    """
    HTML win banner rendered inline in the README.
    Uses the actual cat GIF from the completed maze.
    """
    cat_colour   = state["cat_colour"]
    maze_name    = state["maze_name"]
    completed_by = state["completed_by"]
    move_count   = state["move_count"]
    cat_run_gif  = f"{ASSETS_BASE}/cats/{cat_colour}_run.gif"
    cat_idle_gif = f"{ASSETS_BASE}/cats/{cat_colour}_idle.gif"

    cat_row = "".join(
        f'<img src="{cat_run_gif}" width="48" height="48">'
        for _ in range(11)
    )

    return f"""<table width="100%"><tbody>
<tr>
  <td align="center" style="background:#1a1a2e; padding:6px 0; border:none;">
    {cat_row}
  </td>
</tr>
<tr>
  <td align="center" style="background:#1a1a2e; padding:16px 24px; border:none;">
    <img src="{cat_idle_gif}" width="72" height="72">
    <br/><br/>
    <strong>🎉 maze complete!</strong>
    <br/>
    <code>{maze_name}</code> was adopted by
    <a href="https://github.com/{completed_by}">@{completed_by}</a>
    &nbsp;·&nbsp; {move_count} moves
    <br/><br/>
    <em>a new maze has been prepared...</em>
  </td>
</tr>
<tr>
  <td align="center" style="background:#1a1a2e; padding:6px 0; border:none;">
    {cat_row}
  </td>
</tr>
</tbody></table>"""


def build_hall_of_fame(hall: list) -> str:
    if not hall:
        return "_no completed mazes yet. be the first to adopt a cat!_\n"

    lines = [
        "| # | cat | adopted by | moves |",
        "|---|-----|------------|-------|",
    ]
    for i, entry in enumerate(reversed(hall), 1):
        lines.append(
            f"| {i} | {entry['maze']} | "
            f"[@{entry['winner']}](https://github.com/{entry['winner']}) | "
            f"{entry['moves']} |"
        )
    return "\n".join(lines) + "\n"


def issue_url(direction: str, repo: str) -> str:
    return f"https://github.com/{repo}/issues/new?title=Move%3A+{direction}"


def build_readme(state: dict) -> str:
    repo         = os.environ.get("GITHUB_REPOSITORY",
                                  f"{REPO_OWNER}/{REPO_OWNER}")
    maze_name    = state["maze_name"]
    maze_number  = state["maze_number"]
    move_count   = state["move_count"]
    cat_colour   = state["cat_colour"]
    completed_by = state.get("completed_by")

    maze_table = build_maze_table(state)
    hall_md    = build_hall_of_fame(state.get("hall_of_fame", []))
    cat_idle   = f"{ASSETS_BASE}/cats/{cat_colour}_idle.gif"

    up    = issue_url("UP",    repo)
    down  = issue_url("DOWN",  repo)
    left  = issue_url("LEFT",  repo)
    right = issue_url("RIGHT", repo)

    controls = (
        f'<a href="{up}">⬆️</a>&nbsp;&nbsp;'
        f'<a href="{down}">⬇️</a>&nbsp;&nbsp;'
        f'<a href="{left}">⬅️</a>&nbsp;&nbsp;'
        f'<a href="{right}">➡️</a>'
    )

    win_section = ""
    if completed_by:
        win_section = "\n---\n\n" + build_win_banner(state) + "\n\n---\n"

    return f"""<div align="center">

<img src="{cat_idle}" width="80" height="80" />

# cat heist 🐾

> _a community maze game. help the cat steal the loot._

**maze #{maze_number} — {maze_name}**
{move_count} move{"s" if move_count != 1 else ""} so far

</div>

---
{win_section}
## the maze

{maze_table}

<div align="center">

{controls}

_click a direction · a pre-filled issue opens · just hit submit_
_one move per person every {COOLDOWN_MINUTES} minutes_

</div>

---

## how it works

- click a direction above → a github issue opens, pre-filled
- submit the issue → an action runs, moves the cat, updates this board
- reach the 🚪 exit to complete the maze and **adopt {maze_name}**
- the winner's handle is immortalised in the hall of fame below
- one move per person every {COOLDOWN_MINUTES} minutes — others can still move

---

## hall of fame

{hall_md}

---

<div align="center">

_built with github actions · [source](scripts/update_maze.py)_

</div>
"""


# ---------------------------------------------------------------------------
# Issue parsing
# ---------------------------------------------------------------------------

def parse_direction(title: str):
    title = title.strip()
    direction = title.split(":", 1)[1].strip().upper() if ":" in title else title.upper()
    return direction if direction in DIRECTION_MAP else None


# ---------------------------------------------------------------------------
# Core move logic
# ---------------------------------------------------------------------------

def attempt_move(state: dict, direction: str) -> tuple:
    grid   = state["grid"]
    pr, pc = state["player_pos"]
    dr, dc = DIRECTION_MAP[direction]
    nr, nc = pr + dr, pc + dc

    if not (0 <= nr < MAZE_SIZE and 0 <= nc < MAZE_SIZE):
        return False, "wall"
    if grid[nr][nc] == WALL:
        return False, "wall"

    state["player_pos"] = [nr, nc]
    state["move_count"] += 1
    er, ec = state["exit_pos"]
    return (True, "win") if nr == er and nc == ec else (True, "ok")


# ---------------------------------------------------------------------------
# Win handler
# ---------------------------------------------------------------------------

def handle_win(state: dict, author: str):
    state["completed_by"] = author
    state.setdefault("hall_of_fame", []).append({
        "maze":        state["maze_name"],
        "maze_number": state["maze_number"],
        "winner":      author,
        "moves":       state["move_count"],
    })


# ---------------------------------------------------------------------------
# Comment templates
# ---------------------------------------------------------------------------

def comment_blocked(direction: str, author: str) -> str:
    return (
        f"🐾 **thud.**\n\n"
        f"@{author} tried to go `{direction}` but that's a wall, bestie.\n\n"
        f"_the cat stares at the stones judgementally. try a different direction._"
    )


def comment_moved(direction: str, author: str, move_count: int) -> str:
    arrow = {"UP": "⬆️", "DOWN": "⬇️", "LEFT": "⬅️", "RIGHT": "➡️"}[direction]
    return (
        f"{arrow} **@{author}** moved `{direction}` — move #{move_count}\n\n"
        f"_the board has been updated. check the README!_"
    )


def comment_win(author: str, maze_name: str, move_count: int) -> str:
    return (
        f"🎉 **@{author} completed the maze!**\n\n"
        f"**{maze_name}** has been adopted after {move_count} moves.\n\n"
        f"_a new maze has been generated. the heist continues._"
    )


def comment_cooldown(author: str, minutes_remaining: int) -> str:
    return (
        f"🐱 **patience, little thief.**\n\n"
        f"@{author}, you already moved recently. "
        f"you can move again in **{minutes_remaining} minute{'s' if minutes_remaining != 1 else ''}**.\n\n"
        f"_the cat taps its paw and waits._"
    )


def comment_invalid(author: str, title: str) -> str:
    return (
        f"🤔 @{author}, `{title}` isn't a recognised move.\n\n"
        f"valid titles: `Move: UP` · `Move: DOWN` · `Move: LEFT` · `Move: RIGHT`"
    )


# ---------------------------------------------------------------------------
# Reset handler
# ---------------------------------------------------------------------------

def handle_reset(issue_number: int, author: str):
    """
    Full wipe — state, hall of fame, move history, everything.
    FOR TESTING ONLY. Delete .github/workflows/reset.yml when done.
    Only REPO_OWNER can trigger this.
    """
    repo           = os.environ.get("GITHUB_REPOSITORY", "")
    inferred_owner = repo.split("/")[0] if "/" in repo else REPO_OWNER
    allowed        = {inferred_owner.lower(), REPO_OWNER.lower()}

    if author.lower() not in allowed:
        post_comment(issue_number,
            f"🐱 @{author} nice try. only the repo owner can reset.\n\n"
            f"_the cat ignores you._"
        )
        close_issue(issue_number)
        print(f"Reset blocked — @{author} is not the owner")
        return

    print(f"RESET triggered by @{author} — wiping everything")

    fresh = {
        "maze_number":  0,
        "maze_name":    "",
        "cat_colour":   "white",
        "seed":         None,
        "grid":         [],
        "player_pos":   [1, 1],
        "exit_pos":     [MAZE_SIZE - 2, MAZE_SIZE - 2],
        "move_count":   0,
        "last_movers":  {},
        "completed_by": None,
        "hall_of_fame": [],
    }
    fresh = init_new_maze(fresh)
    save_state(fresh)
    README_FILE.write_text(build_readme(fresh))

    post_comment(issue_number,
        f"🔄 **full reset complete.**\n\n"
        f"everything wiped. fresh start: **{fresh['maze_name']}** (maze #1)\n\n"
        f"_delete the reset workflow when you're done testing._"
    )
    close_issue(issue_number)
    print("Reset done — full wipe.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    issue_number = int(os.environ.get("ISSUE_NUMBER", "0"))
    author       = os.environ.get("ISSUE_AUTHOR",    "unknown")
    title        = os.environ.get("ISSUE_TITLE",     "").strip()

    print(f"Issue #{issue_number} by @{author}: {title!r}")

    if title.upper().startswith(RESET_PREFIX):
        handle_reset(issue_number, author)
        return

    direction = parse_direction(title)
    if direction is None:
        post_comment(issue_number, comment_invalid(author, title))
        close_issue(issue_number)
        print(f"Invalid move title: {title!r}")
        return

    state = load_state()

    if not state.get("grid"):
        print("No grid found — initialising first maze")
        state = init_new_maze(state)
        save_state(state)

    on_cd, mins_left = is_on_cooldown(state, author)
    if on_cd:
        post_comment(issue_number, comment_cooldown(author, mins_left))
        close_issue(issue_number)
        print(f"@{author} on cooldown ({mins_left} min remaining)")
        return

    moved, reason = attempt_move(state, direction)

    if reason == "wall":
        state.setdefault("last_movers", {})[author] = now_iso()
        save_state(state)
        post_comment(issue_number, comment_blocked(direction, author))
        close_issue(issue_number)
        print(f"Blocked: {direction}")
        return

    state.setdefault("last_movers", {})[author] = now_iso()

    if reason == "win":
        handle_win(state, author)
        save_state(state)
        README_FILE.write_text(build_readme(state))
        post_comment(issue_number, comment_win(author, state["maze_name"], state["move_count"]))
        close_issue(issue_number)
        print(f"WIN by @{author}")

        state = init_new_maze(state)
        save_state(state)
        README_FILE.write_text(build_readme(state))
        print(f"New maze ready: {state['maze_name']} (#{state['maze_number']})")
        return

    save_state(state)
    README_FILE.write_text(build_readme(state))
    post_comment(issue_number, comment_moved(direction, author, state["move_count"]))
    close_issue(issue_number)
    print(f"Moved {direction} → {state['player_pos']} (move #{state['move_count']})")


if __name__ == "__main__":
    main()