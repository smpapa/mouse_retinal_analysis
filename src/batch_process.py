"""Batch-process all OCT TIFFs in a folder.

Usage:
    python src/batch_process.py <folder> [-o OUTPUT_DIR]

The folder is scanned for *.tif / *.tiff files; the `annotation/` subfolder is
skipped (those are GT, not raw input). For each image we write an overlay PNG
to OUTPUT_DIR/<stem>_overlay.png and one combined workbook
OUTPUT_DIR/oct_results.xlsx with:

  - `summary` sheet: one row per image
  - one `<stem>` sheet per image with per-x measurements

If a matching annotation TIFF exists, the summary row also contains GT median
errors per boundary.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from io_utils import load_oct, is_normal_filename
from oct_analyzer import analyze, thickness_arrays
from viz import save_overlay
from gt_guided import find_annotation, load_gt, compare


# Excel sheet names are limited to 31 characters. Reserve a few for de-dup.
MAX_SHEET = 28


def _build_detail_dataframe(oct_image, b, scale_y_um, scale_x_um) -> pd.DataFrame:
    layout = oct_image.layout
    W = layout.width
    x_local = np.arange(W)
    relative_x_px = x_local - b.center_x_local
    th = thickness_arrays(b, scale_y_um)

    def to_abs(arr):
        out = arr + layout.top_y
        out[np.isnan(arr)] = np.nan
        return out

    return pd.DataFrame({
        "x": layout.left_x + x_local,
        "x_local": x_local,
        "relative_x_px": relative_x_px,
        "relative_x_um": relative_x_px * scale_x_um,
        "TOP_y": to_abs(b.TOP),
        "ONL_y": to_abs(b.ONL),
        "BM_y": to_abs(b.BM),
        "DET_top_y": to_abs(b.DET_top),
        "DET_bottom_y": to_abs(b.DET_bottom),
        "total_thickness_um": th["total_thickness_um"],
        "outer_thickness_um": th["outer_thickness_um"],
        "detachment_thickness_um": th["detachment_thickness_um"],
        "image_has_detachment": b.has_detachment,
    })


def _summary_row(image_path: Path, oct_image, b, df, anno_summary) -> dict:
    layout = oct_image.layout
    scale = oct_image.scale
    n_meas = int((~df["total_thickness_um"].isna()).sum())
    row = {
        "filename": image_path.name,
        "filename_says_normal": is_normal_filename(image_path.name),
        "has_detachment": b.has_detachment,
        "n_measurable_cols": n_meas,
        "mean_total_thickness_um":
            float(df["total_thickness_um"].dropna().mean()) if n_meas else np.nan,
        "mean_outer_thickness_um":
            float(df["outer_thickness_um"].dropna().mean()) if n_meas else np.nan,
        "mean_detachment_thickness_um":
            float(df["detachment_thickness_um"].dropna().mean()),
        "scale_um_per_px_y": scale.um_per_px_y,
        "scale_um_per_px_x": scale.um_per_px_x,
        "scale_source": scale.source,
        "bscan_left_x": layout.left_x,
        "bscan_right_x": layout.right_x,
        "bscan_top_y": layout.top_y,
        "bscan_bot_y": layout.bot_y,
        "center_x": layout.center_x,
    }
    if anno_summary is not None:
        row.update(anno_summary)
    return row


def _process_one(image_path: Path, output_dir: Path) -> tuple[dict, pd.DataFrame, str]:
    """Run analysis on a single image. Returns (summary_row, detail_df, sheet_name)."""
    oct_image = load_oct(image_path)
    b = analyze(oct_image)

    overlay_path = output_dir / f"{image_path.stem}_overlay.png"
    save_overlay(oct_image, b, overlay_path)

    df = _build_detail_dataframe(oct_image, b,
                                 oct_image.scale.um_per_px_y,
                                 oct_image.scale.um_per_px_x)

    anno = find_annotation(image_path)
    anno_summary = None
    if anno is not None:
        try:
            gt = load_gt(anno, oct_image)
            anno_summary = compare(b, gt)
        except Exception as exc:
            anno_summary = {"gt_error": str(exc)}

    summary = _summary_row(image_path, oct_image, b, df, anno_summary)

    sheet = image_path.stem[:MAX_SHEET]
    return summary, df, sheet


def _make_unique(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    base = name
    i = 2
    while f"{base[:MAX_SHEET-3]}_{i}" in used:
        i += 1
    out = f"{base[:MAX_SHEET-3]}_{i}"
    used.add(out)
    return out


def batch_run(folder: str | Path, output_dir: str | Path) -> Path:
    folder = Path(folder).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    images = []
    for ext in ("*.tif", "*.tiff", "*.TIF", "*.TIFF"):
        images.extend(folder.glob(ext))
    images = sorted(set(images))
    if not images:
        raise SystemExit(f"No TIFF files found in {folder}")

    print(f"Processing {len(images)} images from {folder}")

    summaries: list[dict] = []
    sheets: list[tuple[str, pd.DataFrame]] = []
    used_sheet_names: set[str] = set()

    for i, p in enumerate(images, 1):
        try:
            summary, df, sheet_name = _process_one(p, output_dir)
        except Exception as exc:
            print(f"  [{i}/{len(images)}] FAIL {p.name}: {exc}")
            traceback.print_exc()
            summaries.append({"filename": p.name, "error": str(exc)})
            continue
        sheet_name = _make_unique(sheet_name, used_sheet_names)
        summaries.append(summary)
        sheets.append((sheet_name, df))
        flag = "DET" if summary["has_detachment"] else "   "
        print(f"  [{i}/{len(images)}] {flag} {p.name}  "
              f"meas={summary['n_measurable_cols']:4d}  "
              f"total={summary['mean_total_thickness_um']:6.1f}um")

    summary_df = pd.DataFrame(summaries)
    out_xlsx = output_dir / "oct_results.xlsx"
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as w:
        summary_df.to_excel(w, sheet_name="summary", index=False)
        for name, df in sheets:
            df.to_excel(w, sheet_name=name, index=False)

    print(f"\nWrote {out_xlsx}")
    return out_xlsx


def main():
    ap = argparse.ArgumentParser(description="Batch OCT analysis.")
    ap.add_argument("folder", type=str, help="Folder of TIFF images")
    ap.add_argument("-o", "--output", type=str, default=None,
                    help="Output directory (default: <folder>/output)")
    args = ap.parse_args()

    folder = Path(args.folder).resolve()
    output_dir = Path(args.output).resolve() if args.output else folder / "output"
    batch_run(folder, output_dir)


if __name__ == "__main__":
    main()
