// The Grammar tab: the source editor, its saved/unsaved state, Save, Revert, Build with this, Score on all
// houses, and loading a grammar's source from the server.
import { $, esc, st, api, status, dirty, houseList } from "./state.js";
import { build, showTab } from "./app.js";
import { rs } from "./runs.js";
import { setFollow } from "./live.js";

export async function loadGrammar() {
  const g = await api("GET", `/api/grammar/${$("#grammar").value}`);
  st.saved = g.source;
  st.origin = null;
  $("#src").value = g.source;
  editState();
}

export function editState() {
  const d = dirty();
  $("#edState").innerHTML = d
    ? `<b>Unsaved${st.origin ? `: ${esc(st.origin)}` : " edits"}.</b> Builds use them. Save writes grammars/${esc($("#grammar").value)}.py; Revert goes back to it.`
    : `Saved as grammars/${esc($("#grammar").value)}.py. Edit, then Build with this (Cmd+Enter) to try it.`;
  $("#edState").className = d ? "dirty" : "";
  $("#dirty").textContent = d ? "*" : "";
}

export function jumpToRule(name) {
  const r = st.data.rules.find((x) => x.name === name);
  showTab("editor");
  if (!r) return;
  const ta = $("#src");
  const lines = ta.value.split("\n");
  const start = lines.slice(0, Math.max(0, r.line - 2)).join("\n").length + (r.line > 1 ? 1 : 0);
  const end = lines.slice(0, r.end).join("\n").length;
  ta.focus();
  ta.setSelectionRange(start, end);
  ta.scrollTop = Math.max(0, (r.line - 4) * 18.6);
}

$("#src").addEventListener("input", () => { setFollow(false); editState(); });
$("#src").addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    const ta = e.target;
    const [a, b] = [ta.selectionStart, ta.selectionEnd];
    ta.setRangeText("    ", a, b, "end");
    editState();
  }
});
$("#edBuild").addEventListener("click", () => build());
$("#edRevert").addEventListener("click", () => { setFollow(false); $("#src").value = st.saved; st.origin = null; editState(); build(); });
$("#edSave").addEventListener("click", async () => {
  try {
    await api("PUT", `/api/grammar/${$("#grammar").value}`, { source: $("#src").value });
    st.saved = $("#src").value;
    st.origin = null;
    editState();
    status(`saved grammars/${$("#grammar").value}.py`);
  } catch (e) { status(e.message, true); }
});
$("#edScore").addEventListener("click", async () => {
  const g = $("#grammar").value;
  try {
    const job = await api("POST", "/api/jobs", { kind: "evaluate", settings: {
      grammar: `grammars/${g}.py`, houses: houseList.map((h) => `data/houses/${h.id}.json`) } });
    rs.anyRunning = true;
    rs.watch.add(job.id);
    status(`scoring grammars/${g}.py on ${houseList.length} houses${dirty() ? " (the saved file, not your unsaved edits)" : ""}; Runs shows the log`);
  } catch (e) { status(e.message, true); }
});
