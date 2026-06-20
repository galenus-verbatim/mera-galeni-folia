async function initCtsSearch() {
    const input = document.getElementById("cts");
    const datalist = document.getElementById("cts-list");
    if (!input || !datalist) return;

    let urlMap;
    let editionsWithPages = [];

    try {
        const BASE_URL =
            document.getElementById("base-url").dataset["baseUrl"];
        const ctsIndexUrl = document.getElementById('cts-index').dataset['ctsIndex'];
        const resp = await fetch(ctsIndexUrl);
        const editions = await resp.json();

        urlMap = new Map();
        const fragment = document.createDocumentFragment();

        for (const ed of editions) {
            for (const ref of ed.refs) {
                const url = `${BASE_URL ? BASE_URL : "/"}${ed.b}:${ref}/`;

                const kuehnKey = `${ed.v}.${ref}`;
                urlMap.set(kuehnKey, url);
                const kuehnOpt = document.createElement("option");
                kuehnOpt.value = kuehnKey;
                kuehnOpt.label = ed.t;
                fragment.appendChild(kuehnOpt);

                const urnKey = `${ed.b}:${ref}`;
                urlMap.set(urnKey, url);
                const urnOpt = document.createElement("option");
                urnOpt.value = urnKey;
                urnOpt.label = ed.t;
                fragment.appendChild(urnOpt);
            }

            if (ed.first_pages && ed.first_pages.some(p => p)) {
                editionsWithPages.push({ ed, BASE_URL });
            }
        }

        datalist.appendChild(fragment);
    } catch (e) {
        console.warn("CTS index fetch failed", e);
        return;
    }

    // Compare two Kühn page-n values like "18b.926" or "17a.100".
    // Volume part compared as string; page part compared numerically.
    function comparePageN(a, b) {
        const dotA = a.lastIndexOf('.');
        const dotB = b.lastIndexOf('.');
        const volA = a.slice(0, dotA);
        const volB = b.slice(0, dotB);
        if (volA !== volB) return volA < volB ? -1 : 1;
        return parseInt(a.slice(dotA + 1)) - parseInt(b.slice(dotB + 1));
    }

    // Resolve a page-based query like "18b.926" to a chapter URL.
    // Multiple works can share the same volume, so we check all matching
    // editions and pick the one whose closest first_page is the largest
    // (i.e. the work that actually contains the requested page).
    function resolveByPage(query) {
        const lastDot = query.lastIndexOf('.');
        if (lastDot < 0) return null;
        const queryVol = query.slice(0, lastDot);
        if (!queryVol) return null;

        const matching = editionsWithPages.filter(({ ed }) =>
            ed.v.split('-').map(v => v.trim()).some(v => v === queryVol)
        );
        if (matching.length === 0) return null;

        let bestURL = null;
        let bestFP = null;

        for (const { ed, BASE_URL } of matching) {
            // Find the largest first_page <= query within this edition.
            let bestIdx = -1;
            for (let i = 0; i < ed.first_pages.length; i++) {
                const fp = ed.first_pages[i];
                if (!fp) continue;
                if (comparePageN(fp, query) <= 0) {
                    bestIdx = i;
                } else {
                    break;
                }
            }
            if (bestIdx < 0) continue;

            const fp = ed.first_pages[bestIdx];
            if (bestFP === null || comparePageN(fp, bestFP) > 0) {
                bestFP = fp;
                const ref = ed.refs[bestIdx];
                bestURL = `${BASE_URL ? BASE_URL : '/'}${ed.b}:${ref}/`;
            }
        }

        return bestURL;
    }

    // Resolve a page+line query like "18b.926.5" to a chapter URL with a
    // line anchor. Falls back to null for anything that isn't
    // "{vol}.{page}.{line}" with numeric page and line.
    function resolveByLine(query) {
        const parts = query.split('.');
        if (parts.length !== 3) return null;
        const [vol, page, line] = parts;
        if (!/^\d+$/.test(page) || !/^\d+$/.test(line)) return null;

        const pageQuery = `${vol}.${page}`;
        const url = resolveByPage(pageQuery);
        if (!url) return null;

        return `${url}#l${pageQuery}.${line}`;
    }

    function navigate() {
        const val = input.value.trim();
        const url = urlMap.get(val) || resolveByLine(val) || resolveByPage(val);
        if (url) location.href = url;
    }

    input.addEventListener("change", navigate);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            navigate();
        }
    });
}

document.addEventListener("DOMContentLoaded", initCtsSearch);
