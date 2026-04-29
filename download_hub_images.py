#!/usr/bin/env python3
"""
download_hub_images.py — one-time hub image downloader for the Gray Movie Vault

Reads data/artists.json and data/collections.json, then downloads the hub
thumbnail for each entry into images/hubs/{id}.jpg.

Three sources, in priority order:

  1. CUSTOM_URLS (defined below) — user-supplied URLs for hubs where we
     want a specific image regardless of TMDB. Highest priority.

  2. TMDB person profile — for entries with a personId, fetches
     /person/{id} and downloads profile_path at h632 size.

  3. TMDB movie/collection poster — for entries with movieId or
     collectionId (no personId), fetches poster_path at w500 size.

After this runs once, all hub artwork is local. TMDB is no longer hit
at runtime for hub images. The vault renderer will reference
images/hubs/{id}.jpg via the customImage field set in the JSON.

Usage:
    python3 download_hub_images.py

Re-run safely: skips files that already exist locally. Pass --force to
re-download everything (e.g. if a TMDB image you previously cached has
been updated upstream and you want the new one).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TMDB_KEY = "573382ec2121f69d6a89fce35293591a"  # Same key the vault uses
TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"

# Custom URLs — user-supplied, override TMDB for these specific hubs.
# Each value is the source URL. The destination filename is derived from the
# hub id (images/hubs/{id}.jpg).
CUSTOM_URLS = {
    "hope-crosby":   "https://trailersfromhell.com/wp-content/uploads/2019/03/road4.jpg",
    "marx-brothers": "https://mediaproxy.tvtropes.org/width/1200/https://static.tvtropes.org/pmwiki/pub/images/img_2999_0.jpeg",
    "eddie-murphy":  "https://media.themoviedb.org/t/p/w300_and_h450_face/qgjMfefsKwSYsyCaIX46uyOXIpy.jpg",
    "holiday-films": "https://blogs.libraries.indiana.edu/wp-content/uploads/2024/11/istockphoto-523110863-612x612-1.jpg",
    "80s-comedies":  "https://miro.medium.com/v2/resize:fit:1400/1*kCnenbmCLEPTa6Q0bVYxfA.jpeg",
}

USER_AGENT = "GrayMovieVault/1.0 (image cache builder)"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def http_get(url: str, timeout: int = 30) -> bytes:
    """GET with a sensible UA. Raises on HTTP/network errors."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_get_json(url: str) -> dict:
    return json.loads(http_get(url).decode("utf-8"))


# ---------------------------------------------------------------------------
# TMDB lookups
# ---------------------------------------------------------------------------

def tmdb_person_profile(person_id: int) -> str | None:
    """Return profile_path (e.g. '/abc.jpg') or None."""
    data = http_get_json(f"{TMDB_API}/person/{person_id}?api_key={TMDB_KEY}")
    return data.get("profile_path")


def tmdb_movie_poster(movie_id: int) -> str | None:
    data = http_get_json(f"{TMDB_API}/movie/{movie_id}?api_key={TMDB_KEY}")
    return data.get("poster_path")


def tmdb_collection_poster(collection_id: int) -> str | None:
    data = http_get_json(f"{TMDB_API}/collection/{collection_id}?api_key={TMDB_KEY}")
    return data.get("poster_path")


# ---------------------------------------------------------------------------
# Resolve source URL for a single hub entry
# ---------------------------------------------------------------------------

def source_url_for(entry: dict) -> tuple[str, str] | None:
    """Return (source_url, source_kind) or None if no source available.
    source_kind is one of 'custom' | 'tmdb_person' | 'tmdb_movie' | 'tmdb_collection'."""
    eid = entry["id"]

    # 1. Custom URL wins
    if eid in CUSTOM_URLS:
        return CUSTOM_URLS[eid], "custom"

    # 2. TMDB person profile
    pid = entry.get("personId")
    if pid:
        path = tmdb_person_profile(pid)
        if path:
            return f"{TMDB_IMG}/h632{path}", "tmdb_person"

    # 3. TMDB movie poster (Marx Brothers fallback if it didn't have a custom)
    mid = entry.get("movieId")
    if mid:
        path = tmdb_movie_poster(mid)
        if path:
            return f"{TMDB_IMG}/w500{path}", "tmdb_movie"

    # 4. TMDB collection poster (Hope & Crosby fallback if it didn't have a custom)
    cid = entry.get("collectionId")
    if cid:
        path = tmdb_collection_poster(cid)
        if path:
            return f"{TMDB_IMG}/w500{path}", "tmdb_collection"

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data",
                    help="Directory containing artists.json and collections.json (default: data/)")
    ap.add_argument("--out", default="images/hubs",
                    help="Output directory for downloaded images (default: images/hubs/)")
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if the local file already exists")
    ap.add_argument("--sleep", type=float, default=0.25,
                    help="Seconds to sleep between TMDB API calls (default: 0.25)")
    args = ap.parse_args()

    data_dir = Path(args.data)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load both JSONs
    artists = json.loads((data_dir / "artists.json").read_text(encoding="utf-8"))
    collections = json.loads((data_dir / "collections.json").read_text(encoding="utf-8"))
    entries = artists + collections

    # Filter to entries that declare a customImage path (we only download
    # what the JSON expects to find locally)
    entries = [e for e in entries if e.get("customImage")]

    print(f"Hub entries needing local images: {len(entries)}", file=sys.stderr)
    print(f"Output directory: {out_dir}", file=sys.stderr)
    print(file=sys.stderr)

    counts = {"downloaded": 0, "skipped_exists": 0, "skipped_no_source": 0, "errors": 0}

    for entry in entries:
        eid = entry["id"]
        out_path = out_dir / f"{eid}.jpg"

        if out_path.exists() and not args.force:
            print(f"  [skip] {eid:24s} (already exists)", file=sys.stderr)
            counts["skipped_exists"] += 1
            continue

        try:
            src = source_url_for(entry)
            if src is None:
                print(f"  [WARN] {eid:24s} no source available — skipping",
                      file=sys.stderr)
                counts["skipped_no_source"] += 1
                continue
            url, kind = src

            # Polite pacing — only matters for TMDB; custom hosts get one hit each
            if kind != "custom":
                time.sleep(args.sleep)

            data = http_get(url)
            out_path.write_bytes(data)
            print(f"  [ok]   {eid:24s} {kind:18s} {len(data)/1024:>5.0f} KB",
                  file=sys.stderr)
            counts["downloaded"] += 1

        except (HTTPError, URLError) as e:
            print(f"  [ERR]  {eid:24s} {e}", file=sys.stderr)
            counts["errors"] += 1
        except Exception as e:
            print(f"  [ERR]  {eid:24s} {type(e).__name__}: {e}", file=sys.stderr)
            counts["errors"] += 1

    print(file=sys.stderr)
    print(f"Done. downloaded={counts['downloaded']}  "
          f"skipped_exists={counts['skipped_exists']}  "
          f"skipped_no_source={counts['skipped_no_source']}  "
          f"errors={counts['errors']}", file=sys.stderr)

    if counts["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
