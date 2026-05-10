"""TIFF loading, IR/B-scan panel split, scale-bar detection."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image


# Folder-level fallback used when in-image scale bar detection fails.
# Heidelberg synthetic mouse OCTs in this dataset are roughly this resolution.
FALLBACK_UM_PER_PX_Y = 3.87
FALLBACK_UM_PER_PX_X = 11.50


@dataclass
class BscanLayout:
    """Geometry of the B-scan panel inside a TIFF."""
    left_x: int
    right_x: int      # inclusive
    top_y: int
    bot_y: int        # inclusive
    center_x: int     # absolute coords (image-frame)

    @property
    def width(self) -> int:
        return self.right_x - self.left_x + 1

    @property
    def height(self) -> int:
        return self.bot_y - self.top_y + 1


@dataclass
class ScaleInfo:
    um_per_px_y: float
    um_per_px_x: float
    source: str = "fallback"   # "in_image" or "fallback"


@dataclass
class OctImage:
    """Loaded TIFF with computed layout."""
    path: Path
    rgb: np.ndarray           # full image, HxWx3 uint8
    gray: np.ndarray          # full image, HxW uint8
    layout: BscanLayout
    scale: ScaleInfo
    bscan_rgb: np.ndarray = field(init=False)
    bscan_gray: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        l = self.layout
        self.bscan_rgb = self.rgb[l.top_y:l.bot_y + 1, l.left_x:l.right_x + 1]
        self.bscan_gray = self.gray[l.top_y:l.bot_y + 1, l.left_x:l.right_x + 1]


def load_rgb(path: str | Path) -> np.ndarray:
    """Load TIFF as HxWx3 uint8 RGB."""
    im = Image.open(str(path)).convert("RGB")
    return np.asarray(im, dtype=np.uint8)


# Tunables for the dark-background-run detector below. Values picked
# empirically against the project's mouse OCT corpus.
_BG_DARK_THRESH = 30          # pixel < this counts as "near-black"
_BG_ROUGH_FRAC = 0.7          # column with this fraction of dark pixels
                              # qualifies for the rough run-search
_BG_MIN_RUN = 200             # B-scan panel always sustains at least
                              # this many such columns
_BG_GAP_TOL = 50              # bright gaps shorter than this don't break
                              # a rough run (e.g. the bright retinal band
                              # can raise frac_dark briefly inside the panel)
_BG_SKIP_INITIAL = 100        # ignore short black image-borders at x<100
_BG_REFINE_FRAC = 0.85        # the actual IR/B-scan clip line is where
                              # frac_dark sustains > this — a tighter
                              # threshold than the rough scan above
_BG_REFINE_WINDOW = 30        # max columns to walk forward from the
                              # rough start when refining


def _bscan_left_edge_via_dark_bg(rgb: np.ndarray) -> int | None:
    """Find the left edge of the B-scan panel.

    Two-stage heuristic:

    1. **Rough**: locate the leftmost sustained run of "mostly dark"
       columns (``frac_dark > 0.7`` for at least 200 columns, ignoring
       small bright gaps and short leading image borders). The B-scan
       panel always satisfies this — the IR fundus to its left has
       plenty of mid-grey pixels and never sustains such a long
       almost-all-dark run.

    2. **Refine**: walk forward from the rough start (within 30 cols)
       to the first column where ``frac_dark >= 0.85``. The IR fundus
       circle's right edge is **clipped vertically** by the panel
       boundary; that clip line shows up as a sharp jump in frac_dark
       (~0.79 -> ~0.95 over a couple of columns). The rough threshold
       0.7 catches the gradual edge of the IR circle a few columns
       too early; the refine threshold 0.85 lands precisely on the
       clip line.

    Returns None when no qualifying run is found.
    """
    gray = rgb.mean(axis=2)
    H, W = gray.shape
    frac_dark = (gray < _BG_DARK_THRESH).mean(axis=0)
    is_dark = frac_dark > _BG_ROUGH_FRAC

    # ---- Stage 1: rough — first sustained dark-background run.
    start_scan = 0
    if is_dark[0]:
        non_dark = np.where(~is_dark[:_BG_SKIP_INITIAL])[0]
        if len(non_dark):
            start_scan = int(non_dark[0])

    rough = None
    run_start = -1
    run_end = -1
    bright_gap = 0
    for x in range(start_scan, W):
        if is_dark[x]:
            if run_start == -1:
                run_start = x
            run_end = x
            bright_gap = 0
        else:
            if run_start != -1:
                bright_gap += 1
                if bright_gap > _BG_GAP_TOL:
                    if run_end - run_start + 1 >= _BG_MIN_RUN:
                        rough = run_start
                        break
                    run_start = -1
                    run_end = -1
                    bright_gap = 0
    if rough is None:
        if run_start != -1 and run_end - run_start + 1 >= _BG_MIN_RUN:
            rough = run_start
        else:
            return None

    # ---- Stage 2: refine to the actual clip line.
    hi = min(W, rough + _BG_REFINE_WINDOW)
    for x in range(rough, hi):
        if frac_dark[x] >= _BG_REFINE_FRAC:
            return x
    return rough  # fallback if the sharp clip never materialises


# Public name kept for backwards compatibility (was previously the
# mid-grey-circle approach; see git history for the old logic).
_ir_circle_right_edge = _bscan_left_edge_via_dark_bg


def detect_bscan_layout(rgb: np.ndarray) -> BscanLayout:
    """Find the B-scan panel.

    Left edge: the right cut-off line of the IR fundus circle (the
    rightmost column where the circular grey content is still present).
    Right edge: the right edge of the image.
    Center: the geometric midpoint of left and right (per spec).
    """
    H, W, _ = rgb.shape

    ir_edge = _ir_circle_right_edge(rgb)
    if ir_edge is None:
        left_x = 0
    else:
        left_x = ir_edge

    right_x = W - 1
    bs_cols = rgb[:, left_x:right_x + 1].mean(axis=2)
    row_max = bs_cols.max(axis=1)
    nonempty_rows = np.where(row_max > 40)[0]
    if len(nonempty_rows) > 0:
        top_y, bot_y = int(nonempty_rows[0]), int(nonempty_rows[-1])
    else:
        top_y, bot_y = 0, H - 1

    center_x = (left_x + right_x) // 2
    return BscanLayout(left_x=left_x, right_x=right_x,
                       top_y=top_y, bot_y=bot_y, center_x=center_x)


def detect_scale(rgb: np.ndarray, layout: BscanLayout) -> ScaleInfo:
    """Detect scale bars next to the B-scan panel.

    Heidelberg layouts typically draw a vertical scale tick column to the
    right of the B-scan and a horizontal scale tick row below it. Tick marks
    are short bright segments at known micron spacing (200 µm / 200 µm).

    The detector here is intentionally conservative: it looks for the
    spacing between tick rows / columns near the B-scan panel. If anything
    feels off it returns the fallback.
    """
    gray = rgb.mean(axis=2)
    H, W = gray.shape

    um_y, um_x = None, None

    # Vertical scale: column band immediately to the right of the panel,
    # within `right_x + 1 .. right_x + 60`. Look for rows that are bright.
    rs = layout.right_x + 1
    re = min(W, layout.right_x + 60)
    if re - rs > 5:
        strip = gray[layout.top_y:layout.bot_y + 1, rs:re]
        row_max = strip.max(axis=1)
        bright_rows = np.where(row_max > 200)[0]
        if len(bright_rows) >= 3:
            # Tick rows cluster as small groups; estimate spacing.
            diffs = np.diff(bright_rows)
            big = diffs[diffs > 2]
            if len(big) >= 2:
                spacing_px = float(np.median(big))
                # Heidelberg scale ticks are usually 200 µm apart.
                um_y = 200.0 / spacing_px

    # Horizontal scale: row band immediately below the panel.
    bs = layout.bot_y + 1
    be = min(H, layout.bot_y + 40)
    if be - bs > 5:
        strip = gray[bs:be, layout.left_x:layout.right_x + 1]
        col_max = strip.max(axis=0)
        bright_cols = np.where(col_max > 200)[0]
        if len(bright_cols) >= 3:
            diffs = np.diff(bright_cols)
            big = diffs[diffs > 2]
            if len(big) >= 2:
                spacing_px = float(np.median(big))
                um_x = 200.0 / spacing_px

    if um_y is not None and um_x is not None:
        return ScaleInfo(um_per_px_y=um_y, um_per_px_x=um_x, source="in_image")
    if um_y is not None:
        return ScaleInfo(um_per_px_y=um_y,
                         um_per_px_x=FALLBACK_UM_PER_PX_X,
                         source="in_image")
    return ScaleInfo(um_per_px_y=FALLBACK_UM_PER_PX_Y,
                     um_per_px_x=FALLBACK_UM_PER_PX_X,
                     source="fallback")


def load_oct(path: str | Path) -> OctImage:
    """Load a TIFF and compute its layout + scale."""
    p = Path(path)
    rgb = load_rgb(p)
    gray = rgb.mean(axis=2).astype(np.uint8)
    layout = detect_bscan_layout(rgb)
    scale = detect_scale(rgb, layout)
    return OctImage(path=p, rgb=rgb, gray=gray, layout=layout, scale=scale)


def is_normal_filename(name: str) -> Optional[bool]:
    """Heuristic: does the filename suggest a normal vs detach image?

    The dataset uses suffixes like '4H', '6H', '8H', '10H', '4V', etc.
    The spec calls 4H/4V 'normal' and longer time points 'detach', but we do
    not rely on this — detection is image-driven. This is only used for a
    sanity-check column in the summary sheet.

    Returns True for likely-normal, False for likely-detach, None if unsure.
    """
    stem = Path(name).stem.upper()
    for tag in ("_4H", "_4V"):
        if stem.endswith(tag) or stem.split("(")[0].endswith(tag):
            return True
    for tag in ("_6H", "_6V", "_7H", "_7V", "_8H", "_8V",
                "_9H", "_9V", "_10H", "_10V"):
        if stem.endswith(tag) or stem.split("(")[0].endswith(tag):
            return False
    return None
