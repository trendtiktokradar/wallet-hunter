// Respaldo para Vercel: guarda peticiones de escaneo en queue.json de la rama "queue" (si el box está apagado,
// las recoge cuando vuelve). Necesita en Vercel: WH_PIN (mismo PIN del box) y WH_GH_TOKEN (token con Contents: write).
const OWNER = "trendtiktokradar", REPO = "wallet-hunter", BRANCH = "queue", FILE = "queue.json";
const bad = new Map();
async function gh(path, opts = {}) {
  const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/${path}`, { ...opts, headers: { Authorization: `Bearer ${process.env.WH_GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "wallet-hunter", ...(opts.headers || {}) } });
  return r;
}
module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") return res.status(405).json({ error: "solo POST" });
  if (!process.env.WH_PIN || !process.env.WH_GH_TOKEN) return res.status(503).json({ error: "Falta configurar WH_PIN / WH_GH_TOKEN en Vercel" });
  const ip = (req.headers["x-forwarded-for"] || "").split(",")[0];
  const b = bad.get(ip) || 0;
  if (b >= 10) return res.status(429).json({ error: "Demasiados PIN incorrectos" });
  const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : (req.body || {});
  if (String(body.pin || "") !== process.env.WH_PIN) { bad.set(ip, b + 1); return res.status(401).json({ error: "PIN incorrecto" }); }
  const items = String(Array.isArray(body.items) ? body.items.join(" ") : body.items || "").split(/[\s,;]+/).filter(x => /^(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})$/.test(x)).slice(0, 25);
  if (!items.length) return res.status(400).json({ error: "No hay direcciones válidas" });
  const kind = body.kind === "wallets" ? "wallets" : "tokens";
  const chain = String(body.chain || "auto").replace(/[^a-z]/g, "").slice(0, 20) || "auto";
  for (let attempt = 0; attempt < 3; attempt++) {
    let sha, q = [];
    const cur = await gh(`contents/${FILE}?ref=${BRANCH}`);
    if (cur.status === 200) { const j = await cur.json(); sha = j.sha; try { q = JSON.parse(Buffer.from(j.content, "base64").toString()); } catch (e) { q = []; } }
    else if (cur.status === 404) {
      const main = await (await gh(`git/ref/heads/main`)).json();
      await gh(`git/refs`, { method: "POST", body: JSON.stringify({ ref: `refs/heads/${BRANCH}`, sha: main.object && main.object.sha }) });
    }
    const id = "v" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    q.push({ id, kind, chain, items, t: Math.floor(Date.now() / 1000) });
    q = q.slice(-100);
    const put = await gh(`contents/${FILE}`, { method: "PUT", body: JSON.stringify({ message: "cola", branch: BRANCH, sha, content: Buffer.from(JSON.stringify(q)).toString("base64") }) });
    if (put.ok) return res.status(200).json({ ok: true, id, items, queued: "github" });
  }
  return res.status(502).json({ error: "No se pudo guardar en la cola" });
};
