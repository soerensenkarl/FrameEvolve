// The Live tab: a running search as it happens. Polls the run's live state, shows the proposer's actions as
// a feed, the draft's diff against its parent, and (when Follow is on) builds the draft in the 3D view.
import { $, esc, st, api, status, grammarList, loadLists } from "./state.js";
import { build, showTab } from "./app.js";
import { editState } from "./editor.js";
import { lt, fmtScore, diffHtml } from "./runs.js";

export const lv = {
  run: null, follow: false, data: null, proposal: "", count: 0, t0: 0, draft: null, parent: null, parentSrc: "",
  houseFor: null, runData: null, runKey: "", news: "",
};

export function startLive(name, follow) {
  if (lv.run !== name) {
    Object.assign(lv, { run: name, data: null, proposal: "", count: 0, draft: null, parent: null, parentSrc: "",
      houseFor: null, runData: null, runKey: "", news: "" });
    $("#lvFeed").innerHTML = "";
  }
  if (follow) setFollow(true);
  liveTick();
}

export function setFollow(on) {
  if (lv.follow === on) return;
  lv.follow = on;
  document.querySelectorAll(".lvFollow").forEach((b) => { b.checked = on; });
  if (on && lv.draft != null) followDraft();
}

const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const span = (s) => (s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);
const ft = (x) => `${Math.round(x).toLocaleString()} ft`;

let liveBusy = false;
async function liveTick() {
  if (!lv.run || liveBusy) return;
  liveBusy = true;
  try {
    const d = await api("GET", `/api/run/${encodeURIComponent(lv.run)}/live?proposal=${lv.proposal}&after=${lv.count}`);
    const name = d.live?.proposal || "";
    if (name && name !== lv.proposal) {   // a new iteration: the server sent all of its actions
      lv.proposal = name;
      $("#lvFeed").innerHTML = "";
      lv.t0 = d.live?.started || d.events[0]?.time || Date.now() / 1000;   // times count from the iteration's start
    }
    lv.data = d;
    if (name === lv.proposal) {   // once stopped there is no proposal: keep the last iteration's feed
      lv.count = d.count;
      appendFeed(d.events);
    }
    if (d.live?.parent && d.live.parent !== lv.parent) {
      lv.parent = d.live.parent;
      lv.parentSrc = await api("GET", `/api/run/${lv.run}/grammar/${lv.parent}`).then((g) => g.source).catch(() => "");
    }
    const key = JSON.stringify([d.job?.done, d.live?.stage, d.live?.iteration]);
    if (key !== lv.runKey) {   // an iteration ended or a stage changed: the chart and the news
      lv.runKey = key;
      lv.runData = await api("GET", `/api/run/${lv.run}`).catch(() => lv.runData);
      const r = lv.runData;
      const best = r?.candidates.reduce((a, c) => (!a || lt(c.total, a.total) < 0 ? c : a), null);
      $("#lvChart").innerHTML = best ? `<div class="muted">Best so far: <b>${esc(best.id)}</b>, ${fmtScore(best.total)} over
        ${r.houses.length} houses. ${r.candidates.length - 1} of ${r.iterations.length} edits kept; the Runs view has the chart.</div>` : "";
      renderNews();
    }
    if (d.draft != null && d.draft !== lv.draft) {
      lv.draft = d.draft;
      renderDraftDiff();
      if (lv.follow) await followDraft();
    }
  } catch (e) {   // the next tick tries again, unless the run is gone
    if (/not found|no such run/i.test(e.message)) Object.assign(lv, { run: null, follow: false });
  } finally { liveBusy = false; }
  renderLiveHead();
  renderRunLive();
}
setInterval(liveTick, 1500);

function liveState() {
  // a line or two saying where the search is
  const d = lv.data;
  if (!d) return { on: false, html: "" };
  const L = d.live, job = d.job;
  const on = d.active;
  if (L && (!on || L.stage === "stopped")) return { on, html: `<b>${esc(lv.run)}</b> has stopped, after ${lv.runData?.iterations.length ?? "its"} iterations.` };
  if (!L) {
    return { on, html: on ? `<b>${esc(lv.run)}</b>: ${job.done} of ${job.of} iterations done. This search started before the live view
      existed, so only finished iterations show.` : `<b>${esc(lv.run)}</b> is not running.` };
  }
  const of = job ? `, ${Math.min(job.done + 1, job.of)} of ${job.of} in this search` : "";
  return { on, html: `<b>${esc(lv.run)}</b>, iteration ${L.iteration}${of}: <span class="stage">${esc(L.stage)}</span>
    for ${span(Date.now() / 1000 - L.time)}
    ${L.parent ? `<div class="muted">parent ${esc(L.parent)} on ${(L.houses || []).map(esc).join(", ")}</div>` : ""}` };
}

function followLine() {
  return `<label class="chk follow" title="On: the 3D view, rules and stepping follow Claude's draft. Off: browse freely.">
    <input type="checkbox" class="lvFollow" ${lv.follow ? "checked" : ""}> Follow live</label>
    <span class="muted">${lv.follow ? (lv.draft != null ? `the 3D view shows the draft on ${esc($("#house").value)}` : "waiting for a draft") : "the 3D view is yours"}</span>`;
}

function renderLiveHead() {
  $("#liveDot").textContent = lv.data?.active ? "●" : "";
  if (!lv.run) return;
  const s = liveState();
  $("#lvHead").innerHTML = `<div class="lv-status">${s.on ? `<span class="livedot"></span>` : ""}<div>${s.html}</div></div>
    <div class="lv-follow">${followLine()}</div>`;
  $("#lvFeedTitle").hidden = !lv.proposal;
}

function renderNews() {
  // say clearly when a child is kept
  const L = lv.data?.live;
  const last = lv.runData?.iterations.at(-1);
  let html = "";
  if (L?.stage === "scoring on every house") html = `<div class="news good">${esc(L.child)} beat ${esc(L.parent)}: scoring it on every house...</div>`;
  else if (L?.accepted) html = `<div class="news good"><b>Kept as ${esc(L.child)}</b>: iteration ${L.iteration} beat ${esc(L.parent)} on ${(L.houses || []).map(esc).join(", ")}.</div>`;
  else if (L?.stage === "between iterations" && last?.iteration === L.iteration) {
    html = `<div class="news">Iteration ${L.iteration} not kept: ${esc(last.error || "not better than its parent on these houses")}.</div>`;
  }
  if (html !== lv.news) {
    if (L?.accepted && !lv.news.includes(`Kept as ${L.child}`)) status(`run ${lv.run}: kept ${L.child}`);
    lv.news = html;
    $("#lvNews").innerHTML = html;
  }
}

export function renderRunLive() {
  // the live box at the top of the Runs view
  const el = document.getElementById("runLive");
  if (!el || !lv.data) return;
  const s = liveState();
  const lastSay = [...$("#lvFeed").querySelectorAll(".fi")].at(-1)?.textContent || "";
  el.innerHTML = `<div class="runlive"><div>${s.html}</div>${lv.news}
    ${lastSay ? `<div class="lastfeed" title="the proposer's latest action">${esc(lastSay)}</div>` : ""}
    <div class="row">${followLine()}<button data-act="watch" class="primary">Watch in 3D</button></div></div>`;
}

document.addEventListener("change", (e) => { if (e.target.classList.contains("lvFollow")) setFollow(e.target.checked); });
$("#runsMain").addEventListener("click", (e) => {
  if (e.target.closest("button[data-act=watch]")) { setFollow(true); showTab("view3d"); showTab("live"); }
});

async function followDraft() {
  // the draft as unsaved edits to its parent grammar, built on a house of this iteration's minibatch
  const L = lv.data?.live;
  if (!L || lv.draft == null) return;
  const gname = `${lv.run}.${L.parent}`;
  if (!grammarList.includes(gname)) await loadLists($("#house").value);
  if (grammarList.includes(gname) && $("#grammar").value !== gname) {
    $("#grammar").value = gname;
    st.saved = lv.parentSrc;
    st.hidden.clear();
  }
  if (lv.houseFor !== L.iteration) {
    lv.houseFor = L.iteration;
    if (L.houses?.length && !L.houses.includes($("#house").value)) $("#house").value = L.houses[0];
  }
  $("#src").value = lv.draft;
  st.origin = `Live draft: run ${lv.run}, iteration ${L.iteration}`;
  editState();
  await build(true);
}

function renderDraftDiff() {
  const box = $("#lvDiff");
  box.hidden = lv.draft == null;
  if (lv.draft == null) return;
  const d = diffHtml(lv.parentSrc, lv.draft);
  box.querySelector("summary").innerHTML = `Draft against ${esc(lv.parent)}: <span class="good">+${d.add}</span> <span class="bad">-${d.del}</span> lines`;
  box.querySelector("div").innerHTML = d.html;
}

function enclosing(src, snippet) {
  // the function a piece of text sits in: a name, "" at the top of the file, null when not found
  const first = String(snippet || "").split("\n").map((l) => l.trim()).find((l) => l && l !== "...");
  if (!first || !src) return null;
  const lines = src.split("\n");
  let i = lines.findIndex((l) => l.includes(first));
  if (i < 0) return null;
  if (lines[i].startsWith("@")) while (i < lines.length - 1 && !lines[i].startsWith("def ")) i++;
  for (; i >= 0; i--) {
    const m = lines[i].match(/^def (\w+)/);
    if (m) return m[1];
    if (lines[i] && !/^[\s@#]/.test(lines[i])) return "";
  }
  return "";
}

function editWords(input) {
  const defs = (t) => new Set([...String(t || "").matchAll(/def (\w+)\(/g)].map((m) => m[1]));
  const added = [...defs(input.new)].filter((n) => !defs(input.old).has(n));
  if (added.length) return `added ${added.join(", ")}`;
  const name = enclosing(lv.draft, input.new) ?? enclosing(lv.parentSrc, input.old);
  return name ? `edited ${name}` : name === "" ? "edited the settings at the top" : "edited the grammar";
}

function feedHtml(e) {
  const t = `<i>${clock(Math.max(0, e.time - lv.t0))}</i>`;
  const line = (text, cls = "") => `<div class="fi ${cls}">${t}${text}</div>`;
  const inp = e.input || {};
  if (e.kind === "start") return line(`Claude starts: ${esc(e.model)}, ${esc(e.effort)} effort, via ${esc(e.via)}`, "muted");
  if (e.kind === "say") return `<div class="fi say">${t}<span>${esc(e.text)}</span></div>`;
  if (e.kind === "tool") {
    if (e.tool === "view_grammar") {
      const a = +inp.start || 1, b = +inp.end || 0;
      return line(a <= 1 && !b ? "read the whole grammar" : `read lines ${a}-${b || "end"}`);
    }
    if (e.tool === "edit_grammar") return line(esc(editWords(inp)), "edit");
    if (e.tool === "write_grammar") return line("rewrote the whole grammar", "edit");
    if (e.tool === "check_grammar") return line(`checking the draft on ${(lv.data?.live?.houses || []).map(esc).join(", ") || "this round's houses"}...`);
    return line(`${esc(e.tool)}`);
  }
  if (e.kind === "result") {
    const text = String(e.text || "");
    if (e.tool === "edit_grammar" && text.startsWith("Not changed")) return line(`edit not applied: ${esc(text.replace(/^Not changed: /, ""))}`, "bad");
    if (e.tool === "check_grammar") {
      const m = text.match(/Total over these houses: (\d+) hard, (\d+) soft, cost ([\d.]+) \(parent: \[([^\]]*)\]\)/);
      const head = m ? (() => {
        const p = m[4].split(",").map(Number);
        return `checked: <b>${m[1]} hard, ${m[2]} soft, cost ${ft(+m[3])}</b> <span class="muted">(parent ${p[0]} hard, ${p[1]} soft, ${ft(p[2])})</span>`;
      })() : esc(text.split("\n")[0]);
      return `<div class="fi check">${t}<span>${head}<details><summary>reports</summary><pre class="code wrap">${esc(text)}</pre></details></span></div>`;
    }
  }
  return "";   // view results, write confirmations and draft notices say nothing new
}

function appendFeed(events) {
  if (!events.length) return;
  const feed = $("#lvFeed");
  const atEnd = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 30;
  feed.insertAdjacentHTML("beforeend", events.map(feedHtml).join(""));
  if (atEnd) feed.scrollTop = feed.scrollHeight;
}
