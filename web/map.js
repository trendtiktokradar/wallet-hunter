/* Mapa de Wallets. El grafo solo pinta direcciones que el usuario añadió
   o que devolvió el box. No hay dataset de demostración en la web publicada. */
(function () {
  "use strict";
  var SOL = /[1-9A-HJ-NP-Za-km-z]{32,44}/;
  var st = {
    mode: "wallets", coin: "", scope: "context", from: "", to: "",
    chips: [], hidden: {}, selected: null, side: "fund",
    result: null, positions: {}, zoom: 1, pan: { x: 0, y: 0 },
    fixture: false, detail: false, why: false, status: "", job: null, bound: false, loaded: false
  };

  function WH() { return window.WH || {}; }
  function esc(s) { var f = WH().esc; return f ? f(s) : String(s == null ? "" : s); }
  function short(a) { var f = WH().short; return f ? f(a) : (a ? a.slice(0, 4) + "…" + a.slice(-4) : ""); }
  function $(id) { return document.getElementById(id); }
  function toast(msg) { var f = WH().toast; if (f) f(msg); else st.status = msg; }

  function parseList(text) {
    var ok = [], bad = [], seen = {};
    String(text || "").split(/[\s,;]+/).forEach(function (part) {
      part = part.trim();
      if (!part) return;
      if (/^0x/i.test(part)) { bad.push(part); return; }
      var tail = part.split("/").pop().split("?")[0].split("#")[0];
      var m = tail.match(/[1-9A-HJ-NP-Za-km-z]{32,44}$/);
      if (!m) { bad.push(part); return; }
      if (seen[m[0]]) return;
      seen[m[0]] = 1;
      ok.push(m[0]);
    });
    return { ok: ok, bad: bad };
  }

  function aliases() {
    var src = (WH().aliases && WH().aliases()) || {}, out = {};
    Object.keys(src).forEach(function (k) {
      var i = k.indexOf(":");
      if (k.slice(0, i) === "solana") out[k.slice(i + 1)] = src[k];
    });
    return out;
  }
  function nameOf(addr, node) {
    var al = aliases()[addr] || (node && node.alias) || (wallet(addr) && wallet(addr).alias);
    return al || short(addr);
  }
  function wallet(addr) { return st.result && st.result.by_wallet ? st.result.by_wallet[addr] : null; }
  function fecha(ts) {
    if (!ts) return "sin fecha en la fuente";
    try { return new Date(ts * 1000).toLocaleString("es-ES", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }); }
    catch (e) { return String(ts); }
  }
  function sol(n) {
    if (n == null || isNaN(+n)) return "–";
    var s = (Math.round(+n * 1000) / 1000).toString().replace(".", ",");
    return s + " SOL";
  }
  function assetAmt(m) {
    if (m.kind === "swap_buy" || m.kind === "swap_sell") return sol(m.amount) + (m.token_amount != null ? " · " + String(m.token_amount).replace(".", ",") + " token" : "");
    if (m.asset && m.asset !== "native") return String(m.amount).replace(".", ",") + " · " + short(m.asset);
    return sol(m.amount);
  }

  function persist() {
    if (st.fixture) return;
    try { sessionStorage.setItem("wh_map_draft", JSON.stringify({ chips: st.chips, mode: st.mode, coin: st.coin, selected: st.selected, side: st.side })); } catch (e) { }
  }
  function restore() {
    try {
      var d = JSON.parse(sessionStorage.getItem("wh_map_draft") || "null");
      if (!d || !Array.isArray(d.chips)) return;
      st.chips = d.chips.filter(function (a) { return typeof a === "string" && SOL.test(a); });
      st.mode = d.mode === "coin" ? "coin" : "wallets";
      st.coin = typeof d.coin === "string" && SOL.test(d.coin) ? d.coin : "";
      st.selected = st.chips.indexOf(d.selected) >= 0 ? d.selected : (st.chips[0] || null);
      st.side = d.side === "moves" ? "moves" : "fund";
    } catch (e) { }
  }

  function addChips(list) {
    list.forEach(function (a) {
      delete st.hidden[a];
      if (st.chips.indexOf(a) < 0) st.chips.push(a);
    });
    if (!st.selected || st.chips.indexOf(st.selected) < 0) st.selected = list[0] || st.chips[0] || null;
    persist();
  }
  function removeChip(addr) {
    st.chips = st.chips.filter(function (a) { return a !== addr; });
    st.hidden[addr] = 1;
    if (st.selected === addr) st.selected = st.chips[0] || null;
    st.status = "Wallet quitada del mapa. Su alias guardado no se ha borrado.";
    persist(); render();
  }

  function view() {
    var chips = {};
    st.chips.forEach(function (a) { if (!st.hidden[a]) chips[a] = 1; });
    var nodes = {}, edges = [];
    if (st.result && !st.result.unavailable) {
      (st.result.edges || []).forEach(function (e) {
        if (st.hidden[e.from] || st.hidden[e.to]) return;
        if (!chips[e.to] && !chips[e.from]) return;
        edges.push(e);
      });
      (st.result.nodes || []).forEach(function (n) {
        if (st.hidden[n.id]) return;
        if (chips[n.id] || edges.some(function (e) { return e.from === n.id || e.to === n.id; })) nodes[n.id] = n;
      });
    }
    Object.keys(chips).forEach(function (a) {
      if (!nodes[a]) nodes[a] = { id: a, kind: "wallet", role: "wallet", alias: aliases()[a] || null, pending: true };
    });
    return { nodes: Object.keys(nodes).map(function (k) { return nodes[k]; }), edges: edges };
  }

  function layout(v) {
    var cx = 430, cy = 230, rx = 210, ry = 120;
    var wallets = v.nodes.filter(function (n) { return n.kind !== "service" && n.kind !== "cex" && n.kind !== "origin"; });
    wallets.forEach(function (n, i) {
      if (st.positions[n.id]) return;
      var ang = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, wallets.length);
      var rad = wallets.length < 2 ? 0 : 1;
      st.positions[n.id] = { x: cx + Math.cos(ang) * rx * rad, y: cy + Math.sin(ang) * ry * rad };
    });
    var extras = v.nodes.filter(function (n) { return !st.positions[n.id]; });
    extras.forEach(function (n, i) {
      var links = v.edges.filter(function (e) { return e.from === n.id || e.to === n.id; });
      var pts = links.map(function (e) { return st.positions[e.from === n.id ? e.to : e.from]; }).filter(Boolean);
      var base = pts.length ? { x: pts.reduce(function (s, p) { return s + p.x; }, 0) / pts.length, y: pts.reduce(function (s, p) { return s + p.y; }, 0) / pts.length } : { x: cx, y: cy };
      var ang = Math.atan2(base.y - cy, base.x - cx);
      if (!pts.length) ang = i;
      ang += (i - (extras.length - 1) / 2) * 0.42;
      st.positions[n.id] = { x: cx + Math.cos(ang) * (rx + 80), y: cy + Math.sin(ang) * (ry + 70) };
    });
    var ids = v.nodes.map(function (n) { return n.id; });
    for (var it = 0; it < 30; it++) {
      for (var i = 0; i < ids.length; i++) for (var j = i + 1; j < ids.length; j++) {
        var pa = st.positions[ids[i]], pb = st.positions[ids[j]];
        if (!pa || !pb || pa.pinned || pb.pinned) continue;
        var dx = pb.x - pa.x, dy = pb.y - pa.y, d = Math.hypot(dx, dy) || 1;
        if (d < 148) {
          var push = (148 - d) / 2;
          pa.x -= dx / d * push; pb.x += dx / d * push;
          pa.y -= dy / d * push; pb.y += dy / d * push;
        }
      }
    }
    ids.forEach(function (id) {
      var p = st.positions[id];
      if (!p || p.pinned) return;
      p.x = Math.max(80, Math.min(780, p.x));
      p.y = Math.max(56, Math.min(400, p.y));
    });
  }

  function strokeOf(n) {
    if (n.kind === "service" || n.kind === "cex") return "#9aa6b8";
    if (n.kind === "origin") return "#e4c58b";
    return "#8ec5ef";
  }

  function draw() {
    var svg = $("mapSvg"); if (!svg) return;
    var v = view(); layout(v);
    var NS = "http://www.w3.org/2000/svg";
    function el(tag, attrs, text) {
      var n = document.createElementNS(NS, tag);
      Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
      if (text != null) n.textContent = text;
      return n;
    }
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var defs = el("defs");
    var marker = el("marker", { id: "mapArrow", viewBox: "0 0 10 10", refX: "8", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" });
    marker.appendChild(el("path", { d: "M0,0 L10,5 L0,10 z", fill: "#6fd0c0" }));
    defs.appendChild(marker);
    svg.appendChild(defs);
    var g = el("g", { transform: "translate(" + st.pan.x + " " + st.pan.y + ") translate(430 240) scale(" + st.zoom + ") translate(-430 -240)" });
    svg.appendChild(g);
    if (!v.nodes.length) {
      g.appendChild(el("text", { x: "430", y: "236", "text-anchor": "middle", fill: "#8aa0bb", "font-size": "14" }, "Sin wallets en el mapa. Pega una dirección y pulsa Añadir al mapa."));
    }
    v.edges.forEach(function (e) {
      var a = st.positions[e.from], b = st.positions[e.to];
      if (!a || !b) return;
      var dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      var x1 = a.x + dx / len * 28, y1 = a.y + dy / len * 28, x2 = b.x - dx / len * 34, y2 = b.y - dy / len * 34;
      var col = e.service ? "#8b95a7" : "#6fd0c0";
      g.appendChild(el("line", { x1: x1, y1: y1, x2: x2, y2: y2, stroke: col, "stroke-width": e.service ? "1.6" : "2", "marker-end": "url(#mapArrow)" }));
      var label = (e.amount != null ? sol(e.amount) : "SOL") + (e.confirmed === false ? " · sin clasificar" : "");
      g.appendChild(el("text", { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 6, "text-anchor": "middle", fill: "#b7ebe3", "font-size": "11" }, label));
    });
    v.nodes.forEach(function (n) {
      var p = st.positions[n.id]; if (!p) return;
      var grp = el("g", { class: "mapnode", "data-id": n.id, transform: "translate(" + p.x + " " + p.y + ")" });
      var selected = st.selected === n.id;
      grp.appendChild(el("circle", { r: "26", fill: "#1a2c44", stroke: selected ? "#5ee0c5" : strokeOf(n), "stroke-width": selected ? "3.5" : "2" }));
      var letter = n.kind === "service" || n.kind === "cex" ? "S" : n.kind === "origin" ? "O" : (n.id || "?").slice(0, 1);
      grp.appendChild(el("text", { y: "5", "text-anchor": "middle", fill: strokeOf(n), "font-size": "16" }, letter));
      var lab = (n.kind === "service" || n.kind === "cex") && n.label ? n.label : nameOf(n.id, n);
      grp.appendChild(el("text", { y: "46", "text-anchor": "middle", fill: "#e7eef8", "font-size": "12" }, lab.length > 22 ? lab.slice(0, 20) + "…" : lab));
      var sub = n.coin_label || (n.hypothesis ? "Posible madre · hipótesis" : (n.pending ? "sin buscar" : ""));
      if (sub) grp.appendChild(el("text", { y: "62", "text-anchor": "middle", fill: n.hypothesis ? "#e4c58b" : "#93c5fd", "font-size": "10" }, sub.length > 28 ? sub.slice(0, 26) + "…" : sub));
      if (n.coincidence) {
        var badge = el("g", { transform: "translate(0 74)" });
        badge.appendChild(el("rect", { x: "-54", y: "-11", width: "108", height: "18", rx: "8", fill: "#134e4a" }));
        badge.appendChild(el("text", { y: "2", "text-anchor": "middle", fill: "#ccfbf1", "font-size": "10" }, "Coincidencia alta"));
        grp.appendChild(badge);
      }
      g.appendChild(grp);
    });
    var leg = $("mapLegend");
    if (leg) leg.innerHTML = '<span><i style="background:#6fd0c0"></i>SOL revisado</span><span><i style="background:#8b95a7"></i>servicio o exchange con fuente (no es un dueño)</span><span><i style="background:#e4c58b;height:10px;border-radius:50%"></i>origen sin identificar</span>';
  }

  function coinHits(addr) {
    var w = wallet(addr);
    return (w && w.coin_events) || [];
  }
  function coincidences(addr) {
    if (!st.result) return [];
    return (st.result.coincidences || []).filter(function (h) { return h.wallet === addr; });
  }

  function renderSide() {
    var el = $("mapSide"); if (!el) return;
    if (document.activeElement && (document.activeElement.id === "mapAlias")) return;
    var addr = st.selected;
    if (!addr) { el.innerHTML = '<p class="muted">Selecciona una wallet del mapa.</p>'; return; }
    var node = (view().nodes.filter(function (n) { return n.id === addr; })[0]) || { id: addr, kind: "wallet" };
    var w = wallet(addr);
    var al = aliases()[addr] || (w && w.alias) || "";
    var html = '<div class="mapkicker">' + (node.kind === "service" || node.kind === "cex" ? "Servicio · con fuente" : "Wallet seleccionada") + "</div>";
    html += "<h2>" + esc(nameOf(addr, node)) + "</h2>";
    html += '<div class="mini" style="word-break:break-all">' + esc(addr) + ' <button type="button" class="copy" data-copy="' + esc(addr) + '">📋</button></div>';
    if (node.kind === "service" || node.kind === "cex") {
      html += '<p class="mini">' + esc(node.label || "Servicio") + (node.source ? " · " + esc(node.source) : "") + ". Compartirlo no indica mismo dueño. No se le atribuye un propietario.</p>";
    } else if (!node.identified && node.kind === "origin") {
      html += '<p class="mini">Sin identificar: no está en la lista de exchanges ni en la de servicios con fuente.</p>';
    }
    if (node.hypothesis) html += '<p class="mini">' + esc(node.hypothesis) + "</p>";
    html += '<div class="mapalias"><input id="mapAlias" maxlength="40" placeholder="Alias (se reutiliza en otras búsquedas)" value="' + esc(al) + '"><button type="button" class="ghost" id="mapSaveAlias">Guardar wallet</button></div>';
    html += '<div class="segtabs"><button type="button" id="mapTabFund"' + (st.side === "fund" ? ' class="on"' : "") + '>Fondeo</button><button type="button" id="mapTabMoves"' + (st.side === "moves" ? ' class="on"' : "") + ">Movimientos</button></div>";
    if (!st.result) html += '<p class="mini">Aún no se ha buscado en la cadena. Los chips no son un análisis.</p>';
    else if (st.result.unavailable) html += '<p class="mini">' + esc(st.result.unavailable.message || "Análisis no disponible.") + "</p>";
    else if (!w) html += '<p class="mini">Esta dirección está en el mapa y todavía no se ha leído su historial. Pulsa Buscar conexiones.</p>';
    else if (st.side === "fund") html += fundHtml(addr, w);
    else html += moveHtml(addr, w);
    if (st.mode === "coin" && st.coin) html += coinHtml(addr);
    html += coinBox(addr);
    el.innerHTML = html;
  }

  function fundHtml(addr, w) {
    var rows = w.funders || [];
    if (!rows.length) return '<p class="mini">' + esc((w.coverage && w.coverage.note) || "En lo revisado no apareció un fondeo. Eso no demuestra que no exista fuera del intervalo.") + "</p>";
    return rows.map(function (f) {
      var who = f.label ? esc(f.label) + (f.source ? ' <span class="mini">· ' + esc(f.source) + "</span>" : "") : esc(short(f.address)) + ' <span class="mini">· sin identificar</span>';
      var link = f.url ? '<a class="xl" target="_blank" rel="noopener" href="' + esc(f.url) + '">Solscan</a>' : '<span class="mini">sin enlace (la referencia no es una firma)</span>';
      var add = st.chips.indexOf(f.address) >= 0 ? "" : '<button type="button" class="ghost" data-add="' + esc(f.address) + '">Añadir origen al mapa</button> <button type="button" class="ghost" data-hop="' + esc(f.address) + '">Buscar un salto atrás</button>';
      return '<div class="maprow"><div><b class="amt in">' + esc(sol(f.amount)) + "</b> · " + esc(fecha(f.ts)) + "</div><div>" + who + "</div>" +
        (f.note ? '<div class="mini">' + esc(f.note) + "</div>" : "") +
        '<div class="row" style="margin-top:6px">' + link + add + "</div></div>";
    }).join("");
  }
  function moveHtml(addr, w) {
    var rows = w.movements || [];
    if (!rows.length) return '<p class="mini">' + esc((w.coverage && w.coverage.note) || "En lo revisado no aparecieron movimientos. Eso no demuestra que no existan fuera del intervalo.") + "</p>";
    var more = w.movements_more ? '<p class="mini">Hay más movimientos en la página leída; se muestran los más recientes hasta el tope.</p>' : "";
    var page = w.coverage && w.coverage.next_cursor ? '<button type="button" class="ghost" id="mapMore">Cargar la página siguiente de esta wallet</button>' : "";
    return more + rows.map(function (m) {
      var dir = m.direction === "in" ? "in" : "out";
      var sign = dir === "in" ? "+" : "−";
      var cp = m.counterparty_label ? esc(m.counterparty_label) + (m.counterparty_source ? " · " + esc(m.counterparty_source) : "") : (m.counterparty ? esc(short(m.counterparty)) + (m.counterparty_kind === "unidentified" || !m.counterparty_kind ? " · sin identificar" : "") : "sin contraparte en la tx");
      var kind = m.verified_swap ? (m.kind === "swap_buy" ? "Compra verificada" : "Venta verificada") : (m.kind === "token_in" ? "Recibió token (no es compra)" : m.kind === "token_out" ? "Envió token (no es venta)" : "Transferencia");
      var link = m.url ? '<a class="xl" target="_blank" rel="noopener" href="' + esc(m.url) + '">Solscan</a>' : "";
      var add = m.counterparty && st.chips.indexOf(m.counterparty) < 0 && m.counterparty_kind !== "ignored" ? '<button type="button" class="ghost" data-add="' + esc(m.counterparty) + '">Añadir contraparte</button>' : "";
      return '<div class="maprow"><div><b class="amt ' + dir + '">' + sign + esc(assetAmt(m)) + "</b> · " + esc(fecha(m.ts)) + "</div><div>" + cp + "</div><div class=\"mini\">" + esc(kind) + "</div><div class=\"row\" style=\"margin-top:6px\">" + link + add + "</div></div>";
    }).join("") + page;
  }
  function coinHtml(addr) {
    var ev = coinHits(addr);
    if (!ev.length) return '<div class="mapcoinbox"><b>Coin</b><p class="mini">En lo revisado de esta wallet no hay un swap ni una transferencia de esta CA. No se infiere actividad.</p></div>';
    return '<div class="mapcoinbox"><b>En esta coin</b>' + ev.slice(0, 8).map(function (e) {
      var link = e.url ? ' <a class="xl" target="_blank" rel="noopener" href="' + esc(e.url) + '">Solscan</a>' : "";
      return '<div class="mini" style="margin-top:4px">' + esc(e.label || e.kind) + " · " + esc(fecha(e.ts)) + link + "</div>";
    }).join("") + "</div>";
  }
  function coinBox(addr) {
    var hits = coincidences(addr);
    var html = "";
    if (hits.length) {
      var h = hits[0];
      html += '<div class="mapcoinbox"><span class="mapbadge">Coincidencia alta</span><p>' + esc(h.motive) + "</p>";
      html += '<button type="button" class="ghost" id="mapDetail">' + (st.detail ? "Ocultar detalle" : "Ver detalle de la muestra") + "</button>";
      if (st.detail) {
        var toks = (h.detail && h.detail.tokens) || [];
        html += '<div class="mini" style="margin-top:6px">Denominadores: ' + esc(h.detail.sample_a) + " y " + esc(h.detail.sample_b) + " coins con swap verificado. En común: " + esc(h.overlap) + " de " + esc(h.denom) + " (" + Math.round(h.ratio * 100) + " %).</div>";
        html += '<div class="mini">' + toks.map(esc).join("<br>") + (h.detail.tokens_more ? "<br>…" : "") + "</div>";
      }
      html += '<div style="margin-top:6px"><button type="button" class="ghost" id="mapHypo">Guardar como hipótesis</button></div></div>';
    }
    var rejected = ((st.result && st.result.rejected) || []).filter(function (r) { return r.wallet === addr || r.counterpart === addr; });
    if (st.result && !st.result.unavailable && !hits.length && rejected.length) {
      html += '<button type="button" class="ghost" id="mapWhy">' + (st.why ? "Ocultar" : "Por qué no hay coincidencia alta") + "</button>";
      if (st.why) html += rejected.map(function (r) { return '<p class="mini">' + esc(nameOf(r.wallet === addr ? r.counterpart : r.wallet)) + ": " + esc(r.reason) + "</p>"; }).join("");
    }
    return html;
  }

  function renderCoinPanel() {
    var el = $("mapCoin"); if (!el) return;
    el.classList.toggle("hide", st.mode !== "coin");
    if (st.mode !== "coin") return;
    if (document.activeElement && document.activeElement.closest && document.activeElement.closest("#mapCoin")) return;
    var coin = st.result && st.result.coin;
    var html = '<div class="mapkicker">Contexto de coin</div><p class="mini">La CA no dispara un listado de holders. Puedes añadir sospechosos, cargar solo los primeros compradores verificados (tope de transacciones) o un intervalo de como máximo 7 días.</p>';
    html += '<div class="mapalias"><input id="mapCa" placeholder="CA de Solana (se respetan mayúsculas)" value="' + esc(st.coin) + '"></div>';
    html += '<div class="row"><button type="button" class="ghost" id="mapUseCa">Usar esta CA</button><button type="button" class="ghost" id="mapEarly">Primeros compradores</button></div>';
    html += '<div class="row" style="margin-top:8px"><label class="mini">Desde <input id="mapFrom" type="date" value="' + esc(st.from) + '"></label><label class="mini">Hasta <input id="mapTo" type="date" value="' + esc(st.to) + '"></label><button type="button" class="ghost" id="mapInterval">Intervalo acotado</button></div>';
    if (coin) {
      html += '<p class="mini" style="margin-top:8px">CA ' + esc(coin.address) + (coin.symbol ? " · " + esc(coin.symbol) : "") + "</p>";
      html += '<p class="mini">' + esc(coin.axiom_note || "") + "</p>";
      if (coin.axiom) html += '<a class="xl" target="_blank" rel="noopener" href="' + esc(coin.axiom) + '">Axiom · pool verificado</a>';
      if (coin.note) html += '<p class="mini">' + esc(coin.note) + "</p>";
      if ((coin.buyers || []).length) {
        html += '<div class="mini" style="margin-top:6px">Compras verificadas en lo leído (no son todos los holders):</div>';
        html += coin.buyers.map(function (b) { return '<div class="mini">' + esc(short(b.address)) + " · " + esc(fecha(b.ts)) + ' <button type="button" class="ghost" data-add="' + esc(b.address) + '">Añadir</button></div>'; }).join("");
      }
      if ((coin.receipts || []).length) {
        html += '<div class="mini" style="margin-top:6px">Recibieron el token (no es una compra):</div>';
        html += coin.receipts.map(function (b) { return '<div class="mini">' + esc(short(b.address)) + ' <button type="button" class="ghost" data-add="' + esc(b.address) + '">Añadir</button></div>'; }).join("");
      }
    }
    el.innerHTML = html;
  }

  function renderChips() {
    var el = $("mapChips"); if (!el) return;
    el.innerHTML = st.chips.map(function (a) {
      var on = st.selected === a ? ' style="outline:2px solid #5ee0c5"' : "";
      return '<span class="mapchip"' + on + '><button type="button" data-sel="' + esc(a) + '">' + esc(nameOf(a)) + '</button><button type="button" data-x="' + esc(a) + '" aria-label="Quitar del mapa">×</button></span>';
    }).join("");
  }
  function renderGroups() {
    var el = $("mapGroups"); if (!el) return;
    if (document.activeElement && (document.activeElement.id === "mapGroupName" || document.activeElement.id === "mapGroupPick")) return;
    var groups = (WH().groups && WH().groups()) || [];
    var opts = groups.map(function (g) { return '<option value="' + esc(g.id) + '">' + esc((g.emoji ? g.emoji + " " : "") + g.name) + "</option>"; }).join("");
    el.innerHTML = "<h3>Grupos guardados</h3><input id=\"mapGroupName\" maxlength=\"40\" placeholder=\"Nombre del grupo\"><button type=\"button\" class=\"ghost\" id=\"mapSaveGroup\">Guardar grupo</button><select id=\"mapGroupPick\"><option value=\"\">Cargar un grupo…</option>" + opts + "</select><button type=\"button\" class=\"ghost\" id=\"mapLoadGroup\">Cargar en el mapa</button><span class=\"mini\">Guardar y cargar usa los grupos del box (PIN). Cargar cambia las wallets del mapa, no borra alias.</span>";
  }
  function renderBanner() {
    var el = $("mapBanner"); if (!el) return;
    if (st.fixture) {
      el.className = "mapbanner warn";
      el.textContent = "FIXTURA LOCAL DE PRUEBA · NO ES LA CADENA · estos nodos no son un análisis. En la web publicada esta vista no existe.";
      return;
    }
    var box = WH().boxOk && WH().boxOk();
    el.className = "mapbanner info";
    if (st.result && st.result.unavailable) el.textContent = st.result.unavailable.message;
    else if (!box) el.textContent = "Buscar conexiones necesita el box encendido (el servicio Python del equipo, no esta página). Mientras no responda, el mapa no inventa relaciones: solo guarda aquí las wallets que pegues.";
    else el.textContent = "La búsqueda es bajo demanda y con tope. No vigila wallets ni envía alertas.";
  }
  function renderModes() {
    var w = $("mapModeW"), c = $("mapModeC");
    if (w) w.classList.toggle("on", st.mode !== "coin");
    if (c) c.classList.toggle("on", st.mode === "coin");
    var title = $("mapTitle"), lead = $("mapLead");
    if (!title) return;
    if (st.mode === "coin") { title.textContent = "La coin como contexto"; lead.textContent = "La CA fija la coin. Las compras verificadas y las recepciones del token se muestran aparte. El fondeo es el mismo grafo."; }
    else if (st.result && !st.result.unavailable) { title.textContent = "De una wallet a sus posibles orígenes"; lead.textContent = "Orígenes dentro de lo revisado. Un servicio en gris no es un dueño. Una hipótesis de origen común no prueba coordinación."; }
    else { title.textContent = "Mapa de Wallets"; lead.textContent = "Pega una o varias wallets, colócalas en el mapa y busca conexiones solo cuando quieras. Quitar una del mapa no borra su alias."; }
  }
  function renderCoverage() {
    var el = $("mapCoverage"); if (!el) return;
    var sum = st.result && st.result.coverage && st.result.coverage.summary;
    el.textContent = sum || "Fondeo = entradas de SOL ≥ 0,05 que no son un swap, en como máximo 30 días y 100 transferencias por wallet (hasta 3 páginas). Vacío significa que no apareció en ese intervalo. Coincidencia alta: al menos 8 coins con swap verificado en cada wallet, 5 en común y el 35 % de la muestra más pequeña, más una contraparte que no sea servicio ni exchange. Una coin compartida no basta.";
  }
  function renderStatus() { var el = $("mapStatus"); if (el) el.textContent = st.status || ""; }

  function render() {
    renderBanner(); renderModes(); renderCoinPanel(); renderChips(); draw(); renderSide(); renderGroups(); renderCoverage(); renderStatus();
  }

  function localFixture() {
    return /^(localhost|127\.0\.0\.1)$/.test(location.hostname) && /mapfixture/.test(location.hash || "");
  }
  function applyFixture(kind) {
    var A = "AAAAkWziSE1VPGUSLDqD1oCam1cogQVwFU4GpVDDYyki";
    var B = "BBBBhCbbzwWsFkeLSTKkfrxVrnCPFhBdMq6i1evQcuiL";
    var C = "CCCCXF69bNHPp5LUMm1pUaCZvCCbQXp4ZSAynrVViF2r";
    var O = "MoMxyz1111111111111111111111111111111111111";
    var O2 = "Nfund2222222222222222222222222222222222222";
    var S = "F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe";
    var sig = "1".repeat(88);
    st.fixture = true; st.mode = kind === "coin" ? "coin" : "wallets"; st.coin = kind === "coin" ? "Mint1111111111111111111111111111111111pump" : "";
    st.chips = [A, B, C]; st.hidden = {}; st.selected = B; st.positions = {};
    st.result = {
      fixture: true, unavailable: null, wallets: [A, B, C],
      coverage: { partial: false, summary: "FIXTURA · no es una lectura de la cadena. Sirve solo para ver la maquetación en local." },
      nodes: [
        { id: O, kind: "origin", role: "origin", label: null, hypothesis: "Hipótesis: en lo revisado fondeó a 2 wallets de este mapa. No prueba mismo dueño.", identified: false },
        { id: O2, kind: "origin", role: "origin", identified: false },
        { id: A, kind: "wallet", role: "wallet", alias: "Wallet A", coin_label: kind === "coin" ? "Compró · verificado" : null },
        { id: B, kind: "wallet", role: "wallet", alias: "Wallet B", coincidence: true, coin_label: kind === "coin" ? "Vendió · verificado" : null },
        { id: C, kind: "wallet", role: "wallet", alias: "Wallet C", coin_label: kind === "coin" ? "Recibió token" : null },
        { id: S, kind: "service", role: "service", label: "Relay", source: "docs.relay.link (ejemplo de fixture)", verified: true }
      ],
      edges: [
        { from: O, to: A, amount: 12, confirmed: true, service: false },
        { from: O, to: B, amount: 8, confirmed: true, service: false },
        { from: O2, to: B, amount: 3, confirmed: true, service: false },
        { from: O2, to: O, amount: 30, confirmed: true, service: false },
        { from: S, to: C, amount: 1, confirmed: true, service: true }
      ],
      by_wallet: {},
      coincidences: [{
        wallet: B, counterpart: A, overlap: 6, denom: 8, ratio: 0.75, near_buys: 2,
        motive: "Con Wallet A: 6 coins distintas en común de 8 en la muestra más pequeña (75 %). Ventana de la fixture, no de la cadena. Contraparte: mismo origen de fixture. Compras próximas: 2. Es una hipótesis de solape, no una prueba de mismo dueño.",
        counterpart_why: "fixture", detail: { tokens: ["coin-1", "coin-2", "coin-3", "coin-4", "coin-5", "coin-6"], tokens_more: 0, sample_a: 8, sample_b: 8 }
      }],
      rejected: [],
      coin: kind === "coin" ? {
        address: st.coin, symbol: "FIXTURE", pool: "Curve111111111111111111111111111111111111",
        axiom: "https://axiom.trade/meme/Curve111111111111111111111111111111111111",
        axiom_note: "Enlace de fixture, no de un pool consultado.",
        buyers: [{ address: A, ts: 1762500000 }], receipts: [{ address: C, ts: 1762501000 }], note: "Recorte de fixture."
      } : null
    };
    function pack(addr, funders, moves, events) {
      st.result.by_wallet[addr] = { alias: { A: "Wallet A", B: "Wallet B", C: "Wallet C" }[addr] || null, funders: funders, movements: moves, coin_events: events || [], coverage: { note: null } };
    }
    pack(A, [{ address: O, amount: 12, ts: 1762503000, url: "https://solscan.io/tx/" + sig, confirmed: true, label: null }], [
      { direction: "in", counterparty: O, amount: 12, asset: "native", kind: "native_in", ts: 1762503000, url: "https://solscan.io/tx/" + sig }
    ], kind === "coin" ? [{ kind: "swap_buy", label: "Compró · verificado", verified: true, ts: 1762504000, url: "https://solscan.io/tx/" + sig }] : []);
    pack(B, [
      { address: O, amount: 8, ts: 1762502000, url: "https://solscan.io/tx/" + sig, confirmed: true, label: null },
      { address: O2, amount: 3, ts: 1762490000, url: "https://solscan.io/tx/" + sig, confirmed: true, label: null }
    ], [
      { direction: "in", counterparty: O, amount: 8, asset: "native", kind: "native_in", ts: 1762502000, url: "https://solscan.io/tx/" + sig },
      { direction: "out", counterparty: C, amount: 1, asset: "native", kind: "native_out", ts: 1762505000, url: "https://solscan.io/tx/" + sig }
    ], kind === "coin" ? [{ kind: "swap_sell", label: "Vendió · verificado", verified: true, ts: 1762504500, url: "https://solscan.io/tx/" + sig }] : []);
    pack(C, [{ address: S, amount: 1, ts: 1762480000, url: "https://solscan.io/tx/" + sig, confirmed: true, label: "Relay", source: "fixture · docs.relay.link" }], [], kind === "coin" ? [{ kind: "token_in", label: "Recibió el token (no es una compra)", verified: false, ts: 1762501000 }] : []);
    st.status = "Fixture local. Buscar conexiones pide al box datos reales y sustituye esta vista.";
  }

  function maybeFixture() {
    if (!localFixture()) { if (st.fixture) { st.fixture = false; st.result = null; } return; }
    var kind = /mapfixture=coin/.test(location.hash) ? "coin" : "wallets";
    if (st.fixture && st._fx === kind) return;
    st._fx = kind;
    applyFixture(kind);
  }

  function setStatus(t) { st.status = t; renderStatus(); }

  function search(hops, extra) {
    if (st.fixture) { st.fixture = false; st.result = null; st._fx = ""; }
    var api = WH().api, pin = WH().needPin;
    if (!api || !pin) { setStatus("El panel todavía no está listo."); return; }
    if (!(WH().boxOk && WH().boxOk())) { setStatus("El box no responde. No se inventa el grafo."); renderBanner(); return; }
    if (!pin()) return;
    var body = { op: "search", mode: st.mode, wallets: st.chips.join("\n"), hops: hops || 1, scope: st.scope || "context" };
    if (st.mode === "coin") body.coin = st.coin;
    if (st.scope === "interval") { body.from_ts = st.fromTs; body.to_ts = st.toTs; }
    if (extra && extra.cursor && extra.addr) { body.page = 2; body.cursors = {}; body.cursors[extra.addr] = extra.cursor; }
    setStatus("Buscando en el intervalo acotado…");
    api("/api/map", body).then(function (r) {
      st.job = r.id; poll();
    }).catch(function (e) {
      setStatus(e.message || "No se pudo buscar.");
      renderBanner();
    });
  }
  function poll() {
    var api = WH().api; if (!api || !st.job) return;
    api("/api/map", { op: "status", id: st.job }).then(function (r) {
      if (r.status === "pending" || r.status === "running") { setStatus(r.progress || "En cola…"); setTimeout(poll, 1500); return; }
      if (r.result) {
        st.result = r.result; st.fixture = false;
        if (r.result.coin && r.result.coin.buyers && st.scope === "first_buyers") addChips(r.result.coin.buyers.map(function (b) { return b.address; }));
        setStatus(r.result.unavailable ? r.result.unavailable.message : "Listo. Cobertura en el pie del mapa.");
        render();
      } else setStatus(r.error || r.message || "La búsqueda no devolvió resultado.");
    }).catch(function (e) { setStatus(e.message || "No se pudo leer el estado."); });
  }

  function useCa() {
    var raw = ($("mapCa") && $("mapCa").value) || "";
    var p = parseList(raw);
    if (p.ok.length !== 1) { setStatus("La CA tiene que ser una dirección Solana. No se reescribe a minúsculas."); return; }
    st.coin = p.ok[0]; st.mode = "coin"; st.scope = "context"; persist(); render();
  }
  function readDates() {
    var from = $("mapFrom") && $("mapFrom").value, to = $("mapTo") && $("mapTo").value;
    if (!from || !to) return null;
    var a = Date.parse(from + "T00:00:00Z"), b = Date.parse(to + "T23:59:59Z");
    if (!(a < b)) return null;
    if (b - a > 7 * 86400 * 1000) { setStatus("El intervalo máximo es 7 días."); return null; }
    st.from = from; st.to = to; st.fromTs = Math.floor(a / 1000); st.toTs = Math.floor(b / 1000);
    return true;
  }

  function bind() {
    if (st.bound) return; st.bound = true;
    $("mapAdd").onclick = function () {
      var p = parseList($("mapInput").value);
      if (!p.ok.length) { setStatus(p.bad.length ? "Ninguna dirección Solana válida. EVM no entra en este mapa y las de Solana no se pasan a minúsculas." : "Pega al menos una wallet."); return; }
      addChips(p.ok); $("mapInput").value = "";
      setStatus(p.bad.length ? "Añadidas " + p.ok.length + ". Se ignoró alguna entrada que no es Solana." : "Añadidas al mapa. Aún no se ha buscado en la cadena.");
      render();
    };
    $("mapSearch").onclick = function () { st.scope = st.mode === "coin" && st.coin ? "context" : "context"; search(1); };
    $("mapModeW").onclick = function () { st.mode = "wallets"; persist(); render(); };
    $("mapModeC").onclick = function () { st.mode = "coin"; persist(); render(); };
    $("mapZin").onclick = function () { st.zoom = Math.min(2.2, st.zoom * 1.15); draw(); };
    $("mapZout").onclick = function () { st.zoom = Math.max(0.55, st.zoom / 1.15); draw(); };
    $("mapCenter").onclick = function () { st.zoom = 1; st.pan = { x: 0, y: 0 }; st.positions = {}; draw(); };
    $("tab-map").addEventListener("click", function (e) {
      var t = e.target.closest("[data-x],[data-sel],[data-add],[data-hop],#mapSaveAlias,#mapTabFund,#mapTabMoves,#mapDetail,#mapWhy,#mapHypo,#mapMore,#mapUseCa,#mapEarly,#mapInterval,#mapSaveGroup,#mapLoadGroup");
      if (!t) return;
      if (t.dataset.x) { e.stopPropagation(); removeChip(t.dataset.x); return; }
      if (t.dataset.sel) { st.selected = t.dataset.sel; persist(); render(); return; }
      if (t.dataset.add) { addChips([t.dataset.add]); setStatus("Añadida al mapa. Pulsa Buscar conexiones para leerla. El alias no se ha tocado."); render(); return; }
      if (t.dataset.hop) { addChips([t.dataset.hop]); search(2); return; }
      if (t.id === "mapTabFund") { st.side = "fund"; renderSide(); return; }
      if (t.id === "mapTabMoves") { st.side = "moves"; renderSide(); return; }
      if (t.id === "mapDetail") { st.detail = !st.detail; renderSide(); return; }
      if (t.id === "mapWhy") { st.why = !st.why; renderSide(); return; }
      if (t.id === "mapMore") {
        var w = wallet(st.selected);
        if (w && w.coverage && w.coverage.next_cursor) search(1, { addr: st.selected, cursor: w.coverage.next_cursor });
        return;
      }
      if (t.id === "mapSaveAlias") return saveAlias();
      if (t.id === "mapHypo") return saveHyp();
      if (t.id === "mapUseCa") return useCa();
      if (t.id === "mapEarly") { useCa(); if (!st.coin) return; st.scope = "first_buyers"; search(1); return; }
      if (t.id === "mapInterval") { useCa(); if (!st.coin || !readDates()) { if (st.coin) setStatus("Elige un desde y un hasta, como máximo 7 días."); return; } st.scope = "interval"; search(1); return; }
      if (t.id === "mapSaveGroup") return saveGroup();
      if (t.id === "mapLoadGroup") return loadGroup();
    });
    var svg = $("mapSvg"), drag = null;
    svg.addEventListener("pointerdown", function (e) {
      var node = e.target.closest && e.target.closest(".mapnode");
      svg.setPointerCapture(e.pointerId);
      var pt = point(e);
      if (node) drag = { kind: "node", id: node.getAttribute("data-id"), x: pt.x, y: pt.y, moved: false, ox: st.positions[node.getAttribute("data-id")].x, oy: st.positions[node.getAttribute("data-id")].y };
      else drag = { kind: "pan", x: e.clientX, y: e.clientY, ox: st.pan.x, oy: st.pan.y, moved: false };
    });
    svg.addEventListener("pointermove", function (e) {
      if (!drag) return;
      if (drag.kind === "pan") {
        if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 3) drag.moved = true;
        if (!drag.moved) return;
        st.pan.x = drag.ox + (e.clientX - drag.x); st.pan.y = drag.oy + (e.clientY - drag.y); draw();
        return;
      }
      var pt = point(e);
      if (Math.hypot(pt.x - drag.x, pt.y - drag.y) > 3) drag.moved = true;
      if (!drag.moved) return;
      st.positions[drag.id] = { x: drag.ox + (pt.x - drag.x), y: drag.oy + (pt.y - drag.y), pinned: true };
      draw();
    });
    function end() {
      if (!drag) return;
      var d = drag; drag = null;
      if (!d.moved && d.kind === "node") { st.selected = d.id; persist(); render(); }
    }
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", function () { drag = null; });
    svg.addEventListener("wheel", function (e) {
      e.preventDefault();
      st.zoom = Math.max(0.55, Math.min(2.2, st.zoom * (e.deltaY < 0 ? 1.08 : 0.92)));
      draw();
    }, { passive: false });
  }
  function point(e) {
    var svg = $("mapSvg"), pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    var ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    var p = pt.matrixTransform(ctm.inverse());
    return { x: (p.x - st.pan.x - 430) / st.zoom + 430, y: (p.y - st.pan.y - 240) / st.zoom + 240 };
  }

  function saveAlias() {
    var addr = st.selected, input = $("mapAlias");
    if (!addr || !input) return;
    var api = WH().api, pin = WH().needPin;
    if (!api || !pin || !pin()) return;
    api("/api/aliases", { op: "set", chain: "solana", address: addr, alias: input.value.trim() }).then(function (r) {
      if (WH().setAliases) WH().setAliases(r.aliases);
      setStatus(input.value.trim() ? "Alias guardado en el box. Quitarlo del mapa no lo borra." : "Alias borrado del box.");
      render();
    }).catch(function (e) { setStatus(e.message || "No se pudo guardar el alias."); });
  }
  function saveHyp() {
    var addr = st.selected, hit = coincidences(addr)[0];
    if (!hit) return;
    var api = WH().api, pin = WH().needPin;
    if (!pin()) return;
    api("/api/map", { op: "hypothesis", wallet: addr, counterpart: hit.counterpart, motive: hit.motive, evidence: { overlap: hit.overlap, denom: hit.denom, ratio: hit.ratio } }).then(function () {
      setStatus("Hipótesis guardada en el box. No es una conclusión ni una etiqueta de la wallet.");
    }).catch(function (e) { setStatus(e.message || "No se pudo guardar la hipótesis."); });
  }
  function saveGroup() {
    var name = ($("mapGroupName") && $("mapGroupName").value || "").trim();
    if (!name || !st.chips.length) { setStatus("Escribe un nombre y deja al menos una wallet en el mapa."); return; }
    var api = WH().api, pin = WH().needPin;
    if (!pin()) return;
    api("/api/groups", { op: "save", group: { name: name, emoji: "🗺", chain: "solana", wallets: st.chips.slice(), source: "mapa" } }).then(function (r) {
      if (WH().setGroups) WH().setGroups(r.groups);
      setStatus("Grupo guardado. Las wallets siguen con sus alias.");
      renderGroups();
    }).catch(function (e) { setStatus(e.message || "No se pudo guardar el grupo."); });
  }
  function loadGroup() {
    var id = $("mapGroupPick") && $("mapGroupPick").value;
    var groups = (WH().groups && WH().groups()) || [];
    var g = groups.filter(function (x) { return x.id === id; })[0];
    if (!g) { setStatus("Elige un grupo."); return; }
    var wallets = (g.wallets || []).filter(function (a) { return SOL.test(a); });
    st.chips = wallets; st.hidden = {}; st.selected = wallets[0] || null; st.positions = {};
    persist(); setStatus("Grupo cargado en el mapa. Todavía no se ha buscado en la cadena."); render();
  }

  function show() {
    bind();
    if (!st.loaded) { st.loaded = true; restore(); }
    maybeFixture();
    render();
  }
  window.WHMap = { show: show };
})();
