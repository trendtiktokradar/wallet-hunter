"""Bundles, clusters y señales entre wallets (insider, sniper, copy-trader, hubs, distribuidores)."""
import hashlib, json, time
from collections import defaultdict
from itertools import combinations
from .config import cfg
from . import cex
from .chains import CHAINS


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def analyze(c, chain, window_days=30, now=None):
    """Recalcula todo para una chain. Devuelve {wallet: señales} y guarda bundles en la BD."""
    now = now or int(time.time())
    since = now - window_days * 86400
    bc, cc, ct = cfg()["bundle"], cfg()["cluster"], cfg()["copy_trader"]
    wallets = {r["address"]: dict(r) for r in c.execute("SELECT * FROM wallets WHERE chain=?", (chain,))}
    sig = defaultdict(lambda: {"bundles": [], "cluster_size": 0, "cluster": None, "insider": False, "sniper": False,
                               "early_rank_min": None, "copy_of": None, "funder_is_hub": False, "distinct_out": 0, "links": []})
    tokens = {r["address"]: dict(r) for r in c.execute("SELECT * FROM tokens WHERE chain=?", (chain,))}
    is_sol = chain == "solana"
    # ---- bundles, snipers, rank temprano
    c.execute("DELETE FROM bundles WHERE chain=?", (chain,))
    bundle_rows = []
    for tok, t in tokens.items():
        buyers = [dict(r) for r in c.execute("SELECT * FROM token_buyers WHERE chain=? AND token=? AND kind='early' ORDER BY first_buy_slot, rank", (chain, tok))]
        if not buyers:
            continue
        launch_slot = t.get("launch_slot") or min(b["first_buy_slot"] for b in buyers if b["first_buy_slot"] is not None)
        launch_ts = t.get("launch_ts")
        by_slot = defaultdict(list)
        for b in buyers:
            w = b["wallet"]
            s = sig[w]
            if b["rank"] is not None:
                s["early_rank_min"] = b["rank"] if s["early_rank_min"] is None else min(s["early_rank_min"], b["rank"])
            if b["first_buy_slot"] is None:
                continue
            gap = b["first_buy_slot"] - launch_slot
            bt = max(3, CHAINS[chain].get("block_time") or 3)
            if (is_sol and gap <= 3) or (not is_sol and launch_ts and b["first_buy_ts"] and b["first_buy_ts"] - launch_ts <= bt):
                if w != t.get("creator"):
                    s["sniper"] = True
            if gap == 0 and t.get("creator") and w != t.get("creator") and is_sol:
                s["insider"] = True
            if gap <= bc["early_slots"]:
                by_slot[b["first_buy_slot"]].append(b)
        for slot, bs in by_slot.items():
            ws = sorted({b["wallet"] for b in bs if b["wallet"] != t.get("creator")})
            need = bc["min_wallets"] if slot - launch_slot <= bc["first_slots_strict"] else bc["min_wallets_late"]
            if len(ws) >= need:
                bid = hashlib.sha1(f"{chain}:{tok}:{slot}".encode()).hexdigest()[:10]
                total = sum(b["native_spent"] or 0 for b in bs)
                bundle_rows.append((bid, chain, tok, slot, bs[0]["first_buy_ts"], json.dumps(ws), total))
                for w in ws:
                    sig[w]["bundles"].append(bid)
    c.executemany("INSERT OR REPLACE INTO bundles VALUES(?,?,?,?,?,?,?)", bundle_rows)
    # ---- insiders por creador
    creators = {t["creator"]: tok for tok, t in tokens.items() if t.get("creator")}
    creator_funders = {wallets[cr]["funder"] for cr in creators if cr in wallets and wallets[cr].get("funder")}
    for w, row in wallets.items():
        f = row.get("funder")
        if w in creators:
            continue
        if f and (f in creators or (f in creator_funders and not cex.label(chain, f))):
            sig[w]["insider"] = True
        for cr in creators:
            if cr in wallets and wallets[cr].get("funder") == w:
                sig[w]["insider"] = True
    # ---- fondeadores / hubs
    funded = defaultdict(list)
    for w, row in wallets.items():
        if row.get("funder"):
            funded[row["funder"]].append(w)
    uf = UF()
    pairs = set()
    def link(a, b, kind):
        if a == b or a not in wallets or b not in wallets:
            return
        uf.union(a, b)
        key = tuple(sorted((a, b)))
        if key not in pairs:
            pairs.add(key)
            sig[a]["links"].append((b, kind)) if len(sig[a]["links"]) < 30 else None
            sig[b]["links"].append((a, kind)) if len(sig[b]["links"]) < 30 else None
    for f, ws in funded.items():
        lab = cex.label(chain, f)
        if not lab and len(ws) >= cc["hub_min_funded"]:
            for w in ws:
                sig[w]["funder_is_hub"] = True
        if f in wallets:
            for w in ws:
                link(w, f, "fondeó")
        if not lab and 2 <= len(ws) <= cc["generic_funder_max"]:
            for a, b in combinations(ws, 2):
                link(a, b, "mismo fondeador")
        if lab and len(ws) >= 2:
            # mismo exchange, en pocos minutos y con importe parecido
            ws_sorted = sorted(ws, key=lambda x: wallets[x].get("funded_at") or 0)
            for a, b in combinations(ws_sorted, 2):
                ta, tb = wallets[a].get("funded_at"), wallets[b].get("funded_at")
                aa, ab = wallets[a].get("funder_amount") or 0, wallets[b].get("funder_amount") or 0
                if ta and tb and abs(ta - tb) <= cc["cex_time_window_min"] * 60 and aa and ab and abs(aa - ab) / max(aa, ab) <= cc["cex_amount_tolerance"]:
                    link(a, b, f"mismo CEX ({lab})")
    # ---- 2 saltos: wallets cuyos fondeadores fueron fondeados por la misma dirección (no CEX)
    grand = {r["address"]: r["funder"] for r in c.execute("SELECT address, funder FROM funders WHERE chain=? AND funder IS NOT NULL AND funder_label IS NULL", (chain,))}
    by_grand = defaultdict(set)
    for f, ws in funded.items():
        gf = grand.get(f)
        if gf and not cex.label(chain, gf):
            for w in ws:
                by_grand[gf].add(w)
            if gf in wallets:
                for w in ws:
                    link(w, gf, "fondeó (2 saltos)")
    for gf, ws in by_grand.items():
        if 2 <= len(ws) <= cc["generic_funder_max"]:
            for a, b in combinations(sorted(ws), 2):
                if wallets[a].get("funder") != wallets[b].get("funder"):
                    link(a, b, "mismo fondeador (2 saltos)")
    # insiders de 2 saltos: el fondeador del fondeador es el dev o el fondeador del dev
    dev_side = set(creators) | creator_funders
    for w, row in wallets.items():
        if w in creators:
            continue
        gf = grand.get(row.get("funder"))
        if gf and gf in dev_side:
            sig[w]["insider"] = True
        if row.get("funder") and grand.get(row["funder"]) is None and row["funder"] in dev_side:
            sig[w]["insider"] = True
    # ---- transferencias directas entre wallets de la base
    outs = defaultdict(set)
    for r in c.execute("SELECT wallet, counterparty, direction, asset, amount_native FROM transfers WHERE chain=? AND ts>=?", (chain, since)):
        w, cp = r["wallet"], r["counterparty"]
        if not cp:
            continue
        if cp in wallets and (r["asset"] != "native" or (r["amount_native"] or 0) >= cc["min_transfer_native"]):
            link(w, cp, "transferencia")
        if r["direction"] == "out" and r["asset"] == "native" and (r["amount_native"] or 0) >= cc["min_transfer_native"] and not cex.label(chain, cp):
            outs[w].add(cp)
    for w, s in outs.items():
        sig[w]["distinct_out"] = len(s)
    # ---- fondeo sincronizado: varios compradores tempranos reciben fondos (de remitentes distintos o no)
    #      en la misma ventana corta antes de comprar el token -> grupo coordinado
    win = cc.get("sync_window_s", 120)
    for tok in tokens:
        rows = [dict(r) for r in c.execute("""SELECT t.wallet, t.ts FROM transfers t JOIN token_buyers b ON b.chain=t.chain AND b.wallet=t.wallet AND b.token=?
                 WHERE t.chain=? AND t.direction='in' AND t.asset='native' AND t.amount_native>=? AND t.ts BETWEEN b.first_buy_ts-? AND b.first_buy_ts
                 AND b.rank<=? ORDER BY t.ts""", (tok, chain, cc.get("sync_min_native", 0.3), cc.get("sync_lookback_s", 1800), cc.get("sync_max_rank", 150)))]
        best = {}
        for r in rows:
            best.setdefault(r["wallet"], r["ts"])  # primer fondeo dentro de la ventana previa
        items = sorted(best.items(), key=lambda x: x[1])
        i = 0
        while i < len(items):
            j = i
            # ventana anclada al primer fondeo del grupo (no encadenada), para no fusionar
            # toda la actividad de una moneda muy negociada en un solo grupo
            while j + 1 < len(items) and items[j + 1][1] - items[i][1] <= win:
                j += 1
            grp = [w for w, _ in items[i:j + 1]]
            if len(grp) >= cc.get("sync_min_wallets", 3):
                for w in grp:
                    sig[w]["fund_sync"] = True
                for a, b in zip(grp, grp[1:]):
                    link(a, b, "fondeo sincronizado")
            i = j + 1
    # ---- co-bundle repetido
    co = defaultdict(int)
    for row in bundle_rows:
        for a, b in combinations(json.loads(row[5]), 2):
            co[(a, b)] += 1
    for (a, b), k in co.items():
        if k >= 2:
            link(a, b, "bundles repetidos")
    # ---- clusters
    comps = defaultdict(list)
    for w in wallets:
        if w in uf.p:
            comps[uf.find(w)].append(w)
    comps = sorted([m for m in comps.values() if len(m) >= 2], key=lambda m: (-len(m), min(m)))
    clusters = []
    for i, members in enumerate(comps, 1):
        cid = f"{chain[:3].upper()}-C{i}"  # p.ej. SOL-C1, ETH-C2: únicos entre cadenas
        clusters.append({"id": cid, "wallets": members, "size": len(members)})
        for w in members:
            sig[w]["cluster"], sig[w]["cluster_size"] = cid, len(members)
    # ---- copy-traders (con todos los swaps de la base)
    firsts = defaultdict(dict)
    for r in c.execute("SELECT wallet, token, MIN(slot) s FROM swaps WHERE chain=? AND side='buy' AND ts>=? GROUP BY wallet, token", (chain, since)):
        if r["s"] is not None:
            firsts[r["token"]][r["wallet"]] = r["s"]
    follow = defaultdict(lambda: defaultdict(set))
    gap = ct["max_slot_gap"] if is_sol else ct["max_block_gap"]
    for tok, m in firsts.items():
        if len(m) < 2:
            continue
        items = sorted(m.items(), key=lambda x: x[1])
        for i, (lw, ls) in enumerate(items):
            for fw, fs in items[i + 1:]:
                if fs - ls > gap:
                    break
                if fs > ls:
                    follow[fw][lw].add(tok)
    for fw, leaders in follow.items():
        best = max(leaders.items(), key=lambda x: len(x[1]))
        if len(best[1]) >= ct["min_tokens"]:
            sig[fw]["copy_of"] = best[0]
    c.commit()
    return sig, clusters, len(pairs), bundle_rows
