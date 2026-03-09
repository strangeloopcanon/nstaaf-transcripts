function initPagefindSearch() {
  if (!window.PagefindUI) {
    window.setTimeout(initPagefindSearch, 100);
    return;
  }

  document.querySelectorAll("[data-pagefind-search]").forEach((element) => {
    if (element.dataset.pagefindReady === "true") {
      return;
    }

    element.dataset.pagefindReady = "true";
    new window.PagefindUI({
      element,
      excerptLength: 24,
      resetStyles: false,
      showImages: false,
      showSubResults: true,
      translations: {
        placeholder: "Search transcripts by keyword, phrase, person, place, or topic",
        zero_results: "No transcript matches that search yet.",
      },
    });
  });
}

document.addEventListener("DOMContentLoaded", initPagefindSearch);
