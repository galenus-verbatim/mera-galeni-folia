import json
import os
import re

from pathlib import Path
from typing import Any

import markdown

from flask import abort, render_template, url_for

from kodon_py.config import default_config
from kodon_py.server import create_app, load_passage_from_urn, load_toc_from_urn

from mera_galeni_folia.build import (
    _format_critical_edition,
    _format_modern_translation,
    _int_or_zero,
)
from mera_galeni_folia.reading import (
    get_iiif_config,
    load_editions,
    load_images_config,
)
from mera_galeni_folia.zotero import SORT_ORDERS, fetch_opera, read_zotero_json

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JSON_DIR = (ROOT_DIR / "tei_json").absolute()

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
                f"p{current_page_n}l{text_container.get('n', '0')}"
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


def write_cts_index(editions):
    kuehn_editions = [
        e for e in editions if (e.get("editors") or "").startswith("Kühn")
    ]

    result = []
    for ed in kuehn_editions:
        nav = ed.get("nav") or ""
        vol = ed.get("volume") or ""
        title = ed.get("title") or ""
        base_urn = ed.get("cts") or ""

        hrefs = re.findall(r'href="\./(urn:[^"]+)"', nav)
        refs = [urn.rsplit(":", 1)[1] for urn in hrefs if ":" in urn]

        if refs:
            result.append(
                {
                    "t": title,
                    "v": vol,
                    "b": base_urn,
                    "refs": refs,
                }
            )

    with open(CTS_INDEX, "w") as f:
        json.dump(result, f)


def setup():
    config = default_config

    config["static_folder"] = (APP_DIR / "static").absolute()  # ty:ignore[invalid-assignment]
    config["template_folder"] = (APP_DIR / "templates").absolute()  # ty:ignore[invalid-assignment]

    app = create_app(
        json_dir=JSON_DIR,
        config=config,
    )

    fetch_opera()

    editions = load_editions()
    zotero_data = read_zotero_json()

    app.jinja_env.globals["BASE_URL"] = os.getenv("FREEZER_BASE_URL", "")

    write_cts_index(editions)

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
        for key, info in SORT_ORDERS.items():
            sorted_lists[key] = info["sort_fn"](zotero_data)

        return (
            render_template(
                "index.html.jinja",
                items=items,
                sorted_lists=sorted_lists,
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
        # Build lookup from work-level CTS URN to multi-language titles
        urn_to_titles: dict[str, dict] = {}
        urn_to_tags: dict[str, list] = {}
        urn_to_kuehn: dict[str, dict] = {}
        urls: dict[str, str] = {}

        for opus in zotero_data:
            cts_urn = opus.get("ctsURN")
            if cts_urn:
                urn_to_titles[cts_urn] = {
                    "greek_title": opus.get("greekTitle"),
                    "latin_title": opus.get("latinTitle"),
                    "french_title": opus.get("frenchTitle"),
                    "english_title": opus.get("englishTitle"),
                }

                addable_tags = [
                    t for t in opus["tags"] if t.startswith("_") and t != "_opus"
                ]
                if urn_to_tags.get(cts_urn) is not None:
                    print(f"Already saw cts URN {cts_urn}")
                    urn_to_tags[cts_urn] += addable_tags
                else:
                    urn_to_tags[cts_urn] = addable_tags

                urn_to_kuehn[cts_urn] = {
                    "kuehnEditionVolume": opus.get("kuehnEditionVolume"),
                    "kuehnEditionPages": opus.get("kuehnEditionPages"),
                    "callNumber": opus.get("callNumber"),
                }

                urls[cts_urn] = opus.get("url")  # ty:ignore[invalid-assignment]

        # Enrich editions with multi-language titles and Kuehn/Fichtner info
        for edition in editions:
            edition_urn = edition.get("cts", "")
            titles = next(
                (t for urn, t in urn_to_titles.items() if edition_urn.startswith(urn)),
                None,
            )
            if titles:
                edition.update(titles)
            else:
                edition.setdefault("greek_title", None)
                edition.setdefault("latin_title", edition.get("title"))
                edition.setdefault("french_title", None)
                edition.setdefault("english_title", None)

            edition_tags = next(
                (
                    tags
                    for urn, tags in urn_to_tags.items()
                    if edition_urn.startswith(urn)
                ),
                None,
            )

            if edition_tags:
                edition["tags"] = edition_tags

            kuehn_info = next(
                (
                    info
                    for urn, info in urn_to_kuehn.items()
                    if edition_urn.startswith(urn)
                ),
                None,
            )
            if kuehn_info:
                edition.update(kuehn_info)
            else:
                edition.setdefault("kuehnEditionVolume", None)
                edition.setdefault("kuehnEditionPages", None)
                edition.setdefault("callNumber", None)

            url = next(url for urn, url in urls.items() if edition_urn.startswith(urn))

            if url:
                edition["url"] = url

        # the order of `all_tags` is important for sorting
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

        return (
            render_template(
                "recherche.html.jinja",
                editions=editions,
                all_tags=all_tags,
                BASE_URL=os.getenv("FREEZER_BASE_URL", "//127.0.0.1:5000/"),
            ),
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @app.route("/<path:urn>/")
    def reading(urn):
        """Text reader page for a given CTS URN."""

        passage = load_passage_from_urn(urn, JSON_DIR)

        text_containers = passage.get("text_containers", [])

        if text_containers is None or len(text_containers) == 0:
            abort(404)

        if text_containers[0]["urn"] != urn:
            urn = text_containers[0]["urn"]

        previous_urn = passage["previous"]
        next_urn = passage["next"]

        toc = load_toc_from_urn(urn, JSON_DIR)  # ty: ignore
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
                edition_title=toc.get("title", ""),
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
