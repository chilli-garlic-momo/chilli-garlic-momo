#!/usr/bin/env python3
"""
maze_generator.py — Cat Heist maze generation
Generates a random solvable maze using recursive backtracking.

Grid conventions
----------------
  1 = wall
  0 = path (walkable)

Grid size is always ODD in both dimensions so the algorithm works cleanly.
We use 11×11 (configurable via MAZE_SIZE).

Cell coordinate system
----------------------
  [row][col], origin top-left
  row 0 = top, row MAZE_SIZE-1 = bottom

Player always starts at (1, 1) — top-left path cell.
Exit  always placed at  (MAZE_SIZE-2, MAZE_SIZE-2) — bottom-right path cell.

Standalone usage
----------------
  python3 scripts/maze_generator.py
  python3 scripts/maze_generator.py --seed 42   # reproducible maze

Imported usage
--------------
  from scripts.maze_generator import generate_maze, MAZE_SIZE
  grid, player_pos, exit_pos = generate_maze()
  grid, player_pos, exit_pos = generate_maze(seed=42)
"""

import random
import argparse
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAZE_SIZE = 11          # must be odd; controls the grid dimensions
WALL      = 1
PATH      = 0

# ---------------------------------------------------------------------------
# Core generation
# ---------------------------------------------------------------------------

def generate_maze(seed: Optional[int] = None) -> tuple[list[list[int]], list[int], list[int]]:
    """
    Generate a random maze using iterative recursive backtracking.

    Returns
    -------
    grid       : 2D list[list[int]], MAZE_SIZE × MAZE_SIZE, 1=wall 0=path
    player_pos : [row, col] starting position (always [1, 1])
    exit_pos   : [row, col] exit position (always [MAZE_SIZE-2, MAZE_SIZE-2])
    """
    rng = random.Random(seed)
    size = MAZE_SIZE

    # Start with everything walled
    grid = [[WALL] * size for _ in range(size)]

    # ---------------------------------------------------------------------------
    # Recursive backtracking (iterative via explicit stack)
    #
    # The algorithm visits "cells" on a 2-step grid (odd indices only).
    # When moving from cell A to cell B, it carves the wall between them too.
    # ---------------------------------------------------------------------------

    def carve(start_row: int, start_col: int):
        stack = [(start_row, start_col)]
        grid[start_row][start_col] = PATH

        while stack:
            row, col = stack[-1]

            # Neighbours 2 steps away (still inside bounds, still walled)
            neighbours = []
            for dr, dc in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                nr, nc = row + dr, col + dc
                if 1 <= nr < size - 1 and 1 <= nc < size - 1:
                    if grid[nr][nc] == WALL:
                        neighbours.append((nr, nc, dr, dc))

            if neighbours:
                nr, nc, dr, dc = rng.choice(neighbours)
                # Carve the wall between current cell and chosen neighbour
                grid[row + dr // 2][col + dc // 2] = PATH
                grid[nr][nc] = PATH
                stack.append((nr, nc))
            else:
                stack.pop()

    # Start carving from (1,1)
    carve(1, 1)

    # ---------------------------------------------------------------------------
    # Guarantee the border is fully walled (algorithm shouldn't touch it,
    # but explicit enforcement makes the renderer's job simpler)
    # ---------------------------------------------------------------------------
    for i in range(size):
        grid[0][i]        = WALL   # top row
        grid[size - 1][i] = WALL   # bottom row
        grid[i][0]        = WALL   # left col
        grid[i][size - 1] = WALL   # right col

    # Ensure player start and exit are open
    player_pos = [1, 1]
    exit_pos   = [size - 2, size - 2]
    grid[player_pos[0]][player_pos[1]] = PATH
    grid[exit_pos[0]][exit_pos[1]]     = PATH

    # Open a path from exit to the border wall so the exit is reachable
    # from the bottom-right (the backtracker usually handles this but
    # explicit guarantee avoids edge cases)
    _ensure_exit_reachable(grid, exit_pos, rng)

    return grid, player_pos, exit_pos


def _ensure_exit_reachable(
    grid: list[list[int]],
    exit_pos: list[int],
    rng: random.Random,
) -> None:
    """
    Verify the exit cell is reachable from (1,1) via BFS.
    If somehow it isn't (extremely rare), carve a direct corridor.
    This is a safety net — the backtracker almost never needs it.
    """
    start = tuple(exit_pos)
    target = (1, 1)
    visited = {start}
    queue = [start]

    while queue:
        r, c = queue.pop(0)
        if (r, c) == target:
            return  # reachable, nothing to do
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < MAZE_SIZE and 0 <= nc < MAZE_SIZE:
                if grid[nr][nc] == PATH and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append((nr, nc))

    # Not reachable — carve a simple L-shaped corridor from exit to (1,1)
    er, ec = exit_pos
    # Carve up until row 1
    for r in range(er, 0, -1):
        grid[r][ec] = PATH
    # Carve left until col 1
    for c in range(ec, 0, -1):
        grid[1][c] = PATH


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_maze(grid: list[list[int]], player_pos: list[int], exit_pos: list[int]) -> dict:
    """
    Run a suite of checks on a generated maze.

    Returns a dict with keys:
      valid         : bool — overall pass/fail
      border_sealed : bool — all border cells are walls
      start_open    : bool — player_pos is a PATH cell
      exit_open     : bool — exit_pos is a PATH cell
      reachable     : bool — exit is reachable from player via BFS
      path_length   : int  — shortest path length (0 if unreachable)
      wall_count    : int
      path_count    : int
    """
    size = MAZE_SIZE
    results: dict = {}

    # Border check
    border_ok = all(
        grid[0][c] == WALL and grid[size-1][c] == WALL and
        grid[r][0] == WALL and grid[r][size-1] == WALL
        for r in range(size) for c in range(size)
        if r in (0, size-1) or c in (0, size-1)
    )
    results["border_sealed"] = border_ok

    pr, pc = player_pos
    er, ec = exit_pos
    results["start_open"] = grid[pr][pc] == PATH
    results["exit_open"]  = grid[er][ec] == PATH

    # BFS shortest path
    from collections import deque
    visited = {(pr, pc)}
    queue   = deque([(pr, pc, 0)])
    path_length = 0
    reachable   = False

    while queue:
        r, c, dist = queue.popleft()
        if (r, c) == (er, ec):
            reachable   = True
            path_length = dist
            break
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr, nc = r+dr, c+dc
            if 0 <= nr < size and 0 <= nc < size:
                if grid[nr][nc] == PATH and (nr,nc) not in visited:
                    visited.add((nr,nc))
                    queue.append((nr, nc, dist+1))

    results["reachable"]    = reachable
    results["path_length"]  = path_length

    flat = [grid[r][c] for r in range(size) for c in range(size)]
    results["wall_count"] = flat.count(WALL)
    results["path_count"] = flat.count(PATH)

    results["valid"] = all([
        results["border_sealed"],
        results["start_open"],
        results["exit_open"],
        results["reachable"],
    ])

    return results


# ---------------------------------------------------------------------------
# Pretty-print for terminal testing
# ---------------------------------------------------------------------------

DISPLAY = {
    WALL: "██",
    PATH: "  ",
}

DISPLAY_WITH_MARKERS = {
    "wall":   "██",
    "path":   "  ",
    "player": "🐱",
    "exit":   "🚪",
}

def render_terminal(
    grid: list[list[int]],
    player_pos: list[int],
    exit_pos: list[int],
) -> str:
    lines = []
    for r, row in enumerate(grid):
        line = ""
        for c, cell in enumerate(row):
            if [r, c] == player_pos:
                line += DISPLAY_WITH_MARKERS["player"]
            elif [r, c] == exit_pos:
                line += DISPLAY_WITH_MARKERS["exit"]
            elif cell == WALL:
                line += DISPLAY_WITH_MARKERS["wall"]
            else:
                line += DISPLAY_WITH_MARKERS["path"]
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cat Heist maze generator")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducible mazes")
    parser.add_argument("--validate", action="store_true", default=True,
                        help="Run validation suite after generation (default: on)")
    parser.add_argument("--stress", type=int, default=0, metavar="N",
                        help="Generate N mazes and validate each (stress test)")
    args = parser.parse_args()

    if args.stress > 0:
        _stress_test(args.stress)
        return

    grid, player_pos, exit_pos = generate_maze(seed=args.seed)

    print(f"\nMaze ({MAZE_SIZE}×{MAZE_SIZE})  seed={args.seed}")
    print(render_terminal(grid, player_pos, exit_pos))

    if args.validate:
        results = validate_maze(grid, player_pos, exit_pos)
        print(f"\nValidation:")
        print(f"  border sealed : {results['border_sealed']}")
        print(f"  start open    : {results['start_open']}")
        print(f"  exit open     : {results['exit_open']}")
        print(f"  reachable     : {results['reachable']}")
        print(f"  shortest path : {results['path_length']} steps")
        print(f"  walls / paths : {results['wall_count']} / {results['path_count']}")
        print(f"\n  {'✓ VALID' if results['valid'] else '✗ INVALID'}")


def _stress_test(n: int):
    """Generate n mazes, validate each, report pass/fail stats."""
    passed = 0
    failed = 0
    min_path = float("inf")
    max_path = 0

    print(f"Stress test: generating {n} mazes...")
    for i in range(n):
        grid, player_pos, exit_pos = generate_maze(seed=i)
        results = validate_maze(grid, player_pos, exit_pos)
        if results["valid"]:
            passed += 1
            min_path = min(min_path, results["path_length"])
            max_path = max(max_path, results["path_length"])
        else:
            failed += 1
            print(f"  FAILED seed={i}: {results}")

    print(f"\nResults: {passed}/{n} passed, {failed} failed")
    print(f"Path length range: {min_path}–{max_path} steps")


if __name__ == "__main__":
    main()