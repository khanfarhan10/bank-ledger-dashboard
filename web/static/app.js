/* Bank Ledger Dashboard — frontend logic.
 * Talks to /api/*, renders metric cards + Tabulator grids, and wires the
 * right-click context menu + inline editing that make this a real dashboard
 * rather than a static table. */

"use strict";

// ---------- tiny helpers ----------
const $ = (sel) => document.querySelector(sel);
const elFrom = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; };

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  if (!res.ok) { const t = await res.text(); throw new Error(t || res.statusText); }
  return res.status === 204 ? null : res.json();
}

function fmtINR(n) {
  if (n === null || n === undefined || isNaN(n)) return "—";
  const neg = n < 0;
  n = Math.abs(Math.round(n));
  let s = String(n);
  let last3 = s.slice(-3);
  let rest = s.slice(0, -3);
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
  TOAST_T = setTimeout(() => { t.className = "toast"; }, 2600);
}

// ---------- global state ----------
const STATE = { meta: { categories: [], review_statuses: [], persons: [], threshold: 0 }, tables: {}, pageLoaded: {} };

// ---------- decision actions ----------
async function saveDecision(txnId, fields) {
  try {
    await api("/api/decision", { method: "POST", body: JSON.stringify(Object.assign({ transaction_id: txnId }, fields)) });
    toast("Saved");
    reloadActive();
  } catch (e) { toast("Save failed: " + e.message, true); }
}
async function resetDecision(txnId) {
  try {
    await api("/api/decision/reset", { method: "POST", body: JSON.stringify({ transaction_id: txnId }) });
    toast("Reset to auto");
    reloadActive();
  } catch (e) { toast("Reset failed: " + e.message, true); }
}

// ---------- right-click context menu ----------
function rowContextMenu() {
  const cats = STATE.meta.categories || [];
  const statuses = STATE.meta.review_statuses || [];
  const catMenu = cats.map((c) => ({ label: c, action: (e, row) => saveDecision(row.getData().transaction_id, { category: c }) }));
  const statusMenu = statuses.map((s) => ({ label: s, action: (e, row) => saveDecision(row.getData().transaction_id, { manual_review_status: s }) }));

  return [
    { label: "🏷  Reclassify", menu: catMenu },
    { label: "🔁  Mark as self-transfer", action: (e, row) => saveDecision(row.getData().transaction_id, { category: "self_transfer" }) },
    { separator: true },
    { label: "👤  Related to Benazir", action: (e, row) => saveDecision(row.getData().transaction_id, { manual_person: "benazir", manual_review_status: "confirmed_related" }) },
    { label: "👤  Related to Nazrana", action: (e, row) => saveDecision(row.getData().transaction_id, { manual_person: "nazrana", manual_review_status: "confirmed_related" }) },
    { label: "👥  Related to both", action: (e, row) => saveDecision(row.getData().transaction_id, { manual_person: "both", manual_review_status: "confirmed_related" }) },
    { separator: true },
    { label: "📋  Review status", menu: statusMenu },
    { label: "📝  Add / edit note…", action: (e, row) => {
        const d = row.getData();
        const note = window.prompt("Note for this transaction:", d.manual_comment || "");
        if (note !== null) saveDecision(d.transaction_id, { manual_comment: note });
      } },
    { label: "🚩  Add / edit flags…", action: (e, row) => {
        const d = row.getData();
        const f = window.prompt("Flags (comma-separated):", d.manual_flags || "");
        if (f !== null) saveDecision(d.transaction_id, { manual_flags: f });
      } },
    { separator: true },
    { label: "↺  Reset to auto", action: (e, row) => resetDecision(row.getData().transaction_id) },
  ];
}

// ---------- column definitions ----------
function amountFormatter(cell) {
  const d = cell.getRow().getData();
  const v = cell.getValue();
  const span = document.createElement("span");
  span.textContent = fmtINR(v);
  span.className = d.direction === "RECEIVED" ? "cell-pos" : (d.direction === "PAID_OUT" ? "cell-neg" : "");
  return span;
}
function tagsFormatter(cell) {
  const v = cell.getValue();
  if (!v) return "";
  return v.split(",").filter(Boolean).map((t) => `<span class="tag-chip">${t}</span>`).join(" ");
}

function ledgerColumns(editable) {
  const catEditor = { editor: "list", editorParams: { values: STATE.meta.categories, autocomplete: true, freetext: true } };
  const statusEditor = { editor: "list", editorParams: { values: STATE.meta.review_statuses } };
  const cols = [
    { title: "Date", field: "transaction_date", width: 100, headerFilter: "input" },
    { title: "Bank", field: "source_bank", width: 70 },
    { title: "Description", field: "description", widthGrow: 4, minWidth: 260, headerFilter: "input", tooltip: (e, cell) => cell.getRow().getData().raw_description || "" },
    { title: "Amount", field: "amount", width: 115, hozAlign: "right", formatter: amountFormatter, sorter: "number" },
    { title: "Dir", field: "direction", width: 95 },
    Object.assign({ title: "Category", field: "category", width: 140, headerFilter: "input" }, editable ? catEditor : {}),
    { title: "Tags", field: "tags", width: 150, formatter: tagsFormatter },
    Object.assign({ title: "Review", field: "manual_review_status", width: 120 }, editable ? statusEditor : {}),
    Object.assign({ title: "Note", field: "manual_comment", widthGrow: 2, minWidth: 140 }, editable ? { editor: "input" } : {}),
  ];
  return cols;
}

function rowFormatter(row) {
  const d = row.getData();
  const el = row.getElement();
  el.classList.toggle("row-self", !!d.is_self_transfer);
  el.classList.toggle("row-dup", !!d.is_duplicate);
  el.classList.toggle("row-manual", !!d.is_manual_entry);
}

function makeLedgerGrid(hostId, rows, editable, height) {
  const table = new Tabulator("#" + hostId, {
    data: rows,
    columns: ledgerColumns(editable),
    layout: "fitColumns",
    height: height || 620,
    placeholder: "No transactions",
    rowFormatter,
    rowContextMenu: rowContextMenu(),
    movableColumns: true,
    index: "transaction_id",
  });
  if (editable) {
    table.on("cellEdited", (cell) => {
      const f = cell.getField();
      const id = cell.getRow().getData().transaction_id;
      const map = { category: "category", manual_review_status: "manual_review_status", manual_comment: "manual_comment" };
      if (map[f]) saveDecision(id, { [map[f]]: cell.getValue() });
    });
  }
  return table;
}

// ---------- navigation ----------
function showPage(page) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + page));
  STATE.active = page;
  loaders[page] && loaders[page]();
}
function reloadActive() {
  if (STATE.active && loaders[STATE.active]) { STATE.pageLoaded[STATE.active] = false; loaders[STATE.active](); }
  // Overview totals depend on edits too — invalidate it.
  STATE.pageLoaded.overview = false;
}

// ---------- page loaders ----------
const loaders = {};

loaders.overview = async function () {
  const o = await api("/api/overview");
  const card = (label, value, cls, foot) =>
    `<div class="card"><div class="label">${label}</div><div class="value ${cls || ""}">${value}</div>${foot ? `<div class="foot">${foot}</div>` : ""}</div>`;
  $("#ovCards").innerHTML = [
    card("Real income", fmtINR(o.income_total), "green", `${o.transactions} txns • ${o.real_transactions} real`),
    card("Real expense", fmtINR(o.expense_total), "red", "excludes investments & self-transfers"),
    card("Invested / saved", fmtINR(o.investment_total), "amber", "not counted as expense"),
    card("Net (real)", fmtINR(o.net), o.net >= 0 ? "green" : "red", `${o.date_from || "?"} → ${o.date_to || "?"}`),
    card("Self-transfers excluded", fmtINR(o.self_transfer_total), "", `${o.self_transfer_count} internal moves`),
    card("Duplicates excluded", fmtINR(o.duplicate_total), "", `${o.duplicate_count} rows`),
  ].join("");

  const cats = (o.categories || []).filter((c) => c.category !== "self_transfer").slice(0, 12);
  const max = Math.max(1, ...cats.map((c) => c.paid_out + c.received));
  $("#ovCategories").innerHTML = cats.map((c) => {
    const total = c.paid_out + c.received;
    const pct = Math.round((total / max) * 100);
    return `<div class="bar-row"><div class="name">${c.category}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <div class="amt">${fmtINR(total)}</div></div>`;
  }).join("");

  const pr = (name, t) => `<div class="person-row"><span>${name}</span>
    <span class="nums">paid <b class="neg">${fmtINR(t.paid)}</b> • recv <b class="pos">${fmtINR(t.received)}</b> • net ${t.net >= 0 ? '<b class="pos">' : '<b class="neg">'}${fmtINR(t.net)}</b></span></div>`;
  $("#ovPeople").innerHTML = pr("Benazir Rahaman", o.benazir) + pr("Nazrana / Najrana", o.nazrana);

  if (o.overall_gaps && o.overall_gaps.length) {
    $("#ovCoverage").innerHTML = `<span class="pill warn">${o.overall_gaps.length} month(s) missing</span>` +
      o.overall_gaps.slice(0, 18).map((m) => `<span class="pill warn">${m}</span>`).join("");
  } else {
    $("#ovCoverage").innerHTML = `<span class="pill ok">Complete — no month gaps across ${o.files} file(s)</span>`;
  }
  STATE.pageLoaded.overview = true;
};

loaders.ledger = async function () {
  if (STATE.pageLoaded.ledger && STATE.tables.ledger) return;
  const data = await api("/api/ledger");
  if (STATE.tables.ledger) STATE.tables.ledger.destroy();
  STATE.tables.ledger = makeLedgerGrid("ledgerGrid", data.rows, true);
  // bank filter options
  const banks = Array.from(new Set(data.rows.map((r) => r.source_bank).filter(Boolean))).sort();
  $("#ledgerBank").innerHTML = `<option value="">All banks</option>` + banks.map((b) => `<option>${b}</option>`).join("");
  $("#ledgerCat").innerHTML = `<option value="">All categories</option>` + STATE.meta.categories.map((c) => `<option>${c}</option>`).join("");
  applyLedgerFilter();
  STATE.pageLoaded.ledger = true;
};

function applyLedgerFilter() {
  const t = STATE.tables.ledger; if (!t) return;
  const q = $("#ledgerSearch").value.toLowerCase();
  const bank = $("#ledgerBank").value;
  const dir = $("#ledgerDir").value;
  const cat = $("#ledgerCat").value;
  const hideSelf = $("#ledgerHideSelf").checked;
  t.setFilter((row) => {
    if (bank && row.source_bank !== bank) return false;
    if (dir && row.direction !== dir) return false;
    if (cat && row.category !== cat) return false;
    if (hideSelf && row.is_self_transfer) return false;
    if (q) {
      const hay = ((row.description || "") + " " + (row.raw_description || "")).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

loaders.persons = async function () {
  const p = await api("/api/persons");
  const card = (label, t) => `<div class="card"><div class="label">${label}</div>
    <div class="value">${fmtINR(t.net)}</div>
    <div class="foot">paid ${fmtINR(t.paid)} • received ${fmtINR(t.received)} • ${t.count} txns</div></div>`;
  $("#personCards").innerHTML = card("Benazir — net", p.benazir) + card("Nazrana — net", p.nazrana);

  if (STATE.tables.persons) STATE.tables.persons.destroy();
  STATE.tables.persons = makeLedgerGrid("personsGrid", p.rows, true, 420);

  if (STATE.tables.cp) STATE.tables.cp.destroy();
  STATE.tables.cp = new Tabulator("#counterpartiesGrid", {
    data: p.counterparties,
    layout: "fitColumns",
    height: 340,
    placeholder: "No counterparties",
    columns: [
      { title: "Counterparty", field: "counterparty", widthGrow: 3 },
      { title: "Txns", field: "transactions", width: 80, hozAlign: "right" },
      { title: "Paid", field: "paid_out", width: 130, hozAlign: "right", formatter: (c) => fmtINR(c.getValue()) },
      { title: "Received", field: "received", width: 130, hozAlign: "right", formatter: (c) => fmtINR(c.getValue()) },
      { title: "Net", field: "net", width: 130, hozAlign: "right", formatter: (c) => { const s = document.createElement("span"); s.textContent = fmtINR(c.getValue()); s.className = c.getValue() >= 0 ? "cell-pos" : "cell-neg"; return s; } },
    ],
  });
};

loaders.investments = async function () {
  const inv = await api("/api/investments");
  const card = (l, v, foot) => `<div class="card"><div class="label">${l}</div><div class="value amber">${v}</div>${foot ? `<div class="foot">${foot}</div>` : ""}</div>`;
  $("#invCards").innerHTML =
    card("Total invested", fmtINR(inv.total), "money put into savings/investments") +
    card("80C tax-saving", fmtINR(inv.tax_saving_80c_total || 0), `${inv.tax_saving_80c_count || 0} transactions (PPF, LIC, NPS, ELSS…)`) +
    card("Instruments", (inv.by_instrument || []).length, "distinct investment types");

  const rows = (inv.by_instrument || []).map((i) =>
    `<tr><td>${i.instrument}</td><td class="num">${i.transactions}</td><td class="num">${fmtINR(i.total)}</td><td>${i.first || ""} → ${i.last || ""}</td></tr>`).join("");
  $("#invByInstrument").innerHTML = `<table class="mini"><thead><tr><th>Instrument</th><th class="num">Txns</th><th class="num">Total</th><th>Period</th></tr></thead><tbody>${rows || '<tr><td colspan=4 class="muted">None detected</td></tr>'}</tbody></table>`;

  if (STATE.tables.inv) STATE.tables.inv.destroy();
  STATE.tables.inv = makeLedgerGrid("invGrid", inv.rows, true, 340);
};

loaders.income = async function () {
  const inc = await api("/api/income");
  const card = (l, v, foot) => `<div class="card"><div class="label">${l}</div><div class="value green">${v}</div>${foot ? `<div class="foot">${foot}</div>` : ""}</div>`;
  $("#incCards").innerHTML = card("Total income", fmtINR(inc.total), "salary, refunds, interest — real money in");

  const rows = (inc.by_source || []).map((s) =>
    `<tr><td>${s.source}</td><td class="num">${s.payments}</td><td class="num">${fmtINR(s.total)}</td><td>${s.first || ""} → ${s.last || ""}</td></tr>`).join("");
  $("#incBySource").innerHTML = `<table class="mini"><thead><tr><th>Source</th><th class="num">Payments</th><th class="num">Total</th><th>Period</th></tr></thead><tbody>${rows || '<tr><td colspan=4 class="muted">None</td></tr>'}</tbody></table>`;

  if (STATE.tables.inc) STATE.tables.inc.destroy();
  STATE.tables.inc = makeLedgerGrid("incGrid", inc.rows, true, 340);
};

loaders.large = async function () {
  const thr = $("#largeThreshold").value || STATE.meta.threshold;
  const data = await api("/api/large?threshold=" + encodeURIComponent(thr));
  $("#largeThreshold").value = data.threshold;
  $("#largeCount").textContent = `${data.count} transaction(s) ≥ ${fmtINR(data.threshold)}`;
  if (STATE.tables.large) STATE.tables.large.destroy();
  STATE.tables.large = makeLedgerGrid("largeGrid", data.rows, true);
};

loaders.manual = async function () {
  const data = await api("/api/manual-entries");
  if (STATE.tables.manual) STATE.tables.manual.destroy();
  STATE.tables.manual = new Tabulator("#manualGrid", {
    data: data.rows,
    layout: "fitColumns",
    height: 340,
    placeholder: "No manual entries yet",
    columns: [
      { title: "Date", field: "entry_date", width: 105 },
      { title: "Person", field: "person", width: 110 },
      { title: "Amount", field: "amount", width: 110, hozAlign: "right", formatter: (c) => fmtINR(c.getValue()) },
      { title: "Dir", field: "direction", width: 90 },
      { title: "Category", field: "category", width: 130 },
      { title: "Description", field: "description", widthGrow: 2 },
      { title: "", field: "manual_entry_id", width: 44, hozAlign: "center", formatter: () => "🗑",
        cellClick: async (e, cell) => {
          if (!confirm("Delete this manual entry?")) return;
          await api("/api/manual-entries/" + cell.getValue(), { method: "DELETE" });
          toast("Deleted"); loaders.manual();
        } },
    ],
  });
};

// ---------- init ----------
async function init() {
  STATE.meta = await api("/api/meta");
  // populate category selects
  $("#manualCat").innerHTML = `<option value="">(none)</option>` + STATE.meta.categories.map((c) => `<option>${c}</option>`).join("");
  $("#largeThreshold").value = STATE.meta.threshold;

  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showPage(t.dataset.page)));
  $("#refreshBtn").addEventListener("click", async () => { await api("/api/refresh", { method: "POST" }); STATE.pageLoaded = {}; toast("Re-read statements"); showPage(STATE.active || "overview"); });

  ["ledgerSearch", "ledgerBank", "ledgerDir", "ledgerCat"].forEach((id) => $("#" + id).addEventListener("input", applyLedgerFilter));
  $("#ledgerHideSelf").addEventListener("change", applyLedgerFilter);

  $("#largeApply").addEventListener("click", loaders.large);
  $("#largeSave").addEventListener("click", async () => {
    await api("/api/threshold", { method: "POST", body: JSON.stringify({ value: parseFloat($("#largeThreshold").value) }) });
    toast("Threshold saved"); STATE.pageLoaded = {}; loaders.large();
  });

  $("#manualForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = Object.fromEntries(fd.entries());
    body.amount = parseFloat(body.amount || "0");
    try { await api("/api/manual-entries", { method: "POST", body: JSON.stringify(body) }); toast("Entry added"); e.target.reset(); loaders.manual(); }
    catch (err) { toast("Failed: " + err.message, true); }
  });

  showPage("overview");
}

init().catch((e) => toast("Init failed: " + e.message, true));
