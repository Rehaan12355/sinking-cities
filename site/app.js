/* Sinking Cities: static front end. All numbers come from site/data/, built by pipeline/. */
(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n) => Math.round(n).toLocaleString("en-US");
  const NEVER = 255;

  // Which city: ?city=<id> in the address, otherwise the first one built.
  const cities = await fetch("data/cities.json").then((r) => r.json());
  const asked = new URLSearchParams(location.search).get("city");
  const cid = cities.some((c) => c.id === asked) ? asked : cities[0].id;
  const D = `data/${cid}/`;
  const [city, tracts, series] = await Promise.all([
    fetch(D + "city.json").then((r) => r.json()),
    fetch(D + "tracts.geojson").then((r) => r.json()),
    fetch(D + "series.json").then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  const hasSinking = city.status.sinking;
  const N = city.nisar && city.nisar.ok && city.nisar.coverage ? city.nisar : null;   // NISAR coverage view, when built
  const pct = (x) => Math.round(x * 100) + "%";
  // Tracts without a nearby place name read better with their city in front.
  for (const f of tracts.features) {
    const p = f.properties;
    if (p.name.startsWith("Tract ")) p.name = `${p.city.replace(/ area$/, "")} tract ${p.tract}`;
  }
  const byId = new Map(tracts.features.map((f) => [f.properties.id, f.properties]));
  const ICON = {
    play: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2.5v11l9.5-5.5z" fill="currentColor"/></svg>',
    pause: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z" fill="currentColor"/></svg>',
  };
  const base = city.base_year;
  const floodDays = Math.round(city.water.htf_recent_mean_days);

  const state = { view: "flood", yearIdx: 0, monthIdx: series ? series.dates.length - 1 : 0, withSinking: hasSinking, selected: null, playing: null };
  document.title = `Sinking Cities: ${city.name}`;
  if (cities.length > 1) {
    $("place").innerHTML = `<label class="sr-only" for="city-pick">City</label><select id="city-pick">${cities.map((c) => `<option value="${c.id}"${c.id === cid ? " selected" : ""}>${c.name}</option>`).join("")}</select>`;
    $("city-pick").onchange = (e) => (location.search = "?city=" + e.target.value);
  } else {
    $("place").textContent = city.name;
  }
  document.querySelectorAll('a[href="methods.html"]').forEach((a) => (a.href = "methods.html?city=" + cid));
  $("with-sinking").checked = hasSinking;
  if (!hasSinking) {
    $("sink-switch").hidden = true;
    $("notice").hidden = false;
    $("notice").textContent =
      "Radar sinking measurements are not loaded yet, so this map shows sea level rise alone. Flood years will move earlier once sinking is added.";
  }

  /* ---------- map ---------- */
  const map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/dark",
    bounds: [city.bounds.slice(0, 2), city.bounds.slice(2)],
    fitBoundsOptions: { padding: 20 },
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  await new Promise((res) => map.on("load", res));
  // Tint the dark base map: graphite land, near-black water, quiet labels, so the data is the only colour.
  for (const l of map.getStyle().layers) {
    try {
      if (l.type === "background") map.setPaintProperty(l.id, "background-color", "#1c1f23");
      else if (l.type === "fill" && /water/.test(l.id)) map.setPaintProperty(l.id, "fill-color", "#0f1215");
      else if (l.type === "fill" && /landuse|landcover|park|building|aeroway|pier/.test(l.id)) map.setPaintProperty(l.id, "fill-color", "#202428");
      else if (l.type === "line" && /water/.test(l.id)) map.setPaintProperty(l.id, "line-color", "#0f1215");
      // Roads sit above the data in this style: draw them as faint light lines instead of heavy black ones.
      else if (l.type === "line" && /road|highway|motorway|bridge|tunnel|rail|aeroway/.test(l.id)) map.setPaintProperty(l.id, "line-color", /casing|subtle|minor|path/.test(l.id) ? "rgba(255,255,255,0)" : "rgba(255,255,255,0.08)");
      else if (l.type === "line" && /boundary|admin/.test(l.id)) map.setPaintProperty(l.id, "line-color", "rgba(255,255,255,0.12)");
      else if (l.type === "symbol") {
        map.setPaintProperty(l.id, "text-color", /water/.test(l.id) ? "#5d6a73" : "#b9c0c6");
        map.setPaintProperty(l.id, "text-halo-color", "#16181b");
      }
    } catch (e) { /* a layer without that property: leave it */ }
  }

  // Flood picture: each pixel stores the first year it floods (R with sinking, G sea level only).
  const img = new Image();
  img.src = D + "flood.png";
  await img.decode();
  const cv = document.createElement("canvas");
  cv.width = img.width;
  cv.height = img.height;
  const ctx = cv.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  const srcPx = ctx.getImageData(0, 0, cv.width, cv.height).data;
  const out = ctx.createImageData(cv.width, cv.height);
  const out32 = new Uint32Array(out.data.buffer);
  const [w, s, e, n] = city.flood_bounds;
  const corners = [[w, n], [e, n], [e, s], [w, s]];
  // ABGR little-endian: long-flooded ground is deep blue, newly flooded ground brighter.
  const OLD = (235 << 24) | (214 << 16) | (143 << 8) | 43;
  const NEW = (245 << 24) | (245 << 16) | (224 << 8) | 127;

  function drawFlood() {
    const ch = state.withSinking ? 0 : 1;
    const idx = state.yearIdx;
    for (let i = 0, p = ch; i < out32.length; i++, p += 4) {
      const v = srcPx[p];
      out32[i] = v === NEVER || v > idx ? 0 : v > 0 && idx - v < 5 ? NEW : OLD;
    }
    ctx.putImageData(out, 0, 0);
    const src = map.getSource("flood");
    if (src) { src.play(); src.pause(); }
  }

  const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
  map.addSource("tracts", { type: "geojson", data: tracts, promoteId: "id" });
  if (hasSinking) {
    map.addSource("sinking-img", { type: "image", url: D + "sinking.png", coordinates: corners });
    map.addLayer({ id: "sinking-img", type: "raster", source: "sinking-img", paint: { "raster-opacity": 0.8, "raster-resampling": "nearest" }, layout: { visibility: "none" } }, firstLabel);
  }
  if (N) {
    const [nw, ns, ne, nn] = N.coverage_bounds;
    map.addSource("nisar-img", { type: "image", url: D + "nisar.png", coordinates: [[nw, nn], [ne, nn], [ne, ns], [nw, ns]] });
    map.addLayer({ id: "nisar-img", type: "raster", source: "nisar-img", paint: { "raster-opacity": 0.9, "raster-resampling": "nearest" }, layout: { visibility: "none" } }, firstLabel);
    $("tab-nisar").hidden = false;
  }
  map.addSource("flood", { type: "canvas", canvas: cv, coordinates: corners, animate: false });
  map.addLayer({ id: "flood", type: "raster", source: "flood", paint: { "raster-opacity": 0.95, "raster-resampling": "nearest", "raster-fade-duration": 0 } }, firstLabel);
  map.addLayer({ id: "tract-fill", type: "fill", source: "tracts", paint: { "fill-color": "#000", "fill-opacity": 0 } }, firstLabel);
  map.addLayer({ id: "tract-line", type: "line", source: "tracts", paint: { "line-color": "#ffffff", "line-opacity": 0.14, "line-width": 0.6 } }, firstLabel);
  // Neighborhoods past the flooding share: a see-through red wash with a soft edge.
  map.addLayer({ id: "tract-hit", type: "fill", source: "tracts", paint: { "fill-color": "#ff6b57", "fill-opacity": 0.22 }, filter: ["==", "id", ""] }, "flood");
  map.addLayer({ id: "tract-hit-edge", type: "line", source: "tracts", paint: { "line-color": "#ff6b57", "line-opacity": 0.45, "line-width": 0.8 }, filter: ["==", "id", ""] }, firstLabel);
  map.addLayer({ id: "tract-hover", type: "line", source: "tracts", paint: { "line-color": "#f1f2f0", "line-width": 1.5, "line-opacity": 0.8 }, filter: ["==", "id", ""] });
  map.addLayer({ id: "tract-selected", type: "line", source: "tracts", paint: { "line-color": "#f1f2f0", "line-width": 3 }, filter: ["==", "id", ""] });

  const rampExpr = (input, k) => ["interpolate", ["linear"], input, ...city.ramp.flatMap(([v, c]) => [v * k, c])];

  /* ---------- rendering ---------- */
  function fyKey() { return state.withSinking ? "fy_mid" : "fy_ocean"; }
  function modeKey() { return state.withSinking ? "sinking" : "ocean"; }

  function renderMap() {
    const flood = state.view === "flood";
    map.setLayoutProperty("flood", "visibility", flood ? "visible" : "none");
    map.setLayoutProperty("tract-hit", "visibility", flood ? "visible" : "none");
    map.setLayoutProperty("tract-hit-edge", "visibility", flood ? "visible" : "none");
    if (hasSinking) map.setLayoutProperty("sinking-img", "visibility", "none");
    if (N) map.setLayoutProperty("nisar-img", "visibility", state.view === "nisar" ? "visible" : "none");
    if (state.view === "nisar") {
      map.setPaintProperty("tract-fill", "fill-opacity", 0);
    } else if (flood) {
      drawFlood();
      map.setPaintProperty("tract-fill", "fill-opacity", 0);
      const hit = ["<=", ["coalesce", ["get", fyKey()], 9999], base + state.yearIdx];
      map.setFilter("tract-hit", hit);
      map.setFilter("tract-hit-edge", hit);
    } else if (hasSinking) {
      const atEnd = !series || state.monthIdx === series.dates.length - 1;
      if (atEnd) {
        map.setPaintProperty("tract-fill", "fill-color", ["case", ["has", "rate"], rampExpr(["get", "rate"], 1), "#3a3f45"]);
      } else {
        for (const f of tracts.features) {
          const s = series.tracts[f.properties.id];
          map.setFeatureState({ source: "tracts", id: f.properties.id }, { sunk: s ? -s[state.monthIdx] : null });
        }
        // Colours reach the same shade as the yearly-rate map when the full record has played.
        map.setPaintProperty("tract-fill", "fill-color", ["case", ["!=", ["feature-state", "sunk"], null], rampExpr(["feature-state", "sunk"], series.span_years), "#3a3f45"]);
      }
      map.setPaintProperty("tract-fill", "fill-opacity", 0.78);
    } else {
      map.setPaintProperty("tract-fill", "fill-color", "#3a3f45");
      map.setPaintProperty("tract-fill", "fill-opacity", 0.5);
    }
  }

  function renderLegend() {
    const L = $("legend");
    if (state.view === "nisar") {
      const c = N.coverage, key = (k, label) => `<div class="key"><span class="sw" style="background:${c.colours[k]}"></span>${label}, ${pct(c[k])}</div>`;
      L.innerHTML = `<b>Which radar can measure this ground</b>
        ${key("nisar_only", "Only NISAR")}${key("both", "Both radars")}${key("sentinel1_only", "Only Sentinel-1")}${key("neither", "Neither")}
        <div class="scale"><span>Land inside the radar study window</span></div>`;
    } else if (state.view === "flood") {
      L.innerHTML = `<b>Floods about ${floodDays}+ days a year</b>
        <div class="key"><span class="sw" style="background:#2b8fd6"></span>Flooding today, or for 5+ years</div>
        <div class="key"><span class="sw" style="background:#7fe0f5"></span>Started flooding in the last 5 years</div>
        <div class="key"><span class="sw" style="background:rgba(255,107,87,0.3);box-shadow:inset 0 0 0 1px rgba(255,107,87,0.55)"></span>Neighborhood with ${Math.round(city.tract_flood_share * 100)}% or more of its land flooding</div>`;
    } else {
      const stops = city.ramp.map(([v, c], i) => `${c} ${(i / (city.ramp.length - 1)) * 100}%`).join(",");
      const end = !series || state.monthIdx === series.dates.length - 1;
      const k = end ? 1 : series.span_years;
      const unit = end ? "mm per year" : "mm since " + series.dates[0].slice(0, 4);
      L.innerHTML = `<b>${end ? "Sinking rate" : "Total sinking"}, ${unit}</b>
        <div class="bar" style="background:linear-gradient(90deg,${stops})"></div>
        <div class="scale"><span>stable</span><span>${Math.round(city.ramp[2][0] * k)}</span><span>${Math.round(city.ramp[city.ramp.length - 1][0] * k)}+</span></div>`;
    }
  }

  function monthName(d) {
    const [y, m] = d.split("-");
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+m - 1] + " " + y;
  }

  function renderBar() {
    const slider = $("slider");
    slider.style.setProperty("--p", (+slider.max ? (slider.value / slider.max) * 100 : 0) + "%");   // filled part of the track
    if (state.view === "nisar") {
      const c = N.coverage;
      const mon = (d) => monthName(d.slice(0, 4) + "-" + d.slice(4, 6)).slice(0, 3);
      const y0 = N.first_date.slice(0, 4), y1 = N.last_date.slice(0, 4);
      $("year-label").textContent = `${mon(N.first_date)}${y0 === y1 ? "" : " " + y0}–${mon(N.last_date)} ${y1}`;
      $("count").textContent = pct(c.both + c.nisar_only);
      $("count-label").textContent = `of this land measured by NISAR in its first ${Math.round(N.days / 30)} months. The Sentinel-1 record reaches ${pct(c.both + c.sentinel1_only)}.`;
    } else if (state.view === "flood") {
      const year = base + state.yearIdx;
      $("year-label").textContent = year;
      slider.setAttribute("aria-valuetext", String(year));
      const m = modeKey();
      const mid = city.people[m + "_mid"][state.yearIdx];
      const lo = city.people[m + "_low"][state.yearIdx];
      const hi = city.people[m + "_high"][state.yearIdx];
      $("count").textContent = fmt(mid);
      $("count-label").textContent = `people live on land that floods regularly ${state.yearIdx ? "by " + year : "today"}` + (lo !== hi ? ` (range ${fmt(lo)} to ${fmt(hi)})` : "");
      if (hasSinking) {
        const extra = city.people.sinking_mid[state.yearIdx] - city.people.ocean_mid[state.yearIdx];
        $("sink-effect").innerHTML = state.withSinking
          ? extra > 0
            ? `Sinking ground puts <b>${fmt(extra)} more people</b> on regularly flooded land by ${year} than sea level rise alone.`
            : `By ${year}, sinking has not yet added people beyond sea level rise alone.`
          : `Showing sea level rise alone. Switch sinking back on to see what the radar adds.`;
      }
    } else if (series) {
      $("year-label").textContent = monthName(series.dates[state.monthIdx]);
      const vals = Object.values(series.tracts).map((s) => -s[state.monthIdx]).filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
      const p95 = vals[Math.floor(vals.length * 0.95)] || 0;
      $("count").textContent = `${Math.max(0, p95).toFixed(0)} mm`;
      $("count-label").textContent = `sunk since ${monthName(series.dates[0])} in the fastest-sinking 5% of neighborhoods`;
    } else {
      $("year-label").textContent = "–";
      $("count").textContent = "–";
      $("count-label").textContent = "Sinking history appears here once radar data is loaded.";
    }
  }

  function setupSlider() {
    const slider = $("slider");
    const ticks = $("ticks");
    ticks.innerHTML = "";
    if (state.view === "nisar") {
      slider.disabled = true;
    } else if (state.view === "flood") {
      slider.max = city.slider_end_year - base;
      slider.value = state.yearIdx;
      slider.disabled = false;
      slider.setAttribute("aria-label", "Year");
      for (let y = Math.ceil(base / 10) * 10; y <= city.slider_end_year; y += 10) {
        ticks.insertAdjacentHTML("beforeend", `<span style="left:${((y - base) / (city.slider_end_year - base)) * 100}%">${y}</span>`);
      }
    } else if (series) {
      slider.max = series.dates.length - 1;
      slider.value = state.monthIdx;
      slider.disabled = false;
      slider.setAttribute("aria-label", "Month");
      series.dates.forEach((d, i) => {
        if (d.endsWith("-01")) ticks.insertAdjacentHTML("beforeend", `<span style="left:${(i / (series.dates.length - 1)) * 100}%">${d.slice(0, 4)}</span>`);
      });
    } else {
      slider.disabled = true;
    }
  }

  function when(p, key) {
    const y = p[key];
    if (y == null) return "after 2150";
    return y <= base ? "already" : "by " + y;
  }

  function renderNisarOverview() {
    const c = N.coverage;
    const month = (d) => monthName(d.slice(0, 4) + "-" + d.slice(4, 6));
    $("headline").textContent = "What NASA's newest radar can see";
    $("subhead").textContent = `NISAR has passed over ${city.short_name} ${N.n_pairs + 1} times, from ${month(N.first_date)} to ${month(N.last_date)}. `
      + (c.nisar_only >= 0.05
        ? `Gold marks the ${pct(c.nisar_only)} of land that only NISAR can measure: marsh edges, woods and soft ground where the older radar loses its signal.`
        : `Here it measures about the same ground as the older Sentinel-1 radar; gold marks the ${pct(c.nisar_only)} only NISAR reaches.`);
    $("sink-switch").hidden = true;
    $("sink-effect").hidden = true;
    $("rank-title").textContent = "Where NISAR adds the most";
    const top = tracts.features.map((f) => f.properties).filter((p) => p.nisar_cov != null && p.pop > 0)
      .sort((a, b) => (b.nisar_cov - b.s1_cov) - (a.nisar_cov - a.s1_cov)).slice(0, 6);
    $("rank").innerHTML = top
      .map((p, i) => `<li style="--i:${i}"><button type="button" data-id="${p.id}">
          <span class="rank-name">${p.name}</span>
          <span class="rank-when gain">+${Math.round((p.nisar_cov - p.s1_cov) * 100)} points</span>
          <span class="rank-sub">NISAR measures ${pct(p.nisar_cov)} of it, Sentinel-1 ${pct(p.s1_cov)}</span>
        </button></li>`)
      .join("");
    $("already").textContent = `NISAR sets no sinking rates here yet. Over ${N.days} days its readings scatter by about ${Math.round(N.neighborhood_scatter_mm)} mm between neighborhoods, `
      + `while the ground itself moved under ${Math.max(1, Math.ceil(N.expected_range_mm))} mm. A longer record will average that noise down.`;
  }

  function renderOverview() {
    if (state.view === "nisar") return renderNisarOverview();
    const flood = state.view === "flood";
    $("headline").textContent = flood ? "When high tides reach home" : "The ground here is going down";
    $("subhead").textContent = flood
      ? `Blue ground floods at high tide ${floodDays} or more days a year, as the lowest streets do today. Red neighborhoods have ${Math.round(city.tract_flood_share * 100)}% of their land flooding.`
      : hasSinking
        ? "NASA radar has measured this ground from space since 2016. The redder a neighborhood, the faster it is sinking."
        : "NASA radar measurements of sinking are not loaded yet. This view fills in once the OPERA ground-motion data is processed.";
    $("sink-switch").hidden = !flood || !hasSinking;
    $("sink-effect").hidden = !flood || !hasSinking;
    const rows = tracts.features.map((f) => f.properties);
    let top;
    if (flood) {
      $("rank-title").textContent = "Next in line";
      const k = fyKey();
      top = rows.filter((p) => p[k] != null && p[k] > base && p.pop > 0).sort((a, b) => a[k] - b[k] || b.pop - a.pop).slice(0, 6);
    } else {
      $("rank-title").textContent = hasSinking ? "Sinking fastest" : "";
      top = hasSinking ? rows.filter((p) => p.rate != null && p.pop > 0).sort((a, b) => b.rate - a.rate).slice(0, 6) : [];
    }
    $("already").textContent = flood && city.already_tracts
      ? `${city.already_tracts} neighborhoods, mostly marsh and waterfront, already have ${Math.round(city.tract_flood_share * 100)}% of their land below the flood line.`
      : "";
    $("rank").innerHTML = top
      .map((p, i) => `<li style="--i:${i}"><button type="button" data-id="${p.id}">
          <span class="rank-name">${p.name}</span>
          <span class="rank-when">${flood ? when(p, fyKey()) : p.rate.toFixed(1) + " mm/yr"}</span>
          <span class="rank-sub">${p.city}, ${fmt(p.pop)} residents${flood && p.rate != null ? ", sinking " + p.rate.toFixed(1) + " mm/yr" : ""}</span>
        </button></li>`)
      .join("");
  }

  function spark(id) {
    if (!series || !series.tracts[id]) return "";
    const v = series.tracts[id];
    const W = 320, H = 70, n = v.length;
    const lo = Math.min(...v, 0), hi = Math.max(...v, 0);
    const x = (i) => (i / (n - 1)) * W;
    const y = (m) => 6 + ((hi - m) / (hi - lo || 1)) * (H - 12);
    const d = v.map((m, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(m).toFixed(1)).join("");
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Ground height change since ${series.dates[0].slice(0, 4)}">
      <line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="#2a2e33"/><path d="${d}" fill="none" stroke="#ff6b57" stroke-width="1.6"/></svg>
      <span class="small">Ground height, ${monthName(series.dates[0])} to ${monthName(series.dates[n - 1])}: ${v[n - 1].toFixed(0)} mm</span>`;
  }

  function plain(p) {
    const early = p.fy_high, late = p.fy_low;
    let range;
    if (early == null) range = { big: "Not before 2150", text: "is not expected to see regular tidal flooding before 2150 in any scenario we ran" };
    else if (late != null && late <= base) range = { big: "Already begun", text: "already has low ground that floods regularly" };
    else {
      const a = early <= base ? "now" : early;
      const b = late == null ? "after 2150" : late;
      range = { big: `${a === "now" ? "Now" : a} to ${b}`, text: `could see regular flooding begin between ${a} and ${b}` };
    }
    return range;
  }

  function planner(p) {
    const y = p.fy_mid;
    if (y == null) return "Low priority for tidal flooding. Keep it in the regional monitoring programme and re-check when new radar data arrives.";
    if (y <= base + 15) return "Act within this budget cycle: map the lowest streets and drains, check evacuation routes at high tide, and prioritise this area for flood protection funding.";
    if (y <= base + 45) return "Plan now, build later: reserve capital funding, avoid new critical facilities on the lowest ground, and set a trigger year for raising roads and utilities.";
    return "Monitor: review every five years against new radar and sea level data, and factor the timeline into long-lived infrastructure decisions.";
  }

  function renderCard() {
    const card = $("card");
    const p = state.selected && byId.get(state.selected);
    $("overview").hidden = !!p;
    card.hidden = !p;
    map.setFilter("tract-selected", ["==", "id", p ? p.id : ""]);
    if (!p) return;
    const r = plain(p);
    const hasRate = p.rate != null;
    const rateHtml = hasRate
      ? `<span class="big">${p.rate > 0.3 ? p.rate.toFixed(1) + " mm a year" : "Stable"}</span>
         <span class="small">± ${p.rate_sigma.toFixed(1)} mm/yr, about ${Math.abs(p.rate_in_decade).toFixed(1)} inches per decade${p.rate < -0.3 ? " (rising)" : ""}</span>${spark(p.id)}`
      : `<span class="small">No radar measurement yet for this neighborhood.</span>`;
    const share = p.sink_share;
    const splitHtml = share != null
      ? `<div class="split"><i class="land" style="width:${share * 100}%"></i><i class="sea" style="width:${(1 - share) * 100}%"></i></div>
         <span class="small">${Math.round(share * 100)}% sinking ground, ${Math.round((1 - share) * 100)}% rising sea${p.years_sooner > 0 ? `. Sinking brings it ${p.years_sooner} years sooner.` : ""}</span>`
      : `<span class="small">${hasRate ? "Not applicable here." : "Available once sinking is measured."}</span>`;
    const yi = Math.min(Math.floor(state.yearIdx / 5), p.people.length - 1);
    card.innerHTML = `
      <button class="btn back" type="button" id="back">Back to the city</button>
      <h1>${p.name}</h1>
      <p class="where">${p.city}, census tract ${p.tract}</p>
      <dl class="facts">
        <div><dt>People living here</dt><dd><span class="big">${fmt(p.pop)}</span><span class="small">2020 Census</span></dd></div>
        <div><dt>Regular flooding could begin</dt><dd><span class="big">${r.big}</span><span class="small">Low to high sea level scenarios. Counted when ${Math.round(city.tract_flood_share * 100)}% of dry land floods about ${floodDays}+ days a year.</span></dd></div>
        <div><dt>Sinking rate</dt><dd>${rateHtml}</dd></div>
        <div><dt>What drives it</dt><dd>${splitHtml}</dd></div>
        <div><dt>On flooded land by ${city.step_years[yi]}</dt><dd><span class="big">${fmt((state.withSinking ? p.people : p.people_ocean)[yi])}</span><span class="small">residents, middle scenario</span></dd></div>
      </dl>
      <div class="say"><h3>For residents</h3>About ${fmt(p.pop)} people live here. This neighborhood ${r.text}${hasRate && p.rate > 0.3 ? `, and the ground is sinking about ${p.rate.toFixed(1)} mm a year` : ""}.</div>
      <div class="say"><h3>For planners</h3>${planner(p)}</div>
      <div class="card-actions"><button class="btn" type="button" id="print">Print this brief</button><button class="btn" type="button" id="csv">Download all neighborhoods (CSV)</button></div>`;
    $("back").onclick = () => select(null);
    $("print").onclick = () => window.print();
    $("csv").onclick = downloadCsv;
  }

  function downloadCsv() {
    const cols = ["id", "name", "city", "pop", "rate", "rate_sigma", "fy_high", "fy_mid", "fy_low", "fy_ocean", "years_sooner", "sink_share"];
    const head = "tract_geoid,name,city,population_2020,sinking_mm_yr,sinking_sigma_mm_yr,flood_year_earliest,flood_year_middle,flood_year_latest,flood_year_sea_level_only,years_sooner_from_sinking,sinking_share";
    const lines = tracts.features.map((f) => cols.map((c) => { const v = f.properties[c]; return v == null ? "" : typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : v; }).join(","));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([head + "\n" + lines.join("\n")], { type: "text/csv" }));
    a.download = "sinking-cities-" + city.id + ".csv";
    a.click();
  }

  function render() { renderMap(); renderLegend(); renderBar(); renderOverview(); renderCard(); }

  function select(id, fly) {
    state.selected = id;
    renderCard();
    if (id && fly) {
      const f = tracts.features.find((t) => t.properties.id === id);
      const b = new maplibregl.LngLatBounds();
      (function walk(c) { typeof c[0] === "number" ? b.extend(c) : c.forEach(walk); })(f.geometry.coordinates);
      map.fitBounds(b, { padding: 140, maxZoom: 13.5, duration: 1400 });
    }
  }

  function setView(v) {
    state.view = v;
    document.body.classList.toggle("view-nisar", v === "nisar");
    document.querySelectorAll(".views button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === v)));
    setupSlider();
    render();
  }

  /* ---------- interaction ---------- */
  document.querySelectorAll(".views button").forEach((b) => (b.onclick = () => { stop(); setView(b.dataset.view); }));
  // The prompt above the slider and the breathing play button are only for first-time visitors.
  function used() {
    $("slider-hint").classList.add("gone");
    $("play").classList.remove("invite");
  }
  $("slider").addEventListener("pointerdown", used);
  $("slider").addEventListener("keydown", used);
  $("slider").oninput = (ev) => {
    if (state.view === "flood") state.yearIdx = +ev.target.value; else state.monthIdx = +ev.target.value;
    renderMap(); renderBar(); renderLegend();
    if (state.selected) renderCard();
  };
  $("with-sinking").onchange = (ev) => { state.withSinking = ev.target.checked; render(); };
  $("rank").onclick = (ev) => { const b = ev.target.closest("button[data-id]"); if (b) select(b.dataset.id, true); };
  map.on("click", "tract-fill", (ev) => select(ev.features[0].properties.id));
  // Hover preview: name and the key figure for the current view.
  const tip = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, className: "tip" });
  map.on("mousemove", "tract-fill", (ev) => {
    const p = byId.get(ev.features[0].properties.id);
    map.getCanvas().style.cursor = "pointer";
    map.setFilter("tract-hover", ["==", "id", p.id]);
    const line = state.view === "nisar"
      ? p.nisar_cov == null ? "No coverage figure" : `NISAR measures ${pct(p.nisar_cov)}, Sentinel-1 ${pct(p.s1_cov)}`
      : state.view === "flood"
      ? p[fyKey()] == null ? "No regular flooding before 2150" : p[fyKey()] <= base ? "Floods regularly already" : `Regular flooding by ${p[fyKey()]}`
      : p.rate == null ? "No radar measurement" : p.rate > 0.3 ? `Sinking ${p.rate.toFixed(1)} mm a year` : "Stable ground";
    tip.setLngLat(ev.lngLat).setHTML(`<b>${p.name}</b><span>${line}, ${fmt(p.pop)} residents</span>`).addTo(map);
  });
  map.on("mouseleave", "tract-fill", () => {
    map.getCanvas().style.cursor = "";
    map.setFilter("tract-hover", ["==", "id", ""]);
    tip.remove();
  });

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function stop() {
    if (state.playing) state.playing.cancelled = true;
    state.playing = null;
    $("play").innerHTML = ICON.play;
    $("play").setAttribute("aria-label", "Play");
    $("caption").hidden = true;
  }
  async function sweep(token, ms, from) {
    const slider = $("slider");
    const max = +slider.max;
    const start = from ?? 0;
    const t0 = performance.now();
    while (!token.cancelled) {
      const f = Math.min(1, (performance.now() - t0) / ms);
      const v = Math.round(start + (max - start) * f);
      if (+slider.value !== v) { slider.value = v; slider.oninput({ target: slider }); }
      if (f >= 1) break;
      await new Promise(requestAnimationFrame);
    }
  }
  $("play").onclick = async () => {
    if (state.playing) return stop();
    const token = (state.playing = { cancelled: false });
    $("play").innerHTML = ICON.pause;
    used();
    $("play").setAttribute("aria-label", "Pause");
    const cur = +$("slider").value;
    await sweep(token, 12000, cur >= +$("slider").max ? 0 : cur);
    if (!token.cancelled) stop();
  };

  // Guided story, timed to fit a 30-second demo recording.
  $("story").onclick = async () => {
    stop();
    used();
    const token = (state.playing = { cancelled: false });
    const cap = $("caption");
    const say = (t) => { cap.textContent = t; cap.hidden = false; };
    // End on a named neighborhood that floods soon and where sinking moves the date; fall back to the soonest.
    const soon = tracts.features.map((f) => f.properties).filter((p) => p.fy_mid != null && p.fy_mid > base && p.pop >= 1500)
      .sort((a, b) => a.fy_mid - b.fy_mid || b.pop - a.pop);
    const star = soon.find((p) => !/ tract /.test(p.name) && p.years_sooner >= 5 && p.fy_mid <= base + 40) || soon[0];
    select(null);
    map.fitBounds([city.bounds.slice(0, 2), city.bounds.slice(2)], { padding: 20, duration: 800 });
    say(`${city.short_name}: ${(city.population / 1e6).toFixed(2)} million people at the water's edge.`);
    if (hasSinking && series) {
      state.monthIdx = 0; setView("sinking");
      await sleep(2500); if (token.cancelled) return;
      say("NASA radar has watched this ground sink since 2016.");
      await sweep(token, 5500); if (token.cancelled) return;
      await sleep(800);
      if (N && !token.cancelled) {
        setView("nisar");
        say(`NISAR, NASA's newest radar, already measures ${pct(N.coverage.both + N.coverage.nisar_only)} of this land.`);
        await sleep(3500);
      }
    } else { state.yearIdx = 0; setView("flood"); await sleep(2500); }
    if (token.cancelled) return;
    state.yearIdx = 0; setView("flood");
    say(hasSinking ? "Sinking ground meets a rising sea." : "The sea is rising toward the lowest streets.");
    await sweep(token, 9000); if (token.cancelled) return;
    await sleep(800);
    if (star && !token.cancelled) {
      const r = plain(star);
      select(star.id, true);
      say(`About ${fmt(star.pop)} people live in the ${star.name}. It ${r.text}${star.years_sooner >= 5 ? `, ${star.years_sooner} years sooner because the ground is sinking` : ""}.`);
      await sleep(7000);
    }
    if (!token.cancelled) stop();
  };

  /* ---------- science check ---------- */
  function checkHtml() {
    const g = city.gps, R = city.radar, N = city.nisar;
    let h = `<h2>Check the science</h2><p>Every number here comes from public data. This panel shows how well the radar agrees with independent measurements.</p>`;
    h += `<h3>Radar against GPS stations</h3>`;
    if (R && R.gps_check) {
      const W = 300, pad = 36, lim = Math.max(4, ...R.gps_check.flatMap((c) => [Math.abs(c.gps_mm_yr), Math.abs(c.insar_mm_yr)])) + 1;
      const sx = (v) => pad + ((v + lim) / (2 * lim)) * (W - 2 * pad), sy = (v) => W - pad - ((v + lim) / (2 * lim)) * (W - 2 * pad);
      h += `<p>${R.gps_summary}</p><svg viewBox="0 0 ${W} ${W}" width="${W}" role="img" aria-label="Radar versus GPS vertical rates">
        <rect x="${pad}" y="${pad}" width="${W - 2 * pad}" height="${W - 2 * pad}" style="fill:var(--paper)"/>
        <line x1="${sx(-lim)}" y1="${sy(-lim)}" x2="${sx(lim)}" y2="${sy(lim)}" stroke="#6b737a" stroke-dasharray="4 3"/>
        ${R.gps_check.map((c) => `<circle cx="${sx(c.gps_mm_yr)}" cy="${sy(c.insar_mm_yr)}" r="4.5" fill="${c.used === false ? "#16181b" : "#ff6b57"}" stroke="#ff6b57"><title>${c.id}: GPS ${c.gps_mm_yr}, radar ${c.insar_mm_yr} mm/yr</title></circle>`).join("")}
        <text x="${W / 2}" y="${W - 8}" text-anchor="middle" font-size="11">GPS vertical rate, mm/yr</text>
        <text x="12" y="${W / 2}" text-anchor="middle" font-size="11" transform="rotate(-90 12 ${W / 2})">Radar vertical rate, mm/yr</text></svg>
        <table><tr><th>Station</th><th class="num">GPS, mm/yr</th><th class="num">Radar, mm/yr</th><th class="num">Difference</th></tr>
        ${R.gps_check.map((c) => `<tr><td>${c.id}${c.used === false ? " *" : ""}</td><td class="num">${c.gps_mm_yr.toFixed(1)} ± ${c.gps_sigma.toFixed(1)}</td><td class="num">${c.insar_mm_yr.toFixed(1)}</td><td class="num">${(c.insar_mm_yr - c.gps_mm_yr).toFixed(1)}</td></tr>`).join("")}</table>
        <p class="small">* Not used for the tie: outside the mapped area, or a GPS rate too uncertain to anchor to. Shown as hollow dots. Negative means sinking.</p>`;
    } else {
      h += `<div class="pending">Radar rates are not loaded yet. ${g.length} GPS stations from the Nevada Geodetic Laboratory are ready for the comparison; their vertical rates range from ${Math.min(...g.map((x) => x.up_mm_yr)).toFixed(1)} to ${Math.max(...g.map((x) => x.up_mm_yr)).toFixed(1)} mm/yr.</div>`;
    }
    h += `<h3>The newest look: NISAR</h3>`;
    h += N && N.ok ? `<p>${N.summary}</p>` : `<div class="pending">${N && N.note ? N.note : "The NISAR comparison has not been run yet."}</div>`;
    const d = city.water.htf_days.filter((x) => x.year >= 1960);
    const mx = Math.max(...d.map((x) => x.days)), bw = 9, H = 120;
    h += `<h3>It has already started</h3><p>Days each year the tide passed NOAA's flood threshold at ${city.water.station_name}. Average for ${city.water.htf_recent_years[0]} to ${city.water.htf_recent_years[1]}: ${city.water.htf_recent_mean_days} days.</p>
      <svg viewBox="0 0 ${d.length * bw} ${H + 16}" width="100%" role="img" aria-label="High-tide flood days per year">
      ${d.map((x, i) => `<rect x="${i * bw}" y="${H - (x.days / mx) * H}" width="${bw - 2}" height="${(x.days / mx) * H}" fill="#2b8fd6"><title>${x.year}: ${x.days} days</title></rect>${x.year % 10 === 0 ? `<text x="${i * bw}" y="${H + 13}" font-size="10" fill="#9aa2a9">${x.year}</text>` : ""}`).join("")}</svg>
      <p><a href="methods.html?city=${cid}">Read the full method and its limits</a></p>`;
    return h;
  }
  $("open-check").onclick = () => { $("check-body").innerHTML = checkHtml(); $("check").showModal(); };

  setView("flood");
  document.body.classList.remove("loading");
})().catch((err) => {
  console.error(err);
  document.body.classList.remove("loading");
  document.querySelector(".panel").insertAdjacentHTML("afterbegin", `<p class="notice">The map data did not load. Check your connection and reload the page.</p>`);
});
