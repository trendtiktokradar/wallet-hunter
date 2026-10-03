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
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
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
