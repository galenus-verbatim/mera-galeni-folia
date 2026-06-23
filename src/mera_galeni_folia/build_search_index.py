"""Build the token-level FTS4 search index (search-index.sqlite) from tei_chunks/.

Run with:
    uv run galenus-index

Steps:
1. Walk tei_chunks/ for every work's metadata.json, and for each leaf passage
   chunk listed in its table of contents, load the chunk's TEI XML
2. Download Stanza models if needed
3. Tokenize and lemmatize each passage's primary text with the
   appropriate Stanza pipeline (grc or la)
4. Write search-index.sqlite:
     tokens(id, token_urn, title, language)
     search_fts USING fts4(form, lemma)   -- rowid == tokens.id

sql.js ships with FTS4 (not FTS5), so we use FTS4 here.
Both columns store diacritic-stripped, lowercased text so the JS query
(which also strips diacritics) matches correctly.
"""

import gzip
import json
import shutil
import sqlite3
import unicodedata
from pathlib import Path

import stanza
from lxml import etree
from tqdm import tqdm

from kodon_py.tei_parser import TEIParser

APP_DIR = Path(__file__).resolve().parent
CHUNKS_DIR = APP_DIR.parent.parent / "tei_chunks"
DST_PATH = APP_DIR / "static" / "search-index.sqlite"

# Languages found in metadata.json's "document.language", which already use
# Stanza's own language codes ("grc", "la").
SUPPORTED_LANGS = ("grc", "la")

# SQLite batch size (rows per commit).
BATCH_SIZE = 5_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def strip_diacritics(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    ).lower()


def is_word(text: str) -> bool:
    return any(c.isalpha() for c in text)


def _collect_leaf_entries(entries: list) -> list[dict]:
    """Flatten a (possibly nested) table of contents to its leaf chunks."""
    result = []
    for entry in entries:
        subpassages = entry.get("subpassages") or []
        if subpassages:
            result.extend(_collect_leaf_entries(subpassages))
        elif "path" in entry:
            result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


def _load_primary_text(chunk_path: Path) -> str | None:
    chunk_root = etree.parse(str(chunk_path)).getroot()
    elements_el = chunk_root.find("elements")
    if elements_el is None:
        return None

    parser = TEIParser(elements_el, chunk_root.get("base_urn", ""), chunk_root.get("unit", ""))
    return parser.primary_text


def process_chunk(
    chunk_dir: Path, entry: dict, document: dict, pipelines: dict[str, stanza.Pipeline]
) -> list[tuple[str, str, str, str, str, str]]:
    """Return a list of (token_urn, title, language, original_form, form, lemma) tuples."""
    language: str = document.get("language", "")
    if language not in pipelines:
        return []

    chunk_path = chunk_dir / entry["path"]
    if not chunk_path.exists():
        return []

    primary_text = _load_primary_text(chunk_path)
    if not primary_text:
        return []

    title: str = document.get("title") or ""
    leaf_urn: str = entry["urn"]

    doc = pipelines[language](primary_text)

    occurrences: dict[str, int] = {}
    rows: list[tuple[str, str, str, str, str, str]] = []
    for sentence in doc.sentences:
        for token in sentence.tokens:
            if not is_word(token.text):
                continue

            occurrences[token.text] = occurrences.get(token.text, 0) + 1
            token_urn = f"{leaf_urn}@{token.text}[{occurrences[token.text]}]"
            lemma = " ".join(w.lemma or w.text for w in token.words)

            rows.append(
                (
                    token_urn,
                    title,
                    language,
                    token.text,
                    strip_diacritics(token.text),
                    strip_diacritics(lemma),
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------


def _init_db(dst_path: Path) -> sqlite3.Connection:
    if dst_path.exists():
        dst_path.unlink()
    dst = sqlite3.connect(dst_path)
    dst.execute("PRAGMA journal_mode=OFF")
    dst.execute("PRAGMA synchronous=OFF")
    dst.execute("PRAGMA cache_size=-64000")
    dst.execute("""
        CREATE TABLE tokens (
            id            INTEGER PRIMARY KEY,
            token_urn     TEXT NOT NULL,
            title         TEXT NOT NULL,
            language      TEXT NOT NULL,
            original_form TEXT NOT NULL
        )
    """)
    # FTS4: two columns so the JS can MATCH against form or lemma transparently.
    dst.execute("CREATE VIRTUAL TABLE search_fts USING fts4(form, lemma)")
    dst.commit()
    return dst


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------


def build(chunks_dir: Path = CHUNKS_DIR, dst_path: Path = DST_PATH) -> None:
    print(f"Downloading Stanza models: {list(SUPPORTED_LANGS)}…")
    for lang in SUPPORTED_LANGS:
        stanza.download(lang, processors="tokenize,pos,lemma", verbose=False)

    print("Loading Stanza pipelines…")
    pipelines: dict[str, stanza.Pipeline] = {
        lang: stanza.Pipeline(lang=lang, processors="tokenize,pos,lemma", verbose=False)
        for lang in SUPPORTED_LANGS
    }

    dst = _init_db(dst_path)

    metadata_paths = sorted(chunks_dir.rglob("metadata.json"))
    print(f"Processing {len(metadata_paths)} works…")

    batch_tokens: list[tuple] = []
    batch_fts: list[tuple] = []
    next_id = 1

    for metadata_path in tqdm(metadata_paths):
        chunk_dir = metadata_path.parent
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        document = metadata.get("document", {})
        leaf_entries = _collect_leaf_entries(metadata.get("table_of_contents", []))

        for entry in leaf_entries:
            for token_urn, title, language, original_form, form, lemma in process_chunk(
                chunk_dir, entry, document, pipelines
            ):
                batch_tokens.append((next_id, token_urn, title, language, original_form))
                batch_fts.append((next_id, form, lemma))
                next_id += 1

                if len(batch_tokens) >= BATCH_SIZE:
                    dst.executemany("INSERT INTO tokens VALUES (?,?,?,?,?)", batch_tokens)
                    dst.executemany(
                        "INSERT INTO search_fts(rowid, form, lemma) VALUES (?,?,?)",
                        batch_fts,
                    )
                    dst.commit()
                    batch_tokens.clear()
                    batch_fts.clear()

    if batch_tokens:
        dst.executemany("INSERT INTO tokens VALUES (?,?,?,?,?)", batch_tokens)
        dst.executemany(
            "INSERT INTO search_fts(rowid, form, lemma) VALUES (?,?,?)",
            batch_fts,
        )
        dst.commit()

    print("Optimizing FTS index…")
    dst.execute("INSERT INTO search_fts(search_fts) VALUES('optimize')")
    dst.commit()
    dst.close()

    size = dst_path.stat().st_size
    print(f"Built {dst_path.name} ({size / 1024 / 1024:.1f} MB), compressing…")

    gz_path = dst_path.with_suffix(".sqlite.gz")
    with (
        open(dst_path, "rb") as f_in,
        gzip.open(gz_path, "wb", compresslevel=9) as f_out,
    ):
        shutil.copyfileobj(f_in, f_out)

    gz_size = gz_path.stat().st_size
    print(f"Done. {gz_path.name} ({gz_size / 1024 / 1024:.1f} MB)")


def main() -> None:
    import time

    t = time.time()
    build()
    print(f"Total: {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
