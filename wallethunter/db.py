"""Base de datos SQLite acumulativa."""
import json, os, sqlite3, threading, time
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets(
  chain TEXT, address TEXT, alias TEXT, first_seen INTEGER, last_scanned INTEGER,
  status TEXT DEFAULT 'pending', error TEXT,
  funder TEXT, funder_label TEXT, funder_amount REAL, funded_at INTEGER,
  first_tx_ts INTEGER, age_truncated INTEGER DEFAULT 0, history_truncated INTEGER DEFAULT 0,
  balance_native REAL, last_activity INTEGER, n_txs_30d INTEGER,
  metrics TEXT, tags TEXT, score REAL, cluster_id TEXT, origins TEXT, prefiltered INTEGER DEFAULT 0,
  PRIMARY KEY(chain, address));
CREATE TABLE IF NOT EXISTS swaps(
  chain TEXT, wallet TEXT, token TEXT, tx TEXT, ts INTEGER, slot INTEGER, side TEXT,
  token_amount REAL, native_amount REAL, dex TEXT,
  PRIMARY KEY(chain, tx, wallet, token, side));
CREATE INDEX IF NOT EXISTS swaps_w ON swaps(chain, wallet);
CREATE INDEX IF NOT EXISTS swaps_t ON swaps(chain, token, slot);
CREATE TABLE IF NOT EXISTS transfers(
  chain TEXT, wallet TEXT, counterparty TEXT, direction TEXT, asset TEXT,
  amount REAL, amount_native REAL, ts INTEGER, tx TEXT,
  PRIMARY KEY(chain, tx, wallet, counterparty, asset, direction));
CREATE INDEX IF NOT EXISTS tr_w ON transfers(chain, wallet);
CREATE INDEX IF NOT EXISTS tr_c ON transfers(chain, counterparty);
CREATE TABLE IF NOT EXISTS tokens(
  chain TEXT, address TEXT, symbol TEXT, name TEXT, launch_ts INTEGER, launch_slot INTEGER,
  creator TEXT, pools TEXT, price_native REAL, price_usd REAL, mc REAL, liq REAL,
  scanned_at INTEGER, n_wallets INTEGER, status TEXT, info TEXT, ath_usd REAL,
  PRIMARY KEY(chain, address));
CREATE TABLE IF NOT EXISTS token_buyers(
  chain TEXT, token TEXT, wallet TEXT, first_buy_ts INTEGER, first_buy_slot INTEGER, rank INTEGER,
  native_spent REAL, kind TEXT DEFAULT 'early', PRIMARY KEY(chain, token, wallet));
CREATE TABLE IF NOT EXISTS token_prices(
  chain TEXT, token TEXT, symbol TEXT, price_native REAL, price_usd REAL, launch_ts INTEGER,
  liq REAL, is_pumpfun INTEGER, updated INTEGER, PRIMARY KEY(chain, token));
CREATE TABLE IF NOT EXISTS bundles(
  id TEXT PRIMARY KEY, chain TEXT, token TEXT, slot INTEGER, ts INTEGER, wallets TEXT, native_total REAL);
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, created INTEGER, kind TEXT, chain TEXT, items TEXT, status TEXT,
  progress TEXT, message TEXT, started INTEGER, finished INTEGER, origin TEXT);
CREATE TABLE IF NOT EXISTS favorites(chain TEXT, address TEXT, alias TEXT, added INTEGER, PRIMARY KEY(chain, address));
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, chain TEXT, wallet TEXT, amount_native REAL,
  amount_usd REAL, sender TEXT, sender_label TEXT, tx TEXT UNIQUE, sent INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS funders(
  chain TEXT, address TEXT, funder TEXT, funder_label TEXT, amount REAL, ts INTEGER, first_tx_ts INTEGER, checked INTEGER,
  PRIMARY KEY(chain, address));
-- fondeadores (wallet madre) de cada ⭐, para vigilarlos
CREATE TABLE IF NOT EXISTS fav_funders(chain TEXT, wallet TEXT, funder TEXT, label TEXT, source TEXT, ts INTEGER, PRIMARY KEY(chain, wallet, funder));
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
-- alias privados (como los favoritos: solo los sirve el box con PIN, no van al data.json público)
-- grupos exportados/guardados desde la web (privados, con PIN): nombre + emoji + wallets
CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY, name TEXT, emoji TEXT, chain TEXT, wallets TEXT, source TEXT, created INTEGER, updated INTEGER);
-- lista de bloqueo opcional: wallets borradas que no se vuelven a añadir al re-escanear ese coin (token '*' = cualquiera)
CREATE TABLE IF NOT EXISTS blocklist(chain TEXT, address TEXT, token TEXT, added INTEGER, PRIMARY KEY(chain, address, token));
-- comprobaciones de «Conexiones entre wallets» (privadas: las sirve el box con PIN; el id es el del trabajo)
CREATE TABLE IF NOT EXISTS checks(id TEXT PRIMARY KEY, created INTEGER, chain TEXT, wallets TEXT, status TEXT, result TEXT, credits INTEGER, summary TEXT, max_score INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS aliases(chain TEXT, address TEXT, alias TEXT, updated INTEGER, PRIMARY KEY(chain, address));
CREATE TABLE IF NOT EXISTS svc_cache(chain TEXT, address TEXT, hub INTEGER, n INTEGER, distinct_cp INTEGER, span_h REAL, why TEXT, ts INTEGER, PRIMARY KEY(chain, address));
"""

_local = threading.local()


def connect(path=None):
    path = path or DB_PATH
    c = getattr(_local, "conns", {}).get(path)
    if c is None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        c = sqlite3.connect(path, timeout=60, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript(SCHEMA)
        # migración: alias antiguos (columna wallets.alias / favoritos) -> tabla privada
        c.execute("INSERT OR IGNORE INTO aliases SELECT chain, address, alias, strftime('%s','now') FROM wallets WHERE alias IS NOT NULL AND alias<>''")
        c.execute("INSERT OR IGNORE INTO aliases SELECT chain, address, alias, added FROM favorites WHERE alias IS NOT NULL AND alias<>''")
        for col in ("kind TEXT DEFAULT 'inflow'", "data TEXT"):     # alertas de varios tipos (entrada grande, dormida, fondeador)
            try:
                c.execute("ALTER TABLE alerts ADD COLUMN " + col)
            except sqlite3.OperationalError:
                pass
        c.commit()
        if not hasattr(_local, "conns"):
            _local.conns = {}
        _local.conns[path] = c
    return c


def kv_get(c, key, default=None):
    r = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def kv_set(c, key, value):
    c.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value)))
    c.commit()


def upsert_wallet(c, chain, address, **fields):
    now = int(time.time())
    c.execute("INSERT OR IGNORE INTO wallets(chain,address,first_seen,status) VALUES(?,?,?,'pending')", (chain, address, now))
    if fields:
        cols = ",".join(f"{k}=?" for k in fields)
        vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
        c.execute(f"UPDATE wallets SET {cols} WHERE chain=? AND address=?", (*vals, chain, address))


def add_origin(c, chain, address, token):
    r = c.execute("SELECT origins FROM wallets WHERE chain=? AND address=?", (chain, address)).fetchone()
    o = json.loads(r[0]) if r and r[0] else []
    if token not in o:
        o.append(token)
        c.execute("UPDATE wallets SET origins=? WHERE chain=? AND address=?", (json.dumps(o), chain, address))


def insert_swaps(c, rows):
    c.executemany("INSERT OR REPLACE INTO swaps(chain,wallet,token,tx,ts,slot,side,token_amount,native_amount,dex) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  [(r["chain"], r["wallet"], r["token"], r["tx"], r["ts"], r.get("slot"), r["side"], r["token_amount"], r["native_amount"], r.get("dex")) for r in rows])


def insert_transfers(c, rows):
    c.executemany("INSERT OR REPLACE INTO transfers(chain,wallet,counterparty,direction,asset,amount,amount_native,ts,tx) VALUES(?,?,?,?,?,?,?,?,?)",
                  [(r["chain"], r["wallet"], r["counterparty"], r["direction"], r["asset"], r.get("amount"), r.get("amount_native"), r["ts"], r["tx"]) for r in rows])


def aliases(c):
    return [dict(r) for r in c.execute("SELECT chain, address, alias, updated FROM aliases ORDER BY updated DESC")]


def set_alias(c, chain, address, alias):
    alias = (str(alias).strip()[:40] if alias else "") or None
    if alias:
        c.execute("INSERT INTO aliases(chain,address,alias,updated) VALUES(?,?,?,strftime('%s','now')) ON CONFLICT(chain,address) DO UPDATE SET alias=excluded.alias, updated=excluded.updated",
                  (chain, address, alias))
    else:
        c.execute("DELETE FROM aliases WHERE chain=? AND address=?", (chain, address))
    c.commit()
    return alias


def groups(c):
    out = []
    for r in c.execute("SELECT * FROM groups ORDER BY updated DESC"):
        d = dict(r); d["wallets"] = json.loads(d["wallets"] or "[]"); out.append(d)
    return out


def save_group(c, g):
    import re, time, hashlib
    name = str(g.get("name") or "").strip()[:40]
    emoji = str(g.get("emoji") or "").strip()[:8]
    ws = g.get("wallets") or []
    if not name or not isinstance(ws, list) or not ws:
        raise ValueError("faltan nombre o wallets")
    ws = [str(w).strip() for w in ws if isinstance(w, str) and 20 <= len(w.strip()) <= 64][:2000]
    if not ws:
        raise ValueError("wallets no válidas")
    chain = str(g.get("chain") or "")[:20] or None
    gid = str(g.get("id") or "")[:40] or hashlib.sha1((name + emoji + ",".join(ws)).encode()).hexdigest()[:12]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", gid):
        raise ValueError("id no válido")
    now = int(time.time())
    c.execute("""INSERT INTO groups(id,name,emoji,chain,wallets,source,created,updated) VALUES(?,?,?,?,?,?,?,?)
                 ON CONFLICT(id) DO UPDATE SET name=excluded.name, emoji=excluded.emoji, chain=excluded.chain, wallets=excluded.wallets, source=excluded.source, updated=excluded.updated""",
              (gid, name, emoji, chain, json.dumps(ws), str(g.get("source") or "")[:60], now, now))
    c.commit()
    return gid


def delete_group(c, gid):
    c.execute("DELETE FROM groups WHERE id=?", (str(gid),)); c.commit()
