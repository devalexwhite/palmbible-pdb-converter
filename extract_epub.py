#!/usr/bin/env python3
"""
Extract and verse-align an Internet Archive OCR Bible EPUB (such as
'The Ignatius Bible' RSV-2CE) into structured JSON for Palm Bible+.

100% of output scripture text comes directly from the user's local EPUB.
A public-domain Verse-Per-Line (VPL) reference (such as World English Bible
Catholic Edition from eBible.org) is used ONLY as a structural alignment guide
to recover exact chapter/verse boundaries where OCR dropped or garbled
superscript verse numbers.
"""

import argparse
import html
import io
import json
import os
import re
import urllib.request
import zipfile
from bisect import bisect_left
from collections import OrderedDict, defaultdict

WEBC_VPL_URL = "https://ebible.org/Scriptures/eng-web-c_vpl.zip"
DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

# All 73 Catholic books in standard Ignatius Bible order, with official PalmBible+ book IDs
# Tuple: (book_num, short_name<=7, full_name<=31, vpl_code, match_patterns)
CATHOLIC_BOOKS = [
    # Old Testament - Pentateuch
    (10, "Gen", "Genesis", "GEN", ["Genesis Chapters"]),
    (20, "Exod", "Exodus", "EXO", ["Exodus Chapters"]),
    (30, "Lev", "Leviticus", "LEV", ["Leviticus Chapters"]),
    (40, "Num", "Numbers", "NUM", ["Numbers Chapters"]),
    (50, "Deut", "Deuteronomy", "DEU", ["Deuteronomy Chapters"]),
    # Historical Books
    (60, "Josh", "Joshua", "JOS", ["Joshua Chapters"]),
    (70, "Judg", "Judges", "JDG", ["Judges Chapters"]),
    (80, "Ruth", "Ruth", "RUT", ["Ruth Chapters"]),
    (90, "1Sam", "1 Samuel", "1SA", ["1 Samuel Chapters"]),
    (100, "2Sam", "2 Samuel", "2SA", ["2 Samuel Chapters"]),
    (110, "1Kgs", "1 Kings", "1KI", ["1 Kings Chapters"]),
    (120, "2Kgs", "2 Kings", "2KI", ["2 Kings Chapters"]),
    (130, "1Chr", "1 Chronicles", "1CH", ["1 Chronicles Chapters"]),
    (140, "2Chr", "2 Chronicles", "2CH", ["2 Chronicles Chapters"]),
    (150, "Ezra", "Ezra", "EZR", ["Ezra Chapters"]),
    (160, "Neh", "Nehemiah", "NEH", ["Nehemiah Chapters"]),
    (170, "Tob", "Tobit", "TOB", ["Tobit Chapters"]),
    (180, "Jdt", "Judith", "JDT", ["Judith Chapters"]),
    (190, "Esth", "Esther", "ESG", ["Esther Chapters"]),
    # Wisdom Books
    (220, "Job", "Job", "JOB", ["Job Chapters"]),
    (230, "Ps", "Psalms", "PSA", ["Psalms Chapters"]),
    (240, "Prov", "Proverbs", "PRO", ["Proverbs Chapters"]),
    (250, "Eccl", "Ecclesiastes", "ECC", ["Ecclesiastes Chapters"]),
    (260, "Song", "Song of Solomon", "SOL", ["Song of Solomon Chapters"]),
    (270, "Wis", "Wisdom", "WIS", ["Wisdom of Solomon Chapters", "Wisdom Chapters"]),
    (280, "Sir", "Sirach", "SIR", ["Sirach Chapters"]),
    # Prophets
    (290, "Isa", "Isaiah", "ISA", ["Isaiah Chapters"]),
    (300, "Jer", "Jeremiah", "JER", ["Jeremiah Chapters"]),
    (310, "Lam", "Lamentations", "LAM", ["Lamentations Chapters"]),
    (320, "Bar", "Baruch", "BAR", ["Baruch Chapters"]),
    (330, "Ezek", "Ezekiel", "EZE", ["Ezekiel Chapters"]),
    (340, "Dan", "Daniel", "DNG", ["Daniel Chapters"]),
    (350, "Hos", "Hosea", "HOS", ["Hosea Chapters"]),
    (360, "Joel", "Joel", "JOE", ["Joel Chapters"]),
    (370, "Amos", "Amos", "AMO", ["Amos Chapters"]),
    (380, "Obad", "Obadiah", "OBA", ["THE BOOK OF OBADIAH"]),
    (390, "Jonah", "Jonah", "JON", ["Jonah Chapters"]),
    (400, "Mic", "Micah", "MIC", ["Micah Chapters"]),
    (410, "Nah", "Nahum", "NAH", ["Nahum Chapters"]),
    (420, "Hab", "Habakkuk", "HAB", ["Habakkuk Chapters"]),
    (430, "Zeph", "Zephaniah", "ZEP", ["Zephaniah Chapters"]),
    (440, "Hag", "Haggai", "HAG", ["Haggai Chapters"]),
    (450, "Zech", "Zechariah", "ZEC", ["Zechariah Chapters"]),
    (460, "Mal", "Malachi", "MAL", ["Malachi Chapters"]),
    (200, "1Macc", "1 Maccabees", "1MA", ["1 Maccabees Chapters"]),
    (210, "2Macc", "2 Maccabees", "2MA", ["2 Maccabees Chapters"]),
    # New Testament
    (470, "Matt", "Matthew", "MAT", ["Matthew Chapters"]),
    (480, "Mark", "Mark", "MAR", ["Mark Chapters"]),
    (490, "Luke", "Luke", "LUK", ["Luke Chapters"]),
    (500, "John", "John", "JOH", ["John Chapters"]),
    (510, "Acts", "Acts", "ACT", ["The Acts of the Apostles Chapters", "Acts Chapters"]),
    (520, "Rom", "Romans", "ROM", ["Romans Chapters"]),
    (530, "1Cor", "1 Corinthians", "1CO", ["1 Corinthians Chapters"]),
    (540, "2Cor", "2 Corinthians", "2CO", ["2 Corinthians Chapters"]),
    (550, "Gal", "Galatians", "GAL", ["Galatians Chapters"]),
    (560, "Eph", "Ephesians", "EPH", ["Ephesians Chapters"]),
    (570, "Phil", "Philippians", "PHI", ["Philippians Chapters"]),
    (580, "Col", "Colossians", "COL", ["Colossians Chapters"]),
    (590, "1Thess", "1 Thessalonians", "1TH", ["1 Thessalonians Chapters"]),
    (600, "2Thess", "2 Thessalonians", "2TH", ["2 Thessalonians Chapters"]),
    (610, "1Tim", "1 Timothy", "1TI", ["1 Timothy Chapters"]),
    (620, "2Tim", "2 Timothy", "2TI", ["2 Timothy Chapters"]),
    (630, "Titus", "Titus", "TIT", ["Titus Chapters"]),
    (640, "Phlm", "Philemon", "PHM", ["THE LETTER OF PAUL TO PHILEMON"]),
    (650, "Heb", "Hebrews", "HEB", ["Hebrews Chapters"]),
    (660, "Jas", "James", "JAM", ["James Chapters"]),
    (670, "1Pet", "1 Peter", "1PE", ["1 Peter Chapters"]),
    (680, "2Pet", "2 Peter", "2PE", ["2 Peter Chapters"]),
    (690, "1John", "1 John", "1JO", ["1 John Chapters"]),
    (700, "2John", "2 John", "2JO", ["THE SECOND LETTER OF JOHN"]),
    (710, "3John", "3 John", "3JO", ["THE THIRD LETTER OF JOHN"]),
    (720, "Jude", "Jude", "JUD", ["THE LETTER OF JUDE"]),
    (730, "Rev", "Revelation", "REV", ["Revelation Chapters"]),
]

RE_PURE_NUM = re.compile(r"^[0-9]{1,3}$")
RE_OCR_VNUM_STANDALONE = re.compile(
    r"^(?:[0-9]{1,3}[°®©*!?%‘’“”'\"]?|[°®©£¥§¢€«»*!?%]+|[0-9][!%?°*]|[!?*‘’][0-9]|[*°©®][0-9])$"
)
RE_FUSED_VNUM = re.compile(
    r"^([0-9]{1,3}[°®©£¥™§¢€«»*!?%‘’'\"+@#~^]*|[°®©£¥™§¢€«»*!?%+~^][0-9°®©£¥™§¢€«»*!?%'\"`‘’]*|[‘’][0-9]+[°®©*!?%]?)(?=[A-Za-z“\"'‘])"
)
RE_NUM_BRACKET_I = re.compile(r"^[0-9]{1,3}[\]l|!7]$")

OPENING_WORDS = {
    "and", "then", "but", "so", "for", "now", "or", "yet", "therefore",
    "moreover", "behold", "also", "thus", "when", "if", "as", "let",
    "love", "lo", "still", "however", "indeed", "truly",
}


def ensure_webc_vpl(ref_vpl_path=None, cache_dir=DEFAULT_CACHE_DIR):
    """Return path to VPL alignment guide, downloading public-domain WEB-C if requested/needed."""
    if ref_vpl_path:
        if not os.path.exists(ref_vpl_path):
            raise FileNotFoundError(f"Reference VPL file not found: {ref_vpl_path}")
        return ref_vpl_path

    os.makedirs(cache_dir, exist_ok=True)
    cached_txt = os.path.join(cache_dir, "eng-web-c_vpl.txt")
    if os.path.exists(cached_txt):
        return cached_txt

    print(f"Downloading public-domain WEB-C alignment guide from {WEBC_VPL_URL} ...")
    with urllib.request.urlopen(WEBC_VPL_URL) as resp:
        zip_bytes = resp.read()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.endswith("_vpl.txt"):
                with open(cached_txt, "wb") as out:
                    out.write(zf.read(name))
                print(f"Cached alignment guide at {cached_txt}")
                return cached_txt
    raise RuntimeError("Could not find *_vpl.txt inside downloaded archive")


def load_vpl_reference(path):
    """Load VPL text into OrderedDict[book_code][chapter] = [(verse_num, text), ...]."""
    data = OrderedDict()
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^(\S+)\s+(\d+):(\d+)\s+(.*)$", line.strip())
            if not m:
                continue
            bk, ch, vs, txt = m.group(1).upper(), int(m.group(2)), int(m.group(3)), m.group(4)
            data.setdefault(bk, OrderedDict()).setdefault(ch, []).append((vs, txt))
    return data


def load_epub_pages(epub_path):
    """Read all `page_N.html` files from an Internet Archive EPUB in numeric page order."""
    pages = {}
    with zipfile.ZipFile(epub_path) as z:
        page_files = []
        for name in z.namelist():
            m = re.search(r"page_(\d+)\.x?html$", name)
            if m:
                page_files.append((int(m.group(1)), name))
        if not page_files:
            raise ValueError(f"No page_N.html files found inside {epub_path}")
        page_files.sort()
        for pnum, name in page_files:
            raw = z.read(name).decode("utf-8", errors="replace")
            m = re.search(r"<body[^>]*>(.*?)</body>", raw, re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""
            text = html.unescape(text)
            pages[pnum] = re.sub(r"\s+", " ", text).strip()
    return pages


def detect_book_page_ranges(pages):
    """
    Dynamically detect `(start_page, has_index_page)` for every book in CATHOLIC_BOOKS
    plus the scripture end page (start of Parallel/Exegetical Notes).
    """
    max_page = max(pages.keys())
    detected = []
    search_from = 0

    for entry in CATHOLIC_BOOKS:
        book_num, short_name, full_name, vpl_code, patterns = entry
        found_page = None
        has_idx = False
        for p in range(search_from, max_page + 1):
            t = pages.get(p, "")
            head = t[:120]
            for pat in patterns:
                if pat in head:
                    # Skip TOC front-matter pages before page 9
                    if p < 8:
                        continue
                    found_page = p
                    has_idx = "Chapters" in pat
                    break
            if found_page is not None:
                break
        if found_page is None:
            raise RuntimeError(f"Could not locate start page for {full_name} after page {search_from}")
        detected.append((book_num, short_name, full_name, vpl_code, found_page, has_idx))
        search_from = found_page + 1

    # Find back-matter start page (e.g. "PARALLEL NOTES" after Revelation)
    rev_start = detected[-1][4]
    end_page = max_page + 1
    for p in range(rev_start + 1, max_page + 1):
        t = pages.get(p, "")
        if t.startswith("PARALLEL NOTES") or t.startswith("EXEGETICAL NOTES"):
            end_page = p
            break

    return detected, end_page


def norm_word(tok):
    t = re.sub(r"^[0-9°®©£¥™§¢€«»*!?%‘’“”'\"+~^#<>]+", "", tok)
    t = re.sub(r"^L[oO0][rR][dDpPbD»]+$", "lord", t)
    return re.sub(r"[^A-Za-z]", "", t).lower()


def tokenize_ref_verse(text):
    return [nw for tok in text.split() if (nw := norm_word(tok))]


def lis_anchors(pairs):
    if not pairs:
        return []
    pairs.sort(key=lambda x: (x[0], -x[1]))
    tails = []
    tail_idx = []
    prev = [-1] * len(pairs)
    for i, (_, e) in enumerate(pairs):
        pos = bisect_left(tails, e)
        if pos == len(tails):
            tails.append(e)
            tail_idx.append(i)
        else:
            tails[pos] = e
            tail_idx[pos] = i
        if pos > 0:
            prev[i] = tail_idx[pos - 1]
    res = []
    k = tail_idx[-1]
    while k != -1:
        res.append(pairs[k])
        k = prev[k]
    res.reverse()
    return res


def find_anchors_in_range(ref_words, epub_words, r0, r1, e0, e1, n_gram=3, max_freq=3):
    if (r1 - r0) < n_gram or (e1 - e0) < n_gram:
        return []
    ref_map = defaultdict(list)
    for i in range(r0, r1 - n_gram + 1):
        gram = tuple(ref_words[i : i + n_gram])
        if all(gram):
            ref_map[gram].append(i)
    epub_map = defaultdict(list)
    for j in range(e0, e1 - n_gram + 1):
        gram = tuple(epub_words[j : j + n_gram])
        if all(gram):
            epub_map[gram].append(j)
    candidates = []
    for gram, r_positions in ref_map.items():
        if len(r_positions) > max_freq:
            continue
        e_positions = epub_map.get(gram)
        if not e_positions or len(e_positions) > max_freq:
            continue
        for rp in r_positions:
            for ep in e_positions:
                candidates.append((rp, ep))
    return lis_anchors(candidates)


def word_sim(rw, ew):
    if not rw or not ew:
        return -1.0
    if rw == ew:
        return 4.0
    if (rw, ew) in (
        ("yahweh", "lord"), ("lord", "yahweh"),
        ("sky", "heavens"), ("expanse", "firmament"),
        ("dont", "not"), ("didnt", "not"), ("wont", "not"), ("isnt", "not"),
        ("cant", "not"), ("wasnt", "not"), ("werent", "not"), ("havent", "not"),
        ("hasnt", "not"), ("hadnt", "not"), ("doesnt", "not"),
        ("youll", "you"), ("ill", "i"), ("hell", "he"), ("shell", "she"),
        ("theyll", "they"), ("well", "we"),
    ):
        return 2.5
    min_l = min(len(rw), len(ew))
    if min_l >= 4 and rw[:4] == ew[:4]:
        return 2.5
    if min_l >= 3 and rw[:3] == ew[:3]:
        return 1.2
    if min_l >= 4 and rw[-4:] == ew[-4:]:
        return 1.5
    return -1.0


def align_gap_dp(ref_words, epub_words, r0, r1, e0, e1):
    rn, en = r1 - r0, e1 - e0
    if rn == 0:
        return {}
    if en == 0:
        return {r0 + i: e0 for i in range(rn)}
    if rn * en > 250000:
        sub = find_anchors_in_range(ref_words, epub_words, r0, r1, e0, e1, n_gram=1, max_freq=2)
        if sub:
            mapping = {}
            pts = [(r0, e0)] + sub + [(r1, e1)]
            for (ra, ea), (rb, eb) in zip(pts, pts[1:]):
                if ra < rb:
                    mapping.update(align_gap_dp(ref_words, epub_words, ra, rb, ea, eb))
            return mapping
        return {r0 + i: e0 + int(i * en / rn) for i in range(rn)}

    gap_r, gap_e = -1.2, -0.8
    dp = [[0.0] * (en + 1) for _ in range(rn + 1)]
    bt = [[0] * (en + 1) for _ in range(rn + 1)]
    for i in range(1, rn + 1):
        dp[i][0] = i * gap_r
        bt[i][0] = 1
    for j in range(1, en + 1):
        dp[0][j] = j * gap_e
        bt[0][j] = 2

    for i in range(1, rn + 1):
        rw = ref_words[r0 + i - 1]
        dpi, dpp, bti = dp[i], dp[i - 1], bt[i]
        for j in range(1, en + 1):
            ew = epub_words[e0 + j - 1]
            s_diag = dpp[j - 1] + word_sim(rw, ew)
            s_up = dpp[j] + gap_r
            s_left = dpi[j - 1] + gap_e
            if s_diag >= s_up and s_diag >= s_left:
                dpi[j], bti[j] = s_diag, 0
            elif s_up >= s_left:
                dpi[j], bti[j] = s_up, 1
            else:
                dpi[j], bti[j] = s_left, 2

    mapping = {}
    i, j = rn, en
    while i > 0 or j > 0:
        move = bt[i][j]
        if move == 0:
            mapping[r0 + i - 1] = e0 + j - 1
            i -= 1
            j -= 1
        elif move == 1:
            mapping[r0 + i - 1] = e0 + j
            i -= 1
        else:
            j -= 1
    return mapping


def align_book_words(ref_words, epub_words):
    R, E = len(ref_words), len(epub_words)
    if R == 0 or E == 0:
        return {}

    anchors = find_anchors_in_range(ref_words, epub_words, 0, R, 0, E, n_gram=3, max_freq=3)

    refined = [(0, 0)]
    pts = [(0, 0)] + anchors + [(R, E)]
    for (ra, ea), (rb, eb) in zip(pts, pts[1:]):
        if (rb - ra) > 25 and (eb - ea) > 10:
            for rp, ep in find_anchors_in_range(ref_words, epub_words, ra, rb, ea, eb, n_gram=2, max_freq=3):
                if ra < rp < rb and ea < ep < eb:
                    refined.append((rp, ep))
        if rb < R:
            refined.append((rb, eb))
    refined.append((R, E))

    final_pts = [refined[0]]
    for (ra, ea), (rb, eb) in zip(refined, refined[1:]):
        if (rb - ra) > 40 and (eb - ea) > 10:
            for rp, ep in find_anchors_in_range(ref_words, epub_words, ra, rb, ea, eb, n_gram=1, max_freq=2):
                if ra < rp < rb and ea < ep < eb:
                    final_pts.append((rp, ep))
        final_pts.append((rb, eb))

    clean_pts = [final_pts[0]]
    for pt in final_pts[1:]:
        if pt[0] > clean_pts[-1][0] and pt[1] >= clean_pts[-1][1]:
            clean_pts.append(pt)
    if clean_pts[-1] != (R, E):
        clean_pts.append((R, E))

    mapping = {}
    for (ra, ea), (rb, eb) in zip(clean_pts, clean_pts[1:]):
        mapping.update(align_gap_dp(ref_words, epub_words, ra, rb, ea, eb))
    return mapping


def looks_like_verse_marker(tok, expected_vs, is_ch_start, expected_ch):
    target = str(expected_ch if is_ch_start else expected_vs)
    if tok == target:
        return 10
    m = re.match(r"^(\d{1,3})([A-Za-z“\"'‘].*)$", tok)
    if m and m.group(1) == target:
        return 9
    if RE_PURE_NUM.match(tok):
        val = int(tok)
        if (is_ch_start and abs(val - expected_ch) <= 2) or abs(val - expected_vs) <= 3:
            return 6
    m2 = RE_FUSED_VNUM.match(tok)
    if m2 and m2.group(1) not in ("'", "‘", "’", '"', "“"):
        return 5
    if RE_OCR_VNUM_STANDALONE.match(tok):
        return 4
    return 0


def strip_leading_verse_marker(tokens, expected_ch, expected_vs, ref_first_word):
    if not tokens:
        return tokens
    toks = list(tokens)
    is_ch_start = expected_vs == 1
    target_num = str(expected_ch if is_ch_start else expected_vs)

    for _ in range(3):
        if not toks:
            break
        t0 = toks[0]

        if RE_PURE_NUM.match(t0):
            val = int(t0)
            if (
                t0 == target_num
                or (is_ch_start and val in (expected_ch, 1))
                or abs(val - expected_vs) <= 10
                or (len(t0) <= 3 and len(toks) > 1)
            ):
                if ref_first_word == "i" and t0.endswith(("7", "1")) and len(t0) >= 2:
                    prefix_digits = t0[:-1]
                    if prefix_digits == str(expected_vs) or abs(int(prefix_digits) - expected_vs) <= 2:
                        toks[0] = "I"
                        break
                toks.pop(0)
                continue

        if ref_first_word == "i" and RE_NUM_BRACKET_I.match(t0):
            toks[0] = "I"
            break

        if RE_OCR_VNUM_STANDALONE.match(t0) and len(toks) > 1:
            if t0 in ("“", "‘", '"', "'"):
                break
            toks.pop(0)
            continue

        if t0 in ("*", "+", "†", "§", "°", "®", "©", "£", "¥", "™", "@", "¢", "«", "»", "è", "ĉ", "ê", "ŝ") and len(toks) > 1:
            toks.pop(0)
            continue

        m = RE_FUSED_VNUM.match(t0)
        if m:
            rest = t0[m.end() :]
            prefix = m.group(1)
            if rest.lower() == "nd":
                rest = "And"
            elif rest.lower() == "ove" and ref_first_word == "love":
                rest = "Love"
            elif rest.lower() == "f" and ref_first_word == "if":
                rest = "If"
            elif rest.lower() == "n" and ref_first_word == "in":
                rest = "In"
            elif rest.lower() == "t" and ref_first_word == "it":
                rest = "It"
            elif rest.lower() == "our" and ref_first_word == "your":
                rest = "Your"
            elif rest.lower() == "hen" and ref_first_word == "then":
                rest = "Then"
            elif rest.lower() == "ut" and ref_first_word == "but":
                rest = "But"
            elif rest.lower() == "or" and ref_first_word == "for":
                rest = "For"
            if prefix not in ('"', "'", "“", "‘"):
                toks[0] = rest
                break

        if t0 == "nd":
            toks[0] = "And"
            break
        if ref_first_word == "if" and re.match(r"^[A-Z0-9][a-z]{1,2}f$", t0) and t0.lower() != "if":
            toks[0] = "If"
            break
        if ref_first_word == "in" and t0 in ("mn", "tn", "ın", "1n"):
            toks[0] = "In"
            break
        if ref_first_word == "on" and re.match(r"^[A-Z0-9][Oo]n$", t0):
            toks[0] = "On"
            break
        if ref_first_word == "i" and re.match(r"^[0-9°®©*!?%]+I$", t0):
            toks[0] = "I"
            break
        if len(t0) >= 3 and t0[0].islower() and t0[1:].lower() == ref_first_word and t0.lower() != ref_first_word:
            toks[0] = t0[1:]
            break
        if len(t0) >= 3 and t0[0] in ("«", "»") and t0[1:].lower() == ref_first_word:
            toks[0] = t0[1:]
            break
        break

    return toks


def clean_verse_text(text):
    if not text:
        return ""

    # Fix small-caps LORD / GOD OCR variants
    text = re.sub(r"\bL[oO0][rR](?:pD|pb|p|D|bD|b|»)\b", "LORD", text)
    text = re.sub(r"\bL[oO0]RD\b", "LORD", text)
    text = re.sub(r"\bG[oO0]p\b", "GOD", text)
    text = re.sub(r"\bGoD\b", "GOD", text)

    # Remove OCR footnote symbols and superscript letters
    text = re.sub(r"(?<=\s)[@®©£¥™§¢€°*†‡«»ŝĉèê$+~^](?=\s)", "", text)
    text = re.sub(r"([.,;:!?])[a-z]\d(?=\s|$)", r"\1", text)
    text = re.sub(r",!(?=\s|$)", ",", text)
    text = re.sub(r"(?<=[A-Za-z.,;:!?\"'”’])[®©£¥™§¢€°*†‡@ŝĉèê]+", "", text)
    text = re.sub(r"(?<=\s)%(?=\s)", "", text)
    text = re.sub(r"(?:^|(?<=\s))[®©£¥™§¢€°†‡ŝĉèê]+(?=[A-Za-z\"'“‘])", "", text)
    text = re.sub(r"(?<=\s)[bcdefghjklmnopqrstuvwxyz](?=\s)", "", text)
    text = re.sub(r"\s+[*+$†‡]$", "", text)
    text = re.sub(r"(?<=[.!?\"'”’])\s+[bcdefghjklmnopqrstuvwxyz]$", "", text)

    # Rejoin broken line-end hyphens
    text = re.sub(r"\b([A-Za-z]{2,})-\s+([a-z]{2,})\b", r"\1\2", text)

    replacements = {
        "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
        "\u2014": " -- ", "\u2013": "-", "\u2026": "...",
        "\u00ab": '"', "\u00bb": '"', "\u00a0": " ", "\u00ad": "", "\u02bb": "'",
        "Í": "I", "İ": "I", "Ī": "I", "Ì": "I", "Ï": "I", "Į": "I",
        "É": "E", "Ê": "E", "Ë": "E", "Ẹ": "E", "Ħ": "H", "Ż": "Z",
        "Ž": "Z", "ž": "z", "Ņ": "N", "Š": "S", "Ŝ": "S",
        "á": "a", "é": "e", "ë": "e", "í": "i", "ī": "i", "ï": "i",
        "ø": "o", "þ": "p", "Ə": "e",
    }
    for k, v in replacements.items():
        if k in text:
            text = text.replace(k, v)

    text = re.sub(r"\s*--+\s*-*\s*", " -- ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r'(?<=[.!?:"\'])\s+\d{1,3}$', "", text).strip()

    if text.startswith('"') and text.count('"') % 2 == 1:
        if re.match(r'^"(?:And|Then|But|So|For|Now|Or|Yet|When|After|In|The|God|He|She|They|We|You|It)\b', text):
            text = text[1:].lstrip()

    text = "".join(ch if (32 <= ord(ch) <= 126) else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def split_by_anchors(text, start_phrases):
    positions = []
    cur = 0
    for phrase in start_phrases:
        idx = text.find(phrase, cur)
        if idx == -1:
            idx = text.lower().find(phrase.lower(), cur)
        if idx == -1:
            positions.append(cur)
        else:
            positions.append(idx)
            cur = idx + len(phrase)
    positions.append(len(text))
    verses = []
    for a, b in zip(positions, positions[1:]):
        v = text[a:b].strip()
        v = re.sub(r"^(?:[0-9]{1,2}\s+|\[?\d{1,2}\]?\s+)", "", v).strip()
        verses.append(clean_verse_text(v))
    return verses


def reorganize_esther_16ch(chapters_out, esther_text):
    """
    Reorganize Catholic Esther (which places Greek Additions inline with Vulgate chapter
    numbers 11-16) into sequential Chapters 1-16 matching PalmBible+ BibleChecker.book190c
    so every verse stays well under PalmBible+'s 2,048-byte search buffer.
    """
    clean_full = clean_verse_text(esther_text)

    # Fix Ch 1:1 (strip Add A prefix)
    v11 = chapters_out[1][0]
    m1 = re.search(r"In the days of Ahas", v11)
    if m1:
        chapters_out[1][0] = v11[m1.start() :].strip()

    # Fix Ch 3:13 (strip Add B suffix)
    if len(chapters_out[3]) >= 13:
        v313 = chapters_out[3][12]
        m3 = re.search(r"The King's Letter", v313)
        if m3:
            chapters_out[3][12] = v313[: m3.start()].strip()

    # Split Ch 4 extra verses into Mordecai's Prayer (13:8-18) & Esther's Prayer (14:1-19)
    ch4_extra = chapters_out[4][17:]
    chapters_out[4] = chapters_out[4][:17]
    mord_prayer, esth_prayer = [], []
    in_esth = False
    for v in ch4_extra:
        if not in_esth and "Esther the queen" in v:
            in_esth = True
            idx = v.find("Esther the queen")
            and_idx = v.rfind("And ", 0, idx + 4)
            split_at = and_idx if and_idx != -1 else idx
            if v[:split_at].strip():
                p_clean = re.sub(r"\s*Esther's Prayer.*$", "", v[:split_at]).strip()
                if p_clean:
                    mord_prayer.append(p_clean)
            esth_prayer.append(v[split_at:].strip())
        elif in_esth:
            esth_prayer.append(v)
        else:
            mord_prayer.append(re.sub(r"^Mordecai's Prayer\s*\[?13\]?\s*", "", v).strip())

    # Fix Ch 5:1 (strip Add D prefix)
    v51 = chapters_out[5][0]
    m5 = re.search(r"\[5\]\s*\d?\s*And the king said to her", v51)
    if m5:
        chapters_out[5][0] = re.sub(r"^\[5\]\s*\d?\s*", "", v51[m5.start() :]).strip()
    elif "And the king said to her" in v51:
        chapters_out[5][0] = v51[v51.find("And the king said to her") :].strip()

    # Fix Ch 8:13 (strip Add E prefix)
    if len(chapters_out[8]) >= 13:
        v813 = chapters_out[8][12]
        m8 = re.search(r"a copy of what was written", v813, re.I)
        if m8:
            chapters_out[8][12] = v813[m8.start() :].strip()
        else:
            m8b = re.search(
                r"a copy of what was written.*?to avenge themselves upon their enemies\.",
                clean_full,
                re.I,
            )
            if m8b:
                chapters_out[8][12] = m8b.group(0).strip()

    # Extract Postscript (11:1)
    postscript_v = ""
    if len(chapters_out[10]) >= 14:
        postscript_v = chapters_out[10].pop()
    else:
        mp = re.search(r"Postscript\s+11\s+(.*)$", clean_full)
        if mp:
            postscript_v = mp.group(1).strip()
    postscript_v = re.sub(r"^Postscript\s*11\s*", "", postscript_v).strip()
    postscript_v = re.sub(r"^tn\b", "In", postscript_v).strip()

    # Ch 11 (11:1-12)
    dream_start = clean_full.find("In the second year of the reign")
    plot_start = clean_full.find("Mordecai Discovers a Plot")
    if dream_start != -1 and plot_start != -1:
        ch11_dream = split_by_anchors(
            clean_full[dream_start:plot_start].strip(),
            [
                "In the second year of the reign",
                "He was a Jew, dwelling",
                "He was one of the captives",
                "And this was his dream:",
                "Behold, noise",
                "And behold, two great dragons",
                "And at their roaring",
                "And behold, a day of darkness",
                "And the whole righteous nation",
                "Then they cried to God",
                "Night came, and the sun rose",
            ],
        )
        if ch11_dream and "Mordecai saw in this dream" in ch11_dream[-1]:
            last = ch11_dream.pop()
            idx = last.find("Mordecai saw in this dream")
            ch11_dream.append(re.sub(r"\s*12$", "", last[:idx]).strip())
            ch11_dream.append(last[idx:].strip())
        chapters_out[11] = [postscript_v] + ch11_dream

    # Ch 12 (12:1-6)
    p12_start = clean_full.find("Now Mordecai took his rest")
    p12_end = clean_full.find("King Ahasuerus Deposes")
    if p12_start != -1 and p12_end != -1:
        chapters_out[12] = split_by_anchors(
            clean_full[p12_start:p12_end].strip(),
            [
                "Now Mordecai took his rest",
                "He overheard their conversation",
                "Then the king examined",
                "The king made a permanent record",
                "And the king ordered Mordecai",
                "But Haman, the son of Hammedatha",
            ],
        )

    # Ch 13 (13:1-7 + 13:8-18)
    let1_start = clean_full.find("This is a copy of the letter:")
    let1_end = clean_full.find("copy of the document was to be issued", let1_start if let1_start != -1 else 0)
    ch13_letter = []
    if let1_start != -1 and let1_end != -1:
        ch13_letter = split_by_anchors(
            clean_full[let1_start : max(let1_start, let1_end - 4)].strip(),
            [
                "This is a copy of the letter:",
                '"Having become ruler',
                '"When I asked my counselors',
                "pointed out to us that among",
                "We understand that this people",
                '"Therefore we have decreed',
                "so that those who have long been",
            ],
        )
    if ch13_letter or mord_prayer:
        chapters_out[13] = ch13_letter + mord_prayer

    # Ch 14 (14:1-19)
    if esth_prayer:
        chapters_out[14] = esth_prayer

    # Ch 15 (15:1-16)
    inv_start = clean_full.find("On the third day, when she ended")
    inv_end = clean_full.find("[5]", inv_start if inv_start != -1 else 0)
    if inv_start != -1 and inv_end != -1:
        chapters_out[15] = split_by_anchors(
            clean_full[inv_start:inv_end].strip(),
            [
                "On the third day, when she ended",
                "Then, majestically adorned",
                "while the other followed",
                "She was radiant with perfect beauty",
                "When she had gone through all the doors",
                "Lifting his face, flushed",
                "Then God changed the spirit",
                '"What is it, Esther?',
                "Then he raised the golden scepter",
                "and he embraced her",
                "she said to him,",
                "For you are wonderful",
                "But as she was speaking",
                "And the king was agitated",
            ],
        )

    # Ch 16 (16:1-24)
    ed_start = clean_full.find("The following is a copy of this letter:")
    ed_end = clean_full.find("a copy of what was written", ed_start if ed_start != -1 else 0)
    if ed_start != -1 and ed_end != -1:
        ed_text = clean_full[ed_start : max(ed_start, ed_end - 3)].strip().replace("hecause", "because")
        chapters_out[16] = split_by_anchors(
            ed_text,
            [
                "The following is a copy of this letter:",
                '"The more often they are honored',
                "They not only seek to injure",
                "They not only take away thankfulness",
                "And often many of those who are set",
                "when these men by the false trickery",
                '"What has been wickedly accomplished',
                "For the future we will take care",
                "by changing our methods",
                "For Haman, the son of Hammedatha",
                "having become our guest",
                "But, unable to restrain his arrogance",
                "and with intricate craft",
                "He thought that in this way",
                '"But we find that the Jews',
                "and are sons of the Most High",
                '"You will therefore do well',
                "because the man himself",
                '"Therefore post a copy',
                "And give them reinforcements",
                "For God, who rules over all things, has made",
                '"Therefore you shall observe',
                "so that both now and hereafter",
                '"Every city and country',
            ],
        )

    return chapters_out


def detect_book_header_end(tokens, first_ref_words):
    limit = min(len(tokens), 50)
    target = [w for w in first_ref_words[:10] if w]
    best_idx = 0
    best_score = -1.0
    for idx in range(limit):
        for t_start in range(min(4, len(target))):
            score = 0.0
            for offset in range(min(5, len(target) - t_start)):
                if idx + offset < len(tokens):
                    nw = norm_word(tokens[idx + offset])
                    tw = target[t_start + offset]
                    if nw == tw:
                        score += 3.0
                    elif nw and tw and len(nw) >= 4 and nw[:4] == tw[:4]:
                        score += 1.5
            score -= t_start * 0.5
            if score > best_score:
                best_score = score
                best_idx = idx
    return best_idx if best_score >= 4.0 else 0


def extract_epub_to_bible_data(epub_path, ref_vpl_path=None, report_path=None, quiet=False):
    """Extract and align all 73 books from an OCR EPUB, returning structured Bible data."""
    vpl_path = ensure_webc_vpl(ref_vpl_path)
    ref_bible = load_vpl_reference(vpl_path)
    pages = load_epub_pages(epub_path)
    detected_books, scripture_end_page = detect_book_page_ranges(pages)

    bible_out = []
    total_verses = 0
    missing_verses = []
    suspect_long = []

    for idx, (book_num, short_name, full_name, vpl_code, start_page, has_idx_page) in enumerate(detected_books):
        end_page = detected_books[idx + 1][4] if idx + 1 < len(detected_books) else scripture_end_page
        content_start = start_page + 1 if has_idx_page else start_page

        book_pages_text = []
        tiny_pages = 0
        for p in range(content_start, end_page):
            pt = pages.get(p, "")
            if len(pt) < 120 and p != end_page - 1:
                tiny_pages += 1
            if pt:
                book_pages_text.append(pt)
        raw_book_text = " ".join(book_pages_text)
        raw_tokens = raw_book_text.split()
        norm_tokens = [norm_word(t) for t in raw_tokens]

        # Preserve Sirach Prologue before 1:1
        sirach_prologue = ""
        if vpl_code == "SIR":
            for i in range(min(len(raw_tokens), 450)):
                if (
                    norm_tokens[i] == "all"
                    and i + 2 < len(norm_tokens)
                    and norm_tokens[i + 1] == "wisdom"
                    and norm_tokens[i + 2] == "comes"
                ):
                    sirach_prologue = re.sub(
                        r"^THE BOOK OF SIRACH\s+", "", clean_verse_text(" ".join(raw_tokens[:i]))
                    ).strip()
                    raw_tokens = raw_tokens[i:]
                    norm_tokens = norm_tokens[i:]
                    break

        ref_chapters = ref_bible[vpl_code]
        ref_verses = []
        ref_flat_words = []
        verse_ref_spans = []
        for ch, vlist in ref_chapters.items():
            for vs, vtxt in vlist:
                rw = tokenize_ref_verse(vtxt)
                r0 = len(ref_flat_words)
                ref_flat_words.extend(rw)
                ref_verses.append((ch, vs, rw))
                verse_ref_spans.append((r0, len(ref_flat_words)))

        header_end = detect_book_header_end(raw_tokens, ref_verses[0][2] if ref_verses else [])
        if header_end > 0:
            raw_tokens = raw_tokens[header_end:]
            norm_tokens = norm_tokens[header_end:]

        mapping = align_book_words(ref_flat_words, norm_tokens)

        v_count = len(ref_verses)
        v_starts = []
        for vi in range(v_count):
            r0, r1 = verse_ref_spans[vi]
            ep = mapping.get(r0, 0) if r0 < r1 else (v_starts[-1] if v_starts else 0)
            v_starts.append(ep)
        for vi in range(1, v_count):
            if v_starts[vi] < v_starts[vi - 1]:
                v_starts[vi] = v_starts[vi - 1]
        v_starts.append(len(raw_tokens))

        # Boundary pass 1: snap to OCR verse markers / sentence starts within +-3 tokens
        refined_starts = [0]
        for vi in range(1, v_count):
            ch, vs, rw = ref_verses[vi]
            pred = v_starts[vi]
            lo = max(refined_starts[-1], pred - 3)
            hi = min(len(raw_tokens), pred + 4)
            best_pos, best_score = pred, -100.0
            ref_w0 = rw[0] if rw else ""
            for pos in range(lo, hi):
                if pos >= len(raw_tokens):
                    continue
                tok = raw_tokens[pos]
                score = -abs(pos - pred) * 1.5
                vm = looks_like_verse_marker(tok, vs, vs == 1, ch)
                if vm > 0:
                    score += vm
                    if RE_PURE_NUM.match(tok) or RE_OCR_VNUM_STANDALONE.match(tok):
                        if pos + 1 < len(raw_tokens) and norm_tokens[pos + 1] == ref_w0:
                            score += 5.0
                    elif norm_tokens[pos] == ref_w0:
                        score += 5.0
                elif norm_tokens[pos] == ref_w0:
                    score += 3.0
                    if pos > 0 and raw_tokens[pos - 1][-1:] in (".", "!", "?", ";", '"', "”", "'", "’"):
                        score += 2.5
                if score > best_score:
                    best_score, best_pos = score, pos
            refined_starts.append(best_pos)
        refined_starts.append(len(raw_tokens))

        # Boundary pass 2: slide left past trailing opening conjunctions after sentence ends
        for vi in range(1, v_count):
            s_prev, s_cur = refined_starts[vi - 1], refined_starts[vi]
            if s_cur - s_prev < 3:
                continue
            ch, vs, _ = ref_verses[vi]
            for back in range(1, min(4, s_cur - s_prev)):
                cand = s_cur - back
                prev_tok = raw_tokens[cand - 1]
                if prev_tok[-1:] in (".", "!", "?", ";") or prev_tok[-2:] in (
                    '."', '!"', '?"', ".”", "!”", "?”", ".'"
                ):
                    if all(
                        norm_word(t) in OPENING_WORDS
                        or looks_like_verse_marker(t, vs, vs == 1, ch) > 0
                        or RE_PURE_NUM.match(t)
                        or RE_OCR_VNUM_STANDALONE.match(t)
                        for t in raw_tokens[cand:s_cur]
                    ):
                        refined_starts[vi] = cand
                        break

        chapters_out = OrderedDict()
        book_missing = 0
        book_total = 0
        for vi in range(v_count):
            ch, vs, rw = ref_verses[vi]
            span_toks = raw_tokens[refined_starts[vi] : refined_starts[vi + 1]]
            ref_w0 = rw[0] if rw else ""
            cleaned_toks = strip_leading_verse_marker(span_toks, ch, vs, ref_w0)
            vtext = clean_verse_text(" ".join(cleaned_toks))

            if vpl_code == "SIR" and ch == 1 and vs == 1 and sirach_prologue:
                vtext = f"[{sirach_prologue}] {vtext}"

            if not vtext or (len(vtext) <= 2 and len(rw) >= 4):
                vtext = "[Missing in source EPUB scan]"
                book_missing += 1
                missing_verses.append(f"{short_name} {ch}:{vs}")
            elif len(vtext) > 1200 and len(rw) < 60:
                suspect_long.append((f"{short_name} {ch}:{vs}", len(vtext), len(rw)))

            chapters_out.setdefault(ch, []).append(vtext)
            book_total += 1
            total_verses += 1

        if vpl_code == "ESG" and "Mordecai" in raw_book_text[:1500]:
            old_total = book_total
            chapters_out = reorganize_esther_16ch(chapters_out, raw_book_text)
            book_total = sum(len(v) for v in chapters_out.values())
            total_verses += book_total - old_total

        bible_out.append(
            {
                "book_num": book_num,
                "short_name": short_name,
                "full_name": full_name,
                "chapters": [chapters_out[ch] for ch in sorted(chapters_out.keys())],
            }
        )
        if not quiet:
            extra = f"  (missing={book_missing}, tiny_pages={tiny_pages})" if (book_missing or tiny_pages) else ""
            print(f"  [{idx+1:2d}/{len(detected_books)}] {full_name:18s} ({book_num:3d}): {len(chapters_out):3d} ch, {book_total:4d} vs{extra}")

    if report_path:
        lines = [
            f"Extraction Report for {os.path.basename(epub_path)}",
            f"Books: {len(bible_out)}",
            f"Total verses: {total_verses}",
            f"Missing/OCR-dropped verses: {len(missing_verses)}",
            f"Suspect long verses: {len(suspect_long)}",
            "",
            "--- Missing verses ---",
            *missing_verses,
        ]
        if suspect_long:
            lines.append("")
            lines.append("--- Suspect long verses ---")
            for ref, clen, rlen in suspect_long:
                lines.append(f"  {ref}: {clen} chars (ref {rlen} words)")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    if not quiet:
        print(f"Extracted {len(bible_out)} books, {total_verses:,} verses ({len(missing_verses)} missing in source scan).")
    return bible_out


def main():
    parser = argparse.ArgumentParser(
        description="Extract & verse-align an OCR Bible EPUB into JSON for Palm Bible+."
    )
    parser.add_argument("--epub", required=True, help="Path to local OCR Bible EPUB")
    parser.add_argument(
        "--ref-vpl",
        default=None,
        help="Path to VPL alignment guide (omit to auto-download public-domain WEB-C VPL)",
    )
    parser.add_argument("-o", "--output", required=True, help="Output JSON file path")
    parser.add_argument("--report", default=None, help="Optional extraction report output path")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    bible_data = extract_epub_to_bible_data(
        args.epub, ref_vpl_path=args.ref_vpl, report_path=args.report, quiet=args.quiet
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(bible_data, f, ensure_ascii=True)
    if not args.quiet:
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
