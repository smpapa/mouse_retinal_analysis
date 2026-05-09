# OCT Analysis — Design

Date: 2026-05-05
Spec source: `README_ANALYSIS_OCT.md`

## Scope

Implement OCT B-scan boundary detection for Heidelberg synthetic TIFFs in
`data/mouse_data_org/`. Extract `TOP / ONL / BM` and (when present)
`DET top / DET bottom`. Produce per-image overlay PNGs and a consolidated
Excel workbook.

## Approach

GT-guided + raw-intensity hybrid:

- The same raw-intensity pipeline runs on every image. No annotation seeds
  are baked in.
- For 4H/6H, annotation TIFFs are loaded only as reference: median |Δy|
  is logged per boundary. Annotation coords are never copied into output.

## Module layout

```
src/
  io_utils.py       TIFF load, IR/B-scan split, scale bar detection
  oct_analyzer.py   Per-column boundary detection (BM, ONL, TOP, DET top/bot)
  gt_guided.py      Annotation color extraction + GT comparison
  viz.py            Overlay rendering
  analyze_single.py Single-image entry point
  batch_process.py  Folder batch entry point
requirements.txt
```

## Detection algorithm

Per column x in the B-scan area:

1. Compute 1D vertical intensity profile, smooth (σ ≈ 1.5px).
2. Threshold with `median + k·MAD` to find bright bands (continuous runs ≥ 2px).
3. `BM` = lower edge of the bottom-most bright band.
4. `ONL` = upper edge of the next distinct bright band above BM.
5. `TOP` = upper edge of the topmost retinal bright complex.
6. Confidence per candidate: gradient strength + neighbor consistency.

Per side (left / right of `center_x`):

- Pick anchor column with highest joint confidence.
- Extend toward center while neighbors agree (Δy ≤ Δmax, conf ≥ τ).
- Stop on confidence break — leave NaN gap, never bridge sides.

## Detachment

Per column where ONL and BM both exist:

- Inspect intensity in `(ONL, BM)`. Cavity = continuous dark run with
  thickness ≥ 4px, mean intensity below image-specific dark threshold.
- Image flagged as detached if cavity columns ≥ 5% of measurable columns
  AND form a horizontally connected cluster.
- For detach columns, `DET top` and `DET bottom` are the cavity edges.
- Otherwise: `DET_*` stays NaN. Normal images get no DET overlay.

## GT comparison (4H / 6H only)

Annotation TIFF colour mapping (derived from inspection):

- BM      → magenta (high R, low G, mid B)
- TOP     → green
- ONL     → cyan / blue
- DET     → yellow

Per-column GT y is the mean y of matching colored pixels. `gt_guided` reports
per-boundary median absolute error vs raw detection.

## Outputs

Per image:

- `output/<basename>_overlay.png` — original + 1px boundary lines.
  Colour scheme: TOP green, ONL cyan, BM magenta, DET top yellow,
  DET bottom black, center grey dashed.

Batch:

- `output/oct_results.xlsx`
  - `summary` sheet — one row per image
  - one detail sheet per image with per-x measurements

## Measurement rule

Total / Outer thickness only computed where TOP, ONL, BM are all present.
Detachment thickness only where DET top and DET bottom both exist.
Units in µm via detected scale bar; fallback to folder-default µm/px.

## Constraints (from spec)

- Center-based left/right segments are independent. Never bridge.
- NaN columns are kept as gaps. Do not interpolate cosmetically.
- Annotation seed never overrides raw detection.
- `4H` overlays must contain only TOP/ONL/BM (no DET lines).
