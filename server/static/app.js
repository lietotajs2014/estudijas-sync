// Vienīgais JS: "Kopēt" pogas (CSP aizliedz inline skriptus).
document.addEventListener("click", (e) => {
  const id = e.target?.dataset?.copy;
  if (!id) return;
  const input = document.getElementById(id);
  input.select();
  navigator.clipboard?.writeText(input.value).then(() => {
    const old = e.target.textContent;
    e.target.textContent = "Nokopēts ✓";
    setTimeout(() => (e.target.textContent = old), 1500);
  });
});

// Savienošanas koda lapa: kamēr kods ir ekrānā, ik pa 3 s pārbauda, vai lietotne jau pieslēdzās.
(function () {
  const box = document.getElementById("pair");
  if (!box) return;
  const wait = document.getElementById("pair-wait");
  let tries = 0;
  const tick = async () => {
    tries++;
    try {
      const r = await fetch(box.dataset.statusUrl, { credentials: "same-origin" });
      const j = await r.json();
      if (j.linked) {
        wait.textContent = "Savienots ✓";
        location.href = "/confirm";
        return;
      }
    } catch (e) { /* tīkla kļūme — mēģinām vēlreiz */ }
    if (tries < 200) setTimeout(tick, 3000);
    else wait.textContent = "Kods beidzies — atjauno lapu un izveido jaunu.";
  };
  setTimeout(tick, 3000);
})();
