async function initCtsSearch() {
    const input = document.getElementById("cts");
    const datalist = document.getElementById("cts-list");
    if (!input || !datalist) return;

    let urlMap;
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

const osdContainer = document.getElementById("osd-viewer");

if (osdContainer && typeof imgkuhn !== "undefined" && imgkuhn.count > 0) {
    const tileSources = Array.from({ length: imgkuhn.count }, (_, i) => ({
        type: "image",
        url: imgkuhn.url.replace("%%", String(i + 1).padStart(4, "0")),
        buildPyramid: false,
        ajaxWithCredentials: false,
        crossOriginPolicy: "Anonymous",
    }));

    const firstPb = document.querySelector(".tei-pb");
    const firstEditionPage = firstPb
        ? parseInt(String(firstPb.dataset.n).split(".").pop(), 10)
        : 1;
    const initialPage = firstEditionPage + imgkuhn.pdiff - 2;

    const osdViewer = OpenSeadragon({
        id: "osd-viewer",
        prefixUrl:
            "https://cdn.jsdelivr.net/npm/openseadragon@6.0.2/build/openseadragon/images/",
        tileSources,
        sequenceMode: true,
        preserveViewport: true,
        initialPage,
        defaultZoomLevel: 1,
    });

    function goToEditionPage(editionPageStr) {
        const pageNum = parseInt(String(editionPageStr).split(".").pop(), 10);
        if (isNaN(pageNum)) return;
        const physIndex = pageNum + imgkuhn.pdiff - 1;
        osdViewer.goToPage(physIndex);
        const padded = String(physIndex + 1).padStart(4, "0");
        const titleEl = document.getElementById("image_title");
        if (titleEl) titleEl.innerHTML = imgkuhn.title.replace(/%%/g, padded);
    }

    function updateTitle() {
        const physIndex = osdViewer.currentPage();
        const padded = String(physIndex + 1).padStart(4, "0");
        const titleEl = document.getElementById("image_title");
        if (titleEl) titleEl.innerHTML = imgkuhn.title.replace(/%%/g, padded);
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll(".tei-pb").forEach((span) => {
            span.style.cursor = "pointer";
            span.addEventListener("click", () => goToEditionPage(span.dataset.n));
        });

        const prevBtn = document.getElementById("image_prev");
        const nextBtn = document.getElementById("image_next");
        if (prevBtn) {
            prevBtn.style.cursor = "pointer";
            prevBtn.addEventListener("click", () => {
                osdViewer.goToPage(Math.max(0, osdViewer.currentPage() - 1));
                updateTitle();
            });
        }
        if (nextBtn) {
            nextBtn.style.cursor = "pointer";
            nextBtn.addEventListener("click", () => {
                osdViewer.goToPage(
                    Math.min(imgkuhn.count - 1, osdViewer.currentPage() + 1)
                );
                updateTitle();
            });
        }

        updateTitle();
    });
}
