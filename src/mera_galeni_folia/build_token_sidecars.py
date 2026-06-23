"""Generate .tokens.json sidecars for every leaf chunk under tei_chunks/.

Run with:
    uv run galenus-tokenize

For each leaf passage chunk, tokenizes the chunk's primary text with the
appropriate Stanza pipeline and writes a sibling "<chunk>.tokens.json" file:

    {"urn": cts_urn, "tokens": [...]}

app.py's _load_passage loads this sidecar, if present, and splices the
tokens into the parsed element tree via kodon_py.tei_parser.inject_tokens,
so reading pages render token-level <span id="..."> elements instead of
plain text_run content.

Each token has:
    start_char, end_char  -- offsets into the chunk's primary_text
    text                  -- the token's surface form
    whitespace            -- True if whitespace follows this token in the source
    urn                   -- "{cts_urn}@{text}[{occurrence}]" for word tokens,
                             None for punctuation (nothing to cite/highlight)

The word/punctuation split and the per-word occurrence count reuse
build_search_index.py's is_word(), so a search result's token_urn always
resolves to the matching span id on the reading page.

Re-running is safe: chunks that already have a .tokens.json are skipped
unless --force is given.
"""

import argparse
import json
import time
from pathlib import Path

import stanza
from lxml import etree
from tqdm import tqdm

from kodon_py.tei_parser import TEIParser

from mera_galeni_folia.build_search_index import CHUNKS_DIR, SUPPORTED_LANGS, is_word


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


def _load_primary_text(chunk_path: Path) -> tuple[str, str] | None:
    """Return (cts_urn, primary_text) for a chunk XML file."""
    chunk_root = etree.parse(str(chunk_path)).getroot()
    elements_el = chunk_root.find("elements")
    if elements_el is None:
        return None

    parser = TEIParser(
        elements_el, chunk_root.get("base_urn", ""), chunk_root.get("unit", "")
    )
    return chunk_root.get("cts_urn", ""), parser.primary_text


def tokenize_chunk(chunk_urn: str, primary_text: str, nlp: stanza.Pipeline) -> list[dict]:
    """Tokenize primary_text into a list of inject_tokens-ready token dicts."""
    all_tokens = [t for sentence in nlp(primary_text).sentences for t in sentence.tokens]

    occurrences: dict[str, int] = {}
    tokens: list[dict] = []

    for i, token in enumerate(all_tokens):
        text = token.text.strip()
        if not text:
            continue

        end_char = token.end_char
        next_start = (
            all_tokens[i + 1].start_char if i + 1 < len(all_tokens) else len(primary_text)
        )
        whitespace = end_char < next_start and primary_text[end_char].isspace()

        urn = None
        if is_word(text):
            occurrences[text] = occurrences.get(text, 0) + 1
            urn = f"{chunk_urn}@{text}[{occurrences[text]}]"

        tokens.append(
            {
                "start_char": token.start_char,
                "end_char": end_char,
                "text": text,
                "whitespace": whitespace,
                "urn": urn,
            }
        )

    return tokens


def generate_sidecar(chunk_path: Path, nlp: stanza.Pipeline) -> bool:
    """Write chunk_path's .tokens.json sidecar. Returns False if there was nothing to tokenize."""
    loaded = _load_primary_text(chunk_path)
    if loaded is None:
        return False
    cts_urn, primary_text = loaded

    if not primary_text.strip():
        return False

    tokens = tokenize_chunk(cts_urn, primary_text, nlp)

    sidecar_path = chunk_path.with_suffix(".tokens.json")
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump({"urn": cts_urn, "tokens": tokens}, f, ensure_ascii=False)

    return True


def build(chunks_dir: Path = CHUNKS_DIR, force: bool = False) -> None:
    print(f"Downloading Stanza models: {list(SUPPORTED_LANGS)}…")
    for lang in SUPPORTED_LANGS:
        stanza.download(lang, processors="tokenize,pos,lemma", verbose=False)

    print("Loading Stanza pipelines…")
    pipelines: dict[str, stanza.Pipeline] = {
        lang: stanza.Pipeline(lang=lang, processors="tokenize,pos,lemma", verbose=False)
        for lang in SUPPORTED_LANGS
    }

    metadata_paths = sorted(chunks_dir.rglob("metadata.json"))
    print(f"Processing {len(metadata_paths)} works…")

    generated = skipped = failed = 0

    for metadata_path in tqdm(metadata_paths):
        chunk_dir = metadata_path.parent
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        language = metadata.get("document", {}).get("language", "")
        nlp = pipelines.get(language)
        if nlp is None:
            continue

        for entry in _collect_leaf_entries(metadata.get("table_of_contents", [])):
            chunk_path = chunk_dir / entry["path"]
            if not chunk_path.exists():
                continue

            sidecar_path = chunk_path.with_suffix(".tokens.json")
            if sidecar_path.exists() and not force:
                skipped += 1
                continue

            try:
                if generate_sidecar(chunk_path, nlp):
                    generated += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                print(f"  FAILED: {chunk_path}: {exc}")

    print(f"Tokens: {generated} generated, {skipped} skipped, {failed} failed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate .tokens.json sidecars for tei_chunks/"
    )
    parser.add_argument(
        "--chunks-dir",
        type=Path,
        default=CHUNKS_DIR,
        help="Root directory of chunk XML files (default: tei_chunks/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-tokenize even if .tokens.json already exists",
    )
    args = parser.parse_args()

    t = time.time()
    build(args.chunks_dir, args.force)
    print(f"Total: {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
