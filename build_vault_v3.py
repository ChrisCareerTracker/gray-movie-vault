#!/usr/bin/env python3
"""
build_vault_v3.py — Gray Movie Vault build script

Reads the master Excel collection and emits three JSON files for the
externalized vault structure:

  data/movies.json       — array of all visible films (Row Type blank or "Film")
  data/collections.json  — landscape genre/studio/era collections (preserved + dormant)
  data/artists.json      — portrait artist hubs (preserved + dormant)

This script is the canonical build step. Run it after every Excel edit:

    python3 build_vault_v3.py \\
        --excel "C_Gray_Movie_Collection_-_FINAL_MASTER_4-28-26_v4_enriched.xlsx" \\
        --out data/

Field names in movies.json mirror the legacy MOVIES JS array exactly so the
renderer code in index.html works without modification.

Cardinal principle:
  Excel preserves collection truth; the vault shows each film once, in best
  quality. Variants/extras hide via Row Type. If a row's Row Type is one of
  Commentary / Alt Cut / Colorized / Disc Set / Variant, it is NOT emitted
  to movies.json. Blank or "Film" = emit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import openpyxl


# ---------------------------------------------------------------------------
# Excel column layout (1-indexed, mirrors v4 master)
# ---------------------------------------------------------------------------

COLUMNS = {
    "year":          1,   # Year
    "title":         2,   # Title
    "dir":           3,   # Director
    "actor":         4,   # Primary Actor
    "supp":          5,   # Supporting Actors
    "genre":         6,   # Genre
    "color":         7,   # Color
    "quality":       8,   # Quality
    "notes":         9,   # Notes
    "desc":         10,   # Description
    "runtime":      11,   # Runtime
    "rating":       12,   # MPAA Rating
    "franchise":    13,   # Franchise/Series
    "decade":       14,   # Decade
    "studio":       15,   # Studio/Distribution
    "tmdb":         16,   # tmdb_id
    # 17: tmdb_confidence — not emitted (build-time signal only)
    "poster":       18,   # tmdb_poster_path
    "backdrop":     19,   # tmdb_backdrop_path
    "cast":         20,   # Full Cast
    "row_type":     21,   # Row Type
}

# Row Type values that mean "do not emit to vault"
HIDDEN_ROW_TYPES = {"Commentary", "Alt Cut", "Colorized", "Disc Set", "Variant"}


# ---------------------------------------------------------------------------
# Cell coercion helpers
# ---------------------------------------------------------------------------

def s(val) -> str:
    """String, with None/whitespace normalized to empty string."""
    if val is None:
        return ""
    return str(val).strip()


def i(val) -> int | None:
    """Integer, or None if blank/non-numeric."""
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Movie row -> dict
# ---------------------------------------------------------------------------

def row_to_movie(row: tuple) -> dict:
    """Translate one Excel row tuple into a movies.json record."""
    def col(name: str):
        return row[COLUMNS[name] - 1]

    return {
        "year":      i(col("year")) or 0,
        "title":     s(col("title")),
        "dir":       s(col("dir")),
        "actor":     s(col("actor")),
        "supp":      s(col("supp")),
        "genre":     s(col("genre")),
        "color":     s(col("color")),
        "quality":   s(col("quality")),
        "notes":     s(col("notes")),
        "desc":      s(col("desc")),
        "runtime":   i(col("runtime")) or 0,
        "rating":    s(col("rating")),
        "franchise": s(col("franchise")),
        "decade":    s(col("decade")),
        "studio":    s(col("studio")),
        "tmdb":      i(col("tmdb")) or 0,
        "poster":    s(col("poster")),
        "backdrop":  s(col("backdrop")),
        "cast":      s(col("cast")),
    }


def is_visible(row: tuple) -> bool:
    """Return True if this row should appear in the vault."""
    rt = s(row[COLUMNS["row_type"] - 1])
    if rt == "" or rt == "Film":
        return True
    if rt in HIDDEN_ROW_TYPES:
        return False
    # Unknown Row Type — be conservative, emit, but warn
    print(f"  WARN: unknown Row Type {rt!r} — emitting anyway", file=sys.stderr)
    return True


# ---------------------------------------------------------------------------
# Build movies.json
# ---------------------------------------------------------------------------

def build_movies(excel_path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb["Movie Collection"]

    movies = []
    skipped = []

    for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(row):  # entirely blank row
            continue
        if not is_visible(row):
            skipped.append((row_num, s(row[COLUMNS["title"] - 1]),
                            s(row[COLUMNS["row_type"] - 1])))
            continue
        movies.append(row_to_movie(row))

    # Sort by year, then title — matches current vault behavior
    movies.sort(key=lambda m: (m["year"], m["title"].lower()))

    print(f"  emitted: {len(movies)} films", file=sys.stderr)
    print(f"  skipped: {len(skipped)} (Row Type filter)", file=sys.stderr)
    for rn, title, rt in skipped:
        print(f"    row {rn}: {title!r} [{rt}]", file=sys.stderr)

    return movies


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--excel", required=True,
                    help="Path to the master enriched Excel file")
    ap.add_argument("--out", default="data",
                    help="Output directory (default: data/)")
    ap.add_argument("--collections", default=None,
                    help="Path to collections seed JSON (optional, copied to out/collections.json)")
    ap.add_argument("--artists", default=None,
                    help="Path to artists seed JSON (optional, copied to out/artists.json)")
    args = ap.parse_args()

    excel_path = Path(args.excel)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading {excel_path.name} ...", file=sys.stderr)
    movies = build_movies(excel_path)

    movies_path = out_dir / "movies.json"
    with movies_path.open("w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote {movies_path} ({movies_path.stat().st_size:,} bytes)",
          file=sys.stderr)

    # Pass-through for collections/artists if provided. Phase 2b will populate
    # these from a seed file in this same directory; for 2a we skip.
    for label, src_arg, out_name in [
        ("collections", args.collections, "collections.json"),
        ("artists",     args.artists,     "artists.json"),
    ]:
        if src_arg:
            src = Path(src_arg)
            data = json.loads(src.read_text(encoding="utf-8"))
            dst = out_dir / out_name
            with dst.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print(f"Wrote {dst} ({len(data)} {label} entries)", file=sys.stderr)


if __name__ == "__main__":
    main()
