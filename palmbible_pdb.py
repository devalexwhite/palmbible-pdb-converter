#!/usr/bin/env python3
"""
Palm Bible+ (.pdb) builder, reader, and round-trip verifier.

Implements the Palm Bible+ 3.x / BibleConverter binary format in pure Python 3
(standard library only):
  - Standard 78-byte Palm OS PDB header (Creator: 'PPBL', Type: 'bibl')
  - Record 0: VersionInfoRecord + 46-byte BookInfo entries (66- or 73-book canon)
  - Record 1: WordIndexRecord (up to 100 length-grouped index entries)
  - WordRecords (4096-byte chunks) with optional greedy bigram dictionary compression
  - Per-book BookIndexRecord + BookRecords (4096-byte chunks)
  - Automatic 14-bit byte-shifted packing (<14,079 unique words) or 16-bit unshifted
  - Independent C-spec round-trip decoder/verifier ported from PalmBible+ source
"""

import argparse
import json
import os
import re
import struct
import sys
import time
from collections import Counter, OrderedDict

# PalmBible+ binary format constants
PDB_HEADER_SIZE = 78
PDB_CREATOR = b"PPBL"
PDB_TYPE = b"bibl"
PDB_FILE_ATTRIB = 24  # 0x0018 (backup + okToInstallNewer)
PDB_VERSION = 1

COPY_PROTECTED = 1
BYTE_UNSHIFTED = 2
RIGHT_ALIGNED = 4

BYTE_SHIFTED_LIMIT = 0x36FF  # 14,079
BYTE_SHIFTED_MAX = 0x3FE0    # 16,352
BYTE_UNSHIFTED_MAX = 0xFFE0  # 65,504

WORD_INDEX_LIMIT = 4095
WORD_RECORD_SIZE = 4096
BOOK_RECORD_SIZE = 2048  # 2048 big-endian uint16s = 4096 bytes per record
MAX_INDEXES = 100        # PalmBible+ decode.h MAX_INDEXES

# Standard USFM / eBible VPL book code -> (PalmBible+ book_num, short_name<=7, full_name<=31)
# Book numbers match BibleConverter's BibleChecker.java so dual-view sync and NT
# highlighting (470..730) work across all Palm Bible+ translations.
STANDARD_BOOKS = OrderedDict(
    [
        # Old Testament - Pentateuch
        ("GEN", (10, "Gen", "Genesis")),
        ("EXO", (20, "Exod", "Exodus")),
        ("LEV", (30, "Lev", "Leviticus")),
        ("NUM", (40, "Num", "Numbers")),
        ("DEU", (50, "Deut", "Deuteronomy")),
        # Historical Books
        ("JOS", (60, "Josh", "Joshua")),
        ("JDG", (70, "Judg", "Judges")),
        ("RUT", (80, "Ruth", "Ruth")),
        ("1SA", (90, "1Sam", "1 Samuel")),
        ("2SA", (100, "2Sam", "2 Samuel")),
        ("1KI", (110, "1Kgs", "1 Kings")),
        ("2KI", (120, "2Kgs", "2 Kings")),
        ("1CH", (130, "1Chr", "1 Chronicles")),
        ("2CH", (140, "2Chr", "2 Chronicles")),
        ("EZR", (150, "Ezra", "Ezra")),
        ("NEH", (160, "Neh", "Nehemiah")),
        ("TOB", (170, "Tob", "Tobit")),
        ("JDT", (180, "Jdt", "Judith")),
        ("EST", (190, "Esth", "Esther")),
        ("ESG", (190, "Esth", "Esther")),
        # Wisdom Books
        ("JOB", (220, "Job", "Job")),
        ("PSA", (230, "Ps", "Psalms")),
        ("PRO", (240, "Prov", "Proverbs")),
        ("ECC", (250, "Eccl", "Ecclesiastes")),
        ("SNG", (260, "Song", "Song of Solomon")),
        ("SOL", (260, "Song", "Song of Solomon")),
        ("WIS", (270, "Wis", "Wisdom")),
        ("SIR", (280, "Sir", "Sirach")),
        # Prophets
        ("ISA", (290, "Isa", "Isaiah")),
        ("JER", (300, "Jer", "Jeremiah")),
        ("LAM", (310, "Lam", "Lamentations")),
        ("BAR", (320, "Bar", "Baruch")),
        ("EZK", (330, "Ezek", "Ezekiel")),
        ("EZE", (330, "Ezek", "Ezekiel")),
        ("DAN", (340, "Dan", "Daniel")),
        ("DNG", (340, "Dan", "Daniel")),
        ("HOS", (350, "Hos", "Hosea")),
        ("JOL", (360, "Joel", "Joel")),
        ("JOE", (360, "Joel", "Joel")),
        ("AMO", (370, "Amos", "Amos")),
        ("OBA", (380, "Obad", "Obadiah")),
        ("JON", (390, "Jonah", "Jonah")),
        ("MIC", (400, "Mic", "Micah")),
        ("NAM", (410, "Nah", "Nahum")),
        ("NAH", (410, "Nah", "Nahum")),
        ("HAB", (420, "Hab", "Habakkuk")),
        ("ZEP", (430, "Zeph", "Zephaniah")),
        ("HAG", (440, "Hag", "Haggai")),
        ("ZEC", (450, "Zech", "Zechariah")),
        ("MAL", (460, "Mal", "Malachi")),
        ("1MA", (200, "1Macc", "1 Maccabees")),
        ("2MA", (210, "2Macc", "2 Maccabees")),
        # New Testament
        ("MAT", (470, "Matt", "Matthew")),
        ("MRK", (480, "Mark", "Mark")),
        ("MAR", (480, "Mark", "Mark")),
        ("LUK", (490, "Luke", "Luke")),
        ("JHN", (500, "John", "John")),
        ("JOH", (500, "John", "John")),
        ("ACT", (510, "Acts", "Acts")),
        ("ROM", (520, "Rom", "Romans")),
        ("1CO", (530, "1Cor", "1 Corinthians")),
        ("2CO", (540, "2Cor", "2 Corinthians")),
        ("GAL", (550, "Gal", "Galatians")),
        ("EPH", (560, "Eph", "Ephesians")),
        ("PHP", (570, "Phil", "Philippians")),
        ("PHI", (570, "Phil", "Philippians")),
        ("COL", (580, "Col", "Colossians")),
        ("1TH", (590, "1Thess", "1 Thessalonians")),
        ("2TH", (600, "2Thess", "2 Thessalonians")),
        ("1TI", (610, "1Tim", "1 Timothy")),
        ("2TI", (620, "2Tim", "2 Timothy")),
        ("TIT", (630, "Titus", "Titus")),
        ("PHM", (640, "Phlm", "Philemon")),
        ("HEB", (650, "Heb", "Hebrews")),
        ("JAS", (660, "Jas", "James")),
        ("JAM", (660, "Jas", "James")),
        ("1PE", (670, "1Pet", "1 Peter")),
        ("2PE", (680, "2Pet", "2 Peter")),
        ("1JN", (690, "1John", "1 John")),
        ("1JO", (690, "1John", "1 John")),
        ("2JN", (700, "2John", "2 John")),
        ("2JO", (700, "2John", "2 John")),
        ("3JN", (710, "3John", "3 John")),
        ("3JO", (710, "3John", "3 John")),
        ("JUD", (720, "Jude", "Jude")),
        ("REV", (730, "Rev", "Revelation")),
    ]
)

# Canonical Catholic book order (1-2 Maccabees after Malachi)
CATHOLIC_BOOK_ORDER = [
    10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160,
    170, 180, 190, 220, 230, 240, 250, 260, 270, 280, 290, 300, 310, 320,
    330, 340, 350, 360, 370, 380, 390, 400, 410, 420, 430, 440, 450, 460,
    200, 210,
    470, 480, 490, 500, 510, 520, 530, 540, 550, 560, 570, 580, 590, 600,
    610, 620, 630, 640, 650, 660, 670, 680, 690, 700, 710, 720, 730,
]


def sanitize_palm_ascii(text):
    """Normalize common Unicode punctuation to Palm OS safe printable ASCII."""
    replacements = {
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u2014": " -- ",
        "\u2013": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\u00ad": "",
    }
    for k, v in replacements.items():
        if k in text:
            text = text.replace(k, v)
    text = "".join(ch if (32 <= ord(ch) <= 126) else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def load_vpl_as_bible_data(vpl_path, catholic_order=True):
    """
    Parse a Verse-Per-Line (VPL) text file (e.g. eBible.org `*_vpl.txt`) into
    the structured JSON list expected by `build_pdb()`.
    """
    books_map = OrderedDict()
    with open(vpl_path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^(\S+)\s+(\d+):(\d+)\s+(.*)$", line.strip())
            if not m:
                continue
            code = m.group(1).upper()
            ch = int(m.group(2))
            vs = int(m.group(3))
            txt = sanitize_palm_ascii(m.group(4))
            if code not in STANDARD_BOOKS:
                continue
            books_map.setdefault(code, OrderedDict()).setdefault(ch, {})[vs] = txt

    bible_data = []
    for code, ch_map in books_map.items():
        book_num, short_name, full_name = STANDARD_BOOKS[code]
        chapters = []
        for ch_num in sorted(ch_map.keys()):
            vs_map = ch_map[ch_num]
            max_vs = max(vs_map.keys())
            ch_verses = [vs_map.get(v, "") for v in range(1, max_vs + 1)]
            chapters.append(ch_verses)
        bible_data.append(
            {
                "book_num": book_num,
                "short_name": short_name,
                "full_name": full_name,
                "chapters": chapters,
            }
        )

    if catholic_order:
        rank = {bn: i for i, bn in enumerate(CATHOLIC_BOOK_ORDER)}
        bible_data.sort(key=lambda b: rank.get(b["book_num"], 1000 + b["book_num"]))
    else:
        bible_data.sort(key=lambda b: b["book_num"])

    return bible_data


def tokenize_verse_for_pdb(text):
    """
    Tokenize a verse string into Palm Bible+ word tokens.

    Separates leading '(' '[' and trailing '. , ? ! ; : ) ]' so PalmBible+
    spaces them natively and keeps the word dictionary compact, while keeping
    quotes attached to adjacent words so quotes render cleanly regardless of
    PalmBible+'s Smart Quotes preference.
    """
    if not text:
        return []
    tokens = []
    for raw in text.split():
        lead = []
        while raw and raw[0] in "([":
            lead.append(raw[0])
            raw = raw[1:]

        trail = []
        while raw and raw[-1] in ".,?!;:) ]":
            trail.append(raw[-1])
            raw = raw[:-1]
        trail.reverse()

        tokens.extend(lead)
        if raw:
            # Stay below PalmBible+ render.c MAX_WORD_LENGTH (60)
            while len(raw) > 55:
                tokens.append(raw[:55])
                raw = raw[55:]
            tokens.append(raw)
        tokens.extend(trail)
    return tokens


def pad_cstring(s, length):
    """Encode string as latin-1, null-terminated and padded to exact `length` bytes."""
    b = s.encode("latin-1", errors="replace")[: length - 1]
    return b + b"\x00" * (length - len(b))


class ShortShifter:
    """14-bit packer for PalmBible+ byte-shifted mode (port of ShortShifter.java)."""

    def __init__(self, byte_shifted):
        self.byte_shifted = byte_shifted
        self.shift = 0
        self.last_short = 0

    def get_short(self, inp):
        if not self.byte_shifted:
            return inp & 0xFFFF
        inp = inp & 0x3FFF
        s = self.shift
        if s == 0:
            res = -1
        elif s == 1:
            res = (self.last_short << 2) | (inp >> 12)
        elif s == 2:
            res = (self.last_short << 4) | (inp >> 10)
        elif s == 3:
            res = (self.last_short << 6) | (inp >> 8)
        elif s == 4:
            res = (self.last_short << 8) | (inp >> 6)
        elif s == 5:
            res = (self.last_short << 10) | (inp >> 4)
        elif s == 6:
            res = (self.last_short << 12) | (inp >> 2)
        else:
            res = (self.last_short << 14) | inp
        self.shift = (s + 1) & 7
        self.last_short = inp
        if res != -1:
            res &= 0xFFFF
        return res

    def flush(self):
        if self.byte_shifted:
            return self.get_short(0)
        return -1


def build_pdb(
    bible_data,
    out_path,
    pdb_name="Bible",
    version_name=None,
    version_info="",
    compress_bigrams=True,
    quiet=False,
):
    """Compile structured Bible data into a Palm Bible+ `.pdb` file."""
    if version_name is None:
        version_name = pdb_name[:15]

    if not quiet:
        print("Tokenizing verses...")

    tokenized_books = []
    vocab_set = set()
    total_tokens = 0
    for book in bible_data:
        chs = []
        for ch_verses in book["chapters"]:
            vs_toks = []
            for vtext in ch_verses:
                toks = tokenize_verse_for_pdb(vtext)
                vocab_set.update(toks)
                total_tokens += len(toks)
                vs_toks.append(toks)
            chs.append(vs_toks)
        tokenized_books.append((book, chs))

    # Sort vocabulary by (byte_length, latin-1 bytes) — required by WordIndexRecord
    sorted_words = sorted(vocab_set, key=lambda w: (len(w.encode("latin-1")), w.encode("latin-1")))
    word_count = len(sorted_words)
    if word_count > BYTE_UNSHIFTED_MAX:
        raise ValueError(f"Unique word count {word_count} exceeds PalmBible+ limit {BYTE_UNSHIFTED_MAX}")

    byte_shifted = word_count < BYTE_SHIFTED_LIMIT
    max_dict_total = BYTE_SHIFTED_MAX if byte_shifted else BYTE_UNSHIFTED_MAX
    max_compressed = max_dict_total - word_count

    if not quiet:
        mode = "14-bit byte-shifted" if byte_shifted else "16-bit unshifted"
        print(f"Unique words: {word_count:,}, Total tokens: {total_tokens:,} ({mode})")

    word_to_id = {w: i + 1 for i, w in enumerate(sorted_words)}

    book_verse_ids = []
    for book, chs in tokenized_books:
        ch_ids = [[[word_to_id[t] for t in toks] for toks in ch] for ch in chs]
        book_verse_ids.append((book, ch_ids))

    # Count uncompressed index entries first so we never exceed MAX_INDEXES (100)
    uncomp_entries = []
    cur_len = 0
    cur_cnt = 0
    for w in sorted_words:
        wl = len(w.encode("latin-1"))
        if cur_len == 0:
            cur_len = wl
        if wl != cur_len or cur_cnt >= WORD_INDEX_LIMIT:
            uncomp_entries.append((cur_len, cur_cnt, 0, 0))
            cur_len = wl
            cur_cnt = 0
        cur_cnt += 1
    if cur_cnt > 0:
        uncomp_entries.append((cur_len, cur_cnt, 0, 0))

    # Bigram compression dictionary (exact semantics of Compressor.java)
    selected_bigrams = []
    bigram_to_id = {}
    if compress_bigrams and max_compressed > 0:
        max_comp_indexes = max(0, MAX_INDEXES - 2 - len(uncomp_entries))
        comp_cap = min(max_compressed, max_comp_indexes * WORD_INDEX_LIMIT)
        if comp_cap > 0:
            bigram_counts = Counter()
            for _, ch_ids in book_verse_ids:
                for ch in ch_ids:
                    for v_ids in ch:
                        for i in range(len(v_ids) - 1):
                            bigram_counts[(v_ids[i], v_ids[i + 1])] += 1
            eligible = [(pair, cnt) for pair, cnt in bigram_counts.items() if cnt > 5]
            eligible.sort(key=lambda x: (-x[1], x[0]))
            selected_bigrams = [pair for pair, _ in eligible[:comp_cap]]
            bigram_to_id = {pair: word_count + i + 1 for i, pair in enumerate(selected_bigrams)}

    # WordIndexRecord (Record 1) & WordRecords
    word_index_entries = list(uncomp_entries)
    rem = len(selected_bigrams)
    while rem > 0:
        chunk = min(rem, WORD_INDEX_LIMIT)
        word_index_entries.append((4, chunk, 1, 1))
        rem -= chunk
    assert len(word_index_entries) <= MAX_INDEXES

    word_index_rec = bytearray(struct.pack(">H", len(word_index_entries)))
    for wl, tw, comp_flag, nothing_flag in word_index_entries:
        word_index_rec.extend(struct.pack(">HHBB", wl, tw, comp_flag, nothing_flag))

    all_word_bytes = bytearray()
    for w in sorted_words:
        all_word_bytes.extend(w.encode("latin-1"))
    for w1, w2 in selected_bigrams:
        all_word_bytes.extend(struct.pack(">HH", w1, w2))

    word_records = [
        bytes(all_word_bytes[i : i + WORD_RECORD_SIZE])
        for i in range(0, len(all_word_bytes), WORD_RECORD_SIZE)
    ] or [b""]

    if not quiet:
        print(
            f"Bigram compressions: {len(selected_bigrams):,}, "
            f"Word index entries: {len(word_index_entries)}, "
            f"Word records: {len(word_records)} ({len(all_word_bytes):,} bytes)"
        )

    # BookIndexRecord + BookRecords per book
    books_built = []
    for book, ch_ids in book_verse_ids:
        shifter = ShortShifter(byte_shifted)
        book_recs = []
        cur_rec = bytearray()
        shorts_in_cur = 0

        total_verses_acc = []
        total_chapter_chars_acc = []
        total_verse_chars_acc = []
        v_acc = 0
        ch_char_acc = 0

        for ch in ch_ids:
            total_chapter_chars_acc.append(ch_char_acc)
            v_acc += len(ch)
            total_verses_acc.append(v_acc)

            vs_char_acc = 0
            for v_ids in ch:
                comp_ids = []
                i = 0
                n = len(v_ids)
                while i < n:
                    if i + 1 < n:
                        cid = bigram_to_id.get((v_ids[i], v_ids[i + 1]))
                        if cid is not None:
                            comp_ids.append(cid)
                            i += 2
                            continue
                    comp_ids.append(v_ids[i])
                    i += 1

                for cid in comp_ids:
                    s14 = shifter.get_short(cid)
                    if s14 != -1:
                        if shorts_in_cur >= BOOK_RECORD_SIZE:
                            book_recs.append(bytes(cur_rec))
                            cur_rec = bytearray()
                            shorts_in_cur = 0
                        cur_rec.extend(struct.pack(">H", s14))
                        shorts_in_cur += 1

                vs_char_acc += len(comp_ids)
                if vs_char_acc > 65535:
                    raise ValueError(
                        f"Chapter token count overflow ({vs_char_acc}) in {book['short_name']}"
                    )
                total_verse_chars_acc.append(vs_char_acc)

            ch_char_acc += vs_char_acc

        tail_short = shifter.flush()
        if tail_short > 0:
            if shorts_in_cur >= BOOK_RECORD_SIZE:
                book_recs.append(bytes(cur_rec))
                cur_rec = bytearray()
                shorts_in_cur = 0
            cur_rec.extend(struct.pack(">H", tail_short))
            shorts_in_cur += 1

        if cur_rec or not book_recs:
            book_recs.append(bytes(cur_rec))

        idx_rec = bytearray(struct.pack(">H", len(ch_ids)))
        for va in total_verses_acc:
            idx_rec.extend(struct.pack(">H", va))
        for cca in total_chapter_chars_acc:
            idx_rec.extend(struct.pack(">I", cca))
        for vca in total_verse_chars_acc:
            idx_rec.extend(struct.pack(">H", vca))

        books_built.append((book, bytes(idx_rec), book_recs))

    # VersionInfoRecord (Record 0)
    ver_rec = bytearray()
    ver_rec.extend(pad_cstring(version_name, 16))
    ver_rec.extend(pad_cstring(version_info, 128))
    ver_rec.extend(b" ")  # sepChar
    ver_attrib = 0 if byte_shifted else BYTE_UNSHIFTED
    ver_rec.extend(struct.pack(">B", ver_attrib))
    ver_rec.extend(struct.pack(">HHH", 1, len(word_records), len(books_built)))

    book_rec_no = len(word_records) + 2
    for book, idx_rec, book_recs in books_built:
        ver_rec.extend(struct.pack(">HHH", book["book_num"], book_rec_no, len(book_recs)))
        ver_rec.extend(pad_cstring(book["short_name"], 8))
        ver_rec.extend(pad_cstring(book["full_name"], 32))
        book_rec_no += len(book_recs) + 1

    # Assemble PDB records
    all_records = [bytes(ver_rec), bytes(word_index_rec)]
    all_records.extend(word_records)
    for _, idx_rec, book_recs in books_built:
        all_records.append(idx_rec)
        all_records.extend(book_recs)

    num_recs = len(all_records)
    if num_recs > 65535:
        raise ValueError(f"Record count {num_recs} exceeds Palm PDB 16-bit limit")

    # Standard 78-byte Palm OS PDB header
    palm_now = int(time.time()) + 2082844800
    header = bytearray(pad_cstring(pdb_name, 32))
    header.extend(
        struct.pack(
            ">HHIIIIII4s4sIIH",
            PDB_FILE_ATTRIB,
            PDB_VERSION,
            palm_now,
            palm_now,
            0,
            0,
            0,
            0,
            PDB_TYPE,
            PDB_CREATOR,
            0,
            0,
            num_recs,
        )
    )
    assert len(header) == PDB_HEADER_SIZE

    offset = PDB_HEADER_SIZE + 8 * num_recs + 2
    rec_list = bytearray()
    for i, rec in enumerate(all_records):
        rec_list.extend(
            struct.pack(">IBBBB", offset, 0, (i >> 16) & 0xFF, (i >> 8) & 0xFF, i & 0xFF)
        )
        offset += len(rec)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(header)
        f.write(rec_list)
        f.write(b"\x00\x00")
        for rec in all_records:
            f.write(rec)

    file_size = os.path.getsize(out_path)
    if not quiet:
        print(f"Wrote {out_path} ({file_size:,} bytes = {file_size / (1024 * 1024):.2f} MB, {num_recs} records)")
    return file_size


class PalmBibleReader:
    """
    Independent Palm Bible+ `.pdb` decoder ported from PalmBible+ 3.2.0 C source
    (`info.c`, `reader.c`, `decode.c`).
    """

    def __init__(self, pdb_path):
        with open(pdb_path, "rb") as f:
            self.data = f.read()

        self.pdb_name = self.data[:32].split(b"\x00", 1)[0].decode("latin-1")
        (
            self.file_attrib,
            self.version,
            self.ctime,
            self.mtime,
            self.btime,
            self.modnum,
            self.app_info,
            self.sort_info,
            self.db_type,
            self.creator,
            self.uid_seed,
            self.next_rec,
            self.num_recs,
        ) = struct.unpack(">HHIIIIII4s4sIIH", self.data[32:78])

        if self.db_type != b"bibl" or self.creator != b"PPBL":
            raise ValueError(
                f"Not a Palm Bible+ PDB (creator={self.creator!r}, type={self.db_type!r})"
            )

        offsets = []
        pos = 78
        for _ in range(self.num_recs):
            offsets.append(struct.unpack(">I", self.data[pos : pos + 4])[0])
            pos += 8
        offsets.append(len(self.data))
        self.records = [self.data[offsets[i] : offsets[i + 1]] for i in range(self.num_recs)]

        r0 = self.records[0]
        self.version_name = r0[0:16].split(b"\x00", 1)[0].decode("latin-1")
        self.version_info = r0[16:144].split(b"\x00", 1)[0].decode("latin-1")
        self.sep_char = chr(r0[144]) if r0[144] != 0 else ""
        self.ver_attrib = r0[145]
        self.byte_shifted = not bool(self.ver_attrib & BYTE_UNSHIFTED)
        self.word_index_rec_num, self.total_word_rec, self.total_books = struct.unpack(
            ">HHH", r0[146:152]
        )

        self.books = []
        bpos = 152
        for _ in range(self.total_books):
            book_num, book_index, total_book_rec = struct.unpack(">HHH", r0[bpos : bpos + 6])
            simple_name = r0[bpos + 6 : bpos + 14].split(b"\x00", 1)[0].decode("latin-1")
            complex_name = r0[bpos + 14 : bpos + 46].split(b"\x00", 1)[0].decode("latin-1")
            self.books.append(
                {
                    "book_num": book_num,
                    "book_index": book_index,
                    "total_book_rec": total_book_rec,
                    "simple_name": simple_name,
                    "complex_name": complex_name,
                }
            )
            bpos += 46

        wi_rec = self.records[self.word_index_rec_num]
        total_indexes = struct.unpack(">H", wi_rec[0:2])[0]
        assert total_indexes <= MAX_INDEXES, f"Word index count {total_indexes} > {MAX_INDEXES}"
        self.word_indexes = []
        self.cached_rel_num_sum = [0]
        self.cached_total_byte_acc = [0]
        wpos = 2
        for _ in range(total_indexes):
            wl, tw, comp, _ = struct.unpack(">HHBB", wi_rec[wpos : wpos + 6])
            self.word_indexes.append((wl, tw, bool(comp)))
            self.cached_rel_num_sum.append(self.cached_rel_num_sum[-1] + tw)
            self.cached_total_byte_acc.append(self.cached_total_byte_acc[-1] + tw * wl)
            wpos += 6

        self.word_stream = b"".join(
            self.records[
                self.word_index_rec_num + 1 : self.word_index_rec_num + 1 + self.total_word_rec
            ]
        )

    def _lookup_word_entry(self, word_num):
        rel = word_num - 1
        for i, (wl, _, comp) in enumerate(self.word_indexes):
            if rel < self.cached_rel_num_sum[i + 1]:
                byte_off = self.cached_total_byte_acc[i] + (rel - self.cached_rel_num_sum[i]) * wl
                return byte_off, wl, comp
        raise KeyError(f"Word number {word_num} out of range")

    def _expand_word_num(self, word_num):
        if word_num >= 0xFFF0:
            return []
        byte_off, wl, comp = self._lookup_word_entry(word_num)
        raw = self.word_stream[byte_off : byte_off + wl]
        if comp:
            ids = struct.unpack(f">{wl // 2}H", raw)
            out = []
            for sub_id in ids:
                if self.byte_shifted and sub_id > 0x3FF0:
                    sub_id |= 0xC000
                bo2, wl2, comp2 = self._lookup_word_entry(sub_id)
                assert not comp2
                out.append(self.word_stream[bo2 : bo2 + wl2].decode("latin-1"))
            return out
        return [raw.decode("latin-1")]

    def _read_compressed_ids(self, book_stream, verse_start, verse_len):
        ids = []
        if self.byte_shifted:
            shift_lookup_start = (0, 3, 2, 1)
            shift_lookup_read = (10, 4, 6, 8)
            comp_start = (verse_start * 7) // 4
            dec_shift = shift_lookup_start[(verse_start * 7) % 4]
            pos = comp_start
            buf = [0, 0, 0]
            if dec_shift == 1:
                buf[1] = book_stream[pos]; pos += 1
            elif dec_shift in (2, 3):
                buf[2] = book_stream[pos]; pos += 1
            for _ in range(verse_len):
                if dec_shift == 0:
                    buf[0] = book_stream[pos]; pos += 1
                    buf[1] = book_stream[pos]; pos += 1
                    buf[2] = 0
                elif dec_shift == 1:
                    buf[0] = buf[1]
                    buf[1] = book_stream[pos]; pos += 1
                    buf[2] = book_stream[pos]; pos += 1
                elif dec_shift == 2:
                    buf[0] = buf[2]
                    buf[1] = book_stream[pos]; pos += 1
                    buf[2] = book_stream[pos]; pos += 1
                else:
                    buf[0] = buf[2]
                    buf[1] = book_stream[pos]; pos += 1
                    buf[2] = 0
                val = ((buf[0] << 16) | (buf[1] << 8) | buf[2]) >> shift_lookup_read[dec_shift]
                val &= 0x3FFF
                dec_shift = (dec_shift + 1) & 3
                if val > 0x3FF0:
                    val |= 0xC000
                ids.append(val)
        else:
            pos = verse_start * 2
            for _ in range(verse_len):
                ids.append(struct.unpack(">H", book_stream[pos : pos + 2])[0])
                pos += 2
        return ids

    def decode_book_tokens(self, book_idx):
        b = self.books[book_idx]
        idx_rec = self.records[b["book_index"]]
        total_ch = struct.unpack(">H", idx_rec[0:2])[0]
        off = 2
        total_verses_acc = struct.unpack(f">{total_ch}H", idx_rec[off : off + 2 * total_ch])
        off += 2 * total_ch
        total_ch_chars_acc = struct.unpack(f">{total_ch}I", idx_rec[off : off + 4 * total_ch])
        off += 4 * total_ch
        total_vs = total_verses_acc[-1] if total_ch > 0 else 0
        total_vs_chars_acc = struct.unpack(f">{total_vs}H", idx_rec[off : off + 2 * total_vs])

        book_stream = b"".join(
            self.records[b["book_index"] + 1 : b["book_index"] + 1 + b["total_book_rec"]]
        )

        chapters = []
        for ch_1 in range(1, total_ch + 1):
            prev_v_acc = total_verses_acc[ch_1 - 2] if ch_1 > 1 else 0
            n_verses = total_verses_acc[ch_1 - 1] - prev_v_acc
            ch_verses = []
            for vs_1 in range(1, n_verses + 1):
                verse_acc = prev_v_acc + vs_1
                verse_start = total_ch_chars_acc[ch_1 - 1]
                if vs_1 > 1:
                    verse_start += total_vs_chars_acc[verse_acc - 2]
                    verse_len = total_vs_chars_acc[verse_acc - 1] - total_vs_chars_acc[verse_acc - 2]
                else:
                    verse_len = total_vs_chars_acc[verse_acc - 1]
                comp_ids = self._read_compressed_ids(book_stream, verse_start, verse_len)
                toks = []
                for cid in comp_ids:
                    toks.extend(self._expand_word_num(cid))
                ch_verses.append(toks)
            chapters.append(ch_verses)
        return chapters

    @staticmethod
    def render_tokens(tokens):
        out = ""
        hold = ""
        for t in tokens:
            if hold:
                t = hold + t
                hold = ""
            if len(t) == 1 and t in "([{<":
                hold = t
                continue
            if len(t) == 1 and t in ".,?!;:)]}>":
                if out.endswith(" "):
                    out = out[:-1]
                out += t + " "
            else:
                out += t + " "
        return out.strip()

    def lookup_verse(self, ref_str):
        """Look up a verse such as 'John 3:16' or '1Cor 13:4'."""
        m = re.match(r"^\s*(.+?)\s+(\d+):(\d+)\s*$", ref_str)
        if not m:
            raise ValueError(f"Invalid verse reference: {ref_str!r} (expected e.g. 'John 3:16')")
        bname, ch, vs = m.group(1).strip().lower(), int(m.group(2)), int(m.group(3))
        for idx, b in enumerate(self.books):
            if b["simple_name"].lower() == bname or b["complex_name"].lower() == bname:
                chs = self.decode_book_tokens(idx)
                return self.render_tokens(chs[ch - 1][vs - 1])
        raise KeyError(f"Book {m.group(1)!r} not found in PDB")


def verify_pdb(pdb_path, bible_data=None, quiet=False):
    """Verify binary structure, PalmBible+ limits, and (if bible_data given) 100% lossless round-trip."""
    rdr = PalmBibleReader(pdb_path)
    rec_sizes = [len(r) for r in rdr.records]
    max_wl = max((wl for wl, _, comp in rdr.word_indexes if not comp), default=0)

    checked_verses = 0
    max_v_len = 0
    max_v_ref = ""
    over_2048 = 0

    if bible_data is not None:
        assert rdr.total_books == len(bible_data), "Book count mismatch"

    for bi, bmeta in enumerate(rdr.books):
        decoded_chs = rdr.decode_book_tokens(bi)
        if bible_data is not None:
            book = bible_data[bi]
            assert bmeta["book_num"] == book["book_num"]
            assert bmeta["simple_name"] == book["short_name"]
            assert bmeta["complex_name"] == book["full_name"]
            assert len(decoded_chs) == len(book["chapters"])

        for ci, dec_ch in enumerate(decoded_chs):
            if bible_data is not None:
                orig_ch = bible_data[bi]["chapters"][ci]
                assert len(dec_ch) == len(orig_ch)
            for vi, dec_toks in enumerate(dec_ch):
                if bible_data is not None:
                    expected_toks = tokenize_verse_for_pdb(bible_data[bi]["chapters"][ci][vi])
                    if dec_toks != expected_toks:
                        raise AssertionError(
                            f"Round-trip mismatch at {bmeta['simple_name']} {ci+1}:{vi+1}"
                        )
                rendered = rdr.render_tokens(dec_toks)
                if len(rendered) > max_v_len:
                    max_v_len = len(rendered)
                    max_v_ref = f"{bmeta['simple_name']} {ci+1}:{vi+1}"
                if len(rendered) >= 2048:
                    over_2048 += 1
                checked_verses += 1

    if not quiet:
        print(f"Verified {pdb_path}:")
        print(f"  PDB Name / Version : {rdr.pdb_name!r} / {rdr.version_name!r}")
        print(f"  Version Info       : {rdr.version_info!r}")
        print(f"  Creator / Type     : {rdr.creator.decode()}/{rdr.db_type.decode()}")
        print(f"  Encoding           : {'14-bit byte-shifted' if rdr.byte_shifted else '16-bit unshifted'}")
        print(f"  Books / Verses     : {rdr.total_books} books, {checked_verses:,} verses")
        print(f"  Records / Max Size : {rdr.num_recs} records (max {max(rec_sizes):,} bytes)")
        print(f"  Word Index / Len   : {len(rdr.word_indexes)} entries (<=100), max word {max_wl} bytes (<=60)")
        print(f"  Longest Verse      : {max_v_len} chars at {max_v_ref} (>=2048: {over_2048})")
        if bible_data is not None:
            print("  Round-trip check   : PASSED (100% lossless)")
    return rdr


def main():
    parser = argparse.ArgumentParser(
        description="Build or inspect/verify Palm Bible+ (.pdb) database files."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="Build a Palm Bible+ .pdb from JSON or VPL text")
    p_build.add_argument("-i", "--input", required=True, help="Input .json or VPL .txt file")
    p_build.add_argument("-o", "--output", required=True, help="Output .pdb file path")
    p_build.add_argument("--name", default="Bible", help="Short PDB / version name (<=15 chars)")
    p_build.add_argument("--info", default="", help="Version info / description (<=127 chars)")
    p_build.add_argument(
        "--protestant-order",
        action="store_true",
        help="Sort VPL books strictly by numeric book ID instead of Catholic order",
    )
    p_build.add_argument("--no-compress", action="store_true", help="Disable bigram compression")
    p_build.add_argument("--no-verify", action="store_true", help="Skip round-trip verification")

    p_insp = sub.add_parser("inspect", help="Inspect and verify an existing Palm Bible+ .pdb")
    p_insp.add_argument("pdb", help="Path to .pdb file")
    p_insp.add_argument("--verse", action="append", default=[], help="Look up verse (e.g. 'John 3:16')")

    args = parser.parse_args()

    if args.cmd == "build":
        if args.input.lower().endswith(".json"):
            with open(args.input, encoding="utf-8") as f:
                bible_data = json.load(f)
        else:
            bible_data = load_vpl_as_bible_data(
                args.input, catholic_order=not args.protestant_order
            )
        build_pdb(
            bible_data,
            args.output,
            pdb_name=args.name,
            version_name=args.name[:15],
            version_info=args.info,
            compress_bigrams=not args.no_compress,
        )
        if not args.no_verify:
            verify_pdb(args.output, bible_data)

    elif args.cmd == "inspect":
        rdr = verify_pdb(args.pdb)
        for ref in args.verse:
            print(f"  {ref} -> {rdr.lookup_verse(ref)}")


if __name__ == "__main__":
    main()
