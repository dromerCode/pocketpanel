// Hoja lateral/inferior genérica (#usheet): fichas y formularios
const $ = (id) => document.getElementById(id);

export function openSheet(title, sub, ...body) {
  $("us-title").textContent = title;
  $("us-sub").textContent = sub || "";
  $("us-body").replaceChildren(...body);
  $("usheet").hidden = false;
}

export function closeSheet() {
  $("usheet").hidden = true;
}

let wired = false;
export function initSheet() {
  if (wired) return;
  wired = true;
  $("us-close").onclick = closeSheet;
  $("usheet").addEventListener("click", (e) => { if (e.target.id === "usheet") closeSheet(); });
}
