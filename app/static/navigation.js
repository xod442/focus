(() => {
  const nav = document.getElementById("primary-nav");
  const toggle = document.querySelector(".nav-toggle");
  if (!nav || !toggle) return;

  const dropdowns = [...nav.querySelectorAll(".nav-dropdown")];
  const closeDropdowns = () => dropdowns.forEach((dropdown) => {
    dropdown.open = false;
  });

  toggle.hidden = false;
  toggle.addEventListener("click", () => {
    const expanded = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", String(!expanded));
    if (expanded) closeDropdowns();
  });

  dropdowns.forEach((dropdown) => {
    dropdown.querySelector("summary").addEventListener("click", () => {
      dropdowns.forEach((other) => {
        if (other !== dropdown) other.open = false;
      });
    });
  });

  document.addEventListener("click", (event) => {
    if (!nav.contains(event.target)) closeDropdowns();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const opened = dropdowns.find((dropdown) => dropdown.open);
    if (opened) {
      opened.open = false;
      opened.querySelector("summary").focus();
    } else if (toggle.getAttribute("aria-expanded") === "true") {
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }
  });
})();
