// Configuración del panel. En local lee ./data.json; publicado, lee la rama "data" de GitHub
// y, si el box está encendido, los datos en directo y la cola a través del túnel del box.
(function () {
  var USER = "trendtiktokradar", REPO = "wallet-hunter";
  var local = /^(localhost|127\.0\.0\.1|0\.0\.0\.0)$/.test(location.hostname) || location.protocol === "file:";
  window.WH_CONFIG = {
    dataUrl: local ? "data.json" : "https://raw.githubusercontent.com/" + USER + "/" + REPO + "/data/data.json",
    boxJsonUrl: "https://api.github.com/repos/" + USER + "/" + REPO + "/contents/box.json?ref=data",
    fallbackUrl: "data.json",
    vercelQueue: "/api/queue",
    local: local,
    refreshSeconds: 60
  };
})();
