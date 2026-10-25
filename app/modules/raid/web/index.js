// RAID: estado del array y SMART de sus discos, en Estado.
import { api, el, fmtBytes } from "/js/api.js";
import { level } from "/js/status.js";

const $ = (id) => document.getElementById(id);

const RAID_STATUS = {
  ok: ["Limpio", "ok"], degraded: ["Degradado", "bad"], rebuilding: ["Reconstruyendo", "warn"], unknown: ["Sin datos", ""],
};

function renderRaid(r) {
  const [label, cls] = RAID_STATUS[r.status] || RAID_STATUS.unknown;
  const badge = $("raid-badge");
  badge.textContent = r.status === "rebuilding" && r.progress != null ? `${label} ${r.progress}%` : label;
  badge.className = `badge ${cls}`;
  const parts = [];
  if (r.problems?.length) parts.push(el("ul", { class: "raid-problems" }, r.problems.map((p) => el("li", {}, `⚠ ${p}`))));
  if (r.size) {
    parts.push(el("div", {},
      el("div", { class: "disk-row" },
        el("span", {}, `${(r.level || "").toUpperCase()} · ${r.devices.length} discos`),
        el("span", { class: "disk-num mono" }, `${fmtBytes(r.avail)} libres · ${r.pct}%`)),
      el("div", { class: `bar ${level(r.pct)}` }, el("i", { style: `width:${r.pct}%` }))));
  }
  parts.push(el("ul", { class: "raid-disks" }, r.devices.map((d) => {
    const bad = d.health === "FAILED" || d.state.includes("faulty");
    const meta = [d.state, d.temp != null ? `${d.temp}°` : null, d.hours != null ? `${Math.round(d.hours / 24)} días encendido` : null,
      (d.realloc || d.pending) ? `${d.realloc || 0} reasignados · ${d.pending || 0} pendientes` : null,
      d.crc ? `${d.crc} errores CRC (¿cable?)` : null].filter(Boolean).join(" · ");
    return el("li", { class: "raid-disk" },
      el("span", { class: "dev" }, d.dev.replace("/dev/", "")),
      el("span", { class: "model" }, d.model || "?"),
      el("span", { class: `health ${bad ? "bad" : d.health ? "ok" : ""}` }, d.health ? (bad ? "✗ SMART" : "✓ SMART") : "–"),
      el("span", { class: "meta" }, meta));
  })));
  if (r.status === "unknown") parts.push(el("span", { class: "muted small" }, "No se pudo leer el RAID"));
  $("raid").replaceChildren(...parts);
}

async function loadRaid() {
  try {
    renderRaid(await api("/api/raid"));
  } catch (e) {
    $("raid-badge").textContent = "Sin datos";
    $("raid-badge").className = "badge";
    $("raid").replaceChildren(el("span", { class: "muted small" }, `No se pudo leer el RAID: ${e.message}`));
  }
}

export default {
  styles: ["style.css"],
  cards: [{ slot: "left", html: "card.html", order: 2, slow: loadRaid }],
};
