// The house picker: the current house as a small drawing in the header; click it for every house as a card
// (its drawing, size, kind, storeys and openings), click a card to build that house. The <select id="house">
// stays the one source of truth: the picker sets it and fires its change, so the rest of the page is unchanged.
import { $, esc, ftin, houseList } from "./state.js";

const COS30 = Math.cos(Math.PI / 6);

export function sketch(polys, w, h) {
  // an isometric drawing of a house's outside: walls (with gables) and roof planes, far ones drawn first
  if (!polys?.length) return `<svg width="${w}" height="${h}"></svg>`;
  const proj = ([x, y, z]) => [(x - y) * COS30, (x + y) * 0.5 - z];
  const shapes = polys.map((q) => {
    const pts = q.p.map(proj);
    const near = q.p.reduce((a, [x, y, z]) => a + x + y + (q.k === "roof" ? 0.6 * z : 0), 0) / q.p.length;
    return { k: q.k, pts, near };
  }).sort((a, b) => a.near - b.near);
  const all = shapes.flatMap((s) => s.pts);
  const [x0, x1] = [Math.min(...all.map((p) => p[0])), Math.max(...all.map((p) => p[0]))];
  const [y0, y1] = [Math.min(...all.map((p) => p[1])), Math.max(...all.map((p) => p[1]))];
  const k = Math.min((w - 4) / (x1 - x0 || 1), (h - 4) / (y1 - y0 || 1));
  const ox = (w - (x1 - x0) * k) / 2, oy = (h - (y1 - y0) * k) / 2;
  const d = (pts) => pts.map(([x, y], i) => `${i ? "L" : "M"}${((x - x0) * k + ox).toFixed(1)} ${((y - y0) * k + oy).toFixed(1)}`).join("") + "Z";
  return `<svg class="sketch" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${shapes.map((s) =>
    `<path class="${s.k}" d="${d(s.pts)}"/>`).join("")}</svg>`;
}

const kindName = { box: "box", L: "L-shaped", T: "T-shaped", U: "U-shaped", ell: "with an ell" };

function card(h, on) {
  return `<button class="hcard ${on ? "on" : ""}" data-house="${esc(h.id)}">${sketch(h.polys, 150, 96)}
    <b>${esc(h.id)}</b><small>${ftin(h.size[0])} x ${ftin(h.size[1])}, ${esc(kindName[h.kind] || h.kind || "")}</small>
    <small>${h.storeys} storey${h.storeys > 1 ? "s" : ""}, ${h.openings} openings</small></button>`;
}

export function renderHousePick() {
  const id = $("#house").value, h = houseList.find((x) => x.id === id);
  $("#housePick").innerHTML = h ? `${sketch(h.polys, 44, 28)}<span>${esc(h.id)}</span><small>${ftin(h.size[0])} x ${ftin(h.size[1])}</small>`
    : `<span>${esc(id || "choose a house")}</span>`;
  if (!$("#housePop").hidden) renderPop();
}

function renderPop() {
  const id = $("#house").value;
  $("#housePop").innerHTML = `<div class="hgrid">${houseList.map((h) => card(h, h.id === id)).join("")}</div>`;
}

function setOpen(open) {
  $("#housePop").hidden = !open;
  $("#housePick").classList.toggle("on", open);
  if (open) {
    renderPop();
    $("#housePop .hcard.on")?.scrollIntoView({ block: "nearest" });
  }
}

$("#housePick").addEventListener("click", (e) => { e.stopPropagation(); setOpen($("#housePop").hidden); });
$("#housePop").addEventListener("click", (e) => {
  const c = e.target.closest("[data-house]");
  if (!c) return;
  const sel = $("#house");
  if (sel.value !== c.dataset.house) {
    sel.value = c.dataset.house;
    sel.dispatchEvent(new Event("change"));
  }
  setOpen(false);
  renderHousePick();
});
document.addEventListener("click", (e) => { if (!$("#housePop").hidden && !e.target.closest("#housePop")) setOpen(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#housePop").hidden) setOpen(false); });
document.addEventListener("houses", renderHousePick);           // the house list was (re)loaded
$("#house").addEventListener("change", renderHousePick);
