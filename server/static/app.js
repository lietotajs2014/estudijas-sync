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
