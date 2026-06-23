import json
import os

from pathlib import Path
from typing import Any

import markdown

from flask import abort, render_template, url_for
from lxml import etree

from kodon_py.config import default_config
from kodon_py.server import create_app, load_toc_from_urn
from kodon_py.tei_parser import TEIParser, inject_tokens
from kodon_py.urn_utils import parse_urn

from mera_galeni_folia.build import (
    _format_critical_edition,
    _format_modern_translation,
    _int_or_zero,
)
from mera_galeni_folia.reading import (
    get_iiif_config,
    load_images_config,
)
from mera_galeni_folia.zotero import SORT_ORDERS, fetch_opera, read_zotero_json

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRAGMENT_DIR = (ROOT_DIR / "tei_chunks").absolute()

CTS_INDEX = APP_DIR / "static" / "json" / "cts_index.json"
FAQ_MARKDOWN = APP_DIR / "static" / "markdown" / "faq.md"
UPDATES_MARKDOWN = APP_DIR / "static" / "markdown" / "actualites.md"

IMAGES_DATA = load_images_config()


def _find_page_ns(
    text_containers, first=None, last=None
) -> tuple[str | None, str | None]:
    for tc in text_containers:
        if tc.get("tagname") == "pb":
            n = tc.get("n")
            if first is None:
                first = n
            last = n
        first, last = _find_page_ns(tc.get("children", []), first, last)
    return first, last


def _assign_line_ids(text_containers, current_page_n=None):
    for text_container in text_containers:
        if text_container.get("tagname") == "pb":
            current_page_n = text_container["n"]

        if text_container.get("tagname") == "lb":
            text_container["html_id"] = (
                f"l{current_page_n}.{text_container.get('n', '')}"
            )

        if len(text_container.get("children", [])) > 0:
            current_page_n = _assign_line_ids(
                text_container["children"], current_page_n
            )

    return current_page_n


def _extract_cts_urn(extra: str | Any) -> str | None:
    """Extract a CTS URN from a Zotero item's 'extra' field."""
    if not isinstance(extra, str):
        return None
    for line in extra.split("\n"):
        if line.startswith("CTS URN: "):
            return line.split("CTS URN: ", 1)[1].strip()
    return None


def _chunk_dir_and_metadata(cts_urn: str, json_dir: Path) -> tuple[Path, dict] | None:
    """Locate the chunk directory and load its metadata.json for a work URN."""
    parsed = parse_urn(cts_urn)
    if not parsed.text_group or not parsed.work or not parsed.work_component:
        return None

    chunk_dir = json_dir / parsed.text_group / parsed.work / parsed.work_component
    metadata_path = chunk_dir / "metadata.json"
    if not metadata_path.exists():
        return None

    with open(metadata_path, encoding="utf-8") as f:
        return chunk_dir, json.load(f)


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


def _load_passage(urn: str, fragment_dir: Path) -> dict | None:
    """Load a passage's text_containers, same shape as kodon_py.server.load_passage_from_urn.

    Reimplemented locally (rather than calling kodon_py.server directly) so that
    a sibling "<chunk>.tokens.json" sidecar, if present, can be injected into the
    parsed elements via inject_tokens. Without a sidecar, text_run nodes are left
    as plain text and rendered as-is by ReadableTextContainer.html.jinja.
    """
    found = _chunk_dir_and_metadata(urn, fragment_dir)
    if found is None:
        return None
    chunk_dir, metadata = found

    leaves = _collect_leaf_entries(metadata.get("table_of_contents", []))
    if not leaves:
        return None

    parsed = parse_urn(urn)
    if parsed.passage_component:
        leaf = next((leaf for leaf in leaves if leaf["urn"] == urn), None)
        if leaf is None:
            return None
    else:
        leaf = leaves[0]

    chunk_path = chunk_dir / leaf["path"]
    if not chunk_path.exists():
        return None

    chunk_root = etree.parse(str(chunk_path)).getroot()
    content_el = chunk_root.find("elements")
    if content_el is None:
        return None

    base_urn = chunk_root.get("base_urn", "")
    unit = chunk_root.get("unit", "")
    cts_urn = chunk_root.get("cts_urn", "")
    prev_urn = chunk_root.get("prev_urn")
    next_urn = chunk_root.get("next_urn")

    parser = TEIParser(content_el, base_urn, unit)

    tokens_path = chunk_path.with_suffix(".tokens.json")
    if tokens_path.exists():
        with open(tokens_path, encoding="utf-8") as f:
            inject_tokens(parser.elements, json.load(f).get("tokens", []))

    children = parser.elements[0]["children"] if parser.elements else []

    return {
        "text_containers": [{"urn": cts_urn, "children": children}],
        "previous": prev_urn,
        "next": next_urn,
    }


def _refs_from_metadata(cts_urn: str, chunk_dir: Path) -> list[str]:
    """Return leaf-level passage refs by flattening the TOC.

    For single-level texts (chapters only) this is identical to the old
    behaviour.  For multi-level texts (book > chapter) it recurses into
    subpassages so refs like "2.71" are returned instead of just "2".
    """
    found = _chunk_dir_and_metadata(cts_urn, chunk_dir)
    if found is None:
        return []
    _chunk_dir, metadata = found

    return [
        entry["urn"].rsplit(":", 1)[1]
        for entry in _collect_leaf_entries(metadata.get("table_of_contents", []))
    ]


def _get_first_pages_per_ref(cts_urn: str, fragment_dir: Path) -> dict[str, str]:
    """Return a mapping of chapter ref -> first Kühn page n in that chapter.

    Page n values are stored verbatim from the <pb n="..."> attribute
    (e.g. "18b.926") so that multi-volume texts can be disambiguated in JS.
    """
    found = _chunk_dir_and_metadata(cts_urn, fragment_dir)
    if found is None:
        return {}
    chunk_dir, metadata = found

    ref_to_first_page: dict[str, str] = {}
    for entry in _collect_leaf_entries(metadata.get("table_of_contents", [])):
        chunk_path = chunk_dir / entry["path"]
        if not chunk_path.exists():
            continue

        chunk_root = etree.parse(str(chunk_path)).getroot()
        elements_el = chunk_root.find("elements")
        if elements_el is None:
            continue

        pb = next(
            (el for el in elements_el.iter() if etree.QName(el).localname == "pb"),
            None,
        )
        if pb is None or not pb.get("n"):
            continue

        ref = entry["urn"].rsplit(":", 1)[1]
        ref_to_first_page[ref] = str(pb.get("n"))

    return ref_to_first_page


def _build_editions_data(zotero_data: list[dict]) -> tuple[list[dict], list[str]]:
    editions = []
    for opus in zotero_data:
        addable_tags = [
            t for t in opus.get("tags", []) if t.startswith("_") and t != "_opus"
        ]
        author = opus.get("author")
        authors = author.get("lastName", "Galenus") if author else "Galenus"
        for ed in opus.get("verbatimEditions", []):
            edition_cts_urn = _extract_cts_urn(ed.get("extra", ""))
            if not edition_cts_urn:
                continue
            creators = ed.get("creators", [])
            editors = "; ".join(
                f"{c.get('lastName', '')}, {c.get('firstName', '')}".strip(", ")
                for c in creators
                if c.get("creatorType") == "editor"
            )
            editions.append(
                {
                    "cts": edition_cts_urn,
                    "kuehnEditionVolume": opus.get("kuehnEditionVolume"),
                    "kuehnEditionPages": opus.get("kuehnEditionPages"),
                    "callNumber": opus.get("callNumber"),
                    "editors": editors,
                    "greek_title": opus.get("greekTitle"),
                    "latin_title": opus.get("latinTitle"),
                    "french_title": opus.get("frenchTitle"),
                    "english_title": opus.get("englishTitle"),
                    "tags": addable_tags,
                    "authors": authors,
                    "title": ed.get("title"),
                }
            )
    all_tags = [
        "gen",
        "anat",
        "physiol",
        "nosol",
        "therap",
        "pharm",
        "hipp",
        "phil",
    ]
    return editions, all_tags


def write_editions_data(zotero_data: list[dict]) -> None:
    editions, all_tags = _build_editions_data(zotero_data)
    path = APP_DIR / "static" / "json" / "editions.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"editions": editions, "all_tags": all_tags}, f, ensure_ascii=False)


def write_cts_index(zotero_data: list[dict], fragment_dir: Path) -> None:
    print("\n\nBuilding rapid access\n\n")
    result = []

    for opus in zotero_data:
        for ed in opus.get("verbatimEditions", []):
            creators = ed.get("creators", [])
            if not any(c.get("lastName") == "Kühn" for c in creators):
                continue

            extra = ed.get("extra", "") or ""
            cts_urn = None
            for line in extra.split("\n"):
                if line.startswith("CTS URN: "):
                    cts_urn = line.split("CTS URN: ", 1)[1].strip()
                    break

            if not cts_urn:
                continue

            refs = _refs_from_metadata(cts_urn, fragment_dir)
            if not refs:
                continue

            first_pages_map = _get_first_pages_per_ref(cts_urn, fragment_dir)
            first_pages = [first_pages_map.get(str(ref), "") for ref in refs]

            result.append(
                {
                    "t": ed.get("title") or "",
                    "v": ed.get("volume") or "",
                    "b": cts_urn,
                    "refs": refs,
                    "first_pages": first_pages,
                }
            )

    with open(CTS_INDEX, "w") as f:
        json.dump(result, f)


def setup():
    config = default_config

    config["static_folder"] = (APP_DIR / "static").absolute()  # ty:ignore[invalid-assignment]
    config["template_folder"] = (APP_DIR / "templates").absolute()  # ty:ignore[invalid-assignment]

    app = create_app(
        fragment_dir=FRAGMENT_DIR,
        config=config,
    )

    fetch_opera()

    zotero_data = read_zotero_json()

    app.jinja_env.globals["BASE_URL"] = os.getenv("FREEZER_BASE_URL", "")

    write_cts_index(zotero_data, FRAGMENT_DIR)
    write_editions_data(zotero_data)

    @app.route("/")
    def index():
        for item in zotero_data:
            for edition in item.get("criticalEditions", []):
                edition["_formatted"] = _format_critical_edition(edition)
            for translation in item.get("modernTranslations", []):
                translation["_formatted"] = _format_modern_translation(translation)
            for edition in item.get("verbatimEditions", []):
                cts_urn = _extract_cts_urn(edition.get("extra", ""))
                edition["_route"] = url_for("reading", urn=cts_urn) if cts_urn else "#"

        items = sorted(
            [i for i in zotero_data if i.get("callNumber")],
            key=lambda i: _int_or_zero(i["callNumber"]),
        )

        sorted_lists: dict[str, list] = {}
        sorted_lists_light: dict[str, list] = {}
        for key, info in SORT_ORDERS.items():
            sorted_lists[key] = info["sort_fn"](zotero_data)
            sorted_lists_light[key] = [
                {
                    "u": item.get("ctsURN"),
                    "c": item.get("callNumber"),
                    "lt": item.get("latinTitle"),
                    "t": item.get("title"),
                    "kv": item.get("kuehnEditionVolume"),
                    "kp": item.get("kuehnEditionPages"),
                    "la": item.get("latinAbbreviatedTitle"),
                    "gt": item.get("greekTitle"),
                    "ft": item.get("frenchTitle"),
                    "et": item.get("englishTitle"),
                    "es": item.get("englishShortTitle"),
                }
                for item in sorted_lists[key]
            ]

        return (
            render_template(
                "index.html.jinja",
                items=items,
                sorted_lists=sorted_lists,
                sorted_lists_light=sorted_lists_light,
                sort_orders=SORT_ORDERS,
                default_sort="kuehn",
            ),
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @app.route("/credits/")
    def credits():
        return (
            render_template("credits.html.jinja"),
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @app.route("/faq/")
    def faq():
        with open(FAQ_MARKDOWN) as f:
            markdown_content = markdown.markdown(f.read())

        return (
            render_template("faq.html.jinja", markdown_content=markdown_content),
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @app.route("/novitates/")
    def novitates():
        with open(UPDATES_MARKDOWN) as f:
            markdown_content = markdown.markdown(f.read())

        return (
            render_template("novitates.html.jinja", markdown_content=markdown_content),
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @app.route("/recherche/")
    def search():
        return (
            render_template("recherche.html.jinja"),
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @app.route("/<path:urn>/")
    def reading(urn):
        """Text reader page for a given CTS URN."""

        passage = _load_passage(urn, FRAGMENT_DIR)

        text_containers = passage.get("text_containers", [])

        if text_containers is None or len(text_containers) == 0:
            abort(404)

        if text_containers[0]["urn"] != urn:
            urn = text_containers[0]["urn"]

        previous_urn = passage["previous"]
        next_urn = passage["next"]

        toc = load_toc_from_urn(urn, FRAGMENT_DIR)  # ty: ignore
        zotero_data = read_zotero_json()
        zotero_item = None

        for item in zotero_data:
            item_urn = item.get("ctsURN")

            if item_urn is not None and urn.startswith(item_urn):
                zotero_item = item
                break

        if zotero_item is None:
            print(f"No zotero item found for {urn}")
            abort(404)

        for edition in zotero_item.get("criticalEditions", []):
            edition["_formatted"] = _format_critical_edition(edition)
        for translation in zotero_item.get("modernTranslations", []):
            translation["_formatted"] = _format_modern_translation(translation)
        for edition in zotero_item.get("verbatimEditions", []):
            verbatim_edition_urn = _extract_cts_urn(edition.get("extra", ""))
            edition["_route"] = (
                url_for("reading", urn=verbatim_edition_urn)
                if verbatim_edition_urn
                else "#"
            )

        kuehn_volume = zotero_item.get("kuehnEditionVolume")

        imgkuhn = None
        if kuehn_volume is not None:
            imgkuhn = get_iiif_config(IMAGES_DATA, str(urn), kuehn_volume)

        work_urn = str(urn).rsplit(":", 1)[0]
        urn_image_map = IMAGES_DATA.get(work_urn, {})

        imgbale = None
        bale_vol = urn_image_map.get("bale")
        if bale_vol:
            imgbale = get_iiif_config(
                IMAGES_DATA, str(urn), bale_vol, edition="bale", abbr="B"
            )

        imgchartier = None
        chartier_vol = urn_image_map.get("chartier")
        if chartier_vol:
            imgchartier = get_iiif_config(
                IMAGES_DATA, str(urn), chartier_vol, edition="chartier", abbr="Ch"
            )

        image_parts = []
        if imgkuhn is not None:
            image_parts.append(f"var imgkuhn = {json.dumps(imgkuhn)};")
        if imgbale is not None:
            image_parts.append(f"var imgbale = {json.dumps(imgbale)};")
        if imgchartier is not None:
            image_parts.append(f"var imgchartier = {json.dumps(imgchartier)};")
        image_vars = "\n".join(image_parts) if image_parts else None

        _assign_line_ids(text_containers)
        current_page_n, last_page_n = _find_page_ns(text_containers)

        if current_page_n == last_page_n:
            page_citation = f"p. {str(current_page_n).split('.')[-1]}"
        else:
            page_citation = f"pp. {str(current_page_n).split('.')[-1]}–{str(last_page_n).split('.')[-1]}"

        critical_edition = None
        for edition in zotero_item.get("verbatimEditions", []):
            verbatim_edition_urn = _extract_cts_urn(edition.get("extra", ""))

            if str(urn).startswith(str(verbatim_edition_urn)):
                critical_edition = edition
                break

        return (
            render_template(
                "reading.html.jinja",
                critical_edition=critical_edition,
                current_urn=urn,
                edition_title=toc.get("document", {}).get("title", ""),
                image_vars=image_vars,
                next_urn=next_urn,
                page_citation=page_citation,
                previous_urn=previous_urn,
                text_containers=text_containers,
                toc=toc,
                zotero_item=zotero_item,
            ),
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    return app


def main():
    """Run the development server."""

    app = setup()

    app.run(debug=True)

    return app
