# OCT HITL (Human-in-the-Loop) Editor — Design

Date: 2026-05-09
Spec source: this conversation
Related: `docs/plans/2026-05-05-oct-analysis-design.md`

## Scope

Add a desktop GUI that lets the user review and correct the per-image
boundary detection produced by `batch_process.py`. Corrections are saved
alongside the automatic results so both are preserved and comparable.

## Decisions (Q&A summary)

| Question | Choice |
|---|---|
| Primary purpose | Per-image override — corrected y values become the final measurement for that image |
| Tool | Python desktop GUI |
| Edit operations | Drag points + erase region (NaN) |
| Library | PySide6 |
| Navigation | Left file list + main canvas |
| Storage | Auto + corrected columns side-by-side in same xlsx |

## Module layout

```
src/
  hitl/
    __init__.py
    main.py             entry point: python src/hitl/main.py
    app.py              MainWindow + state management
    canvas.py           OverlayCanvas: image + boundary lines + edit interactions
    sidebar.py          FileListView: 96 files + corrected ✓ marker
    boundary_model.py   BoundaryEditor: per-image boundary state + undo/redo
    storage.py          load/save: read xlsx, write *_corrected columns
    overlay_render.py   render corrected overlay PNG
```

## UI layout

```
┌─────────────────────────────────────────────────────────────────┐
│  File   Edit   View   Help                            [editor]  │
├──────────────────┬──────────────────────────────────────────────┤
│  📁 Files (96)   │                                              │
│ ┌──────────────┐ │                                              │
│ │ ✓ 21_OS_4H   │ │                                              │
│ │   21_OS_4H(1)│ │       [Main canvas — edit area]              │
│ │ ✓ 21_OS_6H   │ │                                              │
│ │ ◉ 21_OS_8H   │ │                                              │
│ └──────────────┘ │                                              │
│                  │                                              │
│ Boundaries:      │                                              │
│ [✓] TOP          │                                              │
│ [✓] ONL          │                                              │
│ [✓] BM           │                                              │
│ [ ] DET          │                                              │
│                  │                                              │
│ Mode:            │                                              │
│ ◉ Drag           │                                              │
│ ○ Erase region   │                                              │
│                  │                                              │
│ [ Undo ] [Redo]  │                                              │
│ [ Save ]         │                                              │
└──────────────────┴──────────────────────────────────────────────┘
   Status: 21_OS_8H | 1535 cols | TOP edited | unsaved changes ●
```

### Interactions

- **Image select:** left-list click or ↑↓. If unsaved, confirm dialog.
- **Boundary toggle:** checkbox shows/hides each line (ignore lines you
  aren't editing).
- **Drag mode:** hover over a line → handle appears. Click + drag to
  move a point. Adjacent ±15 cols follow with a Gaussian falloff
  (σ = 5). Ctrl + drag = single column only.
- **Erase mode:** drag a rectangle → boundary inside that x range is
  set to NaN. (y is ignored — boundaries are per-column.)
- **Zoom:** Ctrl + wheel (zooms about cursor). **Pan:** right-click
  drag. `0` = fit, `1` = 100%.
- **Shortcuts:** `Ctrl+S` save, `Ctrl+Z` / `Ctrl+Y` undo/redo,
  `1`–`5` select boundary, `D` / `E` switch mode, `←` / `→` prev/next.
- **Status bar:** filename, B-scan width, edited boundaries, dirty `●`.

## Data flow

### Startup

1. Read `oct_results.xlsx` from `output/`.
2. `summary` sheet → image list and metadata.
3. Each image sheet → automatic boundary arrays (`TOP_y`, `ONL_y`, …).
4. If `*_corrected` columns exist, load them too.
5. Populate left list (✓ if any column has corrections).
6. Auto-select first image; render canvas.

### Image switch

1. Check dirty flag → `Save before switch?` if unsaved.
2. Load original TIFF via `io_utils.load_oct`.
3. `boundary_model` initialised with auto + corrected coords.
4. Render canvas.

### Drag operation

```python
def apply_drag(arr, x_local, y_new, sigma=5, ctrl_pressed=False):
    if ctrl_pressed:
        arr[x_local] = y_new
        push_undo(); return
    delta = y_new - arr[x_local]
    for dx in range(-15, 16):
        x = x_local + dx
        if 0 <= x < W and not isnan(arr[x]):
            w = exp(-0.5 * (dx / sigma) ** 2)
            arr[x] += delta * w
    push_undo()
```

### Erase operation

```python
def apply_erase(arr, x1, x2):
    arr[x1:x2 + 1] = np.nan
    push_undo()
```

### Save

1. Pull current edited arrays from `BoundaryEditor`.
2. `storage.save_corrections()`:
   - Write `*_corrected` columns into the image sheet.
   - Recompute `total_thickness_um_corrected`,
     `outer_thickness_um_corrected`,
     `detachment_thickness_um_corrected`.
   - Update `corrected_summary` sheet (one row per image).
3. `overlay_render.render_corrected_overlay()` writes
   `<basename>_overlay_corrected.png` (original
   `<basename>_overlay.png` is left untouched).
4. Clear dirty flag, refresh sidebar ✓ marker.

## Storage format

Each per-image sheet keeps automatic and corrected columns
side-by-side:

```
x | x_local | TOP_y | ONL_y | BM_y | … | total_thickness_um |
                    ↑ unchanged automatic detection ↑

TOP_y_corrected | ONL_y_corrected | BM_y_corrected |
DET_top_y_corrected | DET_bottom_y_corrected |
total_thickness_um_corrected | outer_thickness_um_corrected |
detachment_thickness_um_corrected | corrected_by_user
                    ↑ user edits + recomputed thicknesses ↑
```

Rules:
- corrected cell empty → use automatic value
- corrected cell has number → user-set value
- corrected cell holds the sentinel `"ERASED"` → explicit NaN
- `corrected_by_user` = `TRUE` when this column was edited

New `corrected_summary` sheet:

```
filename | n_corrected_cols | corrected_TOP | corrected_ONL | corrected_BM |
corrected_DET | mean_total_um | mean_total_um_corrected | edit_timestamp
```

### Output files

- `oct_results.xlsx` — same file, columns / sheets added in place.
- `<basename>_overlay_corrected.png` — corrected overlay, written
  alongside the existing `<basename>_overlay.png`.

### Recovery

- Re-running automatic batch refreshes the auto columns; corrected
  columns are preserved.
- Re-launching the HITL editor reads existing corrected columns and
  picks up where the user left off.

## Dependencies

Add `pyside6` to `requirements.txt`. Already-installed scientific stack
(numpy, scipy, pandas, openpyxl, PIL) is sufficient for everything else.

## Constraints inherited from the spec

- The corrected boundary arrays are still per-column, B-scan-relative
  y values — same convention as the automatic detector.
- Center-based left/right independence is preserved by the editor: the
  user is free to drag a point on either side; the algorithm doesn't
  bridge across `center_x`.
- The disc area can still be NaN — erase mode lets the user mark
  it explicitly when the auto detector missed it.
