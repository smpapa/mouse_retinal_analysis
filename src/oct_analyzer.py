"""Per-column boundary and detachment detection.

Conventions
-----------
- All boundary arrays are length = B-scan panel width (`layout.width`).
- Coordinates are stored relative to the B-scan crop:
  `x = 0` is the leftmost column of the crop, `y = 0` is the top row.
- NaN means "unreadable / no candidate found here".
- Left and right segments are kept independent. The detector never
  bridges a gap across `center_x`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks, savgol_filter

from io_utils import OctImage


# Tunables. These are deliberate, conservative defaults that work for the
# Heidelberg synthetic mouse dataset. Adjusting any of these should be done
# by editing this file, not hardcoding fixes per image.
SMOOTH_SIGMA_Y = 1.5            # vertical smoothing of intensity profiles
SMOOTH_SIGMA_X_BAND = 6.0       # horizontal smoothing for band candidates
                                # (broader = follows the band more steadily,
                                #  less affected by local pixel noise)
TOP_ENVELOPE_SIGMA = 3.0        # heavier smoothing used for finding the
                                # upper edge of the retinal complex
TOP_BACKGROUND_K = 2.5          # background = median + K * MAD
TOP_PEAK_FRAC = 0.30            # also require above this fraction of the
                                # BM peak height (clears vitreous noise)
PEAK_MIN_DIST_PX = 4            # min distance between detected peaks
PEAK_MIN_PROMINENCE = 6.0       # min prominence (peak vs surrounding valley)
PEAK_HEIGHT_K_MAD = 2.0         # height threshold = median + K * MAD
PEAK_HEIGHT_FRAC = 0.15         # also drop peaks shorter than this fraction
                                # of the column's strongest peak (clears
                                # vitreous / label noise)
PEAK_Y_MARGIN_PX = 40           # ignore peaks within this many pixels of
                                # the image top edge (label/border noise)
RETINA_BOTTOM_FRAC = 0.55       # retinal peaks must lie above this fraction
                                # of the panel height — anything below is
                                # the scale bar / label / Heidelberg logo
RETINA_HEIGHT_MAX_PX = 110      # all retinal-complex peaks lie within this
                                # many pixels above BM. Wide enough to span
                                # detachment-thickened retinas (10H/9H)
                                # while keeping TOP from chasing noise far
                                # above the band.
EDGE_FRAC = 0.7                 # band edge = where intensity falls to this
                                # fraction of (peak - local_floor) above floor.
                                # 0.7 = stays close to peak (the bright core
                                # of the band), so BM lower edge tracks the
                                # bottom of the bright band rather than the
                                # half-max point that extends into noise.
NEIGHBOUR_DELTA_PX = 20         # max y deviation from local trend before
                                # a raw value is rejected as outlier — must
                                # be tolerant enough that the natural retinal
                                # curvature near the optic disc is not thrown
                                # out as "noise"
TRACK_MAX_GAP_PX = 40           # tracker tolerates up to this many missing
                                # columns before stopping (keeps NaN gaps)
TRACK_TREND_WIN = 51            # rolling-median window — used to spot major
                                # outliers before the local polynomial fit
                                # (smaller window follows curvature better)
TRACK_MIN_SUPPORT = 2           # require at least this many valid raw cols
                                # within the window to support an output value
                                # (low value lets the SG curve extend to the
                                # edges of the readable region)
TRACK_MIN_RUN_LEN = 12          # drop output runs shorter than this — they
                                # are isolated noise spikes near the disc
WOBBLE_NEIGHBORHOOD_PX = 60     # apply the wobble filter only within this
                                # many cols of the disc mask. Far from the
                                # disc the SG-smoothed boundary is already
                                # the optimal path through neighbour values.
WOBBLE_GRAD_PX = 0.9            # if a boundary's per-column slope exceeds
                                # this many pixels-per-column locally, the
                                # column is wobbling — disc-induced noise
WOBBLE_WIN = 7                  # cols on each side for local slope
TRACK_SAVGOL_WIN = 91           # Savitzky-Golay window (odd). Sliding local
                                # polynomial fit smooths noise while still
                                # following the boundary's natural curvature.
TRACK_SAVGOL_DEG = 3            # SG polynomial order per local window
TRACK_OUTLIER_PASSES = 3        # iterative outlier rejection passes
DISC_TOP_FRAC = 0.15            # 'vitreous' = top this fraction of panel
                                # — wide enough to capture disc stalks
                                # that don't reach the very image top
                                # (combined with the connected-run check
                                # to avoid catching scattered noise).
DISC_BRIGHT_THRESH = 100        # intensity defining 'bright' in vitreous
DISC_MIN_BRIGHT_FRAC = 0.10     # bright fraction in vitreous => disc column
DISC_MIN_CONN_RUN = 15          # disc stalk = a connected vertical run of
                                # bright pixels at least this long. Real
                                # stalks form a continuous bright line
                                # (typically 20-40 px tall). Noise specks
                                # rarely produce more than 8-12 px runs.
DISC_DILATE_PX = 12             # widen the disc mask by this many cols on
                                # each side. Kept narrow because the stalk
                                # is well-defined; wider dilate eats into
                                # readable retina around the disc.
COLUMN_MIN_PEAK_HEIGHT = 60     # below this, the column has too weak a
                                # retinal signal to trust — used to clip
                                # off the broken / shadowed edges of the
                                # B-scan where the band fades into noise
ANAT_MIN_TOP_ONL_PX = 5         # ONL must be at least this far below TOP
ANAT_MIN_ONL_BM_PX = 6          # BM must be at least this far below ONL
ANAT_MAX_TOTAL_PX = 130         # BM - TOP must be at most this many px
                                # (mouse retina total thickness incl. detach)
MIN_PEAK_GAP_PX = 10            # required gap between BM peak and ONL peak
                                # — large enough that the ONL peak is a
                                # separate retinal band, not BM's shoulder
ONL_MIN_GAP_FROM_BM_PX = 12     # minimum vertical gap between final ONL
                                # and BM positions (anatomical lower bound
                                # for mouse retina)
ONL_FRAC_FROM_TOP_MIN = 0.40    # ONL must be at least this fraction of
                                # (BM-TOP) below TOP — keeps ONL inside
                                # the dark ONL layer rather than up among
                                # the IPL/INL bright bands (user's yellow
                                # ONL region sits ~50% from TOP toward BM)
ONL_FRAC_FROM_TOP_MAX = 0.70    # ONL must be at most this fraction of
                                # (BM-TOP) below TOP — keeps ONL above
                                # the BM band itself
DET_SEARCH_ABOVE_BM_PX = 28     # only search this many px above BM for cavity
                                # (avoids vitreous gaps when ONL misdetects)
DET_MIN_DIP_DEPTH = 50          # minimum dip depth (intensity drop from
                                # surrounding peaks) for the cavity to count
DET_MAX_CAVITY_INTENSITY = 110  # cavity minimum must be at most this dark
                                # (rejects normal outer-retina shoulders).
                                # Slightly looser to catch faint cavities
                                # that fade toward the image edges.
DET_EDGE_FRAC = 0.5             # DET edges = where intensity rises to this
                                # fraction of (peak - cavity_min)
DET_MIN_RUN_PX = 30             # minimum horizontal run of cavity columns
DET_MIN_FRAC = 0.04             # cavity columns must exceed this share of
                                # measurable columns to mark image-level det.


@dataclass
class BoundaryResult:
    """All boundary arrays in B-scan-relative coords."""
    TOP: np.ndarray
    ONL: np.ndarray
    BM: np.ndarray
    DET_top: np.ndarray
    DET_bottom: np.ndarray
    has_detachment: bool
    center_x_local: int  # x offset inside the B-scan crop

    def to_absolute(self, layout) -> "BoundaryResult":
        """Return a copy whose coords are in the original image frame."""
        def shift_y(a: np.ndarray) -> np.ndarray:
            out = a + layout.top_y
            out[np.isnan(a)] = np.nan
            return out
        return BoundaryResult(
            TOP=shift_y(self.TOP),
            ONL=shift_y(self.ONL),
            BM=shift_y(self.BM),
            DET_top=shift_y(self.DET_top),
            DET_bottom=shift_y(self.DET_bottom),
            has_detachment=self.has_detachment,
            center_x_local=self.center_x_local,
        )


# ---------------------------------------------------------------------------
# Per-column band candidates
# ---------------------------------------------------------------------------

def _complex_upper_edge(profile: np.ndarray, bm_peak: int) -> float:
    """Upper edge of the bright retinal complex containing BM peak.

    The complex is the contiguous run of "above-background" values that
    contains BM peak. Background = median + K * MAD on the heavily-smoothed
    profile (smoothing collapses sub-bands so the complex behaves as one
    bright region).

    Returns the topmost y where the smoothed profile is still above the
    background threshold. NaN if the rise can't be located.
    """
    if bm_peak < 1:
        return float("nan")
    p_env = gaussian_filter1d(profile.astype(np.float32), TOP_ENVELOPE_SIGMA)
    med = float(np.median(p_env))
    mad = float(np.median(np.abs(p_env - med)) + 1e-3)
    bg_mad = med + TOP_BACKGROUND_K * mad
    bg_peak = TOP_PEAK_FRAC * float(p_env[bm_peak])
    background = max(bg_mad, bg_peak)
    if p_env[bm_peak] <= background:
        return float("nan")
    # Limit how far above BM the walk can go: anatomically, retinal total
    # thickness is bounded. Walking past this range usually means we're
    # following bright noise specks in the vitreous, not the band.
    min_y = max(0, bm_peak - RETINA_HEIGHT_MAX_PX)
    y = bm_peak
    while y > min_y and p_env[y] > background:
        y -= 1
    return float(y + 1)


def _peak_lower_edge(p: np.ndarray, peak: int) -> float:
    """First y > peak where p[y] falls to EDGE_FRAC of (peak_h - floor_below).

    `floor_below` is the minimum intensity in [peak, peak + 25].
    Returns NaN if no such y exists (band runs off the bottom).
    """
    n = len(p)
    end = min(n, peak + 30)
    if end - peak < 2:
        return float("nan")
    floor = float(p[peak:end].min())
    peak_h = float(p[peak])
    edge_v = floor + EDGE_FRAC * (peak_h - floor)
    for y in range(peak + 1, end):
        if p[y] <= edge_v:
            return float(y)
    return float("nan")


def _peak_upper_edge(p: np.ndarray, peak: int) -> float:
    """First y < peak where p[y] falls to EDGE_FRAC of (peak_h - floor_above).

    `floor_above` is the minimum intensity in [peak - 25, peak].
    """
    start = max(0, peak - 30)
    if peak - start < 2:
        return float("nan")
    floor = float(p[start:peak + 1].min())
    peak_h = float(p[peak])
    edge_v = floor + EDGE_FRAC * (peak_h - floor)
    for y in range(peak - 1, start - 1, -1):
        if p[y] <= edge_v:
            return float(y)
    return float("nan")


def _local_min_between(p: np.ndarray, y_lo: int, y_hi: int) -> int:
    """Return y of the minimum value in [y_lo, y_hi]."""
    lo = max(0, y_lo)
    hi = min(len(p), y_hi + 1)
    if hi <= lo:
        return y_lo
    return int(lo + np.argmin(p[lo:hi]))


def _column_candidates(profile: np.ndarray) -> dict:
    """Find TOP / ONL / BM candidates from a single 1D vertical profile.

    Method: detect all bright peaks via `find_peaks`, then assign
    semantics by spatial order:
      - BM peak     = lowest peak (largest y).
      - ONL peak    = next peak above BM, with at least MIN_PEAK_GAP_PX
                      separation, and a real valley between.
      - TOP peak    = topmost peak (smallest y), distinct from BM.
    Edges are then derived from each peak (see _peak_*_edge).
    """
    p = gaussian_filter1d(profile.astype(np.float32), SMOOTH_SIGMA_Y)
    n = len(p)
    med = float(np.median(p))
    mad = float(np.median(np.abs(p - med)) + 1e-3)
    height = med + PEAK_HEIGHT_K_MAD * mad
    raw_peaks, props = find_peaks(p, height=height,
                                  distance=PEAK_MIN_DIST_PX,
                                  prominence=PEAK_MIN_PROMINENCE)
    out = {"TOP": None, "ONL": None, "BM": None,
           "conf": {"TOP": 0.0, "ONL": 0.0, "BM": 0.0}}
    if len(raw_peaks) == 0:
        return out

    raw_proms = np.asarray(props.get("prominences", np.zeros(len(raw_peaks))),
                           dtype=np.float32)
    raw_h = np.asarray([p[y] for y in raw_peaks], dtype=np.float32)

    # Filter peaks:
    #   1. drop peaks within PEAK_Y_MARGIN_PX of the top (label/border noise)
    #   2. drop peaks below RETINA_BOTTOM_FRAC of the panel (scale bar / logo)
    #   3. drop peaks much weaker than the strongest peak in this column
    bottom_limit = int(n * RETINA_BOTTOM_FRAC)
    keep = (raw_peaks >= PEAK_Y_MARGIN_PX) & (raw_peaks <= bottom_limit)
    if raw_h.size:
        keep &= raw_h >= PEAK_HEIGHT_FRAC * float(raw_h.max())

    peaks = [int(y) for y in raw_peaks[keep]]
    proms = list(raw_proms[keep])
    if not peaks:
        return out

    # Sort by y ascending; keep prominences aligned.
    order = sorted(range(len(peaks)), key=lambda i: peaks[i])
    peaks = [peaks[i] for i in order]
    proms = [proms[i] for i in order]
    prom_by_y = {peaks[i]: proms[i] for i in range(len(peaks))}

    bm_peak = peaks[-1]
    out["BM"] = _peak_lower_edge(p, bm_peak)

    # Retinal complex window: peaks within RETINA_HEIGHT_MAX_PX above BM.
    complex_peaks = [y for y in peaks
                     if bm_peak - RETINA_HEIGHT_MAX_PX <= y <= bm_peak]

    # ONL detection — explicit "ONL layer" identification per the user's
    # yellow-highlighted annotation:
    #
    #   1. Walk UP from the BM peak through its descending shoulder until
    #      intensity drops to the BM band's lower-shoulder level
    #      (= "BM band ends here, ONL layer begins").
    #   2. Continue UP through the relatively-darker ONL layer until
    #      intensity rises again (= "OPL/INL bright band begins,
    #      ONL layer ends here"). That y is the ONL boundary.
    #
    # If no clear ONL layer is found (very thin retina), fall back to the
    # local-minimum rule between the BM peak and the next prominent peak.
    # ONL = blend of (local min above ONL peak) and (ONL peak itself).
    # The 60/40 weight toward the valley places ONL on the upper-edge
    # shoulder of the ONL/OPL bright band — exactly where the user-drawn
    # cyan annotation line traces.
    onl_peak = None
    for i in range(len(complex_peaks) - 2, -1, -1):
        if bm_peak - complex_peaks[i] >= MIN_PEAK_GAP_PX:
            onl_peak = complex_peaks[i]
            break
    if onl_peak is not None:
        idx = complex_peaks.index(onl_peak)
        upper_bound = complex_peaks[idx - 1] if idx >= 1 \
            else max(0, onl_peak - 25)
        valley = _local_min_between(p, upper_bound, onl_peak - 1)
        out["ONL"] = float(0.6 * valley + 0.4 * onl_peak)

    # TOP: upper edge of the entire retinal bright complex containing BM peak.
    # This works whether the complex has multiple internal sub-peaks or not,
    # so it produces a smooth continuous boundary along the curvature of
    # the retina rather than fragmenting on weak internal peaks.
    out["TOP"] = _complex_upper_edge(profile.astype(np.float32), bm_peak)

    def _conf(y):
        if y is None:
            return 0.0
        return float(np.clip(prom_by_y.get(int(y), 0.0) / 30.0, 0.0, 1.0))

    out["conf"]["BM"] = _conf(bm_peak)
    out["conf"]["ONL"] = _conf(onl_peak) if onl_peak is not None else 0.0
    # TOP rides on the same complex as BM, so it inherits BM's confidence.
    out["conf"]["TOP"] = out["conf"]["BM"] if not np.isnan(out["TOP"] or 0) else 0.0
    return out


# ---------------------------------------------------------------------------
# Side-aware tracking
# ---------------------------------------------------------------------------

def _rolling_median(arr: np.ndarray, win: int) -> np.ndarray:
    """NaN-aware rolling median. `win` must be odd."""
    n = len(arr)
    half = win // 2
    out = np.full(n, np.nan, dtype=np.float32)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        seg = arr[lo:hi]
        seg = seg[~np.isnan(seg)]
        if seg.size > 0:
            out[i] = float(np.median(seg))
    return out


def _rolling_count(arr: np.ndarray, win: int) -> np.ndarray:
    """Per-position count of finite values in a rolling window."""
    finite = (~np.isnan(arr)).astype(np.int32)
    n = len(arr)
    half = win // 2
    out = np.zeros(n, dtype=np.int32)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = int(finite[lo:hi].sum())
    return out


def _detect_disc_columns(bscan_gray: np.ndarray) -> np.ndarray:
    """Return per-column bool mask of optic-disc / disrupted columns.

    The disc creates a vertical bright stalk extending well above the
    retinal complex. We flag columns whose top-of-image (vitreous) band
    contains a significant fraction of bright pixels, then **dilate** the
    mask by ``DISC_DILATE_PX`` on each side so the disrupted neighbourhood
    around the stalk is also marked unreadable (the layers blur into the
    stalk for many pixels on each side).
    """
    H, W = bscan_gray.shape
    top_band_h = int(H * DISC_TOP_FRAC)
    top_band = bscan_gray[:top_band_h]
    bright = top_band > DISC_BRIGHT_THRESH

    # Per-column longest CONNECTED vertical run of bright pixels.
    # Real disc stalks form a continuous bright line; noise specks are
    # scattered and only produce short runs.
    longest_run = np.zeros(W, dtype=np.int32)
    for x in range(W):
        col = bright[:, x]
        cur = 0
        for v in col:
            if v:
                cur += 1
                if cur > longest_run[x]:
                    longest_run[x] = cur
            else:
                cur = 0

    # Combine criteria: enough bright fraction AND a long connected run.
    bright_frac = bright.sum(axis=0).astype(np.float32) / max(top_band_h, 1)
    smoothed_frac = gaussian_filter1d(bright_frac, 1.5)
    smoothed_run = gaussian_filter1d(longest_run.astype(np.float32), 1.5)
    raw_mask = (smoothed_frac > DISC_MIN_BRIGHT_FRAC) \
        & (smoothed_run >= DISC_MIN_CONN_RUN)

    # Anatomical: the optic disc only sits near the centre of the B-scan.
    # Bright artefacts at the left/right edges (IR leakage, scanner noise)
    # are NOT discs, even if they pass the brightness/run tests.
    center_only = np.zeros(W, dtype=bool)
    cx = W // 2
    half_disc_window = int(W * 0.30)   # ± 30% of width
    center_only[max(0, cx - half_disc_window):
                min(W, cx + half_disc_window + 1)] = True
    raw_mask = raw_mask & center_only

    if not raw_mask.any():
        return raw_mask

    # Morphological dilation by DISC_DILATE_PX on each side.
    out = raw_mask.copy()
    idx = np.where(raw_mask)[0]
    for d in range(1, DISC_DILATE_PX + 1):
        out[np.clip(idx - d, 0, W - 1)] = True
        out[np.clip(idx + d, 0, W - 1)] = True
    return out


def _track_boundary(raw_y: np.ndarray, raw_conf: np.ndarray,
                    center_x: int) -> np.ndarray:
    """Robust per-side tracker that outputs a smooth, NaN-respecting trace.

    Per side (left of `center_x`, right of `center_x`):
      1. Compute a first rolling-median trend of raw_y (NaN-aware).
      2. Reject outliers — raw values further than NEIGHBOUR_DELTA_PX from
         the trend. (These are spurious peaks from disc-disrupted columns
         or one-off detector failures.)
      3. Compute a second trend from the inlier-only series.
      4. **Output the smoothed trend itself** (not the raw values) so the
         line is naturally continuous and free of per-column jitter.
      5. Where the trend window has too few supporting columns, leave NaN —
         this gives a real gap in genuinely unreadable regions instead of
         interpolating across them.
    """
    n = len(raw_y)
    out = np.full(n, np.nan, dtype=np.float32)
    if n == 0:
        return out

    sides = [(0, center_x), (center_x, n)]
    for s, e in sides:
        if e <= s:
            continue
        seg_y = raw_y[s:e].copy()
        seg_conf = raw_conf[s:e]
        seg_y[np.isnan(seg_y) | (seg_conf < 0.03)] = np.nan

        if np.all(np.isnan(seg_y)):
            continue

        # Iterative outlier rejection using rolling median as the seed:
        # raw values that deviate too far from a robust local median are
        # discarded, then the median is recomputed on the survivors.
        inliers = seg_y.copy()
        for _ in range(TRACK_OUTLIER_PASSES):
            trend = _rolling_median(inliers, win=TRACK_TREND_WIN)
            diff = np.abs(inliers - trend)
            inliers[diff > NEIGHBOUR_DELTA_PX] = np.nan

        # Savitzky-Golay smoothing: a sliding-window polynomial fit. This
        # preserves the boundary's natural curvature (low-order polynomial
        # at each window) while suppressing per-column noise. NaN gaps in
        # the inlier series are bridged by linear interpolation BEFORE the
        # SG pass, so the smoothed line continues naturally across small
        # gaps where the raw detector failed.
        valid = ~np.isnan(inliers)
        smoothed = np.full_like(inliers, np.nan)
        if int(valid.sum()) >= TRACK_SAVGOL_DEG + 2:
            xs = np.arange(len(inliers))
            interp = np.interp(xs, xs[valid], inliers[valid])
            win = min(TRACK_SAVGOL_WIN, (len(inliers) // 2) * 2 - 1)
            if win > TRACK_SAVGOL_DEG and win % 2 == 1:
                sg = savgol_filter(interp, window_length=win,
                                   polyorder=TRACK_SAVGOL_DEG)
                # Use SG curve everywhere within this side — small gaps
                # (raw detection misses) get filled by the smoothed curve,
                # exactly as the user expects ("연결된 선은 끊어지지 않게").
                # Wide gaps (disc area) get re-masked by the support filter.
                smoothed = sg.astype(np.float32)

        # Coverage gating: NaN out only where local inlier density is too low
        # to trust the smoothed curve. This isolates true "unreadable" gaps
        # (the optic disc, far edges) while keeping continuous fill across
        # short noise-induced dropouts.
        support = _rolling_count(inliers, win=TRACK_TREND_WIN)
        smoothed[support < TRACK_MIN_SUPPORT] = np.nan

        out[s:e] = smoothed

    return out


# ---------------------------------------------------------------------------
# Detachment
# ---------------------------------------------------------------------------

def _detect_detachment(bscan_gray: np.ndarray, ONL: np.ndarray, BM: np.ndarray,
                       ) -> Tuple[np.ndarray, np.ndarray, bool]:
    """Find the hyporeflective cavity between ONL and BM.

    Per column where ONL and BM are both present:
      - Look at the intensity profile in (ONL, BM).
      - A "cavity" is the longest run of dark pixels there. It must be
        sufficiently dark relative to that column's local bright bands and
        thick enough to count.
      - If detected, record DET_top and DET_bottom for that column.

    Image-level detachment flag requires enough cavity columns AND a
    horizontally connected run of them.
    """
    H, W = bscan_gray.shape
    DET_top = np.full(W, np.nan, dtype=np.float32)
    DET_bot = np.full(W, np.nan, dtype=np.float32)

    for x in range(W):
        y_onl = ONL[x]
        y_bm = BM[x]
        if np.isnan(y_onl) or np.isnan(y_bm):
            continue
        y0 = max(int(y_onl) + 1, int(y_bm) - DET_SEARCH_ABOVE_BM_PX)
        y1 = int(y_bm) - 1
        if y1 - y0 < 6:
            continue

        col = bscan_gray[:, x].astype(np.float32)
        seg = col[y0:y1 + 1]
        # Cavity = a local minimum strictly inside the search window with
        # significant dip depth on both sides. This rejects vitreous gaps
        # (which slope away from the boundary) and inter-band shoulders
        # (which dip only marginally).
        i_min = int(np.argmin(seg))
        # Reject if the min sits at the window boundary — cavity must have a
        # peak on each side within the window.
        if i_min < 2 or i_min > len(seg) - 3:
            continue
        cavity_min = float(seg[i_min])
        peak_above = float(seg[:i_min].max())
        peak_below = float(seg[i_min + 1:].max())
        dip_depth = min(peak_above, peak_below) - cavity_min
        if dip_depth < DET_MIN_DIP_DEPTH:
            continue
        if cavity_min > DET_MAX_CAVITY_INTENSITY:
            continue

        # Find DET edges by walking outward from the cavity min until intensity
        # rises to half-way between min and the surrounding peak.
        edge_above = cavity_min + DET_EDGE_FRAC * (peak_above - cavity_min)
        edge_below = cavity_min + DET_EDGE_FRAC * (peak_below - cavity_min)

        i_top = i_min
        while i_top > 0 and seg[i_top] < edge_above:
            i_top -= 1
        i_bot = i_min
        while i_bot < len(seg) - 1 and seg[i_bot] < edge_below:
            i_bot += 1
        DET_top[x] = y0 + i_top
        DET_bot[x] = y0 + i_bot

    # Image-level decision: enough cavity columns AND a connected run.
    measurable = ~(np.isnan(ONL) | np.isnan(BM))
    n_meas = int(measurable.sum())
    has_det_col = ~np.isnan(DET_top)
    n_det = int(has_det_col.sum())

    if n_meas == 0 or n_det / max(n_meas, 1) < DET_MIN_FRAC:
        DET_top[:] = np.nan
        DET_bot[:] = np.nan
        return DET_top, DET_bot, False

    # Check for a connected run of >= DET_MIN_RUN_PX columns.
    runs_lengths = []
    cur = 0
    for v in has_det_col:
        if v:
            cur += 1
        else:
            if cur > 0:
                runs_lengths.append(cur)
            cur = 0
    if cur > 0:
        runs_lengths.append(cur)
    if not runs_lengths or max(runs_lengths) < DET_MIN_RUN_PX:
        DET_top[:] = np.nan
        DET_bot[:] = np.nan
        return DET_top, DET_bot, False

    return DET_top, DET_bot, True


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def _all_column_peaks(profile: np.ndarray) -> list[tuple[int, float, float]]:
    """Return list of (y, height, prominence) for all surviving peaks in a
    column profile, using the same filters as ``_column_candidates``."""
    p = gaussian_filter1d(profile.astype(np.float32), SMOOTH_SIGMA_Y)
    n = len(p)
    med = float(np.median(p))
    mad = float(np.median(np.abs(p - med)) + 1e-3)
    height_thresh = med + PEAK_HEIGHT_K_MAD * mad
    raw_peaks, props = find_peaks(p, height=height_thresh,
                                  distance=PEAK_MIN_DIST_PX,
                                  prominence=PEAK_MIN_PROMINENCE)
    if len(raw_peaks) == 0:
        return []
    raw_proms = np.asarray(props.get("prominences", np.zeros(len(raw_peaks))),
                           dtype=np.float32)
    raw_h = np.asarray([p[y] for y in raw_peaks], dtype=np.float32)
    bottom_limit = int(n * RETINA_BOTTOM_FRAC)
    keep = (raw_peaks >= PEAK_Y_MARGIN_PX) & (raw_peaks <= bottom_limit)
    if raw_h.size:
        keep &= raw_h >= PEAK_HEIGHT_FRAC * float(raw_h.max())
    return [(int(raw_peaks[i]), float(raw_h[i]), float(raw_proms[i]))
            for i in range(len(raw_peaks)) if keep[i]]


def _reselect_bm_by_trend(bs_smooth: np.ndarray, raw_BM: np.ndarray,
                          col_peaks: list[list[tuple[int, float, float]]]
                          ) -> np.ndarray:
    """Per-column, replace the BM peak with the one closest to the global
    trend of BM positions. This corrects columns where the bottommost peak
    is a noise/choroid spike below the real BM band — the column has the
    real BM peak in its candidate list but it was not chosen because of the
    "bottommost" rule. The trend votes for the consistent column.
    """
    W = bs_smooth.shape[1]
    if W == 0 or np.all(np.isnan(raw_BM)):
        return raw_BM

    trend = _rolling_median(raw_BM, win=131)
    out = raw_BM.copy()
    for x in range(W):
        if np.isnan(trend[x]):
            continue
        peaks = col_peaks[x]
        if not peaks:
            continue
        # peaks closer to trend, weighted by prominence (so very weak peaks
        # are tie-broken against)
        target = trend[x]
        best_y = None
        best_score = -np.inf
        for (y, h, prom) in peaks:
            dist = abs(y - target)
            if dist > 25:
                continue
            score = prom - dist  # closer + more prominent wins
            if score > best_score:
                best_score = score
                best_y = y
        if best_y is None:
            continue
        # Replace BM with the lower-edge of the chosen peak.
        new_bm = _peak_lower_edge(
            gaussian_filter1d(bs_smooth[:, x].astype(np.float32),
                              SMOOTH_SIGMA_Y),
            best_y,
        )
        if not np.isnan(new_bm):
            out[x] = new_bm
    return out


def analyze(oct_image: OctImage) -> BoundaryResult:
    """Run the full per-column boundary detection on an OctImage."""
    bs = oct_image.bscan_gray.astype(np.float32)
    H, W = bs.shape

    # Light horizontal smoothing helps band coherence across columns without
    # dragging boundaries between unrelated regions.
    bs_smooth = gaussian_filter1d(bs, SMOOTH_SIGMA_X_BAND, axis=1)

    raw_TOP = np.full(W, np.nan, dtype=np.float32)
    raw_ONL = np.full(W, np.nan, dtype=np.float32)
    raw_BM = np.full(W, np.nan, dtype=np.float32)
    conf_TOP = np.zeros(W, dtype=np.float32)
    conf_ONL = np.zeros(W, dtype=np.float32)
    conf_BM = np.zeros(W, dtype=np.float32)
    col_peak_h = np.zeros(W, dtype=np.float32)   # max retinal peak per col
    col_peaks: list[list[tuple[int, float, float]]] = [[] for _ in range(W)]

    for x in range(W):
        cand = _column_candidates(bs_smooth[:, x])
        if cand["TOP"] is not None:
            raw_TOP[x] = cand["TOP"]
            conf_TOP[x] = cand["conf"]["TOP"]
        if cand["ONL"] is not None:
            raw_ONL[x] = cand["ONL"]
            conf_ONL[x] = cand["conf"]["ONL"]
        if cand["BM"] is not None:
            raw_BM[x] = cand["BM"]
            conf_BM[x] = cand["conf"]["BM"]
        col_peaks[x] = _all_column_peaks(bs_smooth[:, x])
        if col_peaks[x]:
            col_peak_h[x] = max(h for (_, h, _) in col_peaks[x])

    # Weak-signal columns: where the strongest retinal peak is too dim to
    # reliably indicate a band, the column is effectively unreadable. These
    # tend to live at the broken/shadowed edges of the B-scan. Clip them.
    weak_mask = col_peak_h < COLUMN_MIN_PEAK_HEIGHT
    raw_TOP[weak_mask] = np.nan
    raw_ONL[weak_mask] = np.nan
    raw_BM[weak_mask] = np.nan

    # Globally-consistent BM: re-pick each column's BM peak from its
    # candidate list, biased toward the global median trend. This removes
    # the "noise spike below BM" failure mode without introducing any
    # image-specific tuning — it just enforces that adjacent columns'
    # detections should be consistent.
    raw_BM = _reselect_bm_by_trend(bs_smooth, raw_BM, col_peaks)

    center_local = oct_image.layout.center_x - oct_image.layout.left_x

    TOP = _track_boundary(raw_TOP, conf_TOP, center_local)
    ONL = _track_boundary(raw_ONL, conf_ONL, center_local)
    BM = _track_boundary(raw_BM, conf_BM, center_local)

    # Anatomical sanity for ONL with trend-based correction.
    # Step 1: identify ONL cols that look wrong (above TOP, too close to
    #         BM, or jumping far from neighbours). NaN them temporarily.
    # Step 2: build a clean trend from the surviving cols.
    # Step 3: refill the NaN'd cols using the trend, but only where a
    #         smoothly-interpolated neighbour-based estimate exists.
    has_to = ~(np.isnan(TOP) | np.isnan(ONL))
    has_ob = ~(np.isnan(ONL) | np.isnan(BM))
    has_tb = ~(np.isnan(TOP) | np.isnan(BM))
    has_all3 = has_to & has_ob & has_tb
    onl_above_top = has_to & ((ONL - TOP) < ANAT_MIN_TOP_ONL_PX)
    onl_too_close_to_bm = has_ob & ((BM - ONL) < ONL_MIN_GAP_FROM_BM_PX)
    # Proportional constraint: ONL must sit in the upper portion of the
    # retinal complex (between TOP and BM). The user's annotation places
    # ONL roughly 1/3 of the way down from TOP to BM; values below the
    # midpoint are almost certainly mis-detections that picked up part
    # of the BM band as the ONL band.
    thickness = BM - TOP
    frac = np.full_like(ONL, np.nan)
    frac[has_all3] = (ONL[has_all3] - TOP[has_all3]) / np.maximum(
        thickness[has_all3], 1.0)
    onl_too_low = has_all3 & (frac > ONL_FRAC_FROM_TOP_MAX)
    onl_too_high = has_all3 & (frac < ONL_FRAC_FROM_TOP_MIN)
    bad_onl_initial = (onl_above_top | onl_too_close_to_bm
                       | onl_too_low | onl_too_high)

    ONL_clean = ONL.copy()
    ONL_clean[bad_onl_initial] = np.nan
    # Reject cols that jump far from a robust local median computed on
    # the cleaned series — these are spurious peaks the band detector
    # picked up.
    onl_trend_clean = _rolling_median(ONL_clean, win=51)
    onl_diff = np.abs(ONL_clean - onl_trend_clean)
    onl_jump = (~np.isnan(ONL_clean)) & (~np.isnan(onl_trend_clean)) \
        & (onl_diff > NEIGHBOUR_DELTA_PX)
    ONL_clean[onl_jump] = np.nan

    # Refit the trend after outlier removal — this is the "smoothed
    # neighbour-based estimate" the user wants for refilling.
    onl_trend = _rolling_median(ONL_clean, win=51)

    # Now produce the final ONL: keep clean values where they exist,
    # otherwise use the trend if it's defined nearby. Cols where neither
    # the original detection nor the trend exists stay NaN (genuine gaps).
    ONL = ONL_clean.copy()
    needs_fill = np.isnan(ONL) & (~np.isnan(onl_trend))
    ONL[needs_fill] = onl_trend[needs_fill]

    # If BM-TOP is unreasonably large, the column is genuinely broken —
    # drop both endpoints (and ONL too if it's there).
    too_thick = has_tb & ((BM - TOP) > ANAT_MAX_TOTAL_PX)
    TOP[too_thick] = np.nan
    BM[too_thick] = np.nan
    ONL[too_thick] = np.nan

    # Proportional ONL: in low-resolution areas the band peak picks up
    # noise and ONL drifts. Anchor it to the consistent fraction of the
    # TOP–BM thickness observed in the well-detected columns.
    # The retina's layer thicknesses are nearly proportional across
    # adjacent A-scans, so this gives a smooth ONL that follows the
    # TOP/BM curvature exactly.
    has_all3 = (~np.isnan(TOP)) & (~np.isnan(ONL)) & (~np.isnan(BM))
    if int(has_all3.sum()) >= 30:
        thickness_arr = BM - TOP
        ratio_arr = np.full_like(ONL, np.nan)
        ratio_arr[has_all3] = (ONL[has_all3] - TOP[has_all3]) \
            / np.maximum(thickness_arr[has_all3], 1.0)
        median_ratio = float(np.nanmedian(ratio_arr))
        # Blend the per-column band detection with the proportional value
        # so ONL stays close to the band where confident, but is held to
        # the proportional position where the band gets noisy.
        prop_onl = TOP + median_ratio * (BM - TOP)
        valid_band = ~np.isnan(ONL)
        deviation = np.abs(ONL - prop_onl)
        # If ONL deviates by more than 8 px from the proportional value,
        # the band detection has drifted — replace with the proportional.
        replace = valid_band & (~np.isnan(prop_onl)) & (deviation > 8.0)
        ONL[replace] = prop_onl[replace]
        # And refill any remaining NaNs (where band detection failed) with
        # the proportional value if TOP and BM are both known.
        nan_with_prop = np.isnan(ONL) & (~np.isnan(prop_onl))
        ONL[nan_with_prop] = prop_onl[nan_with_prop]

    # Strong final Gaussian smoothing on ONL — the user requires the line
    # to be a continuously gentle curve. We interpolate across the small
    # NaN gaps for the smoothing pass and re-mask afterwards so genuine
    # gaps (disc, edges) stay NaN.
    onl_valid = ~np.isnan(ONL)
    if onl_valid.any():
        xs_arr = np.arange(len(ONL))
        interp_onl = np.interp(xs_arr, xs_arr[onl_valid], ONL[onl_valid])
        ONL_smooth = gaussian_filter1d(interp_onl, sigma=10.0)
        ONL = np.where(onl_valid, ONL_smooth, np.nan).astype(np.float32)

    # Robust polynomial-fit drift correction. A wide-cluster outlier (e.g.
    # 50+ adjacent cols all dragged into noise) defeats a rolling-median
    # trend because the median follows the majority within the window. A
    # global polynomial fit isn't fooled — the smooth retinal curve forces
    # outliers to stand out as residuals, even when they cluster.
    def _robust_poly_correct(arr: np.ndarray, deg: int = 4,
                             passes: int = 5, thresh: float = 5.0) -> None:
        """In-place: replace cols where arr deviates from a robust
        global polynomial fit by more than ``thresh`` px."""
        n = len(arr)
        valid = ~np.isnan(arr)
        if int(valid.sum()) < deg + 2:
            return
        xs_all = np.arange(n, dtype=np.float64)
        # Centre and scale x for numerical stability.
        x_mid = float(xs_all[valid].mean())
        x_scale = float(xs_all[valid].std() + 1e-6)
        xn = (xs_all - x_mid) / x_scale
        inliers = valid.copy()
        for _ in range(passes):
            if int(inliers.sum()) < deg + 2:
                break
            coeffs = np.polyfit(xn[inliers], arr[inliers], deg)
            pred = np.polyval(coeffs, xn)
            resid = np.abs(arr - pred)
            new_inliers = valid & (resid <= thresh)
            if new_inliers.sum() == inliers.sum():
                inliers = new_inliers
                break
            inliers = new_inliers
        if int(inliers.sum()) < deg + 2:
            return
        coeffs = np.polyfit(xn[inliers], arr[inliers], deg)
        pred = np.polyval(coeffs, xn).astype(np.float32)
        # Replace outliers (cols where original deviated >= thresh from poly)
        # with the polynomial value, keeping inliers as-is.
        bad = valid & (np.abs(arr - pred) > thresh)
        arr[bad] = pred[bad]

    _robust_poly_correct(BM, thresh=4.0)
    _robust_poly_correct(TOP, thresh=4.0)
    _robust_poly_correct(ONL, thresh=4.0)

    # Density check on BM: the boundary must lie at a *bright* pixel (the
    # lower edge of the bright BM band). If the current BM y points into a
    # dark/noise pixel, walk upward to the nearest bright pixel.
    # The user's words: "확실한 BM 경계를 잡았으면 경계의 밀도를 따라가야한다"
    # — once a confident BM boundary is found, the line must follow the
    # band's density rather than drift into noise.
    bs_smooth_v = gaussian_filter1d(bs.astype(np.float32), 2.0, axis=0)
    DENSITY_MIN_INTENSITY = 100.0   # below this is "dark / noise area"
    DENSITY_SEARCH_PX = 25          # walk up at most this many px to find brightness
    for x in range(W):
        y = BM[x]
        if np.isnan(y):
            continue
        yi = int(round(y))
        if yi < 0 or yi >= H:
            continue
        if bs_smooth_v[yi, x] >= DENSITY_MIN_INTENSITY:
            continue
        # Walk upward to find a bright pixel.
        for dy in range(1, DENSITY_SEARCH_PX + 1):
            yy = yi - dy
            if yy < 0:
                break
            if bs_smooth_v[yy, x] >= DENSITY_MIN_INTENSITY:
                BM[x] = float(yy)
                break

    # Mask out optic-disc / vitreous-protrusion columns: these are visually
    # broken or smeared, and the spec says unreadable regions should be
    # left blank rather than painted with a guess.
    disc_mask = _detect_disc_columns(oct_image.bscan_gray)
    # Additional disc detection: find cols where TOP got pulled up by the
    # stalk (much smaller y than the local trend). These columns are inside
    # the disrupted disc area even when no bright vitreous pixel triggered
    # the primary disc detector.
    # The disc is anatomically only near the centre of the B-scan, so
    # the trend-based disc filters should only fire there. At the edges
    # any deviation is more likely a localised artifact / shadow that we
    # should smooth out via trend, not delete.
    center_local = oct_image.layout.center_x - oct_image.layout.left_x
    near_center = np.zeros_like(disc_mask)
    half_disc_search_px = 120   # narrower: disc is small, avoid swallowing
                                # readable retina around it
    near_center[max(0, center_local - half_disc_search_px):
                min(W, center_local + half_disc_search_px + 1)] = True

    top_trend = _rolling_median(TOP, win=201)
    top_pulled_up = (~np.isnan(TOP)) & (~np.isnan(top_trend)) \
        & (top_trend - TOP > 15.0) & near_center
    bm_trend = _rolling_median(BM, win=201)
    bm_pulled_down = (~np.isnan(BM)) & (~np.isnan(bm_trend)) \
        & (BM - bm_trend > 15.0) & near_center
    disc_mask = disc_mask | top_pulled_up | bm_pulled_down

    TOP[disc_mask] = np.nan
    ONL[disc_mask] = np.nan
    BM[disc_mask] = np.nan

    # Drop isolated short runs of valid values: tiny segments stranded next
    # to the disc area are residual noise rather than real boundary, and
    # the user wants them treated as part of the disc gap.
    def _drop_short_runs(arr: np.ndarray, min_len: int) -> None:
        valid = ~np.isnan(arr)
        if not valid.any():
            return
        idx = np.where(valid)[0]
        if len(idx) == 0:
            return
        diffs = np.diff(idx)
        gap_pos = np.where(diffs > 1)[0]
        starts = np.concatenate(([idx[0]], idx[gap_pos + 1]))
        ends = np.concatenate((idx[gap_pos], [idx[-1]]))
        for s, e in zip(starts, ends):
            if (e - s + 1) < min_len:
                arr[s:e + 1] = np.nan

    _drop_short_runs(TOP, TRACK_MIN_RUN_LEN)
    _drop_short_runs(ONL, TRACK_MIN_RUN_LEN)
    _drop_short_runs(BM, TRACK_MIN_RUN_LEN)

    # Wobble filter — applied ONLY in the disc neighbourhood. Far from the
    # disc the SG curve already follows the natural slope; only near the
    # stalk are we likely to see disc-induced wobble (sudden changes in
    # slope that the trend filter didn't fully reject).
    if disc_mask.any():
        disc_cols = np.where(disc_mask)[0]
        # Mark cols within ±WOBBLE_NEIGHBORHOOD_PX of any disc col.
        near_disc = np.zeros(W, dtype=bool)
        for d in range(-WOBBLE_NEIGHBORHOOD_PX, WOBBLE_NEIGHBORHOOD_PX + 1):
            near_disc[np.clip(disc_cols + d, 0, W - 1)] = True

        for arr in (TOP, ONL, BM):
            valid = ~np.isnan(arr)
            if not valid.any():
                continue
            # Compute local slope: (y[x+w] - y[x-w]) / (2*w) using nearest
            # valid columns, NaN-aware.
            slope = np.full(W, np.nan, dtype=np.float32)
            for x in range(W):
                if not valid[x] or not near_disc[x]:
                    continue
                left = max(0, x - WOBBLE_WIN)
                right = min(W - 1, x + WOBBLE_WIN)
                yl = arr[left:x]
                yr = arr[x + 1:right + 1]
                yl_v = yl[~np.isnan(yl)]
                yr_v = yr[~np.isnan(yr)]
                if yl_v.size and yr_v.size:
                    slope[x] = (yr_v.mean() - yl_v.mean()) / max(WOBBLE_WIN, 1)
            wobble = (~np.isnan(slope)) & (np.abs(slope) > WOBBLE_GRAD_PX)
            arr[wobble] = np.nan

        # Re-drop short runs after wobble filter (it may strand tiny segments).
        _drop_short_runs(TOP, TRACK_MIN_RUN_LEN)
        _drop_short_runs(ONL, TRACK_MIN_RUN_LEN)
        _drop_short_runs(BM, TRACK_MIN_RUN_LEN)

    # Final fill pass: TOP/ONL/BM should be continuous everywhere except
    # the disc area. NaN gaps from weak signal, anatomical violations, or
    # the wobble filter get bridged by the polynomial fit so the lines
    # form a single unbroken curve through each side of the retina.
    def _fill_non_disc_gaps(arr: np.ndarray, deg: int = 4) -> None:
        valid = ~np.isnan(arr)
        if int(valid.sum()) < deg + 2:
            return
        xs_all = np.arange(W, dtype=np.float64)
        x_mid = float(xs_all[valid].mean())
        x_scale = float(xs_all[valid].std() + 1e-6)
        xn = (xs_all - x_mid) / x_scale
        coeffs = np.polyfit(xn[valid], arr[valid], deg)
        pred = np.polyval(coeffs, xn).astype(np.float32)
        # Fill non-disc cols where the boundary is currently NaN.
        fill = np.isnan(arr) & (~disc_mask)
        arr[fill] = pred[fill]

    _fill_non_disc_gaps(TOP)
    _fill_non_disc_gaps(ONL)
    _fill_non_disc_gaps(BM)

    DET_top, DET_bot, has_det = _detect_detachment(
        oct_image.bscan_gray, ONL, BM,
    )
    DET_top[disc_mask] = np.nan
    DET_bot[disc_mask] = np.nan

    return BoundaryResult(
        TOP=TOP, ONL=ONL, BM=BM,
        DET_top=DET_top, DET_bottom=DET_bot,
        has_detachment=has_det,
        center_x_local=center_local,
    )


def thickness_arrays(b: BoundaryResult, scale_um_per_px_y: float
                     ) -> dict:
    """Compute per-column thickness arrays (in µm). NaN where any required
    boundary is missing for that column."""
    valid = ~(np.isnan(b.TOP) | np.isnan(b.ONL) | np.isnan(b.BM))
    total_um = np.full_like(b.TOP, np.nan)
    outer_um = np.full_like(b.TOP, np.nan)
    total_um[valid] = (b.BM[valid] - b.TOP[valid]) * scale_um_per_px_y
    outer_um[valid] = (b.BM[valid] - b.ONL[valid]) * scale_um_per_px_y

    det_um = np.full_like(b.TOP, np.nan)
    det_valid = ~(np.isnan(b.DET_top) | np.isnan(b.DET_bottom))
    det_um[det_valid] = ((b.DET_bottom[det_valid] - b.DET_top[det_valid])
                         * scale_um_per_px_y)
    return {
        "total_thickness_um": total_um,
        "outer_thickness_um": outer_um,
        "detachment_thickness_um": det_um,
    }
