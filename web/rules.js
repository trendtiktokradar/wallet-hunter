/* Reglas puras del panel: escape, tres estados de etiqueta y quitar ruido.
   Sin DOM, para poder probarlas aparte del panel. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.WHRules = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var NOISE = ["bot", "sniper", "bundle", "one_hit", "insuficiente", "una_vez"];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function tagState(tags, xtags, id) {
    return tags.indexOf(id) >= 0 ? "inc" : xtags.indexOf(id) >= 0 ? "exc" : "";
  }

  function cycle(tags, xtags, id) {
    var st = tagState(tags, xtags, id);
    tags = tags.filter(function (x) { return x !== id; });
    xtags = xtags.filter(function (x) { return x !== id; });
    if (st === "") tags.push(id);
    else if (st === "inc") xtags.push(id);
    return { tags: tags, xtags: xtags, state: st === "" ? "inc" : st === "inc" ? "exc" : "" };
  }

  function noiseOn(xtags, noise, known) {
    var have = noise.filter(function (id) { return known[id]; });
    return have.length > 0 && have.every(function (id) { return xtags.indexOf(id) >= 0; });
  }

  function toggleNoise(tags, xtags, noise, known) {
    var on = noiseOn(xtags, noise, known);
    noise.forEach(function (id) {
      if (!known[id]) return;
      tags = tags.filter(function (x) { return x !== id; });
      xtags = xtags.filter(function (x) { return x !== id; });
      if (!on) xtags.push(id);
    });
    return { tags: tags, xtags: xtags, hidden: !on };
  }

  function passesTags(walletTags, include, exclude, skipX) {
    var i, j;
    for (i = 0; i < include.length; i++) if (walletTags.indexOf(include[i]) < 0) return false;
    for (j = 0; j < exclude.length; j++) if (exclude[j] !== skipX && walletTags.indexOf(exclude[j]) >= 0) return false;
    return true;
  }

  return { NOISE: NOISE, esc: esc, tagState: tagState, cycle: cycle, noiseOn: noiseOn, toggleNoise: toggleNoise, passesTags: passesTags };
});
