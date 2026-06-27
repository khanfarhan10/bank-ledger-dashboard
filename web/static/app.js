/* Bank Ledger Dashboard — frontend.
 * Interactive Tabulator grids + right-click actions + inline approval workflow,
 * Benazir relationship ledger, family savings with overrides, sectioned income,
 * investments, accident/marriage events, and a charts-driven summary. */

"use strict";

const $ = (s) => document.querySelector(s);

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.status === 204 ? null : res.json();
}

function fmtINR(n) {
  if (n === null || n === undefined || isNaN(n)) return "—";
  const neg = n < 0; n = Math.abs(Math.round(n));
  let s = String(n), last3 = s.slice(-3), rest = s.slice(0, -3);
  if (rest) last3 = "," + last3;
  rest = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return (neg ? "-₹" : "₹") + rest + last3;
}

let TOAST_T;
function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(TOAST_T);
  TOAST_T = setTimeout(() => { t.className = "toast"; }, 2400);
}

const STATE = { meta: { categories: [], review_statuses: [], threshold: 0 }, tables: {}, charts: {}, active: "ledger" };

// ---------- decision helpers ----------
async function saveDecision(id, fields) {
  try { await api("/api/decision", { method: "POST", body: JSON.stringify(Object.assign({ transaction_id: id }, fields)) }); toast("Saved"); reloadActive(); }
  catch (e) { toast("Save failed: " + e.message, true); }
}
async function confirmRow(id) { try { await api("/api/decision/confirm", { method: "POST", body: JSON.stringify({ transaction_id: id }) }); toast("Confirmed ✓"); reloadActive(); } catch (e) { toast(e.message, true); } }
async function denyRow(id) { try { await api("/api/decision/deny", { method: "POST", body: JSON.stringify({ transaction_id: id }) }); toast("Denied — moved to unknown"); reloadActive(); } catch (e) { toast(e.message, true); } }
async function resetDecision(id) { try { await api("/api/decision/reset", { method: "POST", body: JSON.stringify({ transaction_id: id }) }); toast("Reset"); reloadActive(); } catch (e) { toast(e.message, true); } }

// ---------- right-click context menu ----------
function rowContextMenu() {
  const cats = STATE.meta.categories || [];
  const statuses = STATE.meta.review_statuses || [];
  return [
    { label: "🏷  Reclassify", menu: cats.map((c) => ({ label: c, action: (e, r) => saveDecision(r.getData().transaction_id, { category: c }) })) },
    { label: "✓  Confirm classification", action: (e, r) => confirmRow(r.getData().transaction_id) },
    { label: "✗  Deny → unknown", action: (e, r) => denyRow(r.getData().transaction_id) },
    { separator: true },
    { label: "🔁  Mark as self-transfer", action: (e, r) => saveDecision(r.getData().transaction_id, { category: "self_transfer" }) },
    { label: "👤  Related to Benazir", action: (e, r) => saveDecision(r.getData().transaction_id, { manual_person: "benazir", manual_review_status: "confirmed_related" }) },
    { label: "👤  Related to Nazrana", action: (e, r) => saveDecision(r.getData().transaction_id, { manual_person: "nazrana", manual_review_status: "confirmed_related" }) },
    { label: "👩  Related to Mother (Husna)", action: (e, r) => saveDecision(r.getData().transaction_id, { manual_person: "mother", manual_review_status: "confirmed_related" }) },
    { label: "🧑  Related to Sister (Zarinne)", action: (e, r) => saveDecision(r.getData().transaction_id, { manual_person: "sister", manual_review_status: "confirmed_related" }) },
    { separator: true },
    { label: "📋  Review status", menu: statuses.map((s) => ({ label: s, action: (e, r) => saveDecision(r.getData().transaction_id, { manual_review_status: s }) })) },
    { label: "📝  Add / edit note…", action: (e, r) => { const d = r.getData(); const n = prompt("Reason / note:", d.manual_comment || ""); if (n !== null) saveDecision(d.transaction_id, { manual_comment: n }); } },
    { separator: true },
    { label: "↺  Reset to auto", action: (e, r) => resetDecision(r.getData().transaction_id) },
  ];
}

// ---------- grid ----------
function amountFormatter(cell) {
  const d = cell.getRow().getData(), v = cell.getValue();
  const span = document.createElement("span");
  span.textContent = fmtINR(v);
  span.className = d.direction === "RECEIVED" ? "cell-pos" : (d.direction === "PAID_OUT" ? "cell-neg" : "");
  return span;
}
function tagsFormatter(cell) {
  const v = cell.getValue(); if (!v) return "";
  return v.split(",").filter(Boolean).map((t) => `<span class="tag-chip">${t}</span>`).join(" ");
}
function statusFormatter(cell) {
  const d = cell.getRow().getData();
  if (d.is_approved) return '<span class="badge ok">✓ approved</span>';
  if (!d.category || d.category === "unknown") return '<span class="badge muted">unknown</span>';
  return '<span class="badge warn">⚠ auto</span>';
}

function baseColumns(editable, withApprove) {
  const catEditor = { editor: "list", editorParams: { values: STATE.meta.categories, autocomplete: true, freetext: true } };
  const statusEditor = { editor: "list", editorParams: { values: STATE.meta.review_statuses } };
  const cols = [
    { title: "Date", field: "transaction_date", width: 100, headerFilter: "input" },
    { title: "Bank", field: "source_bank", width: 70 },
    { title: "Description", field: "description", widthGrow: 4, minWidth: 240, headerFilter: "input", tooltip: (e, c) => c.getRow().getData().raw_description || "" },
    { title: "Amount", field: "amount", width: 115, hozAlign: "right", formatter: amountFormatter, sorter: "number" },
    { title: "Dir", field: "direction", width: 90 },
    Object.assign({ title: "Category", field: "category", width: 140, headerFilter: "input" }, editable ? catEditor : {}),
    { title: "Tags", field: "tags", width: 140, formatter: tagsFormatter },
    { title: "Status", field: "is_approved", width: 100, formatter: statusFormatter },
    Object.assign({ title: "Note", field: "manual_comment", widthGrow: 2, minWidth: 130 }, editable ? { editor: "input" } : {}),
  ];
  if (withApprove) {
    cols.push({ title: "✓", width: 38, hozAlign: "center", headerSort: false, formatter: () => '<span class="act ok">✓</span>', cellClick: (e, c) => confirmRow(c.getRow().getData().transaction_id) });
    cols.push({ title: "✗", width: 38, hozAlign: "center", headerSort: false, formatter: () => '<span class="act no">✗</span>', cellClick: (e, c) => denyRow(c.getRow().getData().transaction_id) });
  }
  return cols;
}

function rowFormatter(row) {
  const d = row.getData(), el = row.getElement();
  el.classList.toggle("row-self", !!d.is_self_transfer);
  el.classList.toggle("row-dup", !!d.is_duplicate);
  el.classList.toggle("row-manual", !!d.is_manual_entry);
  el.classList.toggle("row-pending", !d.is_approved && d.category && d.category !== "unknown");
  el.classList.toggle("row-approved", !!d.is_approved);
}

function makeGrid(hostId, rows, opts) {
  opts = opts || {};
  const t = new Tabulator("#" + hostId, {
    data: rows,
    columns: baseColumns(opts.editable !== false, opts.approve !== false),
    layout: "fitColumns",
    height: opts.height || 600,
    placeholder: "No transactions",
    rowFormatter,
    rowContextMenu: rowContextMenu(),
    movableColumns: true,
    index: "transaction_id",
  });
  if (opts.editable !== false) {
    t.on("cellEdited", (cell) => {
      const f = cell.getField(), id = cell.getRow().getData().transaction_id;
      if (["category", "manual_review_status", "manual_comment"].includes(f)) saveDecision(id, { [f]: cell.getValue() });
    });
  }
  return t;
}

// ---------- navigation ----------
function showPage(page) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + page));
  STATE.active = page;
  loaders[page] && loaders[page]();
}
function reloadActive() { if (STATE.active && loaders[STATE.active]) loaders[STATE.active](); }

const loaders = {};

// ---------- Ledger ----------
loaders.ledger = async function () {
  const data = await api("/api/ledger");
  STATE.ledgerRows = data.rows;
  if (STATE.tables.ledger) STATE.tables.ledger.destroy();
  STATE.tables.ledger = makeGrid("ledgerGrid", data.rows, {});
  const banks = [...new Set(data.rows.map((r) => r.source_bank).filter(Boolean))].sort();
  $("#ledgerBank").innerHTML = `<option value="">All banks</option>` + banks.map((b) => `<option>${b}</option>`).join("");
  $("#ledgerCat").innerHTML = `<option value="">All categories</option>` + STATE.meta.categories.map((c) => `<option>${c}</option>`).join("");
  applyLedgerFilter();
};
function applyLedgerFilter() {
  const t = STATE.tables.ledger; if (!t) return;
  const q = $("#ledgerSearch").value.toLowerCase(), bank = $("#ledgerBank").value, dir = $("#ledgerDir").value,
        cat = $("#ledgerCat").value, hideSelf = $("#ledgerHideSelf").checked, pendingOnly = $("#ledgerPendingOnly").checked;
  t.setFilter((r) => {
    if (bank && r.source_bank !== bank) return false;
    if (dir && r.direction !== dir) return false;
    if (cat && r.category !== cat) return false;
    if (hideSelf && r.is_self_transfer) return false;
    if (pendingOnly && (r.is_approved || !r.category || r.category === "unknown")) return false;
    if (q && !((r.description || "") + " " + (r.raw_description || "")).toLowerCase().includes(q)) return false;
    return true;
  });
}

// ---------- Benazir (masters) ----------
function escapeHtml(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

loaders.benazir = async function () {
  const b = await api("/api/benazir");
  const s = b.summary || {};
  const card = (l, v, cls, foot) => `<div class="card"><div class="label">${l}</div><div class="value ${cls || ""}">${v}</div>${foot ? `<div class="foot">${foot}</div>` : ""}</div>`;
  $("#benazirCards").innerHTML =
    card("Total billed to Benazir", fmtINR(s.total_billed), "red", `${s.master_count} masters + general`) +
    card("Masters total", fmtINR(s.masters_total), "amber", "structured expenses") +
    card("General total", fmtINR(s.general_total), "amber", `${s.txn_count} related txns`);

  const host = $("#benazirMasters"); host.innerHTML = "";
  (b.masters || []).forEach((m) => host.appendChild(masterCard(m)));
};

function masterCard(m) {
  const wrap = document.createElement("div");
  wrap.className = "section master" + (m.code === "GEN" ? " collapsed" : "");
  const isGen = m.code === "GEN";
  const rowsHtml = (m.members || []).map((mem) => {
    const amt = `<span class="${mem.direction === "RECEIVED" ? "cell-pos" : "cell-neg"}">${fmtINR(mem.amount)}</span>`;
    const badge = mem.is_approved ? '<span class="badge ok">✓</span>' : '<span class="badge warn">⚠</span>';
    const acts = `<span class="act ok" data-confirm="${mem.transaction_id}">✓</span> <span class="act no" data-deny="${mem.transaction_id}">✗</span>`;
    const cls = [mem.historic ? "hist-row" : "", mem.offset ? "offset-row" : ""].join(" ").trim();
    const tags = (mem.historic ? ' <span class="tag-chip">historic</span>' : "")
      + (mem.offset ? ` <span class="tag-chip resolved" title="links to ${mem.offset_partner || ""}">↔ ${escapeHtml(mem.offset_note || "resolved")}</span>` : "");
    return `<tr class="${cls}" data-tid="${mem.transaction_id}">
      <td>${mem.transaction_date || ""}</td>
      <td class="muted">${escapeHtml(mem.source_bank)}</td>
      <td title="${escapeHtml(mem.raw_description)}"><span class="${mem.offset ? "strike" : ""}">${escapeHtml(mem.member_label || mem.description)}</span>${tags}</td>
      <td class="num"><span class="${mem.offset ? "strike" : ""}">${amt}</span></td>
      <td>${badge}</td>
      <td class="nowrap">${acts}</td></tr>`;
  }).join("");

  wrap.innerHTML = `
    <div class="section-head master-head">
      <span><span class="master-code">${isGen ? "GENERAL" : "SUMMARY-" + m.code}</span> ${escapeHtml(m.title)}</span>
      <span class="section-meta">${m.base_date || ""} • net <b>${fmtINR(m.net)}</b>${m.declared ? " (declared)" : ""} • ${m.count} rec</span>
    </div>
    <div class="section-body">
      <div class="master-detail">${escapeHtml(m.detail)}
        ${isGen ? "" : `<button class="btn ghost xs" data-edit="${m.code}">✎ Edit header</button>`}</div>
      <table class="mini member-table"><thead><tr><th>Date</th><th>Source</th><th>Description</th><th class="num">Amount</th><th>St</th><th>Act</th></tr></thead>
        <tbody>${rowsHtml || '<tr><td colspan=6 class="muted">No records</td></tr>'}</tbody></table>
    </div>`;

  // collapse toggle
  wrap.querySelector(".master-head").addEventListener("click", () => wrap.classList.toggle("collapsed"));
  // confirm / deny per row
  wrap.querySelectorAll("[data-confirm]").forEach((el) => el.addEventListener("click", (e) => { e.stopPropagation(); confirmRow(el.dataset.confirm); }));
  wrap.querySelectorAll("[data-deny]").forEach((el) => el.addEventListener("click", (e) => { e.stopPropagation(); denyRow(el.dataset.deny); }));
  // edit header
  const editBtn = wrap.querySelector("[data-edit]");
  if (editBtn) editBtn.addEventListener("click", (e) => { e.stopPropagation(); openMasterEditor(wrap, m); });
  return wrap;
}

function openMasterEditor(wrap, m) {
  const body = wrap.querySelector(".master-detail");
  body.innerHTML = `
    <div class="master-edit">
      <label>Title <input id="me_title" class="input" value="${escapeHtml(m.title)}" /></label>
      <label>Base date <input id="me_date" class="input" type="date" value="${m.base_date || ""}" /></label>
      <label class="wide">Details <textarea id="me_detail" class="input" rows="2">${escapeHtml(m.detail)}</textarea></label>
      <label>Declared net ₹ <input id="me_amt" class="input" type="number" value="${m.declared ? Math.round(m.net) : ""}" placeholder="(auto from records)" /></label>
      <button class="btn" id="me_save">Save</button> <button class="btn ghost" id="me_cancel">Cancel</button>
    </div>`;
  body.querySelector("#me_cancel").addEventListener("click", () => loaders.benazir());
  body.querySelector("#me_save").addEventListener("click", async () => {
    const payload = { code: m.code, title: $("#me_title").value, detail: $("#me_detail").value, base_date: $("#me_date").value };
    const amt = $("#me_amt").value;
    if (amt !== "") payload.summary_amount = parseFloat(amt);
    try { await api("/api/benazir/master", { method: "POST", body: JSON.stringify(payload) }); toast("Master updated"); loaders.benazir(); }
    catch (err) { toast("Save failed: " + err.message, true); }
  });
}

// ---------- Search ----------
loaders.search = async function () {
  $("#sCat").innerHTML = `<option value="">Any category</option>` + STATE.meta.categories.map((c) => `<option>${c}</option>`).join("");
};
async function runSearch() {
  try {
    const p = new URLSearchParams();
    const map = { q: "sQ", min_amount: "sMin", max_amount: "sMax", date_from: "sFrom", date_to: "sTo", direction: "sDir", category: "sCat", person: "sPerson" };
    for (const [k, id] of Object.entries(map)) { const v = $("#" + id).value; if (v) p.set(k, v); }
    $("#sCount").textContent = "Searching…";
    const data = await api("/api/search?" + p.toString());
    $("#sCount").textContent = data.count + " result(s)";
    if (STATE.tables.search) { STATE.tables.search.destroy(); STATE.tables.search = null; }
    STATE.tables.search = makeGrid("searchGrid", data.rows, {});
  } catch (e) {
    $("#sCount").textContent = "Search failed";
    toast("Search failed: " + e.message + " — is the server running?", true);
  }
}

// ---------- Family ----------
loaders.family = async function () {
  const f = await api("/api/family");
  const host = $("#familySections"); host.innerHTML = "";
  (f.people || []).forEach((p, i) => {
    const id = "fam_grid_" + i;
    const div = document.createElement("div"); div.className = "panel";
    div.innerHTML = `<h3>${p.label}</h3>
      <div class="cards">
        ${cardHtml("Total sent", fmtINR(p.sent), "red")}
        ${cardHtml("Received back", fmtINR(p.received), "green")}
        ${cardHtml("Net to them", fmtINR(p.net), "amber")}
        ${cardHtml("Saved (your figure)", fmtINR(p.saved), "", p.saved_is_override ? "overridden" : "default = net")}
      </div>
      <div class="override-row">
        <label>Actually saved (₹) <input type="number" class="input" id="fam_save_${p.key}" value="${Math.round(p.saved)}" /></label>
        <label>Note <input class="input" id="fam_note_${p.key}" value="${(p.note || "").replace(/"/g, "&quot;")}" placeholder="e.g. 3L used for home expenses" /></label>
        <button class="btn" data-person="${p.key}">Save override</button>
      </div>
      <div id="${id}" class="grid-host short"></div>`;
    host.appendChild(div);
    STATE.tables[id] = makeGrid(id, p.rows, { height: 300 });
    div.querySelector("button[data-person]").addEventListener("click", async (e) => {
      const person = e.target.dataset.person;
      await api("/api/family/override", { method: "POST", body: JSON.stringify({ person, total_saved: parseFloat($("#fam_save_" + person).value || "0"), note: $("#fam_note_" + person).value }) });
      toast("Override saved"); loaders.family();
    });
  });
};
function cardHtml(l, v, cls, foot) { return `<div class="card"><div class="label">${l}</div><div class="value ${cls || ""}">${v}</div>${foot ? `<div class="foot">${foot}</div>` : ""}</div>`; }

// ---------- Investments ----------
const MANUAL_PORTFOLIO = [
  { name: "PPF", invested: "₹1.5L/yr (2022, 2023)", note: "Mandatory. ~22.5L in → ~40.68L out after 15 yrs, tax-free.", tax: "80C" },
  { name: "SGB (20 g gold)", invested: "₹1.18L", note: "Hold ≥4 yrs; tax-free after 8 yrs, no TDS/GST.", tax: "—" },
  { name: "NPS", invested: "₹0.5L (2023)", note: "Mandatory once above ₹10L slab.", tax: "80CCD(1B)" },
  { name: "Kotak Get Assured Income", invested: "₹1.6L (2025)", note: "₹60k/yr; ₹1L paid, ₹40k returned under scheme.", tax: "80C" },
  { name: "MF — Groww", invested: "₹50k", note: "Mutual funds.", tax: "—" },
  { name: "MF — Zerodha Coin", invested: "₹20k", note: "Mutual funds.", tax: "—" },
  { name: "Sister (Zarinne) MF a/c", invested: "₹75k", note: "Held in sister's account — counted as my investment.", tax: "—" },
  { name: "Crypto — WazirX", invested: "₹50k (at risk)", note: "Halved & locked due to the WazirX hack; can't withdraw.", tax: "—" },
];
loaders.investments = async function () {
  const inv = await api("/api/investments");
  $("#invCards").innerHTML =
    cardHtml("Bank-detected invested", fmtINR(inv.total), "amber", "from statements") +
    cardHtml("80C tax-saving", fmtINR(inv.tax_saving_80c_total || 0), "", (inv.tax_saving_80c_count || 0) + " txns") +
    cardHtml("Instruments", (inv.by_instrument || []).length, "", "types detected");
  $("#invByInstrument").innerHTML = miniTable(["Instrument", "Txns", "Total", "Period"],
    (inv.by_instrument || []).map((i) => [i.instrument, i.transactions, fmtINR(i.total), (i.first || "") + " → " + (i.last || "")]));
  $("#invManual").innerHTML = miniTable(["Instrument", "Invested", "Tax", "Notes"],
    MANUAL_PORTFOLIO.map((p) => [p.name, p.invested, p.tax, p.note]));
  if (STATE.tables.inv) STATE.tables.inv.destroy();
  STATE.tables.inv = makeGrid("invGrid", inv.rows, { height: 320 });
};

// ---------- Income ----------
loaders.income = async function () {
  const inc = await api("/api/income");
  $("#incCards").innerHTML = cardHtml("Total income", fmtINR(inc.total), "green", "salary + freelance + refunds + interest");
  const host = $("#incomeSections"); host.innerHTML = "";
  (inc.sections || []).forEach((sec, i) => {
    const id = "inc_grid_" + i;
    const div = document.createElement("div"); div.className = "section";
    div.innerHTML = `<div class="section-head" data-t="${id}"><span>${sec.label}</span><span class="section-meta">${sec.payments} payments • ${fmtINR(sec.total)}</span></div>
      <div class="section-body"><div id="${id}" class="grid-host short"></div></div>`;
    host.appendChild(div);
    STATE.tables[id] = makeGrid(id, sec.rows, { height: Math.min(320, 60 + sec.rows.length * 34), approve: false, editable: false });
  });
  document.querySelectorAll("#page-income .section-head").forEach((h) => h.addEventListener("click", () => h.parentElement.classList.toggle("collapsed")));
};

// ---------- Accident & Marriage ----------
loaders.events = async function () {
  const a = await api("/api/accident"), m = await api("/api/marriage");
  $("#eventCards").innerHTML =
    cardHtml("Accident insurance claim", fmtINR(a.claim), "green", "ICICI Lombard (received)") +
    cardHtml("Post-accident spend", fmtINR(a.spend), "red", "medical + physio (confirm)") +
    cardHtml("Marriage period spend", fmtINR(m.total), "amber", "~Apr 2023 (confirm)");
  $("#accidentByCat").innerHTML = miniTable(["Category", "Txns", "Total"], (a.by_category || []).map((c) => [c.category, c.count, fmtINR(c.total)]));
  if (STATE.tables.acc) STATE.tables.acc.destroy();
  STATE.tables.acc = makeGrid("accidentGrid", a.rows, { height: 300 });
  if (STATE.tables.mar) STATE.tables.mar.destroy();
  STATE.tables.mar = makeGrid("marriageGrid", m.rows, { height: 240 });
};

// ---------- Large ----------
loaders.large = async function () {
  const thr = $("#largeThreshold").value || STATE.meta.threshold;
  const data = await api("/api/large?threshold=" + encodeURIComponent(thr));
  $("#largeThreshold").value = data.threshold;
  $("#largeCount").textContent = `${data.count} transaction(s) ≥ ${fmtINR(data.threshold)}`;
  if (STATE.tables.large) STATE.tables.large.destroy();
  STATE.tables.large = makeGrid("largeGrid", data.rows, {});
};

// ---------- Manual ----------
loaders.manual = async function () {
  const data = await api("/api/manual-entries");
  if (STATE.tables.manual) STATE.tables.manual.destroy();
  STATE.tables.manual = new Tabulator("#manualGrid", {
    data: data.rows, layout: "fitColumns", height: 320, placeholder: "No manual entries yet",
    columns: [
      { title: "Date", field: "entry_date", width: 100 },
      { title: "Person", field: "person", width: 100 },
      { title: "Amount", field: "amount", width: 110, hozAlign: "right", formatter: (c) => fmtINR(c.getValue()) },
      { title: "Dir", field: "direction", width: 85 },
      { title: "Category", field: "category", width: 130 },
      { title: "Description", field: "description", widthGrow: 2 },
      { title: "", field: "manual_entry_id", width: 42, hozAlign: "center", formatter: () => "🗑",
        cellClick: async (e, c) => { if (!confirm("Delete this manual entry?")) return; await api("/api/manual-entries/" + c.getValue(), { method: "DELETE" }); toast("Deleted"); loaders.manual(); } },
    ],
  });
};

// ---------- Overview / Summary ----------
function makeChart(id, type, labels, data, opts) {
  if (STATE.charts[id]) STATE.charts[id].destroy();
  const ctx = $("#" + id);
  const palette = ["#4f8cff", "#6c5ce7", "#2ecc71", "#ffb020", "#ff6b6b", "#00cec9", "#fd79a8", "#a29bfe", "#55efc4", "#fab1a0", "#74b9ff", "#e17055"];
  STATE.charts[id] = new Chart(ctx, {
    type,
    data: { labels, datasets: [Object.assign({ data, backgroundColor: type === "bar" ? palette[0] : palette, borderWidth: 0 }, opts && opts.dataset || {})] },
    options: Object.assign({ responsive: true, plugins: { legend: { labels: { color: "#8b93a3", boxWidth: 12, font: { size: 11 } }, position: type === "bar" ? "top" : "right" } }, scales: type === "bar" ? { x: { ticks: { color: "#8b93a3" } }, y: { ticks: { color: "#8b93a3" } } } : {} }, opts && opts.options || {}),
  });
}
loaders.overview = async function () {
  const o = await api("/api/overview");
  $("#statusBar").innerHTML =
    `<div class="status-pill ok">✓ ${o.approved} approved</div>
     <div class="status-pill warn">⚠ ${o.unapproved} auto-classified (unverified)</div>
     <div class="status-pill muted">❓ ${o.unknown} unknown</div>`;
  $("#ovCards").innerHTML =
    cardHtml("Real income", fmtINR(o.income_total), "green", `${o.real_transactions} real txns`) +
    cardHtml("Real expense", fmtINR(o.expense_total), "red", "consumption only") +
    cardHtml("Invested", fmtINR(o.investment_total), "amber", "savings, not spend") +
    cardHtml("Family savings", fmtINR(o.family_savings_total), "amber", "to mother/sister") +
    cardHtml("Net (real)", fmtINR(o.net), o.net >= 0 ? "green" : "red", "all money in − out") +
    cardHtml("Self-transfers", fmtINR(o.self_transfer_total), "", `${o.self_transfer_count} excluded`);

  const ch = o.charts || {};
  const ec = (ch.expense_by_category || []).slice(0, 10);
  makeChart("chartExpense", "doughnut", ec.map((x) => x.label), ec.map((x) => x.value));
  const ic = ch.income_by_source || [];
  makeChart("chartIncome", "doughnut", ic.map((x) => x.label.replace(/^[^\w]+/, "")), ic.map((x) => x.value));
  const mf = ch.money_flow || [];
  makeChart("chartFlow", "bar", mf.map((x) => x.label), mf.map((x) => x.value));
  const mo = ch.monthly || [];
  if (STATE.charts.chartMonthly) STATE.charts.chartMonthly.destroy();
  STATE.charts.chartMonthly = new Chart($("#chartMonthly"), {
    type: "line",
    data: { labels: mo.map((x) => x.month), datasets: [
      { label: "Income", data: mo.map((x) => x.income), borderColor: "#2ecc71", backgroundColor: "transparent", tension: 0.3 },
      { label: "Expense", data: mo.map((x) => x.expense), borderColor: "#ff6b6b", backgroundColor: "transparent", tension: 0.3 },
    ] },
    options: { responsive: true, plugins: { legend: { labels: { color: "#8b93a3" } } }, scales: { x: { ticks: { color: "#8b93a3", maxTicksLimit: 12 } }, y: { ticks: { color: "#8b93a3" } } } },
  });

  $("#ovCoverage").innerHTML = (o.overall_gaps && o.overall_gaps.length)
    ? `<span class="pill warn">${o.overall_gaps.length} month(s) missing</span>` + o.overall_gaps.slice(0, 18).map((m) => `<span class="pill warn">${m}</span>`).join("")
    : `<span class="pill ok">Complete — no month gaps across ${o.files} file(s)</span>`;

  const pm = o.paytm_merge || {};
  if (pm.paytm_total) {
    const bysrc = Object.entries(pm.by_source || {}).map(([k, v]) => `<span class="tag-chip">${k}: ${v}</span>`).join(" ");
    $("#ovPaytm").innerHTML =
      `<p class="hint">Paytm sits on top of your bank accounts. ${pm.deduped} payment(s) funded by ICICI/HDFC were already in those statements (matched by UPI Ref No.) and were <b>not</b> double-counted; ${pm.kept} Paytm-only payment(s) were added.</p>
       <div class="person-row"><span>Deduped vs bank (ICICI/HDFC)</span><span class="nums">${pm.deduped}</span></div>
       <div class="person-row"><span>Added (PNB / SBI / credit-card / UPI-Lite)</span><span class="nums">${pm.kept}</span></div>
       <div style="margin-top:8px">${bysrc}</div>
       <p class="hint" style="margin-top:8px">⚠ Paytm history starts 2024, and we have PNB/SBI <i>outflows</i> only (no PNB/SBI account statements / credit-card statements), so "Net (real)" understates income — see docs/income_vs_spend_clarifications.md.</p>`;
  } else {
    $("#ovPaytm").innerHTML = `<span class="muted">No Paytm statements loaded.</span>`;
  }
};

function miniTable(headers, rows) {
  const th = headers.map((h, i) => `<th class="${i > 0 ? "num" : ""}">${h}</th>`).join("");
  const tr = rows.map((r) => "<tr>" + r.map((c, i) => `<td class="${i > 0 ? "num" : ""}">${c}</td>`).join("") + "</tr>").join("");
  return `<table class="mini"><thead><tr>${th}</tr></thead><tbody>${tr || `<tr><td colspan=${headers.length} class="muted">None</td></tr>`}</tbody></table>`;
}

// ---------- init ----------
async function init() {
  STATE.meta = await api("/api/meta");
  $("#manualCat").innerHTML = `<option value="">(none)</option>` + STATE.meta.categories.map((c) => `<option>${c}</option>`).join("");
  $("#largeThreshold").value = STATE.meta.threshold;

  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showPage(t.dataset.page)));
  $("#refreshBtn").addEventListener("click", async () => { await api("/api/refresh", { method: "POST" }); toast("Re-read statements"); showPage(STATE.active); });

  ["ledgerSearch", "ledgerBank", "ledgerDir", "ledgerCat"].forEach((id) => $("#" + id).addEventListener("input", applyLedgerFilter));
  $("#ledgerHideSelf").addEventListener("change", applyLedgerFilter);
  $("#ledgerPendingOnly").addEventListener("change", applyLedgerFilter);
  $("#sRun").addEventListener("click", runSearch);
  // Enter key in any search field triggers the search.
  ["sQ", "sMin", "sMax", "sFrom", "sTo"].forEach((id) =>
    $("#" + id).addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); }));
  $("#largeApply").addEventListener("click", loaders.large);
  $("#largeSave").addEventListener("click", async () => { await api("/api/threshold", { method: "POST", body: JSON.stringify({ value: parseFloat($("#largeThreshold").value) }) }); toast("Threshold saved"); loaders.large(); });

  $("#manualForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target).entries());
    body.amount = parseFloat(body.amount || "0");
    try { await api("/api/manual-entries", { method: "POST", body: JSON.stringify(body) }); toast("Entry added"); e.target.reset(); loaders.manual(); }
    catch (err) { toast("Failed: " + err.message, true); }
  });

  showPage("ledger");
}
init().catch((e) => toast("Init failed: " + e.message, true));
