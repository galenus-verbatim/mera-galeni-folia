async function initCtsSearch() {
    const input = document.getElementById("cts");
    const datalist = document.getElementById("cts-list");
    if (!input || !datalist) return;

    let urlMap;
    try {
        const ctsIndexUrl = document.getElementById('cts-index').dataset['cts-index'];
        const resp = await fetch(ctsIndexUrl);
        const editions = await resp.json();

        urlMap = new Map();
        const fragment = document.createDocumentFragment();

        for (const ed of editions) {
            for (const ref of ed.refs) {
                const url = `/${ed.b}:${ref}/`;

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
        }

        datalist.appendChild(fragment);
    } catch (e) {
        console.warn("CTS index fetch failed", e);
        return;
    }

    function navigate() {
        const url = urlMap.get(input.value.trim());
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

let osdViewer;
let currentPage = { pno: null, dat: null, spanLast: null };
const osdContainer = document.getElementById("osd-viewer");

if (osdContainer) {
    osdViewer = OpenSeadragon({
        id: "osd-viewer",
        prefixUrl:
            "https://cdn.jsdelivr.net/npm/openseadragon@5.0/build/openseadragon/images/",
        showNavigationControl: false,
        animationTime: 0.3,
        springStiffness: 10,
        gestureSettingsMouse: { scrollToZoom: true },
    });
}
