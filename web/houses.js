// The house picker: the current house as a small drawing in the header; click it for every house as a card
// (its drawing, size, kind, storeys and openings), click a card to build that house. The <select id="house">
// stays the one source of truth: the picker sets it and fires its change, so the rest of the page is unchanged.
import { $, esc, ftin, houseList } from "./state.js";

// each house's picture is its stored thumbnail (data/houses/<id>.svg), drawn once by the server
const thumb = (id, w, h) => `<img class="sketch" src="/api/house/${encodeURIComponent(id)}/thumb.svg" width="${w}" height="${h}" alt="" loading="lazy">`;

const kindName = { box: "box", L: "L-shaped", T: "T-shaped", U: "U-shaped", ell: "with an ell" };

function card(h, on) {
  return `<button class="hcard ${on ? "on" : ""}" data-house="${esc(h.id)}">${thumb(h.id, 150, 96)}
    <b>${esc(h.id)}</b><small>${ftin(h.size[0])} x ${ftin(h.size[1])}, ${esc(kindName[h.kind] || h.kind || "")}</small>
    <small>${h.storeys} storey${h.storeys > 1 ? "s" : ""}, ${h.openings} openings</small></button>`;
}

export function renderHousePick() {
  const id = $("#house").value, h = houseList.find((x) => x.id === id);
  $("#housePick").innerHTML = h ? `${thumb(h.id, 44, 28)}<span>${esc(h.id)}</span><small>${ftin(h.size[0])} x ${ftin(h.size[1])}</small>`
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
