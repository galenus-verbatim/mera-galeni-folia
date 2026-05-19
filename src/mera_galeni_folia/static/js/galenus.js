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

(function initIiifViewer() {
    const osdContainer = document.getElementById("osd-viewer");
    if (!osdContainer) return;

    const configs = {};
    if (typeof imgkuhn !== "undefined" && imgkuhn.count > 0) configs.kuhn = imgkuhn;
    if (typeof imgbale !== "undefined") configs.bale = imgbale;
    if (typeof imgchartier !== "undefined") configs.chartier = imgchartier;

    const editionNames = Object.keys(configs);
    if (editionNames.length === 0) return;

    const OSD_PREFIX_URL =
        "https://cdn.jsdelivr.net/npm/openseadragon@6.0.2/build/openseadragon/images/";

    let osdViewer = null;
    let activeEdition = null;
    // imageNo is always the 1-based physical image number (= p + pdiff per the README).
    // For OSD sequence mode we pass imageNo - 1 as the 0-based page index.
    let currentImageNo = 1;

    const spinnerEl = document.getElementById("iiif-loading");
    function showSpinner() { spinnerEl?.classList.remove("hidden"); }
    function hideSpinner() { spinnerEl?.classList.add("hidden"); }

    function scheduleHide(viewer) {
        function poll() {
            if (viewer !== osdViewer) return;
            const item = viewer.world.getItemAt(0);
            if (item && item.getFullyLoaded()) { hideSpinner(); return; }
            requestAnimationFrame(poll);
        }
        requestAnimationFrame(poll);
    }

    // Apply pholes: if the volume has variable pdiff breakpoints, return the
    // correct pdiff for this edition page number.
    function effectivePdiff(config, pageNum) {
        let pdiff = config.pdiff;
        for (const [threshold, newPdiff] of Object.entries(config.pholes || {})) {
            if (pageNum >= parseInt(threshold, 10)) {
                pdiff = newPdiff;
            }
        }
        return pdiff;
    }

    // imageNo → zero-padded 4-digit string used in IIIF URLs.
    function padded(imageNo) {
        return String(imageNo).padStart(4, "0");
    }

    function buildTitleHtml(config, imageNo) {
        const p = padded(imageNo);
        let html = config.title.replace(/%%/g, p);
        if (config.record) {
            html += ` — <a target="_blank" class="external" href="${config.record.replace(/%%/g, p)}">Numerabilis</a>`;
        }
        return html;
    }

    function updateTitle() {
        const titleEl = document.getElementById("image_title");
        if (titleEl && activeEdition) {
            titleEl.innerHTML = buildTitleHtml(configs[activeEdition], currentImageNo);
        }
    }

    // Open a single image in the viewer (used for editions without a known count).
    function openImage(config, imageNo) {
        showSpinner();
        osdViewer.open({
            type: "image",
            url: config.url.replace(/%%/g, padded(imageNo)),
            buildPyramid: false,
            crossOriginPolicy: "Anonymous",
        });
        scheduleHide(osdViewer);
    }

    function switchEdition(edition, imageNo) {
        showSpinner();
        if (osdViewer) {
            osdViewer.destroy();
            osdViewer = null;
        }
        activeEdition = edition;
        currentImageNo = imageNo;
        const config = configs[edition];

        const baseOptions = {
            id: "osd-viewer",
            prefixUrl: OSD_PREFIX_URL,
            defaultZoomLevel: 0.9,
            preserveViewport: true,
        };

        if (config.count > 0) {
            // Sequence mode: tileSource[i] → image i+1.
            const tileSources = Array.from({ length: config.count }, (_, i) => ({
                type: "image",
                url: config.url.replace(/%%/g, padded(i + 1)),
                buildPyramid: false,
                crossOriginPolicy: "Anonymous",
            }));
            osdViewer = OpenSeadragon({
                ...baseOptions,
                tileSources,
                sequenceMode: true,
                initialPage: imageNo - 1,   // OSD is 0-based
            });
        } else {
            osdViewer = OpenSeadragon({
                ...baseOptions,
                tileSources: [{
                    type: "image",
                    url: config.url.replace(/%%/g, padded(imageNo)),
                    buildPyramid: false,
                    crossOriginPolicy: "Anonymous",
                }],
                sequenceMode: false,
            });
        }

        scheduleHide(osdViewer);

        updateTitle();
    }

    function navigateToPage(edition, n) {
        const config = configs[edition];
        if (!config) return;
        const pageNum = parseInt(String(n).split(".").pop(), 10);
        if (isNaN(pageNum)) return;
        // imageNo = p + pdiff  (README formula, 1-based)
        const imageNo = pageNum + effectivePdiff(config, pageNum);

        if (activeEdition === edition && osdViewer) {
            currentImageNo = imageNo;
            if (config.count > 0) {
                showSpinner();
                osdViewer.goToPage(imageNo - 1);   // OSD is 0-based
                scheduleHide(osdViewer);
            } else {
                openImage(config, imageNo);
            }
            updateTitle();
        } else {
            switchEdition(edition, imageNo);
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        // Determine initial image number for the default edition (Kühn).
        const defaultEdition = editionNames[0];
        const defaultConfig = configs[defaultEdition];
        let initialImageNo = 1;
        if (defaultEdition === "kuhn") {
            const firstPb = document.querySelector(".tei-pb");
            if (firstPb) {
                const pageNum = parseInt(String(firstPb.dataset.n).split(".").pop(), 10);
                if (!isNaN(pageNum)) {
                    initialImageNo = pageNum + effectivePdiff(defaultConfig, pageNum);
                }
            }
        }
        switchEdition(defaultEdition, initialImageNo);

        // Kühn page-break click handlers.
        document.querySelectorAll(".tei-pb").forEach((span) => {
            span.style.cursor = "pointer";
            span.addEventListener("click", () => navigateToPage("kuhn", span.dataset.n));
        });

        // Milestone click handlers (ed1page = Bâle, ed2page = Chartier).
        document.querySelectorAll(".tei-milestone").forEach((span) => {
            const unit = span.dataset.unit;
            if (unit === "ed1page" && configs.bale) {
                span.addEventListener("click", () => navigateToPage("bale", span.dataset.n));
            } else if (unit === "ed2page" && configs.chartier) {
                span.addEventListener("click", () => navigateToPage("chartier", span.dataset.n));
            }
        });

        // Prev/next navigation.
        const prevBtn = document.getElementById("image_prev");
        const nextBtn = document.getElementById("image_next");

        if (prevBtn) {
            prevBtn.style.cursor = "pointer";
            prevBtn.addEventListener("click", () => {
                const config = configs[activeEdition];
                const newImageNo = Math.max(1, currentImageNo - 1);
                currentImageNo = newImageNo;
                if (config.count > 0) {
                    showSpinner();
                    osdViewer.goToPage(newImageNo - 1);
                    scheduleHide(osdViewer);
                } else {
                    openImage(config, newImageNo);
                }
                updateTitle();
            });
        }

        if (nextBtn) {
            nextBtn.style.cursor = "pointer";
            nextBtn.addEventListener("click", () => {
                const config = configs[activeEdition];
                const maxImageNo = config.count > 0 ? config.count : Infinity;
                const newImageNo = Math.min(maxImageNo, currentImageNo + 1);
                currentImageNo = newImageNo;
                if (config.count > 0) {
                    showSpinner();
                    osdViewer.goToPage(newImageNo - 1);
                    scheduleHide(osdViewer);
                } else {
                    openImage(config, newImageNo);
                }
                updateTitle();
            });
        }
    });
})();
