#!/usr/bin/env python3
"""
End-to-end CLI converter to build verified Palm Bible+ (.pdb) files from:
  - A locally owned OCR Bible EPUB (e.g., Internet Archive 'The Ignatius Bible' RSV-2CE)
  - A Verse-Per-Line (VPL) text file (e.g., eBible.org `*_vpl.txt`)
  - A pre-extracted JSON file
"""

import argparse
import json
import os
import sys

from extract_epub import extract_epub_to_bible_data
from palmbible_pdb import build_pdb, load_vpl_as_bible_data, verify_pdb


def main():
    parser = argparse.ArgumentParser(
        description="Convert a Bible EPUB, VPL text file, or JSON into a Palm Bible+ (.pdb) database."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--epub", help="Path to local OCR Bible EPUB (e.g. 'The Ignatius Bible.epub')")
    src.add_argument("--vpl", help="Path to Verse-Per-Line text file (e.g. 'eng-web-c_vpl.txt')")
    src.add_argument("--json", help="Path to structured Bible JSON file")

    parser.add_argument("-o", "--output", required=True, help="Output .pdb file path")
    parser.add_argument("--name", default="RSV-2CE", help="PDB / version display name (<=15 chars)")
    parser.add_argument(
        "--info",
        default="The Holy Bible, Revised Standard Version Second Catholic Edition",
        help="Version info / description stored in PDB Record 0 (<=127 chars)",
    )
    parser.add_argument(
        "--ref-vpl",
        default=None,
        help="(EPUB mode) Local VPL alignment guide; omit to auto-download public-domain WEB-C VPL",
    )
    parser.add_argument("--save-json", default=None, help="(EPUB mode) Also save extracted JSON here")
    parser.add_argument("--report", default=None, help="(EPUB mode) Save extraction QA report here")
    parser.add_argument(
        "--protestant-order",
        action="store_true",
        help="(VPL mode) Sort books strictly by PalmBible+ numeric ID instead of Catholic order",
    )
    parser.add_argument("--no-compress", action="store_true", help="Disable bigram compression")
    parser.add_argument("--no-verify", action="store_true", help="Skip round-trip verification")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress progress output")

    args = parser.parse_args()

    if args.epub:
        bible_data = extract_epub_to_bible_data(
            args.epub,
            ref_vpl_path=args.ref_vpl,
            report_path=args.report,
            quiet=args.quiet,
        )
        if args.save_json:
            with open(args.save_json, "w", encoding="utf-8") as f:
                json.dump(bible_data, f, ensure_ascii=True)
            if not args.quiet:
                print(f"Saved extracted JSON to {args.save_json}")
    elif args.vpl:
        bible_data = load_vpl_as_bible_data(args.vpl, catholic_order=not args.protestant_order)
    else:
        with open(args.json, encoding="utf-8") as f:
            bible_data = json.load(f)

    build_pdb(
        bible_data,
        args.output,
        pdb_name=args.name,
        version_name=args.name[:15],
        version_info=args.info,
        compress_bigrams=not args.no_compress,
        quiet=args.quiet,
    )

    if not args.no_verify:
        verify_pdb(args.output, bible_data, quiet=args.quiet)


if __name__ == "__main__":
    main()
