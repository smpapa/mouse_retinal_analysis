"""SQLite-backed canonical store for the HITL editor.

The xlsx pipeline is unchanged for outsiders:
  - `batch_process.py` writes `oct_results.xlsx` (auto results).
  - When the HITL editor opens that folder for the first time, it
    imports the xlsx into a sibling DB (``output/db/oct_results.db``).
  - Every save is now an UPDATE on the DB (~5 ms instead of ~9 s).
  - Closing the editor (or `File > Export to Excel...`) writes a fresh
    xlsx in the original schema so external tools keep working.

This module owns the DB; ``app.py`` is the only caller.
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .boundary_model import BOUNDARY_NAMES
from .storage import (CorrectedSnapshot, ImageRecord,
                       load_workbook as _load_xlsx,
                       save_corrections as _save_xlsx)


_DEFAULT_SCALE_Y = 3.87
_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS images (
    stem TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    width INTEGER NOT NULL,
    scale_um_per_px_y REAL,
    last_edited_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS per_column (
    stem TEXT NOT NULL,
    x_local INTEGER NOT NULL,
    auto_TOP_y REAL,
    auto_ONL_y REAL,
    auto_BM_y REAL,
    auto_DET_top_y REAL,
    auto_DET_bottom_y REAL,
    corr_TOP_y REAL,
    corr_ONL_y REAL,
    corr_BM_y REAL,
    corr_DET_top_y REAL,
    corr_DET_bottom_y REAL,
    PRIMARY KEY (stem, x_local),
    FOREIGN KEY (stem) REFERENCES images(stem) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_per_column_stem ON per_column(stem);
"""


def _to_db(v) -> float | None:
    """Map a NumPy boundary value to a DB cell.

    NaN -> NULL (= "untouched" for corrected, "missing" for auto).
    The ERASED sentinel (-1e9) survives as the same finite number, so
    callers can distinguish it from "untouched" via a magnitude check.
    """
    if v is None:
        return None
    f = float(v)
    if np.isnan(f):
        return None
    return f


def _from_db(v) -> float:
    """Inverse: NULL -> NaN."""
    return float("nan") if v is None else float(v)


class HitlDb:
    """Canonical local store for HITL edits."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute("PRAGMA foreign_keys = ON")
        # WAL mode: better concurrent reader behaviour and crash safety.
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        cur = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        )
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
        elif int(row[0]) != _SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported DB schema version {row[0]}; "
                f"expected {_SCHEMA_VERSION}"
            )
        self._conn.commit()

    # --------------------------------------------------- meta

    def set_meta(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_meta(self, key: str) -> str | None:
        cur = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    # --------------------------------------------------- import / export

    def is_empty(self) -> bool:
        cur = self._conn.execute("SELECT COUNT(*) FROM images")
        return cur.fetchone()[0] == 0

    def import_from_xlsx(self, xlsx_path: str | Path,
                         preserve_corrected_in_db: bool = True) -> int:
        """Populate the DB from an oct_results.xlsx.

        Returns the number of images imported. If `preserve_corrected_in_db`
        is True (default), existing corr_* values in the DB are kept;
        only auto_* values are replaced. This makes re-importing safe
        after batch_process re-runs.
        """
        wb = _load_xlsx(xlsx_path)
        n = 0
        with self._conn:
            self.set_meta("source_xlsx", str(Path(xlsx_path).resolve()))
            for stem, rec in wb.images.items():
                # Pick scale from the summary row that matches this image.
                scale_y = _DEFAULT_SCALE_Y
                if "scale_um_per_px_y" in wb.summary.columns:
                    matching = wb.summary[
                        wb.summary["filename"] == rec.filename
                    ]
                    if not matching.empty:
                        try:
                            v = float(matching["scale_um_per_px_y"].iloc[0])
                            if not np.isnan(v):
                                scale_y = v
                        except (TypeError, ValueError):
                            pass
                # Query existing corr values BEFORE the INSERT OR REPLACE
                # on images, because that triggers ON DELETE CASCADE on
                # per_column and wipes the rows we want to preserve.
                existing_corr: dict[int, tuple] = {}
                if preserve_corrected_in_db:
                    cur = self._conn.execute(
                        """SELECT x_local, corr_TOP_y, corr_ONL_y, corr_BM_y,
                                  corr_DET_top_y, corr_DET_bottom_y
                           FROM per_column WHERE stem = ?""",
                        (stem,),
                    )
                    existing_corr = {r[0]: r[1:] for r in cur.fetchall()}

                self._conn.execute(
                    """INSERT OR REPLACE INTO images
                    (stem, filename, width, scale_um_per_px_y)
                    VALUES (?, ?, ?, ?)""",
                    (stem, rec.filename, rec.width, scale_y),
                )

                rows = []
                for x in range(rec.width):
                    auto_vals = [_to_db(rec.auto[name][x])
                                 for name in BOUNDARY_NAMES]
                    if x in existing_corr:
                        corr_vals = list(existing_corr[x])
                    else:
                        # Pull corrected values out of the xlsx so a
                        # first-time import inherits prior HITL work
                        # captured in *_corrected columns.
                        corr_vals = [_to_db(rec.corrected[name][x])
                                     for name in BOUNDARY_NAMES]
                    rows.append((stem, x, *auto_vals, *corr_vals))

                self._conn.executemany(
                    """INSERT OR REPLACE INTO per_column
                       (stem, x_local,
                        auto_TOP_y, auto_ONL_y, auto_BM_y,
                        auto_DET_top_y, auto_DET_bottom_y,
                        corr_TOP_y, corr_ONL_y, corr_BM_y,
                        corr_DET_top_y, corr_DET_bottom_y)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                n += 1
        return n

    def export_to_xlsx(self, out_xlsx_path: str | Path) -> Path:
        """Write the DB state to an xlsx in the legacy schema.

        Strategy: copy the source xlsx (saved on import) to ``out`` and
        delegate to ``storage.save_corrections`` to apply every image's
        corrections at once. That keeps the on-disk schema identical to
        what batch_process originally produced plus the same `*_corrected`
        and `corrected_summary` extensions the editor used to write.
        """
        out = Path(out_xlsx_path)
        source = self.get_meta("source_xlsx")
        if not source or not Path(source).exists():
            raise RuntimeError(
                "No source xlsx recorded; cannot export. "
                "Run batch analysis or import a workbook first."
            )
        if out.resolve() != Path(source).resolve():
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, out)

        # Build snapshots for every image with at least one correction.
        snapshots: list[CorrectedSnapshot] = []
        scale_y = _DEFAULT_SCALE_Y
        for stem, _filename, has_corr in self.list_images():
            if not has_corr:
                continue
            rec = self.load_image(stem)
            if rec is None:
                continue
            snap = CorrectedSnapshot(
                stem=stem,
                corrected=rec.corrected,
                timestamp=datetime.now(),
            )
            snapshots.append(snap)
            scale_y = self.get_scale(stem)  # last wins; usually constant

        _save_xlsx(out, snapshots, scale_y)
        return out

    # --------------------------------------------------- query

    def list_images(self) -> list[tuple[str, str, bool]]:
        """Return [(stem, filename, has_corrections), ...] sorted by stem."""
        cur = self._conn.execute(
            """SELECT i.stem, i.filename,
                      EXISTS (
                          SELECT 1 FROM per_column pc
                          WHERE pc.stem = i.stem AND (
                              pc.corr_TOP_y IS NOT NULL OR
                              pc.corr_ONL_y IS NOT NULL OR
                              pc.corr_BM_y IS NOT NULL OR
                              pc.corr_DET_top_y IS NOT NULL OR
                              pc.corr_DET_bottom_y IS NOT NULL
                          )
                      ) AS has_corr
               FROM images i ORDER BY i.stem"""
        )
        return [(row[0], row[1], bool(row[2])) for row in cur.fetchall()]

    def load_image(self, stem: str) -> ImageRecord | None:
        cur = self._conn.execute(
            "SELECT filename, width FROM images WHERE stem = ?", (stem,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        filename, width = row[0], int(row[1])

        cur = self._conn.execute(
            """SELECT x_local,
                      auto_TOP_y, auto_ONL_y, auto_BM_y,
                      auto_DET_top_y, auto_DET_bottom_y,
                      corr_TOP_y, corr_ONL_y, corr_BM_y,
                      corr_DET_top_y, corr_DET_bottom_y
               FROM per_column WHERE stem = ? ORDER BY x_local""",
            (stem,),
        )
        auto = {n: np.full(width, np.nan, dtype=float)
                for n in BOUNDARY_NAMES}
        corrected = {n: np.full(width, np.nan, dtype=float)
                     for n in BOUNDARY_NAMES}
        for r in cur.fetchall():
            x = int(r[0])
            for i, name in enumerate(BOUNDARY_NAMES):
                auto[name][x] = _from_db(r[1 + i])
                corrected[name][x] = _from_db(r[6 + i])

        return ImageRecord(stem=stem, filename=filename, width=width,
                            auto=auto, corrected=corrected)

    def get_scale(self, stem: str) -> float:
        cur = self._conn.execute(
            "SELECT scale_um_per_px_y FROM images WHERE stem = ?", (stem,)
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            return _DEFAULT_SCALE_Y
        return float(row[0])

    def get_filename(self, stem: str) -> str | None:
        cur = self._conn.execute(
            "SELECT filename FROM images WHERE stem = ?", (stem,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def has_corrections(self) -> bool:
        cur = self._conn.execute(
            """SELECT EXISTS (
                   SELECT 1 FROM per_column WHERE
                       corr_TOP_y IS NOT NULL OR
                       corr_ONL_y IS NOT NULL OR
                       corr_BM_y IS NOT NULL OR
                       corr_DET_top_y IS NOT NULL OR
                       corr_DET_bottom_y IS NOT NULL
               )"""
        )
        return bool(cur.fetchone()[0])

    # --------------------------------------------------- save

    def save_corrections(self, snapshot: CorrectedSnapshot) -> None:
        """Apply one snapshot to the DB. Fast (typically 5–50 ms)."""
        cur = self._conn.execute(
            "SELECT width FROM images WHERE stem = ?", (snapshot.stem,)
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"Image not found: {snapshot.stem}")
        width = int(row[0])

        rows = []
        for x in range(width):
            vals = [_to_db(snapshot.corrected[n][x])
                    for n in BOUNDARY_NAMES]
            rows.append((*vals, snapshot.stem, x))

        with self._conn:
            self._conn.executemany(
                """UPDATE per_column
                   SET corr_TOP_y = ?, corr_ONL_y = ?, corr_BM_y = ?,
                       corr_DET_top_y = ?, corr_DET_bottom_y = ?
                   WHERE stem = ? AND x_local = ?""",
                rows,
            )
            self._conn.execute(
                "UPDATE images SET last_edited_at = CURRENT_TIMESTAMP "
                "WHERE stem = ?",
                (snapshot.stem,),
            )
