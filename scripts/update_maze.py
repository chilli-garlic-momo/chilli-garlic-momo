#!/usr/bin/env python3
"""
update_maze.py — Cat Heist game engine
Triggered by GitHub Actions on every new issue.
Renders the board as a single composed GIF (assets/board.gif) for a
seamless look — the cat animates inside the image.
"""

import json
import os
import sys
import random
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

from PIL import Image, ImageSequence

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT   = Path(__file__).parent.parent
STATE_FILE  = REPO_ROOT / "game_state.json"
README_FILE = REPO_ROOT / "README.md"
ASSETS_DIR  = REPO_ROOT / "assets"
BOARD_FILE  = ASSETS_DIR / "board.gif"
ASSETS_BASE = "assets"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COOLDOWN_MINUTES = 15
MAZE_SIZE        = 11
WALL             = 1
PATH             = 0
REPO_OWNER       = "chilli-garlic-momo"

TILE_PX     = 64    # size of tile assets on disk
BOARD_WIDTH = 396   # display width of the board in the README (smaller = tweak here)

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

RESET_PREFIX = "[RESET]"

TILE_NAMES = [
    "wall_topleft", "wall_top", "wall_topright",
    "wall_left", "wall_right",
    "wall_bottomleft", "wall_bottomright",
    "floor", "floor_textured_a", "floor_textured_b",
    "exit",
]

TEXTURED_CELLS = {(3, 3), (7, 7), (5, 5)}

# ---------------------------------------------------------------------------
# Maze generation
# ---------------------------------------------------------------------------

def generate_maze(seed=None):
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

def gh_api(method, path, body=None):
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


def post_comment(issue_number, body):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    gh_api("POST", f"/repos/{repo}/issues/{issue_number}/comments", {"body": body})


def close_issue(issue_number):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    gh_api("PATCH", f"/repos/{repo}/issues/{issue_number}",
           {"state": "closed", "state_reason": "completed"})


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state():
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_on_cooldown(state, author):
    last = state.get("last_movers", {}).get(author)
    if not last:
        return False, 0
    elapsed  = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    cooldown = timedelta(minutes=COOLDOWN_MINUTES)
    if elapsed < cooldown:
        return True, int((cooldown - elapsed).total_seconds() // 60) + 1
    return False, 0


def pick_cat_name(maze_number, used_names):
    pool = [n for n in CAT_NAMES if n not in used_names] or CAT_NAMES[:]
    return pool[(maze_number - 1) % len(pool)]


def init_new_maze(state):
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
        "last_mover":   None,
        "completed_by": None,
    })
    return state


# ---------------------------------------------------------------------------
# Board rendering — composes the whole maze into ONE animated GIF
# ---------------------------------------------------------------------------

def tile_name_for_cell(grid, r, c, exit_pos):
    """Pick the correct tile, with orientation-aware interior walls."""
    size   = MAZE_SIZE
    er, ec = exit_pos

    if r == er and c == ec:
        return "exit"

    if grid[r][c] == WALL:
        # border
        if r == 0 and c == 0:               return "wall_topleft"
        if r == 0 and c == size - 1:        return "wall_topright"
        if r == size - 1 and c == 0:        return "wall_bottomleft"
        if r == size - 1 and c == size - 1: return "wall_bottomright"
        if r == 0 or r == size - 1:         return "wall_top"
        if c == 0:                          return "wall_left"
        if c == size - 1:                   return "wall_right"

        # interior — orientation aware
        horiz = grid[r][c - 1] == WALL or grid[r][c + 1] == WALL
        vert  = grid[r - 1][c] == WALL or grid[r + 1][c] == WALL

        if vert and not horiz:
            # vertical wall segment — pick variant by which side has floor
            if grid[r][c + 1] == PATH:
                return "wall_left"    # floor on the right
            if grid[r][c - 1] == PATH:
                return "wall_right"   # floor on the left
            return "wall_left"
        return "wall_top"             # horizontal (or junction) segment

    if (c, r) in TEXTURED_CELLS:
        return "floor_textured_a" if (c + r) % 2 == 0 else "floor_textured_b"
    return "floor"


def render_board(state):
    """Compose the maze + animated cat into assets/board.gif."""
    px       = TILE_PX
    board_px = MAZE_SIZE * px

    # Load and resize all tiles once
    tiles = {
        name: Image.open(ASSETS_DIR / "tiles" / f"{name}.png")
               .convert("RGBA")
               .resize((px, px), Image.NEAREST)
        for name in TILE_NAMES
    }

    grid     = state["grid"]
    pr, pc   = state["player_pos"]
    exit_pos = state["exit_pos"]

    # Build static base board once — player cell gets floor underneath
    base = Image.new("RGBA", (board_px, board_px))
    for r in range(MAZE_SIZE):
        for c in range(MAZE_SIZE):
            name = "floor" if (r == pr and c == pc) else tile_name_for_cell(grid, r, c, exit_pos)
            base.paste(tiles[name], (c * px, r * px))

    # Store base as raw bytes — cheap to restore per frame
    base_bytes = base.tobytes()

    # Load cat idle frames once
    cat_gif    = Image.open(ASSETS_DIR / "cats" / f"{state['cat_colour']}_idle.gif")
    cat_frames = []
    durations  = []
    for frame in ImageSequence.Iterator(cat_gif):
        cat_frames.append(frame.convert("RGBA").resize((px, px), Image.NEAREST))
        durations.append(frame.info.get("duration", 150))

    # Compose each frame: restore base cheaply, drop cat on top, quantize
    frames = []
    for cat_frame in cat_frames:
        composed = Image.frombytes("RGBA", (board_px, board_px), base_bytes)
        composed.alpha_composite(cat_frame, (pc * px, pr * px))
        frames.append(composed.quantize(colors=256, method=Image.Quantize.FASTOCTREE))

    frames[0].save(
        BOARD_FILE,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
    )
    print(f"Board rendered → {BOARD_FILE.relative_to(REPO_ROOT)}")


# ---------------------------------------------------------------------------
# README generation
# ---------------------------------------------------------------------------

def build_win_banner(state):
    cat_colour   = state["cat_colour"]
    maze_name    = state["maze_name"]
    completed_by = state["completed_by"]
    move_count   = state["move_count"]
    cat_run_gif  = f"{ASSETS_BASE}/cats/{cat_colour}_run.gif"
    cat_idle_gif = f"{ASSETS_BASE}/cats/{cat_colour}_idle.gif"

    cat_row = "".join(
        f'<img src="{cat_run_gif}" width="40" height="40">' for _ in range(10)
    )

    return f"""<table width="100%"><tbody>
<tr><td align="center">{cat_row}</td></tr>
<tr><td align="center">
<img src="{cat_idle_gif}" width="64" height="64"><br/>
<strong>🎉 maze complete!</strong><br/>
<code>{maze_name}</code> was adopted by <a href="https://github.com/{completed_by}">@{completed_by}</a> · {move_count} moves<br/>
<em>a new maze has been prepared...</em>
</td></tr>
<tr><td align="center">{cat_row}</td></tr>
</tbody></table>"""


def build_hall_of_fame(hall):
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


def issue_url(direction, repo):
    return f"https://github.com/{repo}/issues/new?title=Move%3A+{direction}"


def build_readme(state):
    repo         = os.environ.get("GITHUB_REPOSITORY", f"{REPO_OWNER}/{REPO_OWNER}")
    maze_name    = state["maze_name"]
    maze_number  = state["maze_number"]
    move_count   = state["move_count"]
    cat_colour   = state["cat_colour"]
    completed_by = state.get("completed_by")
    last_mover   = state.get("last_mover")

    hall_md = build_hall_of_fame(state.get("hall_of_fame", []))
    cat_run = f"{ASSETS_BASE}/cats/{cat_colour}_run.gif"

    # cache-busted board URL so GitHub's image cache always shows the latest move
    board_url = (
        f"https://raw.githubusercontent.com/{repo}/main/assets/board.gif"
        f"?v={maze_number}-{move_count}"
    )

    last_line = ""
    if last_mover:
        last_line = f" · last move by [@{last_mover}](https://github.com/{last_mover})"

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
        win_section = "\n" + build_win_banner(state) + "\n"

    return f"""<div align="center">

# cat heist 🐾 <img src="{cat_run}" width="42" height="42" />

_a community maze game — help **{maze_name}** find the exit_

**total moves made by {maze_name} in maze #{maze_number}: {move_count}**{last_line}
{win_section}
<img src="{board_url}" width="{BOARD_WIDTH}" alt="the maze" />

{controls}

_click a direction · a pre-filled issue opens · hit submit · one move per person every {COOLDOWN_MINUTES} min_

</div>

---

<details>
<summary><b>how it works</b></summary>

- click a direction above → a github issue opens, pre-filled — just submit it
- a github action runs, moves the cat, re-renders this board
- reach the door to complete the maze and **adopt {maze_name}**
- winners are immortalised in the hall of fame
- one move per person every {COOLDOWN_MINUTES} minutes — others can still move

</details>

## hall of fame

{hall_md}

<div align="center">

_built with github actions · [source](scripts/update_maze.py)_

</div>
"""


# ---------------------------------------------------------------------------
# Issue parsing / move logic
# ---------------------------------------------------------------------------

def parse_direction(title):
    title = title.strip()
    direction = title.split(":", 1)[1].strip().upper() if ":" in title else title.upper()
    return direction if direction in DIRECTION_MAP else None


def attempt_move(state, direction):
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


def handle_win(state, author):
    state["completed_by"] = author
    state.setdefault("hall_of_fame", []).append({
        "maze":        state["maze_name"],
        "maze_number": state["maze_number"],
        "winner":      author,
        "moves":       state["move_count"],
    })


def write_outputs(state):
    """Render board GIF + README together — always called as a pair."""
    render_board(state)
    README_FILE.write_text(build_readme(state))


# ---------------------------------------------------------------------------
# Comment templates
# ---------------------------------------------------------------------------

def comment_blocked(direction, author):
    return (
        f"🐾 **thud.**\n\n"
        f"@{author} tried to go `{direction}` but that's a wall, bestie.\n\n"
        f"_the cat stares at the stones judgementally. try a different direction._"
    )


def comment_moved(direction, author, move_count):
    arrow = {"UP": "⬆️", "DOWN": "⬇️", "LEFT": "⬅️", "RIGHT": "➡️"}[direction]
    return (
        f"{arrow} **@{author}** moved `{direction}` — move #{move_count}\n\n"
        f"_the board has been updated. check the README!_"
    )


def comment_win(author, maze_name, move_count):
    return (
        f"🎉 **@{author} completed the maze!**\n\n"
        f"**{maze_name}** has been adopted after {move_count} moves.\n\n"
        f"_a new maze has been generated. the heist continues._"
    )


def comment_cooldown(author, minutes_remaining):
    return (
        f"🐱 **patience, little thief.**\n\n"
        f"@{author}, you already moved recently. "
        f"you can move again in **{minutes_remaining} minute{'s' if minutes_remaining != 1 else ''}**.\n\n"
        f"_the cat taps its paw and waits._"
    )


def comment_invalid(author, title):
    return (
        f"🤔 @{author}, `{title}` isn't a recognised move.\n\n"
        f"valid titles: `Move: UP` · `Move: DOWN` · `Move: LEFT` · `Move: RIGHT`"
    )


# ---------------------------------------------------------------------------
# Reset handler
# ---------------------------------------------------------------------------

def handle_reset(issue_number, author):
    repo           = os.environ.get("GITHUB_REPOSITORY", "")
    inferred_owner = repo.split("/")[0] if "/" in repo else REPO_OWNER
    allowed        = {inferred_owner.lower(), REPO_OWNER.lower()}

    if author.lower() not in allowed:
        post_comment(issue_number,
            f"🐱 @{author} nice try. only the repo owner can reset.\n\n_the cat ignores you._")
        close_issue(issue_number)
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
        "last_mover":   None,
        "completed_by": None,
        "hall_of_fame": [],
    }
    fresh = init_new_maze(fresh)
    save_state(fresh)
    write_outputs(fresh)

    post_comment(issue_number,
        f"🔄 **full reset complete.**\n\nfresh start: **{fresh['maze_name']}** (maze #1)\n\n"
        f"_delete the reset workflow when you're done testing._")
    close_issue(issue_number)


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
        # not a move issue — ignore silently, don't touch it
        print(f"Not a move issue, ignoring: {title!r}")
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
        return

    moved, reason = attempt_move(state, direction)

    if reason == "wall":
        state.setdefault("last_movers", {})[author] = now_iso()
        save_state(state)
        # board doesn't change on a wall hit — skip re-render
        post_comment(issue_number, comment_blocked(direction, author))
        close_issue(issue_number)
        print(f"Blocked: {direction}")
        return

    state.setdefault("last_movers", {})[author] = now_iso()
    state["last_mover"] = author

    if reason == "win":
        handle_win(state, author)
        save_state(state)
        write_outputs(state)
        post_comment(issue_number, comment_win(author, state["maze_name"], state["move_count"]))
        close_issue(issue_number)

        state = init_new_maze(state)
        save_state(state)
        write_outputs(state)
        print(f"New maze ready: {state['maze_name']} (#{state['maze_number']})")
        return

    save_state(state)
    write_outputs(state)
    post_comment(issue_number, comment_moved(direction, author, state["move_count"]))
    close_issue(issue_number)
    print(f"Moved {direction} → {state['player_pos']} (move #{state['move_count']})")


if __name__ == "__main__":
    main()