import { el } from "./api.js";

const NS = "http://www.w3.org/2000/svg";
const SERIES = [
  { key: "cpu", title: "CPU", unit: "%", range: [0, 100] },
  { key: "mem", title: "RAM", unit: "%", range: [0, 100] },
  { key: "temp", title: "Temperatura", unit: "°", range: null },
];
const H = 100, PAD = { l: 30, r: 6, t: 6, b: 16 };

function svg(tag, attrs = {}) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

function fmtTime(t, range) {
  const d = new Date(t * 1000);
  if (range === "7d") return d.toLocaleDateString("es-ES", { weekday: "short" }) + " " + d.getHours() + "h";
  return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

function yDomain(vals, s) {
  if (s.range) return s.range;
  const lo = Math.min(...vals), hi = Math.max(...vals);
  return [Math.floor((lo - 3) / 5) * 5, Math.ceil((hi + 3) / 5) * 5];
}

function drawChart(box, points, s, range) {
  const vals = points.map((p) => p[s.key]).filter((v) => v != null);
  const head = el("div", { class: "chart-head" }, el("span", { class: "chart-title" }, s.title));
  box.replaceChildren(head);
  if (vals.length < 2) {
    box.append(el("div", { class: "chart-empty" }, "Recogiendo datos… (una muestra cada 30 s)"));
    return;
  }
  const last = [...points].reverse().find((p) => p[s.key] != null)[s.key];
  head.append(el("span", { class: "chart-now mono" },
    `ahora ${Math.round(last)}${s.unit} · máx ${Math.round(Math.max(...vals))}${s.unit}`));

  const W = box.clientWidth - 24;
  if (W < 80) return;  // pestaña oculta: ya se pintará al verse (ResizeObserver)
  const [y0, y1] = yDomain(vals, s);
  const t0 = points[0].t, t1 = points[points.length - 1].t;
  const x = (t) => PAD.l + ((t - t0) / Math.max(1, t1 - t0)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - y0) / Math.max(1, y1 - y0)) * (H - PAD.t - PAD.b);

  const g = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `${s.title}: ahora ${Math.round(last)}${s.unit}, máximo ${Math.round(Math.max(...vals))}${s.unit}` });
  g.style.height = `${H}px`;
  for (const v of [y0, (y0 + y1) / 2, y1]) {
    g.append(svg("line", { class: "grid", x1: PAD.l, x2: W - PAD.r, y1: y(v), y2: y(v) }));
    const lab = svg("text", { class: "axis", x: PAD.l - 6, y: y(v) + 3, "text-anchor": "end" });
    lab.textContent = Math.round(v);
    g.append(lab);
  }
  for (const [t, anchor] of [[t0, "start"], [t1, "end"]]) {
    const lab = svg("text", { class: "axis", x: anchor === "start" ? PAD.l : W - PAD.r, y: H - 3, "text-anchor": anchor });
    lab.textContent = fmtTime(t, range);
    g.append(lab);
  }

  // Tramos continuos: un hueco en los datos corta la línea
  const gapLimit = { "1h": 90, "24h": 1800, "7d": 10800 }[range];
  let seg = [];
  const segs = [];
  let prevT = null;
  for (const p of points) {
    const v = p[s.key];
    if (v == null || (prevT != null && p.t - prevT > gapLimit)) { if (seg.length) segs.push(seg); seg = []; }
    if (v != null) seg.push([x(p.t), y(v)]);
    prevT = p.t;
  }
  if (seg.length) segs.push(seg);
  for (const sg of segs) {
    const d = sg.map(([a, b], i) => `${i ? "L" : "M"}${a.toFixed(1)},${b.toFixed(1)}`).join("");
    if (sg.length > 1) {
      g.append(svg("path", { class: "area",
        d: `${d}L${sg[sg.length - 1][0].toFixed(1)},${y(y0)}L${sg[0][0].toFixed(1)},${y(y0)}Z` }));
    }
    g.append(svg("path", { class: "line", d }));
  }

  // Hover / toque: línea vertical + punto + valor
  const cross = svg("line", { class: "cross", y1: PAD.t, y2: H - PAD.b, visibility: "hidden" });
  const dot = svg("circle", { class: "dot", r: 4, visibility: "hidden" });
  g.append(cross, dot);
  const tip = el("div", { class: "chart-tip", hidden: true });
  const withVal = points.filter((p) => p[s.key] != null);
  const move = (e) => {
    const r = g.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = withVal[0];
    for (const p of withVal) if (Math.abs(x(p.t) - px) < Math.abs(x(best.t) - px)) best = p;
    const bx = x(best.t), by = y(best[s.key]);
    cross.setAttribute("x1", bx); cross.setAttribute("x2", bx); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", bx); dot.setAttribute("cy", by); dot.setAttribute("visibility", "visible");
    tip.textContent = `${fmtTime(best.t, range)} · ${Math.round(best[s.key])}${s.unit}`;
    tip.style.left = `${12 + (bx / W) * r.width}px`;
    tip.hidden = false;
  };
  const leave = () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true; };
  g.addEventListener("pointermove", move);
  g.addEventListener("pointerdown", move);
  g.addEventListener("pointerleave", leave);
  box.append(g, tip);
}

export function renderCharts(container, points, range) {
  if (container.children.length !== SERIES.length) {
    container.replaceChildren(...SERIES.map(() => el("div", { class: "chart" })));
  }
  SERIES.forEach((s, i) => drawChart(container.children[i], points, s, range));
}
