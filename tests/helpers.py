"""Fixtures sintéticas con la forma real de las respuestas de Helius (RPC jsonParsed y Enhanced API)."""
WSOL = "So11111111111111111111111111111111111111112"


def rpc_tx(sig, slot, ts, signer, others=(), native=None, tokens=None, transfers=(), programs=(), err=None, fee=5000):
    """native: {cuenta: (pre_lamports, post_lamports)}; tokens: [(owner, mint, pre_ui, post_ui)]"""
    keys = [signer] + [k for k in (native or {}) if k != signer] + list(others) + list(programs)
    keys = list(dict.fromkeys(keys))
    pre = [(native or {}).get(k, (10**9, 10**9))[0] for k in keys]
    post = [(native or {}).get(k, (10**9, 10**9))[1] for k in keys]
    preT, postT = [], []
    for i, (o, m, a, b) in enumerate(tokens or []):
        preT.append({"accountIndex": 100 + i, "mint": m, "owner": o, "uiTokenAmount": {"uiAmountString": str(a), "decimals": 6}})
        postT.append({"accountIndex": 100 + i, "mint": m, "owner": o, "uiTokenAmount": {"uiAmountString": str(b), "decimals": 6}})
    ins = [{"program": "system", "programId": "11111111111111111111111111111111", "parsed": {"type": "transfer", "info": {"source": s, "destination": d, "lamports": l}}} for s, d, l in transfers]
    ins += [{"programId": p, "accounts": [], "data": ""} for p in programs]
    return {"slot": slot, "blockTime": ts, "transaction": {"signatures": [sig], "message": {
        "accountKeys": [{"pubkey": k, "signer": k == signer, "writable": True} for k in keys], "instructions": ins}},
        "meta": {"err": err, "fee": fee, "preBalances": pre, "postBalances": post, "preTokenBalances": preT, "postTokenBalances": postT, "innerInstructions": []}}


def enh_tx(sig, slot, ts, fee_payer, native=None, tokens=None, transfers=(), source="PUMP_FUN", type_="SWAP"):
    acc = {}
    for k, ch in (native or {}).items():
        acc.setdefault(k, {"account": k, "nativeBalanceChange": 0, "tokenBalanceChanges": []})["nativeBalanceChange"] = ch
    for o, m, amt in tokens or []:
        acc.setdefault(o + m, {"account": o + "ata", "nativeBalanceChange": 0, "tokenBalanceChanges": []})["tokenBalanceChanges"].append(
            {"userAccount": o, "tokenAccount": o + "ata", "mint": m, "rawTokenAmount": {"tokenAmount": str(int(amt * 1e6)), "decimals": 6}})
    return {"signature": sig, "slot": slot, "timestamp": ts, "feePayer": fee_payer, "source": source, "type": type_, "transactionError": None,
            "accountData": list(acc.values()), "nativeTransfers": [{"fromUserAccount": s, "toUserAccount": d, "amount": l} for s, d, l in transfers], "tokenTransfers": []}
