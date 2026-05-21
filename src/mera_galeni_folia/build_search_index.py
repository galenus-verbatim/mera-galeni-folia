"""Build the token-level FTS4 search index (search-index.sqlite) from tei_json/.

Run with:
    uv run galenus-index

Steps:
1. Walk tei_json/ for all non-metadata JSON files
2. Download Stanza models if needed
3. Lemmatize word-tokens with the appropriate Stanza pipeline (grc or la),
   using the pre-tokenized input mode so we never re-split the text
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
from typing import Iterator

import stanza
from tqdm import tqdm

APP_DIR = Path(__file__).resolve().parent
JSON_DIR = APP_DIR.parent.parent / "tei_json"
DST_PATH = APP_DIR / "static" / "search-index.sqlite"

# Maps the language code found in the JSON to the Stanza language code.
STANZA_LANG: dict[str, str] = {"grc": "grc", "lat": "la"}

# Maximum words per Stanza "sentence" to avoid memory spikes with the neural POS tagger.
CHUNK_SIZE = 200

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


def _chunks(lst: list, n: int) -> Iterator[list]:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def collect_tokens(textpart: dict) -> list[dict]:
    """Recursively collect all tokens from a textpart tree."""
    result: list[dict] = list(textpart.get("tokens", []))
    for child in textpart.get("textparts", []):
        result.extend(collect_tokens(child))
    return result


# ---------------------------------------------------------------------------
# Lemmatization
# ---------------------------------------------------------------------------


def _lemmatize_words(words: list[str], nlp: stanza.Pipeline) -> list[str]:
    """Return one lemma per word in *words* using a pre-loaded Stanza pipeline."""
    all_lemmas: list[str] = []
    for chunk in _chunks(words, CHUNK_SIZE):
        doc = nlp([chunk])
        all_lemmas.extend(
            w.lemma if w.lemma else w.text for sent in doc.sentences for w in sent.words
        )
    return all_lemmas


def process_file(
    path: Path, pipelines: dict[str, stanza.Pipeline]
) -> list[tuple[str, str, str, str, str, str]]:
    """Return a list of (token_urn, title, language, original_form, form, lemma) tuples for *path*."""
    data = json.loads(path.read_text(encoding="utf-8"))
    language: str = data.get("language", "")
    title: str = data.get("title", "")

    if language not in pipelines:
        return []

    all_tokens: list[dict] = []
    for tp in data.get("textparts", []):
        all_tokens.extend(collect_tokens(tp))

    word_positions = [
        (i, t) for i, t in enumerate(all_tokens) if is_word(t.get("text", ""))
    ]
    if not word_positions:
        return []

    words = [t["text"] for _, t in word_positions]
    lemmas = _lemmatize_words(words, pipelines[language])

    rows: list[tuple[str, str, str, str, str, str]] = []
    for (_, token), lemma in zip(word_positions, lemmas):
        urn = token.get("urn", "")
        if not urn:
            continue
        rows.append(
            (
                urn,
                title,
                language,
                token["text"],
                strip_diacritics(token["text"]),
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


def build(json_dir: Path = JSON_DIR, dst_path: Path = DST_PATH) -> None:
    langs = list(STANZA_LANG.values())
    print(f"Downloading Stanza models: {langs}…")
    for lang in langs:
        stanza.download(lang, processors="tokenize,pos,lemma", verbose=False)

    print("Loading Stanza pipelines…")
    pipelines: dict[str, stanza.Pipeline] = {}
    for json_lang, stanza_lang in STANZA_LANG.items():
        pipelines[json_lang] = stanza.Pipeline(
            lang=stanza_lang,
            processors="tokenize,pos,lemma",
            tokenize_pretokenized=True,
            verbose=False,
        )

    dst = _init_db(dst_path)

    json_files = sorted(
        p for p in json_dir.rglob("*.json") if not p.name.endswith(".metadata.json")
    )
    print(f"Processing {len(json_files)} JSON files…")

    batch_tokens: list[tuple] = []
    batch_fts: list[tuple] = []
    next_id = 1

    for path in tqdm(json_files):
        for token_urn, title, language, original_form, form, lemma in process_file(path, pipelines):
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

    gz_path = dst_path.with_suffix('.sqlite.gz')
    with open(dst_path, 'rb') as f_in, gzip.open(gz_path, 'wb', compresslevel=9) as f_out:
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
