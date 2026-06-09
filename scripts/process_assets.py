#!/usr/bin/env python3
"""
process_assets.py — Cat Heist asset pipeline
Run once from the repo root to generate all assets from raw downloaded spritesheets.

Usage:
    python3 scripts/process_assets.py

Expected input layout (relative to repo root):
    raw_assets/
        WhiteCat_Free_Carysaurus/WhiteCat_Free_Carysaurus/White-Run.png
        WhiteCat_Free_Carysaurus/WhiteCat_Free_Carysaurus/White-Idle.png
        BlackCat_Free_Carysaurus/BlackCat_Free_Carysaurus/Black-Run.png
        BlackCat_Free_Carysaurus/BlackCat_Free_Carysaurus/Black-Idle.png
        BrownCat_Free_Carysaurus/BrownCat_Free_Carysaurus/Brown-Run.png
        BrownCat_Free_Carysaurus/BrownCat_Free_Carysaurus/Brown-Idle.png
        OrangeTabby_Free_Carysaurus/OrangeTabby_Free_Carysaurus/OrangeTabby-Run.png
        OrangeTabby_Free_Carysaurus/OrangeTabby_Free_Carysaurus/OrangeTabby-Idle.png
        SiameseCat-Free-Carysaurus/SiameseCat-Free-Carysaurus/Siamese-Run.png
        SiameseCat-Free-Carysaurus/SiameseCat-Free-Carysaurus/Siamese-Idle.png
        TuxedoCat-Free-Carysaurus/TuxedoCat-Free-Carysaurus/Tuxedo-Run.png
        TuxedoCat-Free-Carysaurus/TuxedoCat-Free-Carysaurus/Tuxedo-Idle.png
        DungeonTileset_Free/DungeonTileset/Tileset.png
        DungeonTileset_Free/DungeonTileset/Props&Items.png

Output layout:
    assets/
        cats/
            white_run.gif
            white_idle.gif
            brown_run.gif   ... (all 6 colours × 2 animations)
        tiles/
            wall_top.png
            wall_topleft.png
            wall_topright.png
            wall_left.png
            wall_right.png
            wall_bottomleft.png
            wall_bottomright.png
            floor.png
            floor_textured_a.png
            floor_textured_b.png
            exit.png
            loot_hidden.png
"""

import os
import sys
import numpy as np
from pathlib import Path
from PIL import Image

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent  # scripts/ -> repo root
RAW_DIR   = REPO_ROOT / "raw_assets"
OUT_DIR   = REPO_ROOT / "assets"

# Tile size in the source spritesheet (px)
TILE_PX = 16

# Output scale factor: 16px * 4 = 64px tiles in the README
TILE_SCALE = 4

# Cat frame size in source spritesheet (px)
CAT_FRAME_PX = 48

# Cat output scale: 48px * 2 = 96px — readable in README without being huge
CAT_SCALE = 2

# GIF frame durations (ms)
RUN_DURATION  = 100   # snappy run cycle
IDLE_DURATION = 150   # slightly slower idle

# Black background threshold for cat transparency (0–255 per channel)
# Anything below this on all 3 channels → transparent
BLACK_THRESHOLD = 15


# ---------------------------------------------------------------------------
# Tile definitions
# ---------------------------------------------------------------------------

# (col, row) in Tileset.png at 16px grid
TILESET_TILES = {
    "wall_topleft":     (0,  0),
    "wall_top":         (1,  0),
    "wall_topright":    (3,  0),
    "wall_left":        (0,  1),
    "wall_right":       (3,  1),
    "wall_bottomleft":  (0,  4),
    "wall_bottomright": (3,  4),
    "floor":            (1,  1),
    "floor_textured_a": (10, 0),
    "floor_textured_b": (11, 0),
    "exit":             (4,  2),
}

# (col, row) in Props&Items.png at 16px grid
PROPS_TILES = {
    "loot_hidden": (2, 2),
}

# ---------------------------------------------------------------------------
# Cat definitions
# ---------------------------------------------------------------------------

# Maps output colour name -> (run_png_path, idle_png_path, n_run_frames, n_idle_frames)
CATS = {
    "white":   ("WhiteCat_Free_Carysaurus/WhiteCat_Free_Carysaurus/White-Run.png",
                "WhiteCat_Free_Carysaurus/WhiteCat_Free_Carysaurus/White-Idle.png",
                6, 12),
    "black":   ("BlackCat_Free_Carysaurus/BlackCat_Free_Carysaurus/Black-Run.png",
                "BlackCat_Free_Carysaurus/BlackCat_Free_Carysaurus/Black-Idle.png",
                6, 12),
    "brown":   ("BrownCat_Free_Carysaurus/BrownCat_Free_Carysaurus/Brown-Run.png",
                "BrownCat_Free_Carysaurus/BrownCat_Free_Carysaurus/Brown-Idle.png",
                6, 12),
    "orange":  ("OrangeTabby_Free_Carysaurus/OrangeTabby_Free_Carysaurus/OrangeTabby-Run.png",
                "OrangeTabby_Free_Carysaurus/OrangeTabby_Free_Carysaurus/OrangeTabby-Idle.png",
                6, 12),
    "siamese": ("SiameseCat-Free-Carysaurus/SiameseCat-Free-Carysaurus/Siamese-Run.png",
                "SiameseCat-Free-Carysaurus/SiameseCat-Free-Carysaurus/Siamese-Idle.png",
                6, 12),
    "tuxedo":  ("TuxedoCat-Free-Carysaurus/TuxedoCat-Free-Carysaurus/Tuxedo-Run.png",
                "TuxedoCat-Free-Carysaurus/TuxedoCat-Free-Carysaurus/Tuxedo-Idle.png",
                6, 12),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_dirs():
    (OUT_DIR / "cats").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "tiles").mkdir(parents=True, exist_ok=True)


def extract_tile(sheet: Image.Image, col: int, row: int, scale: int) -> Image.Image:
    """Crop a single tile from a tileset and scale it up with nearest-neighbour."""
    x0 = col * TILE_PX
    y0 = row * TILE_PX
    tile = sheet.crop((x0, y0, x0 + TILE_PX, y0 + TILE_PX))
    tile_scaled = tile.resize((TILE_PX * scale, TILE_PX * scale), Image.NEAREST)
    return tile_scaled.convert("RGBA")


def black_to_transparent(img: Image.Image, threshold: int = BLACK_THRESHOLD) -> Image.Image:
    """
    Convert near-black pixels to fully transparent.
    Used to remove the solid black background from cat spritesheets.
    """
    rgba = img.convert("RGBA")
    data = np.array(rgba)
    mask = (data[:, :, 0] < threshold) & \
           (data[:, :, 1] < threshold) & \
           (data[:, :, 2] < threshold)
    data[mask, 3] = 0
    return Image.fromarray(data, "RGBA")


def make_cat_gif(
    src_path: Path,
    out_path: Path,
    n_frames: int,
    frame_px: int = CAT_FRAME_PX,
    scale: int = CAT_SCALE,
    duration: int = RUN_DURATION,
):
    """
    Slice a horizontal spritesheet into frames, apply transparency,
    scale up, and save as an animated GIF.
    """
    sheet = Image.open(src_path).convert("RGB")

    expected_w = n_frames * frame_px
    if sheet.width != expected_w:
        print(f"  WARNING: {src_path.name} width={sheet.width}, "
              f"expected {expected_w} for {n_frames} frames of {frame_px}px")

    frames = []
    for i in range(n_frames):
        x0 = i * frame_px
        frame = sheet.crop((x0, 0, x0 + frame_px, frame_px))
        frame_scaled = frame.resize(
            (frame_px * scale, frame_px * scale), Image.NEAREST
        )
        frame_transparent = black_to_transparent(frame_scaled)
        frames.append(frame_transparent)

    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=0,
        disposal=2,   # clear frame before drawing next (clean transparency)
    )
    size_kb = out_path.stat().st_size // 1024
    print(f"  ✓  {out_path.relative_to(REPO_ROOT)}  "
          f"({n_frames} frames, {frame_px*scale}×{frame_px*scale}px, {size_kb}KB)")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_tiles():
    print("\n── Tiles ────────────────────────────────────────")

    tileset_path = RAW_DIR / "DungeonTileset_Free" / "DungeonTileset" / "Tileset.png"
    props_path   = RAW_DIR / "DungeonTileset_Free" / "DungeonTileset" / "Props&Items.png"

    if not tileset_path.exists():
        print(f"  ERROR: Tileset not found at {tileset_path}")
        print("  Make sure raw_assets/ is set up correctly (see script header).")
        sys.exit(1)

    tileset = Image.open(tileset_path).convert("RGB")
    props   = Image.open(props_path).convert("RGB")

    for name, (col, row) in TILESET_TILES.items():
        tile = extract_tile(tileset, col, row, TILE_SCALE)
        out  = OUT_DIR / "tiles" / f"{name}.png"
        tile.save(out)
        print(f"  ✓  {out.relative_to(REPO_ROOT)}  "
              f"({TILE_PX*TILE_SCALE}×{TILE_PX*TILE_SCALE}px)")

    for name, (col, row) in PROPS_TILES.items():
        tile = extract_tile(props, col, row, TILE_SCALE)
        out  = OUT_DIR / "tiles" / f"{name}.png"
        tile.save(out)
        print(f"  ✓  {out.relative_to(REPO_ROOT)}  "
              f"({TILE_PX*TILE_SCALE}×{TILE_PX*TILE_SCALE}px)")


def process_cats():
    print("\n── Cats ─────────────────────────────────────────")

    for colour, (run_rel, idle_rel, n_run, n_idle) in CATS.items():
        run_src  = RAW_DIR / run_rel
        idle_src = RAW_DIR / idle_rel

        if not run_src.exists():
            print(f"  SKIP {colour}_run  — not found: {run_src}")
        else:
            make_cat_gif(
                run_src,
                OUT_DIR / "cats" / f"{colour}_run.gif",
                n_frames=n_run,
                duration=RUN_DURATION,
            )

        if not idle_src.exists():
            print(f"  SKIP {colour}_idle — not found: {idle_src}")
        else:
            make_cat_gif(
                idle_src,
                OUT_DIR / "cats" / f"{colour}_idle.gif",
                n_frames=n_idle,
                duration=IDLE_DURATION,
            )


def verify_outputs():
    print("\n── Verification ─────────────────────────────────")
    expected_tiles = list(TILESET_TILES.keys()) + list(PROPS_TILES.keys())
    expected_cats  = [f"{c}_{a}" for c in CATS for a in ("run", "idle")]

    all_ok = True

    for name in expected_tiles:
        p = OUT_DIR / "tiles" / f"{name}.png"
        status = "✓" if p.exists() else "✗ MISSING"
        if not p.exists():
            all_ok = False
        print(f"  {status}  assets/tiles/{name}.png")

    for name in expected_cats:
        p = OUT_DIR / "cats" / f"{name}.gif"
        status = "✓" if p.exists() else "✗ MISSING"
        if not p.exists():
            all_ok = False
        print(f"  {status}  assets/cats/{name}.gif")

    print()
    if all_ok:
        print("All assets generated successfully.")
    else:
        print("Some assets are missing — check errors above.")
        sys.exit(1)


def main():
    print("Cat Heist — process_assets.py")
    print(f"Repo root : {REPO_ROOT}")
    print(f"Raw assets: {RAW_DIR}")
    print(f"Output    : {OUT_DIR}")

    if not RAW_DIR.exists():
        print(f"\nERROR: raw_assets/ directory not found at {RAW_DIR}")
        print("Create it and move your downloaded asset folders inside.")
        sys.exit(1)

    ensure_dirs()
    process_tiles()
    process_cats()
    verify_outputs()


if __name__ == "__main__":
    main()