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
