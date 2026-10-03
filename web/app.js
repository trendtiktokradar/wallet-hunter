/* Wallet Hunter · panel (sin dependencias) */
(function () {
  "use strict";
  var CFG = window.WH_CONFIG;
  var D = null, BOX = null, BOX_OK = false;
  var S = { coin: "", pendingCoin: null, sel: {}, visible: [], tab: "wallets", sort: "sc", asc: false, tags: [], chain: "", limit: 300, kind: "tokens", scanChain: "auto" };
  var FAVS = load("wh_favs", {});            // "chain:addr" -> {alias}
  var ALIASES = load("wh_aliases", {});      // "chain:addr" -> alias (privados: viven en el box, con PIN; aquí solo una copia local)
  var FRESH_DAYS = 7;
  var GROUPS = load("wh_groups", []);        // grupos guardados en el box (con PIN); copia local para pintar sus emojis
  var G_IDX = {};                            // dirección -> [{emoji, name}]
  var EXP = null;                            // estado del diálogo «Exportar grupo»
  var PIN = localStorage.getItem("wh_pin") || "";
  var $ = function (id) { return document.getElementById(id); };
  var NOW = function () { return Date.now() / 1000; };

  function load(k, d) { try { return JSON.parse(localStorage.getItem(k)) || d; } catch (e) { return d; } }
  function save(k, v) { localStorage.setItem(k, JSON.stringify(v)); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function short(a) { return a ? a.slice(0, 5) + "…" + a.slice(-4) : ""; }
  function num(x, d) { if (x == null || isNaN(x)) return "–"; var a = Math.abs(x); if (a >= 1e6) return (x / 1e6).toFixed(1).replace(".", ",") + "M"; if (a >= 1e4) return (x / 1e3).toFixed(1).replace(".", ",") + "k"; return x.toFixed(d == null ? 2 : d).replace(".", ","); }
  function signed(x, d, suf) { if (x == null) return "–"; return '<span class="' + (x >= 0 ? "pos" : "neg") + '">' + (x >= 0 ? "+" : "") + num(x, d) + (suf || "") + "</span>"; }
  function usd(x) { if (x == null) return "–"; var a = Math.abs(x); var s = a >= 1e6 ? (a / 1e6).toFixed(1) + "M" : a >= 1e3 ? (a / 1e3).toFixed(1) + "k" : a.toFixed(0); return '<span class="' + (x >= 0 ? "pos" : "neg") + '">' + (x >= 0 ? "+" : "-") + "$" + s.replace(".", ",") + "</span>"; }
  function dur(s) { if (s == null) return "–"; s = Math.max(0, s); if (s < 60) return Math.round(s) + "s"; if (s < 3600) return Math.round(s / 60) + "m"; if (s < 86400) return (s / 3600).toFixed(1).replace(".", ",") + "h"; return (s / 86400).toFixed(1).replace(".", ",") + "d"; }
  function ago(ts) { return ts ? "hace " + dur(NOW() - ts) : "–"; }
  function fmtDate(ts) { if (!ts) return "–"; var d = new Date(ts * 1000); return d.toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); }
  function nat(c) { return D && D.chains[c] ? D.chains[c].native : ""; }
  function chainName(c) { return D && D.chains[c] ? D.chains[c].name : c; }
  function scoreColor(s) { if (s == null) return "#475569"; if (s >= 70) return "#4ade80"; if (s >= 55) return "#a3e635"; if (s >= 40) return "#facc15"; if (s >= 25) return "#fb923c"; return "#94a3b8"; }
  function toast(msg, ms) { var t = $("toast"); t.innerHTML = msg; t.classList.remove("hide"); clearTimeout(t._h); t._h = setTimeout(function () { t.classList.add("hide"); }, ms || 3500); }
  function copy(txt, what) {
    var fallback = function () { var ta = document.createElement("textarea"); ta.value = txt; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select(); var ok = false; try { ok = document.execCommand("copy"); } catch (e) { } ta.remove(); if (ok) toast("Copiado: " + esc(what || short(txt))); else prompt("Copia:", txt); };
    (navigator.clipboard && window.isSecureContext ? navigator.clipboard.writeText(txt) : Promise.reject()).then(function () { toast("Copiado: " + esc(what || short(txt))); }, fallback);
  }
  function key(w) { return w.c + ":" + w.a; }
  function isFav(w) { return !!FAVS[key(w)]; }
  function tagDef(id) { return (D.tagIdx || {})[id] || { label: id, help: "", color: "gray" }; }
  function explorer(c, a) { return (D.chains[c] || {}).explorer + a; }
  function gmgn(c, a) { var m = (D.chains[c] || {}).gmgn || { solana: "sol", ethereum: "eth", bsc: "bsc", base: "base" }[c]; return m ? "https://gmgn.ai/" + m + "/address/" + a : null; }
  function exName(c) { return (D.chains[c] || {}).exn || "Explorer"; }
  function exLinks(w, cls) {
    var g = gmgn(w.c, w.a), k = cls || "xl";
    return '<a class="' + k + '" target="_blank" rel="noopener" href="' + esc(explorer(w.c, w.a)) + '" title="Abrir en ' + esc(exName(w.c)) + '">' + esc(exName(w.c)) + "</a>" +
      (g ? '<a class="' + k + '" target="_blank" rel="noopener" href="' + esc(g) + '" title="Abrir en GMGN">GMGN</a>' : "");
  }
  // wallet fresca = su primera transacción (o, si no se conoce, su primer fondeo) fue hace ≤ 7 días y el historial no está truncado
  function bornTs(w) { return w.ft && !w.at ? w.ft : (!w.ft && w.fa ? w.fa : null); }
  function isFresh(w) { var b = bornTs(w); return !!b && NOW() - b <= FRESH_DAYS * 86400; }
  function freshTip(w) { return "Wallet fresca 🌱: su " + (w.ft ? "primera transacción" : "primer fondeo") + " fue hace " + dur(NOW() - bornTs(w)) + " (menos de " + FRESH_DAYS + " días). Típico de wallets creadas para un lanzamiento: insiders, bundlers o snipers con wallets desechables."; }
  function applyAliases() { if (!D) return; D.wallets.forEach(function (w) { var k = key(w); w.al = ALIASES[k] || (FAVS[k] && FAVS[k].alias) || null; }); }

  // ---------------------------------------------------------------- datos
  function fetchJSON(url, opts) { return fetch(url, opts || { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }
  function loadData() {
    var tryBox = BOX && BOX_OK ? fetchJSON(BOX + "/data.json") : Promise.reject();
    return tryBox.catch(function () { return fetchJSON(CFG.dataUrl + (CFG.local ? "" : "?t=" + Math.floor(NOW() / 60))); })
      .catch(function () { return fetchJSON(CFG.fallbackUrl); })
      .then(function (d) { setData(d); });
  }
  function setData(d) {
    D = d; D.tagIdx = {}; d.tags.forEach(function (t) { D.tagIdx[t.id] = t; });
    D.wIdx = {}; d.wallets.forEach(function (w) { D.wIdx[key(w)] = w; }); applyAliases();
    if (!CFG.local && d.box && d.box.url && d.box.url !== BOX) { BOX = d.box.url; checkBox(); }
    renderAll();
  }
  function findBox() {
    if (CFG.local) { BOX = "http://127.0.0.1:18795"; return checkBox(); }
    return fetchJSON(CFG.boxJsonUrl, { cache: "no-store", headers: { Accept: "application/vnd.github.raw+json" } })
      .then(function (b) { if (b && b.url) { BOX = b.url; return checkBox(); } }).catch(function () { });
  }
  function checkBox() {
    if (!BOX) return Promise.resolve();
    return fetch(BOX + "/health", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (h) { BOX_OK = !!h.ok; BOX_PIN_SET = h.pin_set; renderSources(); })
      .catch(function () { BOX_OK = false; renderSources(); });
  }
  var BOX_PIN_SET = null;
  function api(path, body) {
    if ((!BOX || !BOX_OK) && path === "/api/scan" && !CFG.local) {
      // respaldo: cola en GitHub vía la función de Vercel (si está configurada)
      body = body || {}; body.pin = PIN;
      return fetch(CFG.vercelQueue, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.error || "El box no responde y no hay cola de respaldo configurada."); return j; }); });
    }
    if (!BOX || !BOX_OK) return Promise.reject(new Error("El box no responde ahora mismo (¿apagado o reiniciando?). Vuelve a intentarlo en unos minutos."));
    body = body || {}; body.pin = PIN;
    return fetch(BOX + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) { if (r.status === 401) { PIN = ""; localStorage.removeItem("wh_pin"); } throw new Error(j.msg || j.error || ("Error " + r.status)); } return j; }); });
  }
  function needPin() {
    if (PIN) return true;
    var p = prompt("PIN de Wallet Hunter:");
    if (!p) return false;
    PIN = p.trim(); localStorage.setItem("wh_pin", PIN); return true;
  }
  function syncFavs(op, w, alias) {
    if (!BOX_OK || !PIN) return Promise.resolve();
    return api("/api/favs", { op: op, chain: w ? w.c : null, address: w ? w.a : null, alias: alias }).then(function (r) {
      var nf = {}; (r.favs || []).forEach(function (f) { nf[f.chain + ":" + f.address] = { alias: f.alias }; });
      // fusiona: los locales que no estén en el box se suben
      Object.keys(FAVS).forEach(function (k) { if (!nf[k] && op === "list") { var p = k.split(":"); api("/api/favs", { op: "add", chain: p[0], address: p[1], alias: FAVS[k].alias }); nf[k] = FAVS[k]; } });
      FAVS = nf; save("wh_favs", FAVS);
    }).catch(function () { });
  }

  function buildGroupIdx() { G_IDX = {}; (GROUPS || []).forEach(function (g) { (g.wallets || []).forEach(function (a) { (G_IDX[a] = G_IDX[a] || []).push({ emoji: g.emoji, name: g.name }); }); }); }
  buildGroupIdx();
  function groupBadges(w) { return (G_IDX[w.a] || []).map(function (g) { return '<span class="gem" data-tip="Grupo guardado: ' + esc((g.emoji ? g.emoji + " " : "") + g.name) + '">' + esc(g.emoji || "🏷️") + "</span>"; }).join(""); }
  function setGroups(list) { GROUPS = (list || []).map(function (g) { return { id: g.id, name: g.name, emoji: g.emoji, chain: g.chain, wallets: g.wallets, source: g.source }; }); save("wh_groups", GROUPS); buildGroupIdx(); }
  function syncGroups() {
    if (!BOX_OK || !PIN) return Promise.resolve();
    return api("/api/groups", { op: "list" }).then(function (r) { setGroups(r.groups); renderAll(); }).catch(function () { });
  }
  function setAliases(list) { var m = {}; (list || []).forEach(function (a) { m[a.chain + ":" + a.address] = a.alias; }); ALIASES = m; save("wh_aliases", ALIASES); applyAliases(); }
  function syncAliases() {
    if (!BOX_OK || !PIN) return Promise.resolve();
    return api("/api/aliases", { op: "list" }).then(function (r) { setAliases(r.aliases); renderAll(); }).catch(function () { });
  }
  function editAlias(k) {
    var w = D.wIdx[k]; if (!w) return;
    var al = prompt("Alias para " + short(w.a) + " (vacío = quitar). Se guarda en tu box, protegido con PIN; no se publica:", w.al || "");
    if (al == null) return;
    if (!needPin()) return;
    api("/api/aliases", { op: "set", chain: w.c, address: w.a, alias: al.trim() }).then(function (r) {
      setAliases(r.aliases); if (FAVS[k]) { FAVS[k].alias = ALIASES[k] || null; save("wh_favs", FAVS); }
      toast(al.trim() ? "Alias guardado: <b>" + esc(al.trim()) + "</b>" : "Alias quitado"); renderAll();
      if (!$("drawer").classList.contains("hide")) openWallet(k);
    }).catch(function (e) { toast("No se pudo guardar el alias: " + esc(e.message)); });
  }

  // ---------------------------------------------------------------- cabecera
  function renderSources() {
    if (!D) return;
    var s = D.sources || {}, k = D.keys || {}, h = [];
    var hel = s.helius || {};
    var credits = hel.credits_month ? " · " + num(hel.credits_month, 0) + " créditos este mes" : "";
    h.push('<span class="src" title="Helius (Solana)' + esc(credits) + '"><span class="dot ' + (k.helius ? (hel.ok === false ? "bad" : "ok") : "warn") + '"></span>' + (k.helius ? "Helius activo" : "Helius sin key") + "</span>");
    [["dexscreener", "dexscreener"], ["geckoterminal", "geckoterminal"], ["kraken", "kraken"], ["etherscan", "etherscan"], ["blockscout", "blockscout"]].forEach(function (x) {
      var v = s[x[0]];
      if (!v && (x[0] === "etherscan" || x[0] === "blockscout")) { var has = x[0] === "etherscan" ? k.etherscan : k.blockscout; h.push('<span class="src" title="' + (has ? "Configurada, aún sin uso" : "Sin API key") + '"><span class="dot ' + (has ? "" : "warn") + '"></span>' + x[1] + "</span>"); return; }
      var cls = !v ? "" : v.ok ? "ok" : "bad";
      h.push('<span class="src" title="' + esc(v ? (v.ok ? "OK " + ago(v.last_ok) : "Error: " + (v.error || "")) : "Sin uso todavía") + '"><span class="dot ' + cls + '"></span>' + x[1] + "</span>");
    });
    h.push('<span class="src" title="' + esc(BOX ? "Box: " + (BOX_OK ? "encendido (escaneos desde la web disponibles)" : "no responde") : "Box sin túnel publicado") + '"><span class="dot ' + (BOX_OK ? "ok" : "bad") + '"></span>box</span>');
    $("sources").innerHTML = h.join("");
  }
  // ---- vista por coin: S.coin = "chain:CA"
  function coinTok() { if (!S.coin || !D) return null; var i = S.coin.indexOf(":"), c = S.coin.slice(0, i), a = S.coin.slice(i + 1); return D.tokens.find(function (t) { return t.c === c && t.a === a; }) || null; }
  function walletCoins(w) { return w.ct || w.or || []; }
  function inCoin(w, t) { return w.c === t.c && walletCoins(w).indexOf(t.a) >= 0; }
  function findTokenByCA(ca) { if (!D || !ca) return null; var l = ca.toLowerCase(); return D.tokens.find(function (t) { return t.a === ca || (t.a.slice(0, 2) === "0x" && t.a.toLowerCase() === l); }) || null; }
  function coinBundles(t) { return D.bundles.filter(function (b) { return b.c === t.c && b.t === t.a; }); }
  function coinLabel(t) { return (t.sy || short(t.a)) + " · " + chainName(t.c) + " · escaneado " + fmtDate(t.sa); }
  function coinChips(w, max) {
    var cur = coinTok(), cs = walletCoins(w), m = max || 4;
    return cs.slice(0, m).map(function (a) { var k = w.c + ":" + a; return '<span class="coinchip' + (cur && cur.a === a ? " cur" : "") + '" data-coin="' + esc(k) + '" data-tip="Ver solo las wallets de ' + esc(tokenSym(w.c, a)) + '">' + esc(tokenSym(w.c, a)) + "</span>"; }).join("") + (cs.length > m ? '<span class="mini">+' + (cs.length - m) + "</span>" : "");
  }
  function setCoin(k) {
    S.coin = k || ""; S.pendingCoin = null; S.limit = 300;
    var t = coinTok();
    var url = location.pathname + location.search + (t ? "#coin=" + encodeURIComponent(t.a) : "");
    if (location.href.slice(location.href.indexOf(location.pathname)) !== url) history.replaceState(null, "", url);
    renderAll();
  }
  function resolvePendingCoin() {
    if (!S.pendingCoin || !D) return;
    var t = findTokenByCA(S.pendingCoin);
    if (t) { S.coin = t.c + ":" + t.a; S.pendingCoin = null; }
  }
  function fillCoins() {
    var sel = $("coinSel"), toks = D.tokens.slice().sort(function (a, b) { return (b.sa || 0) - (a.sa || 0); });
    var html = '<option value="">Todas (' + toks.length + ")</option>" + toks.map(function (t) { var k = t.c + ":" + t.a; return '<option value="' + esc(k) + '"' + (S.coin === k ? " selected" : "") + ">" + esc(coinLabel(t)) + "</option>"; }).join("");
    if (S.pendingCoin) html += '<option value="" selected>' + esc(short(S.pendingCoin)) + " (aún sin datos)</option>";
    if (sel._h !== html) { sel.innerHTML = html; sel._h = html; }
  }
  function tokenUrl(t) { return ((D.chains[t.c] || {}).explorer || "").replace("/account/", "/token/").replace("/address/", "/token/") + t.a; }
  function renderCoinHead() {
    var el = $("coinHead"), t = coinTok();
    if (!t && !S.pendingCoin) { el.classList.add("hide"); el.innerHTML = ""; return; }
    el.classList.remove("hide");
    if (!t) { el.innerHTML = '<span class="sym">' + esc(short(S.pendingCoin)) + '</span><span class="muted">Esta coin todavía no está en los datos (¿escaneo en cola o en curso? Míralo en Trabajos).</span><button class="ghost right" data-coin="">✕ Ver todas las coins</button>'; return; }
    var nw = chainWallets().length, kv = function (k, v) { return '<div class="kv2">' + k + "<b>" + v + "</b></div>"; };
    el.innerHTML = '<div><div class="sym">' + esc(t.sy || "?") + ' <span class="chainpill">' + esc(chainName(t.c)) + '</span></div><div class="nm">' + esc(t.nm || "") + "</div></div>" +
      '<div class="ca">' + esc(t.a) + ' <button class="copy" data-copy="' + esc(t.a) + '" title="Copiar CA">📋</button></div>' +
      kv("Wallets", nw) + kv("Compradores tempranos", t.nb) + kv("Bundles", coinBundles(t).length) + kv("Lanzado", fmtDate(t.lt)) + kv("Escaneado", fmtDate(t.sa) + " (" + ago(t.sa) + ")") + kv("MC", t.mc ? "$" + num(t.mc, 0) : "–") +
      '<div class="row small"><a class="xl" target="_blank" rel="noopener" href="https://dexscreener.com/' + esc(t.c) + "/" + esc(t.a) + '">DexScreener</a><a class="xl" target="_blank" rel="noopener" href="' + esc(tokenUrl(t)) + '">' + esc(exName(t.c)) + "</a></div>" +
      '<button class="ghost right" data-coin="">✕ Ver todas las coins</button>';
  }
  function chainWallets() { var t = coinTok(); return D.wallets.filter(function (w) { return t ? inCoin(w, t) : (!S.chain || w.c === S.chain); }); }
  function renderCards() {
    var ws = chainWallets(), st = D.stats, ct = coinTok();
    var favs = ws.filter(isFav).length;
    var c = function (t, v, s, cls) { return '<div class="card"><div class="t">' + t + '</div><div class="v ' + (cls || "") + '">' + v + '</div><div class="s">' + (s || "") + "</div></div>"; };
    var ok = ws.filter(function (w) { return w.st !== "pending"; });
    var bl = ct ? coinBundles(ct) : D.bundles.filter(function (b) { return !S.chain || b.c === S.chain; });
    var inB = {}; if (ct) bl.forEach(function (b) { b.w.forEach(function (a) { inB[a] = 1; }); });
    var nb = ws.filter(function (w) { return ct ? inB[w.a] : (w.bu || []).length; }).length;
    var bundles = bl.length;
    var wset = {}; ws.forEach(function (w) { wset[w.a] = 1; });
    var cls = D.clusters.filter(function (b) { return ct ? b.c === ct.c && b.w.some(function (a) { return wset[a]; }) : (!S.chain || b.c === S.chain); }).length;
    var toks = ct ? [ct] : D.tokens.filter(function (t) { return !S.chain || t.c === S.chain; });
    var tw = toks.filter(function (t) { return t.sa && NOW() - t.sa < D.window_days * 86400; }).length;
    $("cards").innerHTML =
      c("Wallets analizadas", ok.length, ws.filter(function (w) { return w.st === "pending"; }).length + " pendientes · " + ws.filter(function (w) { return w.st === "error"; }).length + " error · " + ws.filter(function (w) { return w.pf; }).length + " bots prefiltrados") +
      c("⭐ Mis wallets", favs, '<a data-goto="favs">abrir sección</a>', "y") +
      c("Smart money", count(ws, "smart"), "score ≥ 65 y rentables", "g") +
      c("Snipers · bots", count(ws, "sniper") + " · " + count(ws, "bot"), "", "y") +
      c("En bundle · bundlers", nb + " · " + count(ws, "fondeo_sync"), bundles + " bundles detectados · " + count(ws, "fondeo_sync") + " con fondeo sincronizado", "p") +
      c("Clusters · vínculos", cls + (S.chain || ct ? "" : " · " + D.stats.links), ct ? "clusters con wallets de " + esc(ct.sy || "esta coin") : "fondeo común, transferencias, bundles", "b") +
      (ct ? c("Coin seleccionada", esc(ct.sy || "?"), esc(chainName(ct.c)) + " · escaneada " + ago(ct.sa)) : c("Tokens escaneados · ventana", toks.length + " · " + D.window_days + "d", tw + " en ventana de " + D.window_days + " días"));
  }
  function count(ws, tag) { return ws.filter(function (w) { return w.tg.indexOf(tag) >= 0; }).length; }

  // ---------------------------------------------------------------- filtros
  function val(id) { var v = $(id).value; return v === "" ? null : +v; }
  function filtered(onlyFavs) {
    var q = $("fSearch").value.trim().toLowerCase(), sc = val("fScore"), pn = val("fPnl"), wr = val("fWr"), tk = val("fTok"), trd = val("fTrades"), fh = val("fFund"), fresh = $("fFresh").checked;
    var grp = $("fGroup").value, act = $("fAct").value, fav = $("fFav").checked || onlyFavs, hide = $("fHide").checked;
    return chainWallets().filter(function (w) {
      if (q && w.a.toLowerCase().indexOf(q) < 0 && (w.al || "").toLowerCase().indexOf(q) < 0 && !(G_IDX[w.a] || []).some(function (g) { return (g.name || "").toLowerCase().indexOf(q) >= 0; })) return false;
      if (sc != null && (w.sc || 0) < sc) return false;
      if (pn != null && (w.pn == null || w.pn < pn)) return false;
      if (wr != null && (w.wr == null || w.wr * 100 < wr)) return false;
      if (tk != null && (w.tk || 0) < tk) return false;
      if (trd != null && (w.tr || 0) < trd) return false;
      if (fh != null && (!w.lf || NOW() - w.lf > fh * 3600)) return false;
      if (fresh && !isFresh(w)) return false;
      var inB = (w.bu || []).length > 0, inC = !!w.cl;
      if (grp === "bundle" && !inB) return false;
      if (grp === "cluster" && !inC) return false;
      if (grp === "any" && !inB && !inC) return false;
      if (grp === "none" && (inB || inC)) return false;
      if (act && (!w.la || NOW() - w.la > act * 86400)) return false;
      if (fav && !isFav(w)) return false;
      if (hide && (w.tg.indexOf("bot") >= 0 || w.tg.indexOf("bundle") >= 0 || w.tg.indexOf("insider") >= 0 || w.pf)) return false;
      for (var i = 0; i < S.tags.length; i++) if (w.tg.indexOf(S.tags[i]) < 0) return false;
      return true;
    });
  }
  function renderChips(rows) {
    // todas las etiquetas siempre visibles; orden estable (por frecuencia en la chain elegida, sin filtros)
    var cnt = {}, tot = {};
    rows.forEach(function (w) { w.tg.forEach(function (t) { cnt[t] = (cnt[t] || 0) + 1; }); });
    chainWallets().forEach(function (w) { w.tg.forEach(function (t) { tot[t] = (tot[t] || 0) + 1; }); });
    var ids = D.tags.map(function (t) { return t.id; });
    ids.sort(function (a, b) { return (tot[b] || 0) - (tot[a] || 0) || tagDef(a).label.localeCompare(tagDef(b).label); });
    $("chips").innerHTML = ids.map(function (id) {
      var t = tagDef(id), sel = S.tags.indexOf(id) >= 0, n = cnt[id] || 0;
      var tip = t.help + (sel ? " · Seleccionada: clic para quitarla." : n ? " · Con los filtros actuales: " + n + " wallet" + (n > 1 ? "s" : "") + (S.tags.length ? " (añadiéndola, quedarían " + n + ")" : "") + "." : " · Con los filtros actuales daría 0 resultados.");
      return '<button class="chip c-' + t.color + (sel ? " sel" : "") + (!sel && !n ? " zero" : "") + '" data-tag="' + id + '" data-tip="' + esc(tip) + '"' + (sel ? ' aria-pressed="true"' : "") + ">" + esc(t.label) + '<span class="n">' + n + "</span></button>";
    }).join("");
    var box = $("tagSel");
    if (!S.tags.length) { box.classList.add("hide"); box.innerHTML = ""; return; }
    box.classList.remove("hide");
    box.innerHTML = '<span class="lbl">Filtrando por ' + (S.tags.length > 1 ? "<b>todas</b> estas etiquetas (" + S.tags.length + ")" : "la etiqueta") + ":</span> " +
      S.tags.map(function (id) { var t = tagDef(id); return '<span class="tag c-' + t.color + '">' + esc(t.label) + '<span class="x" data-untag="' + id + '" title="Quitar">✕</span></span>'; }).join("") +
      ' <span class="muted small">→ ' + rows.length + " wallet" + (rows.length === 1 ? "" : "s") + '</span> <button class="clrtags right" id="clrTags">✕ Quitar filtros de etiquetas</button>';
  }
  var COLS = [
    ["sel", '<input type="checkbox" class="selcb" id="selAll" title="Seleccionar todas las visibles">', "l"], ["fav", "⭐", "l"], ["i", "#", ""], ["a", "Wallet", "l"], ["x", "Ver en", "l"], ["c", "Chain", "l"], ["ct", "Coins", "l"], ["sc", "Score", ""], ["pn", "PnL nativo", ""], ["pu", "PnL USD", ""], ["roi", "ROI", ""],
    ["wr", "Win rate", ""], ["tk", "Tokens", ""], ["tr", "Trades", ""], ["ho", "Hold med.", ""], ["en", "Entrada med.", ""], ["sz", "Tamaño med.", ""], ["bal", "Saldo", ""],
    ["ft", "Edad", ""], ["la", "Última act.", ""], ["cl", "Cluster / bundles", "l"], ["tg", "Etiquetas", "l"]
  ];
  var NOSORT = { x: 1, i: 1, sel: 1 };
  var TIPS = { ct: "Coins escaneados en los que participó (comprador temprano o con trades del token). Clic para ver solo esa coin", sel: "Marca wallets para exportarlas como grupo (Axiom / GMGN / CSV)", i: "🌱 = wallet fresca: primera transacción (o primer fondeo) hace menos de 7 días", x: "Abrir la wallet en el explorador de la chain y en GMGN (si la chain está soportada)", tr: "Nº total de trades (compras + ventas) en los últimos 30 días. '≥' = historial truncado, como mínimo", a: "Dirección y alias (✎ para editarlo; se guarda en tu box con PIN y se puede buscar)", pn: "PnL realizado + no realizado de los últimos 30 días, en la moneda nativa de la chain (SOL, ETH, BNB…)", pu: "PnL nativo × precio actual (Kraken)", roi: "PnL ÷ total invertido en compras", wr: "% de tokens con beneficio (entre paréntesis, nº de tokens)", ho: "Mediana del tiempo entre la primera compra y la venta", en: "Mediana del tiempo desde el lanzamiento del token hasta su primera compra", sz: "Compra media en moneda nativa", bal: "Saldo nativo actual", ft: "Antigüedad de la wallet (primera transacción). '>' = historial demasiado largo, como mínimo", sc: "Score 0-100: win rate, PnL, ROI, consistencia, nº de tokens y entrada temprana; penaliza bots, bundles, insiders y rugs" };
  function sortVal(w, k) {
    if (k === "fav") return isFav(w) ? 1 : 0;
    if (k === "ft") return w.ft ? -w.ft : null;
    if (k === "cl") return (w.cl ? 1000 : 0) + (w.bu || []).length;
    if (k === "tg") return w.tg.length;
    if (k === "a") return w.al || w.a;
    if (k === "tr") return w.tr == null ? null : w.tr;
    if (k === "c") return w.c;
    if (k === "ct") return walletCoins(w).length;
    return w[k];
  }
  function renderTable(onlyFavs) {
    var rows = filtered(onlyFavs);
    renderChips(rows);
    var k = S.sort, asc = S.asc;
    rows.sort(function (a, b) { var x = sortVal(a, k), y = sortVal(b, k); if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1; return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); });
    $("fCount").textContent = rows.length + " de " + chainWallets().length;
    var th = COLS.map(function (c) { return '<th class="' + c[2] + (S.sort === c[0] ? " sorted" + (S.asc ? " asc" : "") : "") + '"' + (NOSORT[c[0]] ? "" : ' data-sort="' + c[0] + '"') + (TIPS[c[0]] ? ' data-tip="' + esc(TIPS[c[0]]) + '"' : "") + ">" + c[1] + "</th>"; }).join("");
    document.querySelector("#tbl thead").innerHTML = "<tr>" + th + "</tr>";
    var bIdx = {}; D.bundles.forEach(function (b, i) { bIdx[b.id] = i + 1; });
    S.visible = rows.slice(0, S.limit).map(key);
    var html = rows.slice(0, S.limit).map(function (w, i) {
      var tags = w.tg.slice(0, 7).map(function (t) { var d = tagDef(t); return '<span class="tag c-' + d.color + '" data-tip="' + esc(d.help) + '">' + esc(d.label) + "</span>"; }).join("") + (w.tg.length > 7 ? '<span class="mini">+' + (w.tg.length - 7) + "</span>" : "");
      var grp = (w.cl ? '<span class="cl">' + w.cl + "</span> " : "") + ((w.bu || []).length ? '<span class="mini">' + w.bu.length + " bundle" + (w.bu.length > 1 ? "s" : "") + "</span>" : "");
      return '<tr data-k="' + esc(key(w)) + '">' +
        '<td class="l"><input type="checkbox" class="selcb" data-sel="' + esc(key(w)) + '"' + (S.sel[key(w)] ? " checked" : "") + "></td>" +
        '<td class="l"><button class="star ' + (isFav(w) ? "on" : "") + '" data-star="' + esc(key(w)) + '">' + (isFav(w) ? "★" : "☆") + "</button></td>" +
        '<td class="nowrap">' + (i + 1) + (isFresh(w) ? '<span class="leaf" data-tip="' + esc(freshTip(w)) + '">🌱</span>' : "") + "</td>" +
        '<td class="l">' + groupBadges(w) + '<span class="addr">' + (w.al ? '<b class="alias">' + esc(w.al) + "</b> " : "") + esc(short(w.a)) + '</span><button class="copy" data-copy="' + esc(w.a) + '" title="Copiar">📋</button><button class="edit" data-alias="' + esc(key(w)) + '" title="Editar alias (PIN)">✎</button></td>' +
        '<td class="l nowrap">' + exLinks(w) + "</td>" +
        '<td class="l"><span class="chainpill">' + esc(chainName(w.c)) + "</span></td>" +
        '<td class="l nowrap">' + coinChips(w, 3) + "</td>" +
        '<td><span class="score" style="background:' + scoreColor(w.sc) + '">' + (w.sc == null ? "–" : Math.round(w.sc)) + "</span></td>" +
        "<td>" + signed(w.pn, 2) + "</td><td>" + usd(w.pu) + "</td><td>" + (w.roi == null ? "–" : signed(w.roi * 100, 0, "%")) + "</td>" +
        "<td>" + (w.wr == null ? "–" : Math.round(w.wr * 100) + '% <span class="mini">(' + w.tk + ")</span>") + "</td>" +
        "<td>" + (w.tk == null ? "–" : w.tk) + "</td><td>" + (w.tr == null ? "–" : (w.ht ? "≥" : "") + w.tr) + "</td><td>" + dur(w.ho) + "</td><td>" + dur(w.en) + "</td><td>" + num(w.sz) + "</td><td>" + num(w.bal) + "</td>" +
        "<td>" + (w.ft ? (w.at ? "&gt;" : "") + dur(NOW() - w.ft) : "–") + "</td><td>" + ago(w.la) + "</td>" +
        '<td class="l">' + grp + '</td><td class="tags">' + tags + "</td></tr>";
    }).join("");
    document.querySelector("#tbl tbody").innerHTML = html || '<tr><td colspan="' + COLS.length + '" class="l muted" style="padding:20px">No hay wallets con estos filtros. ' + (D.wallets.length ? "" : "Escanea un token en «Escanear / Añadir».") + "</td></tr>";
    $("moreBtn").classList.toggle("hide", rows.length <= S.limit);
    var all = $("selAll"); if (all) all.checked = S.visible.length > 0 && S.visible.every(function (k) { return S.sel[k]; });
    renderSelBar();
  }

  // ---------------------------------------------------------------- exportar grupo (Axiom / GMGN / CSV / JSON)
  function renderSelBar() {
    var n = Object.keys(S.sel).length, el = $("selBar");
    el.classList.toggle("hide", !n);
    if (n) el.innerHTML = "<b>" + n + "</b> wallet" + (n > 1 ? "s" : "") + ' seleccionada' + (n > 1 ? "s" : "") + ' <button class="exp" data-export="sel">📤 Exportar grupo</button> <button class="ghost" id="selClear">Quitar selección</button>';
  }
  var EMOJIS = ["🐸", "🧠", "🐋", "🎯", "👻", "🕵️", "🤖", "📦", "🕸️", "💀", "🔥", "⚡", "💎", "🚀", "🐀", "⭐"];
  var GMGN_CH = { solana: "sol", ethereum: "eth", bsc: "bsc", base: "base" };
  function exportSource(spec) {
    var p = spec.split(":"), kind = p[0];
    if (kind === "sel") {
      var keys = S.visible.filter(function (k) { return S.sel[k]; }).concat(Object.keys(S.sel).filter(function (k) { return S.visible.indexOf(k) < 0; }));
      return { title: "Selección manual", source: "selección", name: "selección", emoji: "⭐", ws: keys.map(function (k) { var i = k.indexOf(":"); return { c: k.slice(0, i), a: k.slice(i + 1) }; }) };
    }
    if (kind === "cluster") {
      var c = D.clusters[+p[1]]; if (!c) return null;
      var ws = c.w.map(function (a) { return D.wIdx[c.c + ":" + a] || { c: c.c, a: a }; }).sort(function (x, y) { return (y.sc || 0) - (x.sc || 0); });
      var org = {}; ws.forEach(function (w) { (w.or || []).forEach(function (t) { org[t] = (org[t] || 0) + 1; }); });
      var top = Object.keys(org).sort(function (x, y) { return org[y] - org[x]; })[0];
      return { title: "Cluster " + c.id + " · " + chainName(c.c), source: "cluster:" + c.id, name: "cluster " + (top ? tokenSym(c.c, top) : c.id), emoji: "🕸️", ws: ws.map(function (w) { return { c: w.c, a: w.a }; }) };
    }
    if (kind === "bundle") {
      var b = D.bundles[+p[1]]; if (!b) return null;
      return { title: "Bundle del slot/bloque " + b.s + " · " + tokenSym(b.c, b.t), source: "bundle:" + b.id, name: "bundle " + tokenSym(b.c, b.t), emoji: "📦", ws: b.w.map(function (a) { return { c: b.c, a: a }; }) };
    }
    if (kind === "btok") {
      var ch = p[1], tok = p.slice(2).join(":"), seen = {}, list = [];
      D.bundles.filter(function (x) { return x.c === ch && x.t === tok; }).sort(function (x, y) { return x.s - y.s; }).forEach(function (x) { x.w.forEach(function (a) { if (!seen[a]) { seen[a] = 1; list.push({ c: ch, a: a }); } }); });
      return { title: "Todos los bundlers de " + tokenSym(ch, tok), source: "bundlers:" + tok, name: "bundlers " + tokenSym(ch, tok), emoji: "📦", ws: list };
    }
    return null;
  }
  function openExport(spec) {
    var src = exportSource(spec); if (!src || !src.ws.length) { toast("Grupo vacío"); return; }
    EXP = src; EXP.alerts = true; EXP.inName = false;
    var chains = {}; src.ws.forEach(function (w) { chains[w.c] = 1; }); EXP.chains = Object.keys(chains);
    $("modalIn").innerHTML = '<div class="row" style="flex-wrap:nowrap;align-items:flex-start"><h3>📤 Exportar grupo · ' + esc(src.title) + ' <span class="mini">(' + src.ws.length + ' wallets)</span></h3><button class="ghost right" data-mclose>✕</button></div>' +
      '<div class="row" style="gap:10px;flex-wrap:wrap;margin:6px 0"><label>Emoji <input type="text" id="gEmoji" value="' + esc(src.emoji) + '" style="width:60px;font-size:16px;text-align:center" maxlength="8"></label>' +
      '<label>Nombre del grupo <input type="text" id="gName" value="' + esc(src.name) + '" maxlength="40" style="width:220px"></label>' +
      '<label class="chk"><input type="checkbox" id="gAlerts" checked> Alertas activadas (Axiom)</label>' +
      '<label class="chk" data-tip="Axiom y GMGN ya muestran el emoji delante del nombre (campo aparte). Márcalo si quieres que además vaya escrito dentro del nombre."><input type="checkbox" id="gInName"> Emoji también dentro del nombre</label></div>' +
      '<div class="emojis">' + EMOJIS.map(function (e) { return '<button data-emo="' + e + '">' + e + "</button>"; }).join("") + "</div>" +
      '<div class="mini" style="margin:6px 0">Cada wallet se etiqueta como <b id="gPrev"></b> … (numeradas por score). Nombres cortos se leen mejor en las alertas.</div>' +
      (EXP.chains.length > 1 ? '<div class="warnbox">Este grupo mezcla chains (' + EXP.chains.map(chainName).join(", ") + '). Axiom y GMGN importan por chain: mejor exporta cada chain por separado (filtra la tabla por chain y selecciona).</div>' : "") +
      fmtBlock("axiom", "Axiom · Wallet Tracker → Import", '<span class="badge-ok" data-tip="Formato de importación del Wallet Tracker de Axiom según guías públicas (PANews/AiCoin), la documentación de BonkBot y conversores de terceros. No hay página oficial de Axiom con el esquema ni se ha probado la importación en Axiom desde aquí.">formato corroborado (no oficial)</span>', "Abre el Wallet Tracker (abajo a la izquierda) → Import → pega o sube el fichero." + (EXP.chains[0] !== "solana" ? " ⚠️ Axiom es sobre todo Solana: puede no aceptar wallets EVM." : "")) +
      fmtBlock("gmgn", "GMGN · Follow / Wallet tracker → importación masiva", '<span class="badge-ok" data-tip="Formato oficial según docs.gmgn.ai/index/wallets-import-export: array JSON con address, name y emoji. Máximo 2.000 wallets seguidas.">formato oficial (docs GMGN)</span>', "gmgn.ai/follow → botón de importar/exportar arriba a la derecha → pega el texto. Máx. 2.000 wallets seguidas en total." + (GMGN_CH[EXP.chains[0]] ? " Selecciona antes la chain <b>" + GMGN_CH[EXP.chains[0]].toUpperCase() + "</b> en GMGN." : " ⚠️ GMGN no soporta esta chain.")) +
      fmtBlock("csv", "CSV simple (dirección,nombre)", '<span class="badge-guess">genérico</span>', "Para hojas de cálculo, bots de Telegram (/wimport) u otras herramientas.") +
      fmtBlock("json", "JSON simple", '<span class="badge-guess">genérico</span>', "Dirección, chain y etiqueta completa.") +
      '<div class="row" style="margin-top:12px"><button class="primary" id="grpSave">💾 Guardar grupo en el box (PIN)</button><span class="mini">Guardado, su emoji aparece junto a esas wallets en la tabla y puedes buscar por el nombre del grupo. Privado: no se publica.</span></div>';
    $("modal").classList.remove("hide");
    updateExport();
  }
  function fmtBlock(id, title, badge, help) {
    return '<div class="fmt"><div class="hd"><b>' + title + "</b> " + badge + ' <span class="right"></span><button class="ghost" data-cpout="' + id + '">📋 Copiar</button><button class="ghost" data-dl="' + id + '">⬇️ Descargar</button></div>' +
      '<div class="mini" style="margin-bottom:6px">' + help + '</div><textarea readonly id="out-' + id + '" spellcheck="false"></textarea></div>';
  }
  function expOutputs() {
    var em = ($("gEmoji").value || "").trim(), nm = ($("gName").value || "").trim() || "grupo", al = $("gAlerts").checked, inName = $("gInName").checked;
    var full = function (i) { return (em ? em + " " : "") + nm + " " + i; };
    var nameOnly = function (i) { return (inName && em ? em + " " : "") + nm + " " + i; };
    var ws = EXP.ws;
    var csvq = function (x) { return /[",\n]/.test(x) ? '"' + x.replace(/"/g, '""') + '"' : x; };
    return {
      em: em, nm: nm, prev: full(1),
      axiom: JSON.stringify(ws.map(function (w, i) { return { trackedWalletAddress: w.a, name: nameOnly(i + 1), emoji: em || "👀", alertsOn: al }; }), null, 2),
      gmgn: JSON.stringify(ws.map(function (w, i) { return { address: w.a, name: nameOnly(i + 1), emoji: em || "👀" }; }), null, 2),
      csv: "address,name\n" + ws.map(function (w, i) { return w.a + "," + csvq(full(i + 1)); }).join("\n") + "\n",
      json: JSON.stringify(ws.map(function (w, i) { return { address: w.a, chain: w.c, name: full(i + 1) }; }), null, 2)
    };
  }
  function updateExport() {
    if (!EXP) return; var o = expOutputs();
    $("gPrev").textContent = o.prev;
    ["axiom", "gmgn", "csv", "json"].forEach(function (id) { $("out-" + id).value = o[id]; });
    document.querySelectorAll("#modalIn [data-emo]").forEach(function (b) { b.classList.toggle("on", b.dataset.emo === o.em); });
  }
  function slug(x) { return (x || "grupo").toLowerCase().normalize("NFD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "grupo"; }
  function download(id) {
    var o = expOutputs(), ext = id === "csv" ? "csv" : "json";
    var name = (id === "axiom" ? "axiom-" : id === "gmgn" ? "gmgn-" : "wallets-") + slug(o.nm) + "." + ext;
    var blob = new Blob([o[id]], { type: id === "csv" ? "text/csv;charset=utf-8" : "application/json" });
    var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    toast("Descargado: " + esc(name));
  }
  function saveGroup() {
    if (!needPin()) return;
    var o = expOutputs();
    api("/api/groups", { op: "save", group: { name: o.nm, emoji: o.em, chain: EXP.chains.length === 1 ? EXP.chains[0] : null, wallets: EXP.ws.map(function (w) { return w.a; }), source: EXP.source } })
      .then(function (r) { setGroups(r.groups); toast("Grupo guardado: " + esc(o.prev.replace(/ 1$/, ""))); renderAll(); })
      .catch(function (e) { toast("No se pudo guardar: " + esc(e.message)); });
  }
  function closeModal() { $("modal").classList.add("hide"); EXP = null; }

  // ---------------------------------------------------------------- detalle
  function openWallet(k) {
    var w = D.wIdx[k]; if (!w) return;
    var tags = w.tg.map(function (t) { var d = tagDef(t); return '<span class="tag c-' + d.color + '" data-tip="' + esc(d.help) + '">' + esc(d.label) + "</span>"; }).join("");
    var toks = (w.or || []).map(function (t) { var tk = D.tokens.find(function (x) { return x.a === t; }); return esc(tk && tk.sy ? tk.sy : short(t)); }).join(", ");
    var links = (w.lk || []).map(function (l) { return '<a href="#" data-open="' + esc(w.c + ":" + l[0]) + '">' + esc(short(l[0])) + "</a> <span class='mini'>(" + esc(l[1]) + ")</span>"; }).join("<br>");
    $("drawerIn").innerHTML = '<div class="row"><h3 style="margin:0">' + (w.al ? esc(w.al) + " · " : "") + '<span class="addr">' + esc(short(w.a)) + '</span></h3><button class="ghost right" data-close>✕</button></div>' +
      '<div class="mini addr" style="margin:6px 0;word-break:break-all">' + esc(w.a) + ' <button class="copy" data-copy="' + esc(w.a) + '">📋</button></div>' +
      '<div class="row small">' + exLinks(w) + (w.c === "solana" ? '<a class="xl" target="_blank" rel="noopener" href="https://app.axiom.trade/@' + esc(w.a) + '">Axiom</a>' : "") +
      ' <button class="ghost" data-star="' + esc(k) + '">' + (isFav(w) ? "★ Quitar de Mis wallets" : "☆ Añadir a Mis wallets") + '</button> <button class="ghost" data-alias="' + esc(k) + '">✎ ' + (w.al ? "Cambiar alias" : "Poner alias") + '</button> <button class="ghost" data-rescan="' + esc(k) + '">Re-escanear</button></div>' +
      '<div style="margin:10px 0">' + tags + "</div>" +
      '<div class="kv">' +
      "<div>Chain</div><div>" + esc(chainName(w.c)) + "</div>" +
      "<div>Score</div><div><span class='score' style='background:" + scoreColor(w.sc) + "'>" + (w.sc == null ? "–" : Math.round(w.sc)) + "</span></div>" +
      "<div>PnL " + D.window_days + "d</div><div>" + signed(w.pn, 3) + " " + nat(w.c) + " · " + usd(w.pu) + "</div>" +
      "<div>ROI</div><div>" + (w.roi == null ? "–" : signed(w.roi * 100, 1, "%")) + "</div>" +
      "<div>Trades 30d</div><div>" + (w.tr == null ? "–" : (w.ht ? "≥" : "") + w.tr) + "</div>" +
      "<div>Win rate</div><div>" + (w.wr == null ? "–" : Math.round(w.wr * 100) + "% (" + w.w + "/" + w.tk + " tokens, " + (w.tr || 0) + " swaps)") + "</div>" +
      "<div>Hold / entrada</div><div>" + dur(w.ho) + " · " + dur(w.en) + "</div>" +
      "<div>Tamaño medio</div><div>" + num(w.sz, 3) + " " + nat(w.c) + "</div>" +
      "<div>Saldo</div><div>" + num(w.bal, 3) + " " + nat(w.c) + "</div>" +
      "<div>Edad</div><div>" + (w.ft ? (w.at ? "más de " : "") + dur(NOW() - w.ft) + " (" + fmtDate(w.ft) + ")" : "–") + (isFresh(w) ? ' <span class="leaf" data-tip="' + esc(freshTip(w)) + '">🌱 fresca</span>' : "") + "</div>" +
      "<div>Último fondeo</div><div>" + (w.lf ? ago(w.lf) + " (" + fmtDate(w.lf) + ")" : "–") + "</div>" +
      "<div>Última actividad</div><div>" + ago(w.la) + "</div>" +
      "<div>Fondeada por</div><div>" + (w.fu ? '<a href="' + esc(explorer(w.c, w.fu)) + '" target="_blank" rel="noopener">' + esc(short(w.fu)) + "</a>" + (w.fl ? " · <b>" + esc(w.fl) + "</b>" : "") : "–") + "</div>" +
      "<div>Cluster</div><div>" + (w.cl ? '<a href="#" data-cluster="' + esc(w.cl) + '" class="cl">' + esc(w.cl) + "</a>" : "–") + "</div>" +
      "<div>Bundles</div><div>" + ((w.bu || []).length || "–") + "</div>" +
      "<div>Copia a</div><div>" + (w.cp ? '<a href="#" data-open="' + esc(w.c + ":" + w.cp) + '">' + esc(short(w.cp)) + "</a>" : "–") + "</div>" +
      "<div>Mejor ranking temprano</div><div>" + (w.er ? "#" + w.er : "–") + "</div>" +
      "<div>Coins escaneados</div><div>" + (walletCoins(w).length ? coinChips(w, 50) : "–") + "</div>" +
      "<div>Vínculos</div><div>" + (links || "–") + "</div>" +
      "<div>Escaneada</div><div>" + ago(w.ls) + (w.ht ? " · historial truncado" : "") + "</div></div>";
    $("drawer").classList.remove("hide");
  }

  // ---------------------------------------------------------------- otras pestañas
  function tokenSym(c, a) { var t = D.tokens.find(function (x) { return x.a === a && x.c === c; }); return t && t.sy ? t.sy : short(a); }
  function walletLink(c, a) { var w = D.wIdx[c + ":" + a]; return '<a href="#" data-open="' + esc(c + ":" + a) + '" class="addr">' + esc(w && w.al ? w.al : short(a)) + "</a>" + (w && w.sc != null ? ' <span class="score" style="background:' + scoreColor(w.sc) + ';font-size:10px;padding:0 4px">' + Math.round(w.sc) + "</span>" : ""); }
  function renderBundles() {
    var ctb = coinTok();
    var bs = ctb ? coinBundles(ctb) : D.bundles.filter(function (b) { return !S.chain || b.c === S.chain; });
    var by = {}; bs.forEach(function (b) { (by[b.c + ":" + b.t] = by[b.c + ":" + b.t] || []).push(b); });
    var h = '<div class="box"><h3>Bundles detectados (' + bs.length + ')</h3><div class="note">Bundle = 2+ wallets que compran en el mismo slot/bloque en los primeros instantes del token (3+ si es más tarde). Suele indicar un mismo operador (Jito bundles, bots de lanzamiento).</div></div>';
    Object.keys(by).forEach(function (k) {
      var p = k.split(":"), list = by[k].sort(function (a, b) { return a.s - b.s; });
      h += '<div class="box"><h3>' + esc(tokenSym(p[0], p[1])) + ' <span class="chainpill">' + esc(chainName(p[0])) + '</span> <span class="mini">' + list.length + ' bundles</span> <button class="exp" data-export="btok:' + esc(k) + '">📤 Exportar todos los bundlers</button></h3><div style="overflow:auto"><table class="list"><tr><th>Slot/bloque</th><th>Hora</th><th>Wallets</th><th>Total</th><th></th></tr>' +
        list.map(function (b) { return "<tr><td>" + b.s + "</td><td>" + fmtDate(b.ts) + "</td><td>" + b.w.map(function (a) { return walletLink(b.c, a); }).join(" · ") + "</td><td>" + (b.n == null ? "–" : num(b.n) + " " + nat(b.c)) + '</td><td><button class="exp" data-export="bundle:' + D.bundles.indexOf(b) + '">📤 Exportar</button></td></tr>'; }).join("") + "</table></div></div>";
    });
    $("bundlesBox").innerHTML = h;
  }
  function renderTokens() {
    var ts = D.tokens.filter(function (t) { return !S.chain || t.c === S.chain; });
    $("tokensBox").innerHTML = '<div class="box"><h3>Tokens escaneados (' + ts.length + ')</h3><div style="overflow:auto"><table class="list"><tr><th>Token</th><th>Chain</th><th>CA</th><th>Lanzado</th><th>MC</th><th>Escaneado</th><th>Compradores tempranos</th><th>Wallets analizadas</th><th>Bundles</th><th></th></tr>' +
      ts.map(function (t) {
        return "<tr><td><b>" + esc(t.sy || "?") + '</b> <span class="mini">' + esc(t.nm || "") + '</span></td><td><span class="chainpill">' + esc(chainName(t.c)) + '</span></td><td class="addr">' + esc(short(t.a)) + ' <button class="copy" data-copy="' + esc(t.a) + '">📋</button></td><td>' + fmtDate(t.lt) + "</td><td>" + (t.mc ? "$" + num(t.mc, 0) : "–") + "</td><td>" + ago(t.sa) + (t.st === "scanning" ? " (en curso)" : "") + "</td><td>" + t.nb + "</td><td>" + (t.nw || 0) + "</td><td>" + t.bd + '</td><td><button class="ghost" data-coin="' + esc(t.c + ":" + t.a) + '">👛 Ver wallets</button> <button class="ghost" data-rescan-token="' + esc(t.c + ":" + t.a) + '">Re-escanear</button> <a target="_blank" rel="noopener" href="https://dexscreener.com/' + esc(t.c) + "/" + esc(t.a) + '">DexS</a></td></tr>';
      }).join("") + "</table></div></div>";
  }
  function renderConn() {
    var ctc = coinTok(), wsetc = {}; if (ctc) chainWallets().forEach(function (w) { wsetc[w.a] = 1; });
    var cs = D.clusters.filter(function (c) { return ctc ? c.c === ctc.c && c.w.some(function (a) { return wsetc[a]; }) : (!S.chain || c.c === S.chain); });
    var cross = D.cross.filter(function (c) { return ctc ? c.c === ctc.c && c.t.indexOf(ctc.a) >= 0 : (!S.chain || c.c === S.chain); });
    var h = '<div class="box"><h3>🔁 Cruce de coins: wallets que entraron temprano (top 50) en 2+ tokens escaneados (' + cross.length + ')</h3>' +
      (cross.length ? '<div style="overflow:auto"><table class="list"><tr><th>Wallet</th><th>Chain</th><th>Nº tokens</th><th>Ranking medio</th><th>Tokens</th><th>Etiquetas</th></tr>' + cross.slice(0, 200).map(function (x) {
        var w = D.wIdx[x.c + ":" + x.a];
        return "<tr><td>" + walletLink(x.c, x.a) + '</td><td><span class="chainpill">' + esc(chainName(x.c)) + "</span></td><td><b>" + x.n + "</b></td><td>#" + x.ar + "</td><td>" + x.t.map(function (t) { return esc(tokenSym(x.c, t)); }).join(", ") + "</td><td>" + (w ? w.tg.slice(0, 4).map(function (t) { var d = tagDef(t); return '<span class="tag c-' + d.color + '">' + esc(d.label) + "</span>"; }).join("") : "") + "</td></tr>";
      }).join("") + "</table></div>" : '<div class="muted">Aparecerán cuando escanees 2 o más tokens (ideal: tus runners).</div>') + "</div>";
    h += '<div class="box"><h3>Clusters (' + cs.length + ') · ' + D.stats.links + ' vínculos</h3><div class="note">Un cluster une wallets por: mismo fondeador (también a 2 saltos), una fondea a otra, transferencias entre ellas, mismo exchange en pocos minutos con importes parecidos, fondeo sincronizado antes de comprar el mismo token o bundles repetidos.</div></div>';
    cs.forEach(function (c) {
      var ws = c.w.map(function (a) { return D.wIdx[c.c + ":" + a]; }).filter(Boolean).sort(function (a, b) { return (b.sc || 0) - (a.sc || 0); });
      var kinds = {}; ws.forEach(function (w) { (w.lk || []).forEach(function (l) { kinds[l[1]] = (kinds[l[1]] || 0) + 1; }); });
      var pn = ws.reduce(function (s, w) { return s + (w.pn || 0); }, 0);
      h += '<div class="box"><h3><span class="cl">' + esc(c.id) + '</span> <span class="chainpill">' + esc(chainName(c.c)) + "</span> " + c.n + ' wallets · PnL conjunto ' + signed(pn, 2) + " " + nat(c.c) + ' <span class="mini">' + Object.keys(kinds).map(function (k) { return esc(k); }).join(" · ") + '</span> <button class="exp" data-export="cluster:' + D.clusters.indexOf(c) + '">📤 Exportar grupo</button></h3>' +
        ws.slice(0, 60).map(function (w) { return walletLink(w.c, w.a); }).join(" · ") + (ws.length > 60 ? " …" : "") + "</div>";
    });
    $("connBox").innerHTML = h;
  }
  function renderScan() {
    var k = D.keys || {};
    var warn = [];
    if (!k.helius) warn.push("Solana: falta la API key de Helius.");
    if (!k.etherscan && !k.blockscout) warn.push("EVM: falta la API key de Etherscan o Blockscout (sin ella no se pueden escanear Ethereum, BNB, Base…).");
    var chains = ['<option value="auto">Detectar automáticamente</option>'].concat(Object.keys(D.chains).map(function (c) { return '<option value="' + c + '"' + (S.scanChain === c ? " selected" : "") + ">" + esc(D.chains[c].name) + "</option>"; })).join("");
    $("scanBox").innerHTML = '<div class="box"><h3>Escanear token / añadir wallets</h3><div class="form">' +
      '<div class="row"><div class="seg"><button data-kind="tokens" class="' + (S.kind === "tokens" ? "on" : "") + '">Tokens (CA)</button><button data-kind="wallets" class="' + (S.kind === "wallets" ? "on" : "") + '">Wallets sueltas</button></div>' +
      '<label>Chain <select id="scanChain">' + chains + "</select></label></div>" +
      '<textarea id="scanItems" placeholder="' + (S.kind === "tokens" ? "Pega uno o varios CAs (o links de DexScreener/pump.fun/GMGN), separados por espacios o saltos de línea" : "Pega una o varias wallets") + '"></textarea>' +
      '<div class="row"><input id="scanPin" type="password" inputmode="numeric" autocomplete="current-password" placeholder="PIN" value="' + esc(PIN) + '" style="width:120px"><button class="primary" id="scanGo">Lanzar escaneo</button><span id="scanMsg" class="muted"></span></div>' +
      (warn.length ? '<div class="warnbox">' + warn.map(esc).join("<br>") + "</div>" : "") +
      (!BOX_OK ? '<div class="warnbox">El box no responde ahora mismo: no se pueden lanzar escaneos hasta que vuelva (los datos que ves siguen disponibles).</div>' : BOX_PIN_SET === false ? '<div class="warnbox">Falta configurar el PIN en el box.</div>' : "") +
      '<div class="note">Cómo funciona: el escaneo entra en la cola del box (pestaña <b>Trabajos</b>). El box saca los primeros compradores del token (hasta 150 wallets), lee 30 días de actividad de cada una y recalcula métricas, score, etiquetas, bundles y clusters. Con el plan gratis de Helius suele tardar 1-5 min por token. Wallets ya analizadas en las últimas 12 h no se vuelven a leer (ahorra créditos).</div>' +
      "</div></div>";
  }
  var STL = { pending: "pendiente", running: "en curso", done: "hecho", error: "error" };
  function renderJobs() {
    var js = D.jobs || [];
    var run = js.filter(function (j) { return j.status === "running" || j.status === "pending"; }).length;
    $("jobBadge").textContent = run; $("jobBadge").classList.toggle("hide", !run);
    $("jobsBox").innerHTML = '<div class="box"><h3>Trabajos</h3><div style="overflow:auto"><table class="list"><tr><th>Estado</th><th>Tipo</th><th>Chain</th><th>Direcciones</th><th>Progreso / resultado</th><th>Creado</th><th>Duración</th></tr>' +
      (js.map(function (j) {
        var d = j.finished && j.started ? dur(j.finished - j.started) : j.started ? dur(NOW() - j.started) + "…" : "–";
        return '<tr><td><span class="st ' + j.status + '">' + (STL[j.status] || j.status) + "</span></td><td>" + (j.kind === "tokens" ? "Tokens" : "Wallets") + "</td><td>" + esc(j.chain === "auto" ? "auto" : chainName(j.chain)) + '</td><td class="addr">' + j.items.slice(0, 4).map(function (a) { return esc(short(a)); }).join("<br>") + (j.items.length > 4 ? "<br>+" + (j.items.length - 4) : "") + "</td><td>" + esc(j.message || j.progress || "") + (j.status === "done" && j.kind === "tokens" ? " " + j.items.map(function (a) { var t = findTokenByCA(a); return t ? '<button class="ghost" data-coin="' + esc(t.c + ":" + t.a) + '">👛 Ver wallets' + (j.items.length > 1 ? " " + esc(t.sy || short(t.a)) : "") + "</button>" : ""; }).join(" ") : "") + "</td><td>" + fmtDate(j.created) + "</td><td>" + d + "</td></tr>";
      }).join("") || '<tr><td colspan="7" class="muted">Sin trabajos todavía.</td></tr>') + "</table></div></div>";
  }
  function renderFavExtra() {
    var el = $("favExtra");
    if (S.tab !== "favs") { el.classList.add("hide"); return; }
    el.classList.remove("hide");
    var A = S.alerts;
    el.innerHTML = '<div class="box"><h3>🔔 Alertas de Telegram: entradas grandes de dinero en tus ⭐</h3>' +
      (A ? '<div class="row"><label class="chk"><input type="checkbox" id="alEn"' + (A.enabled ? " checked" : "") + "> Activadas</label>" +
        '<label>Avisar si entra ≥ <input type="number" id="alUsd" value="' + esc(A.min_inflow_usd) + '" style="width:90px"> $</label>' +
        '<label>o ≥ <input type="number" id="alSol" step="any" value="' + esc((A.min_inflow_native || {}).solana) + '" style="width:70px"> SOL</label>' +
        '<label class="chk"><input type="checkbox" id="alOnly"' + (A.only_from_funder_or_cex ? " checked" : "") + "> Solo si viene de un exchange, un fondeador conocido o una wallet de la base</label>" +
        '<label>Revisar cada <input type="number" id="alMin" value="' + esc(A.poll_minutes) + '" style="width:60px"> min</label>' +
        '<button class="primary" id="alSave">Guardar</button></div>' + (S.telegram ? "" : '<div class="warnbox" style="margin-top:8px">Telegram aún no está conectado (falta el token del bot): las alertas se guardan en el box y se verán aquí, pero no llegan al móvil.</div>') +
        '<div id="alList" class="small" style="margin-top:8px"></div>'
        : '<div class="muted">Introduce tu PIN (pestaña Escanear) con el box encendido para ver y cambiar las alertas.</div> <button class="ghost" id="alLoad">Cargar ajustes</button>') + "</div>";
  }
  function loadAlerts() {
    if (!needPin()) return;
    api("/api/settings", {}).then(function (r) { S.alerts = r.alerts; S.telegram = r.telegram; renderFavExtra(); return api("/api/alerts", {}); })
      .then(function (r) { if (!r) return; var el = $("alList"); if (el) el.innerHTML = (r.alerts || []).slice(0, 20).map(function (a) { return fmtDate(a.ts) + " · " + walletLink(a.chain, a.wallet) + " recibió <b>" + num(a.amount_native) + " " + nat(a.chain) + "</b> (~$" + num(a.amount_usd, 0) + ") de " + esc(short(a.sender)) + (a.sender_label ? " · " + esc(a.sender_label) : ""); }).join("<br>") || '<span class="muted">Sin alertas todavía.</span>'; })
      .catch(function (e) { toast(esc(e.message)); });
  }

  // ---------------------------------------------------------------- render general
  function renderAll() {
    if (!D) return;
    resolvePendingCoin(); fillCoins(); renderCoinHead();
    renderSources(); renderCards(); renderJobs();
    $("updated").textContent = "Datos: " + ago(D.generated) + (BOX_OK ? " · box en directo" : "");
    var t = S.tab;
    ["wallets", "bundles", "tokens", "conn", "scan", "jobs"].forEach(function (x) { $("tab-" + x).classList.toggle("hide", !(x === t || (x === "wallets" && t === "favs"))); });
    if (t === "wallets" || t === "favs") { renderFavExtra(); renderTable(t === "favs"); }
    if (t === "bundles") renderBundles();
    if (t === "tokens") renderTokens();
    if (t === "conn") renderConn();
    if (t === "scan" && !document.activeElement.closest("#scanBox")) renderScan();
    if (t === "jobs") renderJobs();
  }
  function goto(tab) {
    S.tab = tab; document.querySelectorAll("#tabs button").forEach(function (b) { b.classList.toggle("on", b.dataset.tab === tab); });
    if (tab === "favs" && !S.alerts && PIN && BOX_OK) loadAlerts();
    if (tab === "scan") renderScan();
    renderAll(); window.scrollTo(0, 0);
  }
  function toggleFav(k) {
    var w = D.wIdx[k] || { c: k.split(":")[0], a: k.split(":").slice(1).join(":") };
    if (FAVS[k]) { delete FAVS[k]; syncFavs("remove", w); } else { FAVS[k] = { alias: w.al || null }; if (!PIN && BOX_OK) needPin(); syncFavs("add", w, w.al); }
    save("wh_favs", FAVS); renderAll();
    if (!$("drawer").classList.contains("hide")) openWallet(k);
  }
  function submitScan() {
    var items = $("scanItems").value.trim(); if (!items) { toast("Pega al menos un CA o wallet"); return; }
    PIN = $("scanPin").value.trim(); if (!PIN) { toast("Falta el PIN"); return; }
    localStorage.setItem("wh_pin", PIN);
    var btn = $("scanGo"); btn.disabled = true; $("scanMsg").textContent = "Enviando…";
    var chain = $("scanChain").value; S.scanChain = chain;
    api("/api/scan", { kind: S.kind, chain: chain, items: items }).then(function (r) {
      $("scanMsg").innerHTML = '<span class="pos">En cola (' + r.items.length + ")</span>"; $("scanItems").value = "";
      toast("Escaneo en cola: míralo en Trabajos"); setTimeout(function () { loadData(); goto("jobs"); }, 1200);
    }).catch(function (e) { $("scanMsg").innerHTML = '<span class="neg">' + esc(e.message) + "</span>"; }).then(function () { btn.disabled = false; });
  }
  function quickScan(kind, chain, items) {
    if (!needPin()) return;
    api("/api/scan", { kind: kind, chain: chain, items: items }).then(function () { toast("En cola: míralo en Trabajos"); setTimeout(loadData, 1500); }).catch(function (e) { toast(esc(e.message)); });
  }

  // ---------------------------------------------------------------- eventos
  document.addEventListener("click", function (e) {
    if (e.target.closest("a[target=_blank]")) return; // enlaces externos: no abrir el detalle
    var t = e.target.closest("[data-sel],#selAll,#selClear,[data-export],[data-emo],[data-cpout],[data-dl],#grpSave,[data-mclose],[data-untag],#clrTags,[data-tab],[data-goto],[data-star],[data-copy],[data-sort],[data-tag],[data-open],[data-close],[data-coin],[data-cluster],[data-kind],[data-alias],[data-rescan],[data-rescan-token],#scanGo,#alSave,#alLoad,#fClear,#moreBtn,tr[data-k]");
    if (!t) { if (e.target.id === "drawer") $("drawer").classList.add("hide"); if (e.target.id === "modal") closeModal(); return; }
    if (t.dataset.sel) { e.stopPropagation(); if (t.checked) S.sel[t.dataset.sel] = 1; else delete S.sel[t.dataset.sel]; var all0 = $("selAll"); if (all0) all0.checked = S.visible.length > 0 && S.visible.every(function (k) { return S.sel[k]; }); return renderSelBar(); }
    if (t.id === "selAll") { S.visible.forEach(function (k) { if (t.checked) S.sel[k] = 1; else delete S.sel[k]; }); document.querySelectorAll("#tbl [data-sel]").forEach(function (c) { c.checked = !!S.sel[c.dataset.sel]; }); return renderSelBar(); }
    if (t.id === "selClear") { S.sel = {}; return renderAll(); }
    if (t.dataset.export) { e.preventDefault(); e.stopPropagation(); return openExport(t.dataset.export); }
    if (t.dataset.emo) { $("gEmoji").value = t.dataset.emo; return updateExport(); }
    if (t.dataset.cpout) { return copy($("out-" + t.dataset.cpout).value, t.dataset.cpout.toUpperCase() + " (" + EXP.ws.length + " wallets)"); }
    if (t.dataset.dl) return download(t.dataset.dl);
    if (t.id === "grpSave") return saveGroup();
    if (t.hasAttribute("data-mclose")) return closeModal();
    if (t.dataset.untag) { e.stopPropagation(); S.tags = S.tags.filter(function (x) { return x !== t.dataset.untag; }); return renderAll(); }
    if (t.id === "clrTags") { S.tags = []; return renderAll(); }
    if (t.dataset.tab) return goto(t.dataset.tab);
    if (t.dataset.goto) { e.preventDefault(); return goto(t.dataset.goto); }
    if (t.dataset.star) { e.stopPropagation(); return toggleFav(t.dataset.star); }
    if (t.dataset.copy) { e.stopPropagation(); return copy(t.dataset.copy); }
    if (t.dataset.sort) { if (t.dataset.sort === S.sort) S.asc = !S.asc; else { S.sort = t.dataset.sort; S.asc = ["a", "c", "ho", "en", "ft"].indexOf(S.sort) >= 0; } return renderAll(); }
    if (t.dataset.tag) { var i = S.tags.indexOf(t.dataset.tag); if (i >= 0) S.tags.splice(i, 1); else S.tags.push(t.dataset.tag); return renderAll(); }
    if (t.dataset.open) { e.preventDefault(); return openWallet(t.dataset.open); }
    if (t.hasAttribute("data-close")) return $("drawer").classList.add("hide");
    if (t.hasAttribute("data-coin")) { e.preventDefault(); e.stopPropagation(); $("drawer").classList.add("hide"); var kc = t.dataset.coin; if (kc) { S.tab = "wallets"; document.querySelectorAll("#tabs button").forEach(function (b) { b.classList.toggle("on", b.dataset.tab === "wallets"); }); window.scrollTo(0, 0); } return setCoin(kc); }
    if (t.dataset.cluster) { e.preventDefault(); $("drawer").classList.add("hide"); return goto("conn"); }
    if (t.dataset.kind) { S.kind = t.dataset.kind; return renderScan(); }
    if (t.dataset.alias) { e.stopPropagation(); return editAlias(t.dataset.alias); }
    if (t.dataset.rescan) { var w2 = D.wIdx[t.dataset.rescan]; return quickScan("wallets", w2.c, w2.a); }
    if (t.dataset.rescanToken) { var p = t.dataset.rescanToken.split(":"); return quickScan("tokens", p[0], p[1]); }
    if (t.id === "scanGo") return submitScan();
    if (t.id === "alLoad") return loadAlerts();
    if (t.id === "alSave") {
      var body = { alerts: { enabled: $("alEn").checked, min_inflow_usd: +$("alUsd").value || 0, only_from_funder_or_cex: $("alOnly").checked, poll_minutes: +$("alMin").value || 5, min_inflow_native: { solana: +$("alSol").value || 0 } } };
      return api("/api/settings", body).then(function (r) { S.alerts = r.alerts; toast("Alertas guardadas"); }).catch(function (er) { toast(esc(er.message)); });
    }
    if (t.id === "fClear") { ["fSearch", "fScore", "fPnl", "fWr", "fTok", "fTrades", "fFund"].forEach(function (id) { $(id).value = ""; }); $("fGroup").value = ""; $("fAct").value = ""; $("fFav").checked = false; $("fHide").checked = false; $("fFresh").checked = false; S.tags = []; return renderAll(); }
    if (t.id === "moreBtn") { S.limit += 300; return renderAll(); }
    if (t.dataset.k) return openWallet(t.dataset.k);
  });
  ["fSearch", "fScore", "fPnl", "fWr", "fTok", "fTrades", "fFund", "fGroup", "fAct", "fFav", "fHide", "fFresh"].forEach(function (id) { $(id).addEventListener("input", function () { S.limit = 300; renderAll(); }); });
  $("chainSel").addEventListener("change", function () { S.chain = this.value; var t = coinTok(); if (t && S.chain && t.c !== S.chain) return setCoin(""); renderAll(); });
  $("coinSel").addEventListener("change", function () { setCoin(this.value); });
  window.addEventListener("hashchange", function () { readHash(); renderAll(); });
  // tooltips (ratón y pulsación larga en móvil)
  var tip = $("tip"), lp;
  function showTip(el, x, y) { var h = el.getAttribute("data-tip"); if (!h) return; tip.textContent = h; tip.classList.remove("hide"); var r = tip.getBoundingClientRect(); tip.style.left = Math.min(x + 12, innerWidth - r.width - 8) + "px"; tip.style.top = Math.min(y + 14, innerHeight - r.height - 8) + "px"; }
  document.addEventListener("mouseover", function (e) { var el = e.target.closest("[data-tip]"); if (el) showTip(el, e.clientX, e.clientY); else tip.classList.add("hide"); });
  document.addEventListener("touchstart", function (e) { var el = e.target.closest("[data-tip]"); if (!el) { tip.classList.add("hide"); return; } var t0 = e.touches[0]; lp = setTimeout(function () { showTip(el, t0.clientX, t0.clientY); }, 450); }, { passive: true });
  document.addEventListener("touchend", function () { clearTimeout(lp); setTimeout(function () { tip.classList.add("hide"); }, 2500); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { $("drawer").classList.add("hide"); closeModal(); } });
  $("modal").addEventListener("input", updateExport);

  // ---------------------------------------------------------------- arranque
  function fillChains() { if (!D) return; var sel = $("chainSel"); if (sel.options.length > 1) return; Object.keys(D.chains).forEach(function (c) { var o = document.createElement("option"); o.value = c; o.textContent = D.chains[c].name; sel.appendChild(o); }); }
  function tick() {
    loadData().then(fillChains).catch(function (e) { $("updated").textContent = "No se pudieron cargar los datos (" + e.message + ")"; });
    var running = D && (D.jobs || []).some(function (j) { return j.status === "running" || j.status === "pending"; });
    setTimeout(function () { checkBox().then(tick); }, (running && BOX_OK ? 10 : CFG.refreshSeconds) * 1000);
  }
  findBox().then(function () { if (PIN && BOX_OK) { syncFavs("list"); syncAliases(); syncGroups(); } tick(); });
  function readHash() {
    var h = decodeURIComponent(location.hash.slice(1));
    if (!h) return;
    if (h.indexOf("coin=") === 0) {
      var ca = h.slice(5).trim(), cur = coinTok();
      if (!cur || (cur.a !== ca && cur.a.toLowerCase() !== ca.toLowerCase())) { S.coin = ""; S.pendingCoin = ca; resolvePendingCoin(); }
      if (S.tab !== "wallets" && S.tab !== "favs") S.tab = "wallets";
    } else if (["wallets", "favs", "bundles", "tokens", "conn", "scan", "jobs"].indexOf(h) >= 0) S.tab = h;
  }
  if (location.hash) { readHash(); setTimeout(function () { goto(S.tab); }, 300); }
})();
