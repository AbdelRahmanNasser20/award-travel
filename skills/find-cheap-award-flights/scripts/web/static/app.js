/* Award Flights — frontend logic (vanilla JS). */
const AIRLINES = ["united", "american", "delta", "southwest", "jetblue", "frontier"];
const fmtMiles = (m) => (m == null ? "—" : Number(m).toLocaleString());
const fmtTaxes = (t) => (t == null ? "" : "$" + Number(t).toLocaleString());
const dealClass = (d) => (d === "✅" ? "deal-good" : d === "⚠️" ? "deal-warn" : d === "❌" ? "deal-bad" : "");

const App = {
  mode: "live",
  view: "list",
  results: [],
  ctx: { origin: "", dest: "", cabin: "economy" },

  init() {
    // default dates: a 6-day range starting ~3 weeks out
    const s = new Date(Date.now() + 21 * 864e5), e = new Date(Date.now() + 27 * 864e5);
    document.querySelector('[name=start]').value = s.toISOString().slice(0, 10);
    document.querySelector('[name=end]').value = e.toISOString().slice(0, 10);

    // airline pills
    const box = document.getElementById("airlines");
    AIRLINES.forEach((a) => {
      const el = document.createElement("span");
      el.className = "pill on"; el.dataset.air = a; el.textContent = a;
      el.onclick = () => el.classList.toggle("on");
      box.appendChild(el);
    });

    // chips fill inputs
    document.querySelectorAll(".chips").forEach((c) => {
      const target = c.dataset.target;
      c.querySelectorAll("span").forEach((s2) => s2.onclick = () => {
        document.querySelector(`[name=${target}]`).value = s2.textContent;
      });
    });

    // segmented toggles
    this.seg("mode", (v) => (this.mode = v));
    this.seg("view", (v) => { this.view = v; this.renderResults(); });

    document.getElementById("searchForm").onsubmit = (ev) => { ev.preventDefault(); this.search(); };
    document.getElementById("reloadAll").onclick = () => this.reload("all");
    this.loadFavorites();
  },

  seg(id, cb) {
    const root = document.getElementById(id);
    root.querySelectorAll("button").forEach((b) => b.onclick = () => {
      root.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      cb(b.dataset.mode || b.dataset.view);
    });
  },

  selectedAirlines() {
    return [...document.querySelectorAll("#airlines .pill.on")].map((p) => p.dataset.air);
  },

  async search() {
    const f = document.getElementById("searchForm");
    const q = new URLSearchParams({
      from: f.from.value, to: f.to.value, start: f.start.value, end: f.end.value,
      cabin: f.cabin.value, max_miles: f.max_miles.value || "0",
      airlines: this.selectedAirlines().join(","), mode: this.mode,
    });
    this.ctx = { origin: f.from.value, dest: f.to.value, cabin: f.cabin.value };
    const hint = document.getElementById("searchHint");
    hint.innerHTML = `<span class="spinner"></span> Searching ${this.mode === "live" ? "live airline sites" : "cached SkyView"}… (live runs one browser at a time)`;
    document.getElementById("results").classList.remove("hidden");
    document.getElementById("resultsBody").innerHTML = "";
    try {
      const r = await fetch("/api/search?" + q.toString());
      const data = await r.json();
      if (data.error) throw new Error(data.error);
      this.results = data.rows || [];
      hint.textContent = "";
      this.renderResults();
    } catch (e) {
      hint.innerHTML = `<span class="deal-bad">Search failed: ${e.message}</span>`;
    }
  },

  renderResults() {
    const body = document.getElementById("resultsBody");
    document.getElementById("resultCount").textContent = this.results.length ? `· ${this.results.length}` : "";
    if (!this.results.length) { body.innerHTML = `<p class="text-slate-400 text-sm">No award space found for those parameters.</p>`; return; }
    body.innerHTML = this.view === "table" ? this.tableHTML() : this.listHTML();
    body.querySelectorAll("[data-fav]").forEach((b) => b.onclick = () => this.favorite(+b.dataset.fav, b));
  },

  listHTML() {
    return `<div class="grid grid-cols-1 md:grid-cols-2 gap-3">` + this.results.map((r, i) => `
      <div class="card fade-in flex items-center justify-between gap-3">
        <div>
          <div class="text-xs font-semibold uppercase tracking-wide text-slate-400">${r.program}</div>
          <div class="font-bold">${r.date} · ${this.ctx.origin}→${this.ctx.dest}
            ${r.FlightNumbers ? `<span class="text-slate-400 font-medium">· ${r.FlightNumbers}</span>` : ""}</div>
          <div class="text-sm text-slate-500">
            ${r.DepartTime ? r.DepartTime + (r.ArriveTime ? "→" + r.ArriveTime : "") + " · " : ""}
            ${r.direct ? "Nonstop" : "1+ stop"}</div>
        </div>
        <div class="text-right">
          <div class="text-lg font-extrabold">${fmtMiles(r.miles)} <span class="text-xs font-medium text-slate-400">mi</span></div>
          <div class="text-xs text-slate-500">${fmtTaxes(r.taxes)} <span class="${dealClass(r.deal)}">${r.deal || ""}</span></div>
          <button data-fav="${i}" class="btn-ghost mt-1 text-xs">★ Save</button>
        </div>
      </div>`).join("") + `</div>`;
  },

  tableHTML() {
    return `<div class="card overflow-x-auto"><table class="results"><thead><tr>
      <th>Date</th><th>Program</th><th>Flight</th><th>Depart</th><th>Stops</th><th>Miles</th><th>Taxes</th><th>Deal</th><th></th>
      </tr></thead><tbody>` + this.results.map((r, i) => `<tr class="fade-in">
        <td>${r.date}</td><td>${r.program}</td><td>${r.FlightNumbers || "—"}</td>
        <td>${r.DepartTime || "—"}</td><td>${r.direct ? "Nonstop" : "1+"}</td>
        <td class="font-bold">${fmtMiles(r.miles)}</td><td>${fmtTaxes(r.taxes)}</td>
        <td class="${dealClass(r.deal)}">${r.deal || ""}</td>
        <td><button data-fav="${i}" class="btn-ghost text-xs">★</button></td>
      </tr>`).join("") + `</tbody></table></div>`;
  },

  async favorite(i, btn) {
    const row = this.results[i];
    if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>`; }
    try {
      await fetch("/api/favorites", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ row, origin: this.ctx.origin, dest: this.ctx.dest, cabin: this.ctx.cabin }),
      });
      if (btn) btn.textContent = "★ Saved";
      this.loadFavorites();
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = "★ Save"; }
    }
  },

  async loadFavorites() {
    const r = await fetch("/api/favorites");
    const data = await r.json();
    const favs = data.favorites || [];
    document.getElementById("favCount").textContent = favs.length ? `· ${favs.length}` : "";
    const body = document.getElementById("favBody");
    if (!favs.length) { body.innerHTML = `<p class="text-slate-400 text-sm">No favorites yet — save a result above.</p>`; return; }
    body.innerHTML = favs.map((f) => {
      const fl = f.flight || {};
      return `<div class="card fade-in" id="fav-${f.fid}">
        <div class="flex items-center justify-between">
          <div class="text-xs font-semibold uppercase tracking-wide text-slate-400">${fl.program || "?"}</div>
          <button class="btn-ghost text-xs" onclick="App.reload('${f.fid}')">↻</button>
        </div>
        <div class="font-bold mt-0.5">${fl.date || "?"} · ${f.origin || ""}→${f.dest || ""}
          ${fl.FlightNumbers ? `<span class="text-slate-400 font-medium">· ${fl.FlightNumbers}</span>` : ""}</div>
        <div class="mt-2 flex items-end justify-between">
          <div class="text-2xl font-extrabold" data-miles>${fmtMiles(fl.miles)} <span class="text-xs font-medium text-slate-400">mi</span></div>
          <div class="text-xs text-slate-400" data-status>checked ${(f.checked_at || "").replace("T", " ")}</div>
        </div></div>`;
    }).join("");
  },

  reload(which) {
    const ids = which === "all" ? "all" : [which];
    // open the SSE stream first so we don't miss early events
    const es = new EventSource("/api/reload/stream");
    es.onmessage = (ev) => {
      const e = JSON.parse(ev.data);
      if (e.status === "complete") { es.close(); this.loadFavorites(); return; }
      const card = document.getElementById("fav-" + e.fid);
      if (!card) return;
      const status = card.querySelector("[data-status]");
      const miles = card.querySelector("[data-miles]");
      if (e.status === "loading") status.innerHTML = `<span class="spinner"></span> reloading…`;
      else if (e.status === "error") status.innerHTML = `<span class="deal-bad">error</span>`;
      else if (e.status === "done") {
        miles.innerHTML = `${fmtMiles(e.miles)} <span class="text-xs font-medium text-slate-400">mi</span>`;
        const d = e.delta;
        status.innerHTML = d == null ? "updated"
          : d === 0 ? `<span class="text-slate-400">no change</span>`
          : `<span class="${d < 0 ? "deal-good" : "deal-bad"}">${d > 0 ? "+" : ""}${fmtMiles(d)}</span>`;
      }
    };
    fetch("/api/reload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }) });
  },
};

window.App = App;
document.addEventListener("DOMContentLoaded", () => App.init());
