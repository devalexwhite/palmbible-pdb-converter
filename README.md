# palmbible-pdb-converter

Pure Python 3 tools to convert Bible texts (Verse-Per-Line `.txt`, structured `.json`, or locally owned OCR `.epub` scans such as *The Ignatius Bible* RSV-2CE) into genuine **Palm Bible+** (`.pdb`) databases for Palm OS handhelds.

Zero external Python dependencies — uses only the Python 3 standard library.

## Features

- **Authentic Palm Bible+ binary format** (`PPBL` / `bibl`), implemented directly from the Palm Bible+ 3.x C source and `BibleConverter`:
  - Full 73-book Catholic canon (including Deuterocanonical books and 16-chapter Catholic Esther) as well as 66-book Protestant canons.
  - Uses standard Palm Bible+ book IDs (`10`–`730`) so dual-view synchronization and New Testament highlighting work with other Palm Bible+ modules.
  - Automatic **14-bit byte-shifted** packing (< 14,079 unique words) or **16-bit unshifted** packing (up to 65,504 unique words) plus greedy **bigram dictionary compression**.
- **Built-in C-spec round-trip verifier** (`PalmBibleReader`): decodes every book, chapter, and verse back from the generated `.pdb` and asserts 100% lossless round-trip integrity plus Palm Bible+ hard limits (`MAX_INDEXES <= 100`, `MAX_WORD_LENGTH <= 60`, verse buffer limits).
- **OCR EPUB alignment & cleanup (`extract_epub.py`)**:
  - Dynamically detects all 73 books in Internet Archive OCR EPUBs (like *The Ignatius Bible* RSV-2CE).
  - Uses multi-pass n-gram anchor chaining (LIS) + local Needleman-Wunsch alignment against a public-domain VPL structure guide (e.g. World English Bible — Catholic Edition from eBible.org) purely to locate exact chapter/verse boundaries where OCR dropped or garbled superscript verse numbers.
  - 100% of scripture text comes from your local EPUB; repairs systematic OCR errors (small-caps `LORD`, broken line-end hyphens, stray footnote symbols) and flags any pages blanked out in the source scan.

> **Copyright Note:** This repository contains **only conversion tools** — no copyrighted Bible texts or `.pdb` files are included.

## Requirements

- Python 3.8+ (standard library only)

## Quick Start

### 1. Convert any VPL Bible text file (e.g., from [eBible.org](https://ebible.org/))

```bash
python3 convert.py \
  --vpl eng-web-c_vpl.txt \
  --output WEBC.pdb \
  --name "WEB-C" \
  --info "World English Bible, Catholic Edition"
```

Pass `--protestant-order` if you prefer books ordered strictly by Palm Bible+ numeric ID instead of Catholic canonical order.

### 2. Convert a local OCR Bible EPUB (e.g., *The Ignatius Bible* RSV-2CE)

```bash
python3 convert.py \
  --epub ~/Downloads/"The Ignatius Bible.epub" \
  --output RSV2CE.pdb \
  --name "RSV-2CE" \
  --info "The Holy Bible, Revised Standard Version Second Catholic Edition" \
  --report extraction_report.txt
```

If `--ref-vpl` is omitted, the extractor automatically downloads and caches the public-domain WEB-C VPL file from eBible.org into `.cache/` to use strictly as a verse-boundary alignment guide. You can also pass a local VPL file with `--ref-vpl /path/to/eng-web-c_vpl.txt`.

### 3. Inspect or verify any Palm Bible+ `.pdb`

```bash
python3 palmbible_pdb.py inspect RSV2CE.pdb --verse "Gen 1:1" --verse "John 3:16"
```

## CLI Reference

| Script | Purpose |
|---|---|
| `convert.py` | End-to-end CLI (`--epub`, `--vpl`, or `--json` → verified `.pdb`) |
| `extract_epub.py` | Extract & align an OCR Bible EPUB into structured JSON (`--epub`, `--ref-vpl`, `-o`, `--report`) |
| `palmbible_pdb.py` | Standalone PDB builder & inspector (`build` / `inspect` subcommands) and importable library |

### Structured JSON Schema

If you want to feed your own custom text into `convert.py --json` or `palmbible_pdb.py build`:

```json
[
  {
    "book_num": 10,
    "short_name": "Gen",
    "full_name": "Genesis",
    "chapters": [
      [
        "In the beginning God created the heavens and the earth.",
        "The earth was without form and void..."
      ]
    ]
  }
]
```

- `book_num`: Standard Palm Bible+ book ID (`10` = Genesis … `460` = Malachi, `170` = Tobit, `180` = Judith, `190` = Esther, `200` = 1 Maccabees, `210` = 2 Maccabees, `270` = Wisdom, `280` = Sirach, `320` = Baruch, `470` = Matthew … `730` = Revelation).
- `short_name`: Up to 7 Latin-1 characters.
- `full_name`: Up to 31 Latin-1 characters.

## Installing on a Palm Pilot

1. Install **Palm Bible+** (`PalmBible_en_big.prc` or `PalmBible_en_lite.prc` from [SourceForge](https://sourceforge.net/projects/palmbibleplus/files/)) on your Palm OS device.
2. Transfer your generated `.pdb` file using either method:
   - **Internal RAM:** Install via HotSync, JPilot, or `pilot-xfer -i RSV2CE.pdb`.
   - **SD / Expansion Card (VFS):** Copy the `.pdb` file into `/Palm/Programs/Bible+/` (or `/Palm/Programs/PPBL/`) on the card.

## License

MIT — see [LICENSE](LICENSE).
