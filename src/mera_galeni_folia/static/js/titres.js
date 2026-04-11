function filterEditions() {
  const gommettes = Array.from(
    document.querySelectorAll(".gommette:checked"),
  ).map((cb) => cb.value);

  const tbody = document.querySelector("#editions-table tbody");

  if (!tbody) return;

  tbody.querySelectorAll("tr").forEach((row) => {
    if (gommettes.length === 0) {
      row.hidden = false;
    } else {
      const rowTags = row.dataset.tags.split(" ");

      for (let g of gommettes) {
        if (rowTags.indexOf(g.toLowerCase()) > -1) {
          row.hidden = false;
        } else {
          row.hidden = true;
        }
      }
    }
  });

  const shouldDeduplicate =
    document.getElementById("ignorer-doublons")?.checked ?? false;
  if (shouldDeduplicate) {
    const seen = new Set();
    tbody.querySelectorAll("tr:not([hidden])").forEach((row) => {
      const workUrn = row.dataset.cts.replace(/\.[^.]+$/, "");
      if (seen.has(workUrn)) {
        row.hidden = true;
      } else {
        seen.add(workUrn);
      }
    });
  }
}

document.querySelectorAll(".gommette").forEach((el) => {
  el.addEventListener("change", filterEditions);
});

document.getElementById("tout-cocher").addEventListener("click", () => {
  const gommettes = document.querySelectorAll(".gommette:checked");

  if (gommettes.length === 0) {
    document.querySelectorAll(".gommette").forEach((g) => (g.checked = true));
  } else {
    gommettes.forEach((g) => (g.checked = false));
  }

  filterEditions();
});

document.getElementById("ignorer-doublons").addEventListener("change", () => {
  filterEditions(true);
});

document.querySelectorAll('input[name="author"]').forEach((el) => {
  el.addEventListener("change", (evt) => {
    const author = evt.target.value;
    const rows = document.getElementsByClassName("edition-row");

    if (author === "Toutes") {
      for (el of rows) {
        el.classList.remove("hidden");
      }

      return;
    }

    for (el of rows) {
      if (author === el.dataset.authors) {
        el.classList.remove("hidden");
      } else {
        el.classList.add("hidden");
      }
    }
  });
});
