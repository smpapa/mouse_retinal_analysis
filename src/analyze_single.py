"""Single-image analysis entry point.

Usage:
    python src/analyze_single.py <image.tif> [-o OUTPUT_DIR]

Produces, in OUTPUT_DIR (default: same folder as image, then `output/`):
    <stem>_overlay.png
    <stem>_results.xlsx
    <stem>_log.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make `src/` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from io_utils import load_oct
from oct_analyzer import analyze, thickness_arrays
from viz import save_overlay
from gt_guided import find_annotation, load_gt, compare


def _build_detail_dataframe(oct_image, b, scale_y_um, scale_x_um) -> pd.DataFrame:
    layout = oct_image.layout
    W = layout.width
    x_local = np.arange(W)
    relative_x_px = x_local - b.center_x_local

    th = thickness_arrays(b, scale_y_um)

    # Convert NaN-respecting boundaries to absolute y for the spreadsheet.
    def to_abs(arr):
        out = arr + layout.top_y
        out[np.isnan(arr)] = np.nan
        return out

    df = pd.DataFrame({
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
    return df


def analyze_path(image_path: str | Path, output_dir: str | Path) -> dict:
    """Run analysis on a single image. Writes overlay + xlsx, returns a summary dict."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    oct_image = load_oct(image_path)
    b = analyze(oct_image)

    layout = oct_image.layout
    scale = oct_image.scale

    # Persist overlay.
    overlay_path = out / f"{Path(image_path).stem}_overlay.png"
    save_overlay(oct_image, b, overlay_path)

    # Persist detail table.
    df = _build_detail_dataframe(oct_image, b, scale.um_per_px_y, scale.um_per_px_x)
    xlsx_path = out / f"{Path(image_path).stem}_results.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="detail", index=False)

    n_meas = int((~df["total_thickness_um"].isna()).sum())
    summary = {
        "filename": Path(image_path).name,
        "has_detachment": b.has_detachment,
        "n_measurable_cols": n_meas,
        "mean_total_thickness_um":
            float(df["total_thickness_um"].dropna().mean()) if n_meas else float("nan"),
        "mean_outer_thickness_um":
            float(df["outer_thickness_um"].dropna().mean()) if n_meas else float("nan"),
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

    # Optional GT comparison.
    anno = find_annotation(image_path)
    if anno is not None:
        gt = load_gt(anno, oct_image)
        cmp = compare(b, gt)
        summary.update(cmp)

    # Write a small log too.
    log_path = out / f"{Path(image_path).stem}_log.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"image: {image_path}\n")
        f.write(f"layout: left={layout.left_x} right={layout.right_x} "
                f"top={layout.top_y} bot={layout.bot_y} center={layout.center_x}\n")
        f.write(f"scale: y={scale.um_per_px_y:.3f} um/px  "
                f"x={scale.um_per_px_x:.3f} um/px  source={scale.source}\n")
        f.write(f"has_detachment: {b.has_detachment}\n")
        f.write(f"measurable cols (TOP+ONL+BM): {n_meas}/{layout.width}\n")
        for k, v in summary.items():
            if k.endswith("_median_err_px"):
                f.write(f"GT  {k}: {v}\n")

    return summary


def main():
    ap = argparse.ArgumentParser(description="Analyze a single OCT TIFF.")
    ap.add_argument("image", type=str, help="Path to the TIFF")
    ap.add_argument("-o", "--output", type=str, default=None,
                    help="Output folder (default: <image-folder>/output)")
    args = ap.parse_args()

    image_path = Path(args.image).resolve()
    if args.output:
        out_dir = Path(args.output).resolve()
    else:
        out_dir = image_path.parent / "output"

    summary = analyze_path(image_path, out_dir)
    print("=== Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
