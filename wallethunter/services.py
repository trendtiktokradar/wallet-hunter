"""Wallets de SERVICIOS compartidos (puentes, relayers, bots/terminales de trading, apps, fee payers).

Si dos wallets solo se «conectan» porque las dos usaron el mismo servicio (p. ej. el solver de Relay les mandó SOL,
o las dos pagaron comisión al fee wallet de Axiom), eso NO es un vínculo real: miles de usuarios comparten esa
dirección. Este módulo:
  1) Lista de direcciones conocidas (SERVICES) con nombre, tipo, icono, si está VERIFICADA y la fuente.
     verified=True  → copiada de documentación oficial, repo público o etiqueta de explorer (fuente indicada).
     verified=False → suposición (conocimiento previo / patrón), pendiente de confirmar.
     Extras propios: state/services_extra.json  {"solana": {"addr": "Nombre"}, "evm": {...}}  (se marcan como «manual»).
  2) Autodetección «servicio/hub»: una wallet que fondeó / pagó comisiones / movió fondos con cientos de wallets
     distintas (umbral configurable en config.json → "connect") se marca como servicio aunque no esté en la lista.
     El resultado se guarda en la tabla svc_cache (positivos 30 días, negativos 7) para no gastar créditos otra vez.
Sin IA: solo listas y umbrales."""
import json, os, time
from .config import ROOT

KINDS = {   # tipo → (icono, descripción)
    "bridge": ("🔁", "puente / relayer entre chains"),
    "bot": ("🤖", "bot / terminal de trading"),
    "app": ("📱", "app de trading / wallet"),
    "launchpad": ("🚀", "launchpad"),
    "dex": ("🔄", "agregador / DEX"),
    "mev": ("⚡", "propinas MEV"),
    "fee": ("💸", "pagador de comisiones / relayer"),
    "hub": ("🕸️", "servicio/hub (detectado por actividad)"),
}
# fuentes (para no repetir textos)
S_JITO = "docs.jito.wtf (getTipAccounts)"
S_PUMP = "github pump-fun/pump-public-docs docs/FEE_RECIPIENTS.md"
S_SPELL = "Dune spellbook: solana/…/bot_trades/solana/platforms/*.sql (fee_receiver)"
S_SPELL_EVM = "Dune spellbook: bot_trades (EVM)"
S_LLAMA = "DefiLlama dimension-adapters fees/{}"
S_RELAY = "docs.relay.link (contract addresses)"
S_DLN = "docs.debridge.com + github debridge-finance/dln-contracts"
S_MAYAN = "docs.mayan.finance (contract addresses)"
S_WORM = "wormhole.com/docs (contract addresses)"
S_ACROSS = "github across-protocol/contracts broadcast/deployed-addresses.json"
S_STG = "docs.stargate.finance (mainnet contracts)"
S_ALLB = "docs-core.allbridge.io (Allbridge Core contracts)"
GUESS = "suposición (conocimiento previo, sin fuente confirmada)"


def _add(tab, name, kind, addrs, verified, source, ignore=False):
    for a in addrs:
        tab[a] = {"name": name, "kind": kind, "verified": verified, "source": source, **({"ignore": True} if ignore else {})}


SOL, EVM = {}, {}
# ---- infraestructura que pagan TODOS los traders: se ignora del todo (ni puente ni servicio en el grafo)
_add(SOL, "Jito (propinas)", "mev", ["96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
     "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY", "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49", "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
     "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt", "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL", "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT"],
     True, S_JITO, ignore=True)
_add(SOL, "pump.fun (comisiones)", "launchpad", ["62qc2CNXwrYqQScmEdiZFFAnJR262PxWEuNQtxfafNgV", "7VtfL8fvgNfhz17qKRMjzQEXgbdpnHHHQRh54R9jP2RJ",
     "7hTckgnGnLQR6sdH7YkqFTAA7VwTfYFaZ6EhEsU3saCX", "9rPYyANsfQZw3DnDmKE3YCQF5E8oD89UXoHn9JFEhJUz", "AVmoTthdrX6tKt4nDjco2D775W2YK3sDhxPcMmzUAmTY",
     "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM", "FWsW1xNtWscwNmKv6wVsU1iTzRN6wmmk3MjxRP5tT7hz", "G5UZAVbAf46s7cKWoyKu8kYTip9DGTpbLZ2qa9Aq69dP",
     # reservadas (mayhem)
     "GesfTA3X2arioaHp8bbKdjG9vJtskViWACZoYvxp4twS", "4budycTjhs9fD6xw62VBducVTNgMgJJ5BgtKq7mAZwn6", "8SBKzEQU4nLSzcwF4a74F2iaUDQyTfjGndn6qUWBnrpR",
     "4UQeTP1T39KZ9Sfxzo3WR5skgsaP6NZa87BAkuazLEKH", "8sNeir4QsLsJdYpc9RZacohhK1Y5FLU3nC5LXgYB4aa6", "Fh9HmeLNUMVCvejxCtCL2DbYaRyBFVJ5xrWkLnMH6fdk",
     "463MEnMeGyJekNZFQSTUABBEbLnvMTALbT6ZmsxAbAdq", "6AUH3WEHucYZyC61hqpqYUWVto5qA5hjHuNQ32GNnNxA",
     # recompra (buyback)
     "5YxQFdt3Tr9zJLvkFccqXVUwhdTWJQc1fFg2YPbxvxeD", "9M4giFFMxmFGXtc3feFzRai56WbBqehoSeRE5GK7gf7", "GXPFM2caqTtQYC2cJ5yJRi9VDkpsYZXzYdwYpGnLmtDL",
     "3BpXnfJaUTiwXnJNe7Ej1rcbzqTTQUvLShZaWazebsVR", "5cjcW9wExnJJiqgLjq7DEG75Pm6JBgE1hNv4B2vHXUW6", "EHAAiTxcdDwQ3U4bU6YcMsQGaekdzLS3B5SmYo46kJtL",
     "5eHhjP8JaYkz83CWwvGU2uMUXefd3AazWGx4gpcuEEYD", "A7hAgCzFw14fejgCp387JUJRMNyz4j89JKnhtKU8piqW"], True, S_PUMP, ignore=True)
_add(SOL, "Raydium (autoridad AMM)", "dex", ["5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"], False, GUESS, ignore=True)
_add(SOL, "System Program", "dex", ["11111111111111111111111111111111"], True, "Solana (programa del sistema)", ignore=True)

# ---- puentes / relayers
_add(SOL, "Relay", "bridge", ["F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe"], True, S_RELAY + " · solver Solana")
_add(SOL, "deBridge (DLN)", "bridge", ["src5qyZHqTqecJV4aY6Cb6zDZLMDzrDKKezs22MPHr4", "dst5MGcFPoBeREFAA5E3tU5ij8m5uVYwkzkSAbsLbNo"], True, S_DLN)
_add(SOL, "Mayan", "bridge", ["mayan34VedncxdK2XobtvWFDXQASUTBXhUVzt2kKgny", "BLZRi6frs4X4DNLw56V4EXai1b6QVESN1BhHBTYM9VcY"], True, S_MAYAN)
_add(SOL, "Wormhole", "bridge", ["worm2ZoG2kUd4vFXhvjh93UUH596ayRfgQ2MgjNMTth", "wormDTUJ6AWPNvk59vGQbDvGJmqbDTdgWgAqcLBCgUb"], True, S_WORM)
_add(SOL, "Across", "bridge", ["DLv3NggMiSaef97YCkew5xKUHDh13tVGZ7tydt3ZeAru"], True, S_ACROSS)
_add(SOL, "Allbridge", "bridge", ["BrdgN2RPzEMWF96ZbnnJaUtQDQx7VRXYaHHbYCBvceWB", "CctpV8uRiXws7KZxpUXfPWy9BhCiWaeBRzsJgELvQKvu"], True, S_ALLB)
_add(SOL, "LayerZero", "bridge", ["76y77prsiCMvXMjuoZ5VRrhG5qYBrUMYTE5WgHqgjEn6"], False, GUESS + " · endpoint Solana")

# ---- apps / terminales / bots de trading (fee wallets)
_add(SOL, "Axiom", "bot", ["7LCZckF6XXGQ1hDY6HFXBKWAtiUgL9QY5vj1C4Bn1Qjj", "4V65jvcDG9DSQioUVqVPiUcUY9v6sb6HKtMnsxSKEz5S",
     "CeA3sPZfWWToFEBmw5n1Y93tnV66Vmp8LacLzsVprgxZ", "AaG6of1gbj1pbDumvbSiTuJhRCRkkUNaWVxijSbWvTJW", "7oi1L8U9MRu5zDz5syFahsiLUric47LzvJBQX6r827ws",
     "9kPrgLggBJ69tx1czYAbp7fezuUmL337BsqQTKETUEhP", "DKyUs1xXMDy8Z11zNsLnUg3dy9HZf6hYZidB6WodcaGy", "4FobGn5ZWYquoJkxMzh2VUAWvV36xMgxQ3M7uG1pGGhd",
     "76sxKrPtgoJHDJvxwFHqb3cAXWfRHFLe3VpKcLCAHSEf", "H2cDR3EkJjtTKDQKk8SJS48du9mhsdzQhy8xJx5UMqQK", "8m5GkL7nVy95G4YVUbs79z873oVKqg2afgKRmqxsiiRm",
     "4kuG6NsAFJNwqEkac8GFDMMheCGKUPEbaRVHHyFHSwWz", "8vFGAKdwpn4hk7kc1cBgfWZzpyW3MEMDATDzVZhddeQb", "86Vh4XGLW2b6nvWbRyDs4ScgMXbuvRCHT7WbUT3RFxKG",
     "DZfEurFKFtSbdWZsKSDTqpqsQgvXxmESpvRtXkAdgLwM", "5L2QKqDn5ukJSWGyqR4RPvFvwnBabKWqAqMzH4heaQNB", "DYVeNgXGLAhZdeLMMYnCw1nPnMxkBN7fJnNpHmizTrrF",
     "Hbj6XdxX6eV4nfbYTseysibp4zZJtVRRPn2J3BhGRuK9", "846ah7iBSu9ApuCyEhA5xpnjHHX7d4QJKetWLbwzmJZ8", "5BqYhuD4q1YD3DMAYkc1FeTu9vqQVYYdfBAmkZjamyZg"],
     True, S_LLAMA.format("axiom.ts") + " · fee wallets")
_add(SOL, "Axiom (cashback)", "bot", ["AxiomRXZAq1Jgjj9pHmNqVP7Lhu67wLXZJZbaK87TTSk", "AxiomRYAid8ZDhS1bJUAzEaNSr69aTWB9ATfdDLfUbnc"], True, S_LLAMA.format("axiom.ts") + " · cashbackWallets")
_add(SOL, "Axiom (router)", "bot", ["FLASHX8DrLbgeR8FcfNV1F5krxYcYMUdBkrP1EPBtxB9"], True, S_LLAMA.format("axiom.ts") + " · routerProgram")
_add(SOL, "GMGN", "bot", ["BB5dnY55FXS1e1NXqZDwCzgdYJdMCj3B92PU6Q5Fb6DT", "7sHXjs1j7sDJGVSMSPjD1b4v3FD6uRSvRWfhRdfv5BiA",
     "HeZVpHj9jLwTVtMMbzQRf6mLtFPkWNSg11o68qrbUBa3", "ByRRgnZenY6W2sddo1VJzX9o4sMU4gPDUkcmgrpGBxRy", "DXfkEGoo6WFsdL7x6gLZ7r6Hw2S6HrtrAQVPWYx2A1s9",
     "3t9EKmRiAUcQUYzTZpNojzeGP1KBAVEEbDNmy6wECQpK", "DymeoWc5WLNiQBaoLuxrxDnDRvLgGZ1QGsEoCAM7Jsrx", "dBhdrmwBkRa66XxBuAK4WZeZnsZ6bHeHCCLXa3a8bTJ",
     "6TxjC5wJzuuZgTtnTMipwwULEbMPx5JPW3QwWkdTGnrn"], True, S_LLAMA.format("gmgnai.ts") + " · fee wallets")
_add(SOL, "GMGN (referidos)", "bot", ["EzcD6Kc7GYBqBdRo6Lnv3YiwpAUtxYtb5xKWw8r7Q7H8", "Tw5uhE2uyApRCt9LqN6qMSiEeLYvzvC3P5ToEvTeGEi",
     "69SNcRC8NqjHBSXEcugCN5oFKRQoKmddmWzZYc3tqtxk", "BCNsHAH2887uUF4gdZsph28oNYbgpjgrtVk7Fi7yN67t"], True, S_LLAMA.format("gmgnai.ts") + " · referral wallets")
_add(SOL, "Photon", "bot", ["AVUCZyuT35YSuj4RH7fwiyPu82Djn2Hfg7y2ND2XcnZH"], True, S_LLAMA.format("photon.ts") + " · FEE_WALLET")
_add(SOL, "Photon (router)", "bot", ["BSfD6SHZigAfDWSjzD5Q41jw8LmKwtmjskPH9XW1mrRW"], True, "docs.bitquery.io (Photon program)")
_add(SOL, "BullX", "bot", ["9RYJ3qr5eU5xAooqVcbmdeusjcViL5Nkiq7Gske3tiKq", "F4hJ3Ee3c5UuaorKAMfELBjYCjiiLH75haZTKqTywRP3"], True, S_LLAMA.format("bullx.ts"))
_add(SOL, "Fomo", "app", ["R4rNJHaffSUotNmqSKNEfDcJE8A7zJUkaoM5Jkd7cYX"], True, S_LLAMA.format("fomo/index.ts") + " · fees USDC")
_add(SOL, "Phantom (swap fee)", "app", ["25mYnjJ2MXHZH6NvTTdA63JvjgRVcuiaj6MRiEQNs1Dq", "9yj3zvLS3fDMqi1F8zhkaWfq8TZpZWHe6cz1Sgt7djXf",
     "8psNvWTrdNTiVRNzAgsou9kETXNJm2SXZyaKuJraVRtf", "CnmA6Zb8hLrG33AT4RTzKdGv1vKwRBKQQr8iNckvv8Yg", "2rQZb9xqQGwoCMDkpabbzDB9wyPTjSPj9WNhJodTaRHm",
     "9gnLg6NtVxaASvxtADLFKZ9s8yHft1jXb1Vu6gVKvh1J", "wtpXRqKLdGc7vpReogsRugv6EFCw4HBHcxm8pFcR84a", "D1NJy3Qq3RKBG29EDRj28ozbGwnhmM5yBUp8PonSYUnm"],
     True, S_LLAMA.format("phantom.ts"))
_add(SOL, "Moonshot", "launchpad", ["3udvfL24waJcLhskRAsStNMoNUvtyXdxrWQz4hgi953N"], True, S_LLAMA.format("moonshot.ts") + " · fee wallet")
_add(SOL, "Moonshot (programa)", "launchpad", ["MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qcqUQTrG"], False, GUESS)
_add(SOL, "pump.fun (app)", "launchpad", ["6Vo3245eszAb5wuqEMw8mGdbfRUdKbHhDHP5LcaGuTAB"], True, S_LLAMA.format("pumpfun-app.ts") + " · APP_PROGRAM")
_add(SOL, "Jupiter", "dex", ["BQ72nSv9f3PRyRKCBnHLVrerrv37CYTHm5h3s9VSGQDV", "2MFoS3MPtvyQ4Wh4M9pdfPjz6UhVoNbFbGJAskCPCj3h",
     "HU23r7UoZbqTUuh3vA7emAGztFtqwTeVips789vqxxBw", "3CgvbiM3op4vjrrjH2zcrQUwsqh5veNVRjFCB9N6sRoD", "6LXutJvKUw8Q5ue2gCgKHQdAN4suWW8awzFVC6XCguFx"],
     True, S_LLAMA.format("jupiter.ts") + " · JUPITER_FEE_AUTHORITIES")
_add(SOL, "Jupiter (agregador v6)", "dex", ["JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"], False, GUESS)
_add(SOL, "Maestro", "bot", ["FRMxAnZgkW58zbYcE7Bxqsg99VWpJh6sMP5xLzAWNabN", "MaestroUL88UBnZr3wfoN7hqmNWFi3ZYCGqZoJJHE36"], True, S_SPELL + " + " + S_LLAMA.format("maestro.ts"))
_add(SOL, "Maestro (referidos)", "bot", ["BNuebGMyAsrLytsS13whc3qUqbnM9mVwUJcumD31m5zA"], True, S_LLAMA.format("maestro.ts") + " · rewardRelay")
_add(SOL, "Banana Gun", "bot", ["8r2hZoDfk5hDWJ1sDujAi2Qr45ZyZw5EQxAXiMZWLKh2", "Cj297UauzMX64FU9dKJZRUBWszJ7tEWpVheasq4CfATV",
     "HKMh8nV3ysSofRi23LsfVGLGQKB415QAEfZT96kCcVj4", "7tQiiBdKoScWQkB1RmVuML7DBGnR31cuKPEtMM7Vy5SA", "4BBNEVRgrxVKv9f7pMNE788XM1tt379X9vNjpDH2KCL7",
     "47hEzz83VFR23rLTEeVm9A7eFzjJwjvdupPPmX3cePqF", "EMbqD9Y9jLXEa3RbCR8AsEW1kVa3EiJgDLVgvKh4qNFP", "Lk693UiTzQC4vobasRS1QGcYA9D6RGYLjHp1bWreQtM"], True, S_SPELL)
for _n, _a in [("Trojan", ["BBYXdwhqbCxVRVtnuMTTxh8biNisz3ZxsnHfr44jXytR", "9yMwSPk9mrXSN7yDHUuZurAh1sjbJsfpUqjZ7SvVtdco"]),
               ("BonkBot", ["ZG98FUCjb8mJ824Gbs6RsgVmr1FhXb2oNiJHa2dwmPd"]),
               ("Padre", ["J5XGHmzrRmnYWbmw45DbYkdZAU2bwERFZ11qCDXPvFB5"]),
               ("Bloom", ["7HeD6sLLqAnKVRuSfc1Ko3BSPMNKWgGTiWLKXJF31vKM"]),
               ("Nova", ["noVaE91mUL5jTb8e9Vf6dqJdNPzJpEQ3uAdnQ8h4nVz"]),
               ("MEVX", ["3kxSQybWEeQZsMuNWMRJH4TxrhwoDwfv41TNMLRzFP5A", "BS3CyJ9rRC4Tp8G7f86r6hGvuu3XdrVGNVpbNM9U5WRZ", "4Lpvp1q69SHentfYcMBUrkgvppeEx6ovHCSYjg4UYXiq"]),
               ("Unibot", ["8FEE2ghpWPoxsypBLW87yyqmChjUbcZz41V7bzfiJqGF", "7Yr577ubghnmUTvFgB23iPw3FWReMt18WehCz2b2c9mV"]),
               ("Sol Trading Bot", ["HEPL5rTb6n1Ax6jt9z2XMPFJcDe9bSWvWQpsK7AMcbZg", "K1LRSA1DSoKBtC5DkcvnermRQ62YxogWSCZZPWQrdG5",
                                    "F34kcgMgCF7mYWkwLN3WN7KrFprr2NbwxuLvXx4fbztj", "96aFQc9qyqpjMfqdUeurZVYRrrwPJG2uPV6pceu4B1yb"]),
               ("Magnum", ["CPixcsP8LEMeUoavaHG3bdkywR8s4mZXNN3mYUgbXFev", "8dEe5BM7irAnHtJ6SSWwCRf7njgnyczS3jPrvJJs88U5"]),
               ("PepeBoost", ["G9PhF9C9H83mAjjkdJz4MDqkufiTPMJkx7TnKE1kFyCp"]),
               ("Prophet", ["55vkTc7nZoUQM92AfQG7T8bkNKD4TbWeBPRg8KjyUZre", "Hgckz7Sv8Q5grhLXxDFXGaJD6StPE7Yu8gz611nn1wKS"]),
               ("Alpha Dex", ["6qgwjhV2RQxcPffRdtQBTTEezRykQKXqhcDyv1z3r9tq"]),
               ("Shuriken", ["9cSuF94JWPb1HQzWMcifJzkoggwAtfjsojcUqny5XuJy"]),
               ("Tirador", ["3CicL2SZhjeZrMkQ4trT2di2RKaffovBADqHvRrYKsaJ"]),
               ("Bitfoot", ["BzmpLvrhZHKoXV7CW9F1AVPnie3hNh2JK3BRdHL4Zcya"]),
               ("TradeWiz", ["97VmzkjX9w8gMFS2RnHTSjtMEDbifGXBq9pgosFdFnM"]),
               ("ReadySwap", ["FNKVZeufZY2me2netdgj44tnxqPK1p5GTJkFWukWFRsN"]),
               ("Sanji", ["4E64WX4EARRMfHsvL4ZXbrbpiPcBUyrC62uawGofhdNN"]),
               ("CSwap", ["CSWAP5SpPcVjvpsA1H2n2HjNjMsRaPnZuX8H8bVJN5wy"]),
               ("Sol Gun", ["J3W8Bv948phnEYFCHaSF9CPxbsdRn2LFjBCUwC7Vo5AN"]),
               ("Falcon", ["DfkYw6zrr5cqzQHBTaXBsny54p5ip25CELUZ71hkS5LH"]),
               ("WifBot", ["W1FCMFH3D7QeQcsNSTCMTpJ9BxQdk6VzeQMLJp2dNro"]),
               ("JupBot", ["H2mM9cXi42efgwkSzTRKMVaWHrqJJx1nzNdV1NxWaHjC"]),
               ("AutoSnipe", ["CWEfC6fLi552zE2KFxhPiBAZUWdT78gMd8NGENik2zfE"]),
               ("Soul Sniper", ["6MgcmcZJXfyux7rRSsvjWaG8iegQ29KLxMtWHKoCZ7fn"]),
               ("Looter", ["3Pu1V4duyLyVpAJue1kLAfr74nGjQ3JDzj3aJjnoEXuL"]),
               ("PinkPunk", ["38e4GH49TwjXn2yARvnHueAKvU2xREtuchQahMiz3w9G", "DShXwLqk6ZHZFtdzE8HMDsGJLhEvrxgRdB5K16V28arK"])]:
    _add(SOL, _n, "bot", _a, True, S_SPELL)
_add(SOL, "Nova", "bot", ["noVakKQGTTjpHARvecAUbVnc85AatCLm3ijDFk8JXZB"], True, S_LLAMA.format("nova/index.ts"))

# ---- EVM (las direcciones se guardan en minúsculas)
_add(EVM, "Relay", "bridge", ["0xf70da97812cb96acdf810712aa562db8dfa3dbef"], True, S_RELAY + " · solver")
_add(EVM, "Relay", "bridge", ["0xa5f565650890fba1824ee0f21ebbbf660a179934", "0xf5042e6ffac5a625d4e7848e0b01373d8eb9e222", "0xb92fe925dc43a0ecde6c8b1a2709c170ec4fff4f",
     "0xbbbfd134e9b44bfb5123898ba36b01de7ab93d98", "0xccc88a9d1b4ed6b0eaba998850414b24f1c315be"], True, S_RELAY + " · receiver/router/approvalProxy")
_add(EVM, "deBridge (DLN)", "bridge", ["0xef4fb24ad0916217251f553c0596f8edc630eb66", "0xe7351fd770a37282b91d153ee690b63579d6dd7f"], True, S_DLN)
_add(EVM, "Mayan", "bridge", ["0x40ffe85a28dc9993541449464d7529a922142960", "0xd78d199f8c402e7b5cc2abe278df0412400a3bae",
     "0x337685fdab40d39bd02028545a4ffa7d287cc3e2", "0xc38e4e6a15593f908255214653d3d947ca1c2338"], True, S_MAYAN)
_add(EVM, "Wormhole", "bridge", ["0x98f3c9e6e3face36baad05fe09d375ef1464288b", "0x3ee18b2214aff97000d974cf647e7c347e8fa585",
     "0x8d2de8d2f73f1f4cab472ac9a881c9b123c79627", "0x0b2402144bb366a632d14b83f244d2e0e21bd39c", "0xb6f6d86a8f9879a9c87f643768d9efc38c1da6e7",
     "0x5a58505a96d1dbf8df91cb21b54419fc36e93fde"], True, S_WORM)
_add(EVM, "Across", "bridge", ["0x5c7bcd6e7de5423a257d81b442095a1a6ced35c5", "0x6f26bf09b1c792e3228e5467807a900a503c0281",
     "0x4e8e101924ede233c13e2d8622dc8aed2872d505", "0x9295ee1d8c5b022be115a2ad3c30c72e34e7f096", "0x09aea4b2242abc8bb4bb78d537a67a245a7bec64",
     "0xe35e9842fceaca96570b734083f4a58e8f7c5f2a"], True, S_ACROSS)
_add(EVM, "LayerZero", "bridge", ["0x1a44076050125825900e736c501f859c50fe728c"], True, "Etherscan (etiqueta LayerZero: EndpointV2) + docs.layerzero.network")
_add(EVM, "Stargate", "bridge", ["0x77b2043768d28e9c9ab44e1abfc95944bce57931", "0xc026395860db2d07ee33e05fe50ed7bd583189c7",
     "0x933597a323eb81cae705c5bc29985172fd5a3973", "0x6d6620efa72948c5f68a3c8646d58c00d3f4a980"], True, S_STG + " · Ethereum")
_add(EVM, "Allbridge", "bridge", ["0x609c690e8f7d68a59885c9132e812eebdaaf0c9e", "0x3c4fa639c8d7e65c603145adad8bd12f2358312f",
     "0x7775d63836987f444e2f14aa0fa2602204d7d3e0", "0x9ce3447b58d58e8602b7306316a5ff011b92d189", "0x001e3f136c2f804854581da55ad7660a2b35def7",
     "0x97e5bf5068ea6a9604ee25851e6c9780ff50d5ab", "0xc51397b75b783e31469bfaade79913f3f82210d6"], True, S_ALLB)
_add(EVM, "Banana Gun", "bot", ["0x3328f7f4a1d1c57c35df56bbf0c9dcafca309c49", "0x1fba6b0bbae2b74586fba407fb45bd4788b7b130",
     "0x461efe0100be0682545972ebfc8b4a13253bd602", "0xdc13700db7f7cda382e10dba643574abded4fd5b"], True, S_LLAMA.format("banana-gun-trading.ts") + " · router")
_add(EVM, "Banana Gun", "bot", ["0xf414d478934c29d9a80244a3626c681a71e53bb2", "0x37aab97476ba8dc785476611006fd5dda4eed66b"], True, S_SPELL_EVM + " · deployers")
_add(EVM, "Maestro", "bot", ["0xb0999731f7c2581844658a9d2ced1be0077b7397"], True, S_LLAMA.format("maestro.ts") + " · feeAddress")
_add(EVM, "Maestro (router)", "bot", ["0x2ff99ee6b22aedaefd8fd12497e504b18983cb14", "0x7176456e98443a7000b44e09149a540d06733965",
     "0x34b5561c30a152b5882c8924973f19df698470f4", "0x2cdf4cadf2272b77475732446ba664443277e8c1"], True, S_LLAMA.format("maestro.ts") + " · dispatcher")
_add(EVM, "Phantom (swap fee)", "app", ["0x1bcc58d165e5374d7b492b21c0a572fd61c0c2a0", "0x7afa9d836d2fccf172b66622625e56404e465dbd",
     "0x2cffed5d56eb6a17662756ca0fdf350e732c9818"], True, S_LLAMA.format("phantom.ts"))
_add(EVM, "GMGN", "bot", ["0xb8159ba378904f803639d274cec79f788931c9c8", "0xe3ed4c49c9807367784ab0d0d087d8a6815e7427"], True, S_LLAMA.format("gmgnai.ts"))
_add(EVM, "Axiom", "bot", ["0xdec29d79e8cdf009d2fa33e0558cb5648481cac3", "0x6fb4460e4bebf662fcd9bfa5ce6d6231732bb86c"], True, S_LLAMA.format("axiom.ts") + " · feeReceiver")
_add(EVM, "Flokibot", "bot", ["0xc69df57dbb39e52d5836753e6abb71a9ab271c2d", "0xffdc626bb733a8c2e906242598e2e99752dcb922",
     "0xcc5374be204990a3205eb9f93c5bd37b4f8e2c5e", "0x7b41114ecb5c09d483343116c229be3d3eb3b0fc"], True, S_SPELL_EVM)
_add(EVM, "PepeBoost", "bot", ["0xeabee4c63bd085fd906d6be5d387b5eedff83919"], True, S_SPELL_EVM)
_add(EVM, "Quemado / cero", "dex", ["0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"], True, "convención", ignore=True)

SERVICES = {"solana": SOL, "evm": EVM}
# Sin dirección pública fija (no añadidos): Privy y otros wallets embebidos (cada app elige su fee payer/relayer),
# GMGN/Photon/BullX/Fomo en EVM salvo lo listado. Para esos queda la autodetección por actividad.
NOT_FOUND = ["Privy (fee payer / relayer de wallets embebidos): no hay una dirección pública única; cada app configura la suya → autodetección",
             "Fomo (fee payer de sus wallets embebidos): no publicado → autodetección", "Relay.link: depositarias/solvers en otras chains no listadas"]


def fam(chain):
    return "solana" if chain == "solana" else "evm"


def norm(chain, a):
    return a if chain == "solana" else (a or "").lower()


_extra = {"t": 0, "d": {}}


def extra():
    """state/services_extra.json (añadidos a mano; se relee cada 60 s)."""
    if time.time() - _extra["t"] > 60:
        try:
            with open(os.path.join(ROOT, "state", "services_extra.json")) as f:
                d = json.load(f)
            _extra["d"] = {k: {(a if k == "solana" else a.lower()): v for a, v in (d.get(k) or {}).items()} for k in ("solana", "evm")}
        except Exception:
            _extra["d"] = {}
        _extra["t"] = time.time()
    return _extra["d"]


def decorate(e, auto=False):
    icon, desc = KINDS.get(e.get("kind"), KINDS["hub"])
    out = dict(e, icon=icon, kind_desc=desc, auto=auto)
    out["display"] = f"{icon} {e['name']}"
    return out


def known(chain, a):
    """Servicio de la lista (o de services_extra.json) o None. No consulta la BD."""
    if not a:
        return None
    a = norm(chain, a)
    e = SERVICES[fam(chain)].get(a)
    if e:
        return decorate(e)
    x = extra().get(fam(chain), {}).get(a)
    if x:
        e = x if isinstance(x, dict) else {"name": str(x)}
        return decorate({"name": e.get("name") or "servicio", "kind": e.get("kind") or "fee", "verified": False, "source": "manual (services_extra.json)"})
    return None


def ignored(chain, a):
    e = SERVICES[fam(chain)].get(norm(chain, a))
    return bool(e and e.get("ignore"))


HUB = {"name": "servicio/hub", "kind": "hub", "verified": False, "source": "autodetección"}


def hub_entry(why):
    return decorate(dict(HUB, why=why), auto=True)


# ---- caché de autodetección (tabla svc_cache)
POS_TTL, NEG_TTL = 30 * 86400, 7 * 86400


def cache_get(c, chain, a):
    """→ (es_hub: bool, datos) si hay caché vigente, o None."""
    if c is None:
        return None
    try:
        r = c.execute("SELECT hub, n, distinct_cp, span_h, why, ts FROM svc_cache WHERE chain=? AND address=?", (fam(chain), norm(chain, a))).fetchone()
    except Exception:
        return None
    if not r or time.time() - r[5] > (POS_TTL if r[0] else NEG_TTL):
        return None
    return bool(r[0]), {"n": r[1], "distinct": r[2], "span_h": r[3], "why": r[4], "ts": r[5]}


def cache_put(c, chain, a, hub, n=None, distinct=None, span_h=None, why=None):
    if c is None:
        return
    try:
        c.execute("INSERT OR REPLACE INTO svc_cache(chain,address,hub,n,distinct_cp,span_h,why,ts) VALUES(?,?,?,?,?,?,?,?)",
                  (fam(chain), norm(chain, a), 1 if hub else 0, n, distinct, span_h, why, int(time.time())))
        c.commit()
    except Exception:
        pass


def cached_hubs(c, chain):
    """{address: why} de los hubs autodetectados vigentes (para los escaneos: sin coste)."""
    if c is None:
        return {}
    try:
        rows = c.execute("SELECT address, why, ts FROM svc_cache WHERE chain=? AND hub=1", (fam(chain),)).fetchall()
    except Exception:
        return {}
    now = time.time()
    return {r[0]: r[1] for r in rows if now - r[2] <= POS_TTL}


def label(c, chain, a):
    """Lista conocida → caché de autodetección → None."""
    k = known(chain, a)
    if k:
        return k
    h = cache_get(c, chain, a)
    if h and h[0]:
        return hub_entry(h[1].get("why"))
    return None


def judge(act, C):
    """¿La actividad leída indica un servicio/hub? → texto del motivo o None.
    act: {"n": tx leídas, "span_h": horas que cubren, "distinct": contrapartes distintas, "sampled": transferencias muestreadas}"""
    if not act:
        return None
    n, span = act.get("n") or 0, act.get("span_h")
    if n >= C["hub_min_txs"] and span is not None and span <= C["hub_hours"]:
        return f"{n}+ transacciones en {span:.0f} h".replace(".", ",")
    d = act.get("distinct") or 0
    if d >= C["service_min_counterparties"]:
        return f"movió fondos con {d}+ wallets distintas"
    return None


def stats():
    out = {}
    for f, tab in SERVICES.items():
        v = sum(1 for e in tab.values() if e["verified"])
        out[f] = {"total": len(tab), "verified": v, "guessed": len(tab) - v, "names": sorted({e["name"] for e in tab.values()})}
    return out
