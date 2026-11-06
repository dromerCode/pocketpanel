// Las cuentas y los textos que tienen que coincidir con el servidor (store.py, xlsx.py) y con la plantilla.

// «12,50», «12.5» → 12.5; «1.234» son miles, como se escribe aquí
export const num = (v) => {
  v = String(v ?? "").trim().replace(/€|\s/g, "");
  if (v.includes(",")) v = v.replace(/\./g, "").replace(",", ".");
  else if (/^-?[1-9]\d{0,2}(\.\d{3})+$/.test(v)) v = v.replace(/\./g, "");
  return Number(v);
};

// Los medios, hacia arriba (lejos del cero), quitando antes el ruido de los decimales en binario
const whole = (x) => Math.sign(x) * Math.round(Number(Math.abs(x).toFixed(6)));

export const round2 = (x) => whole(x * 100) / 100;
export const pct = (base, rate) => whole(base * rate) / 100;
export const totalOf = (base, iva, irpf) => round2(base + pct(base, iva) - pct(base, irpf));

// «noviembre de 2026»
export const monthText = (iso) => {
  const d = new Date(`${iso}T12:00:00`);
  return `${d.toLocaleDateString("es-ES", { month: "long" })} de ${d.getFullYear()}`;
};

// El número que recupera una factura automática que se quitó al borrar un cobro. De otro año, no: la numeración de este
// año no iría en orden (lo mismo que hace auto_invoice en store.py)
export const heldNumber = (annulled, id, today) => annulled.find((a) => a.reusable && a.charge === id
  && a.number.startsWith(`${today.slice(0, 4)}-`))?.number;
