"""Representación común de una transacción (sirve para Solana RPC, Helius Enhanced y EVM) y extracción
de swaps/transferencias por wallet a partir de los cambios de saldo. Reglas fijas, sin IA."""
from dataclasses import dataclass, field
from .chains import WSOL, STABLES

SOL_PROGRAMS = {
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "PUMP_FUN",
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "PUMP_AMM",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "RAYDIUM",
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": "RAYDIUM",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "RAYDIUM",
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj": "RAYDIUM_LAUNCHLAB",
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "JUPITER",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "METEORA",
    "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN": "METEORA_DBC",
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB": "METEORA",
    "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG": "METEORA",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "ORCA",
    "MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qcqUQTrG": "MOONSHOT",
}
LAMPORTS = 1e9


@dataclass
class Delta:
    chain: str
    tx: str
    ts: int
    slot: int
    fee_payer: str
    signers: set = field(default_factory=set)
    native: dict = field(default_factory=dict)          # owner -> cambio nativo (en SOL/ETH, no lamports/wei)
    tokens: dict = field(default_factory=dict)          # (owner, mint) -> cambio en unidades UI
    native_transfers: list = field(default_factory=list)  # (from, to, amount_native)
    dex: str = None
    failed: bool = False


def from_rpc(tx, chain="solana"):
    """Transacción RPC (getTransaction / getTransactionsForAddress full, encoding jsonParsed o json)."""
    meta = tx.get("meta") or {}
    t = tx.get("transaction") or {}
    msg = t.get("message") or {}
    keys = []
    signers = set()
    raw_keys = list(msg.get("accountKeys") or [])
    hdr = msg.get("header") or {}
    nsig = hdr.get("numRequiredSignatures")
    for i, k in enumerate(raw_keys):
        if isinstance(k, dict):
            keys.append(k.get("pubkey"))
            if k.get("signer"):
                signers.add(k.get("pubkey"))
        else:
            keys.append(k)
            if nsig is not None and i < nsig:
                signers.add(k)
    la = meta.get("loadedAddresses") or {}
    keys += list(la.get("writable") or []) + list(la.get("readonly") or [])
    sig = (t.get("signatures") or [None])[0]
    d = Delta(chain, sig, tx.get("blockTime") or 0, tx.get("slot") or 0, keys[0] if keys else None, signers or ({keys[0]} if keys else set()))
    d.failed = meta.get("err") is not None
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    for i, k in enumerate(keys[:len(pre)]):
        if i < len(post) and post[i] != pre[i]:
            d.native[k] = d.native.get(k, 0) + (post[i] - pre[i]) / LAMPORTS
    tb = {}
    for b in meta.get("preTokenBalances") or []:
        o = b.get("owner")
        amt = float((b.get("uiTokenAmount") or {}).get("uiAmountString") or (b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        tb[(o, b.get("mint"), b.get("accountIndex"))] = [amt, 0.0]
    for b in meta.get("postTokenBalances") or []:
        o = b.get("owner")
        amt = float((b.get("uiTokenAmount") or {}).get("uiAmountString") or (b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        tb.setdefault((o, b.get("mint"), b.get("accountIndex")), [0.0, 0.0])[1] = amt
    for (o, m, _), (a, b) in tb.items():
        if o and abs(b - a) > 0:
            d.tokens[(o, m)] = d.tokens.get((o, m), 0) + (b - a)
    progs = set()
    def walk(ins):
        for x in ins or []:
            pid = x.get("programId")
            if pid is None and isinstance(x.get("programIdIndex"), int) and x["programIdIndex"] < len(keys):
                pid = keys[x["programIdIndex"]]
            if pid:
                progs.add(pid)
            p = x.get("parsed")
            if isinstance(p, dict) and x.get("program") == "system" and p.get("type") in ("transfer", "transferWithSeed", "createAccount", "createAccountWithSeed"):
                info = p.get("info") or {}
                src = info.get("source")
                dst = info.get("destination") or info.get("newAccount")
                lam = info.get("lamports") or 0
                if src and dst and lam:
                    d.native_transfers.append((src, dst, lam / LAMPORTS))
    walk(msg.get("instructions"))
    for inner in meta.get("innerInstructions") or []:
        walk(inner.get("instructions"))
    for p, name in SOL_PROGRAMS.items():
        if p in progs or p in keys:
            if d.dex is None or name == "PUMP_FUN":
                d.dex = name
    return d


def from_enhanced(tx, chain="solana"):
    """Transacción de la Enhanced Transactions API de Helius."""
    d = Delta(chain, tx.get("signature"), tx.get("timestamp") or 0, tx.get("slot") or 0, tx.get("feePayer"), {tx.get("feePayer")})
    d.failed = bool(tx.get("transactionError"))
    for a in tx.get("accountData") or []:
        ch = a.get("nativeBalanceChange") or 0
        if ch:
            d.native[a.get("account")] = d.native.get(a.get("account"), 0) + ch / LAMPORTS
        for tbc in a.get("tokenBalanceChanges") or []:
            raw = tbc.get("rawTokenAmount") or {}
            try:
                amt = int(raw.get("tokenAmount") or 0) / (10 ** int(raw.get("decimals") or 0))
            except (ValueError, TypeError):
                amt = 0
            key = (tbc.get("userAccount"), tbc.get("mint"))
            if amt:
                d.tokens[key] = d.tokens.get(key, 0) + amt
    for nt in tx.get("nativeTransfers") or []:
        if nt.get("amount"):
            d.native_transfers.append((nt.get("fromUserAccount"), nt.get("toUserAccount"), nt["amount"] / LAMPORTS))
    src = tx.get("source")
    if src and src not in ("UNKNOWN", "SYSTEM_PROGRAM", "SOLANA_PROGRAM_LIBRARY"):
        d.dex = src
    return d


def quote_value(d, owner, native_usd):
    """Cambio total en 'nativo' del owner: nativo + wrapped nativo + stables convertidos."""
    q = d.native.get(owner, 0.0)
    stables = STABLES.get(d.chain, {})
    wrapped = WSOL if d.chain == "solana" else None
    for (o, m), amt in d.tokens.items():
        if o != owner:
            continue
        if m == wrapped or (d.chain != "solana" and m == "native_wrapped"):
            q += amt
        elif m in stables and native_usd:
            q += amt / native_usd
    return q


def is_quote(chain, mint, wrapped=None):
    return mint == WSOL or mint == "native_wrapped" or mint in STABLES.get(chain, {}) or bool(wrapped and mint == wrapped)


def extract(d, owner, native_usd=None, min_native=0.0001, wrapped=None):
    """Devuelve (swaps, transfers) del owner en esta transacción."""
    swaps, transfers = [], []
    if d.failed or not owner:
        return swaps, transfers
    q = quote_value(d, owner, native_usd)
    toks = {m: a for (o, m), a in d.tokens.items() if o == owner and not is_quote(d.chain, m, wrapped) and abs(a) > 0}
    if toks and abs(q) >= min_native:
        # swap: el token con mayor cambio en la dirección contraria al nativo
        if q < 0:
            cands = {m: a for m, a in toks.items() if a > 0}
            side = "buy"
        else:
            cands = {m: a for m, a in toks.items() if a < 0}
            side = "sell"
        if cands:
            m = max(cands, key=lambda k: abs(cands[k]))
            swaps.append({"chain": d.chain, "wallet": owner, "token": m, "tx": d.tx, "ts": d.ts, "slot": d.slot,
                          "side": side, "token_amount": abs(cands[m]), "native_amount": abs(q), "dex": d.dex})
            return swaps, transfers
    # no es swap: transferencias de tokens y nativas
    for m, a in toks.items():
        others = [o for (o, mm), aa in d.tokens.items() if mm == m and o != owner and (aa > 0) != (a > 0)]
        cp = others[0] if others else None
        transfers.append({"chain": d.chain, "wallet": owner, "counterparty": cp, "direction": "in" if a > 0 else "out",
                          "asset": m, "amount": abs(a), "amount_native": 0.0, "ts": d.ts, "tx": d.tx})
    seen = set()
    for src, dst, amt in d.native_transfers:
        if src == owner and dst != owner:
            key = (dst, "out")
        elif dst == owner and src != owner:
            key = (src, "in")
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        transfers.append({"chain": d.chain, "wallet": owner, "counterparty": key[0], "direction": key[1], "asset": "native",
                          "amount": amt, "amount_native": amt, "ts": d.ts, "tx": d.tx})
    return swaps, transfers


def early_buys(d, mint, native_usd=None, wrapped=None):
    """Compradores (firmantes) del mint en esta transacción: [(wallet, native_spent, token_amount)]."""
    out = []
    if d.failed:
        return out
    for (o, m), a in d.tokens.items():
        if m != mint or a <= 0 or o not in d.signers:
            continue
        q = quote_value(d, o, native_usd)
        if q < 0:
            out.append((o, -q, a))
    return out


def traders(d, mint, native_usd=None, wrapped=None):
    """Firmantes que compran o venden el mint en esta transacción."""
    out = []
    if d.failed:
        return out
    for (o, m), a in d.tokens.items():
        if m == mint and o in d.signers and a != 0:
            out.append(o)
    return out
