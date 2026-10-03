"""Registro de chains soportadas."""

CHAINS = {
    "solana": {"name": "Solana", "kind": "solana", "native": "SOL", "kraken": "SOLUSD", "dexscreener": "solana", "gecko": "solana", "explorer_name": "Solscan", "gmgn": "sol", "explorer": "https://solscan.io/account/", "tx": "https://solscan.io/tx/"},
    "ethereum": {"name": "Ethereum", "kind": "evm", "chain_id": 1, "native": "ETH", "kraken": "ETHUSD", "dexscreener": "ethereum", "gecko": "eth", "explorer_name": "Etherscan", "gmgn": "eth", "explorer": "https://etherscan.io/address/", "tx": "https://etherscan.io/tx/",
                 "etherscan_free": True, "blockscout": "https://eth.blockscout.com/api", "wrapped": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "block_time": 12},
    "bsc": {"name": "BNB Chain", "kind": "evm", "chain_id": 56, "native": "BNB", "kraken": "BNBUSD", "dexscreener": "bsc", "gecko": "bsc", "explorer_name": "BscScan", "gmgn": "bsc", "explorer": "https://bscscan.com/address/", "tx": "https://bscscan.com/tx/",
            "etherscan_free": False, "blockscout": None, "wrapped": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", "block_time": 0.75},
    "base": {"name": "Base", "kind": "evm", "chain_id": 8453, "native": "ETH", "kraken": "ETHUSD", "dexscreener": "base", "gecko": "base", "explorer_name": "BaseScan", "gmgn": "base", "explorer": "https://basescan.org/address/", "tx": "https://basescan.org/tx/",
             "etherscan_free": False, "blockscout": "https://base.blockscout.com/api", "wrapped": "0x4200000000000000000000000000000000000006", "block_time": 2},
    "arbitrum": {"name": "Arbitrum", "kind": "evm", "chain_id": 42161, "native": "ETH", "kraken": "ETHUSD", "dexscreener": "arbitrum", "gecko": "arbitrum", "explorer_name": "Arbiscan", "gmgn": None, "explorer": "https://arbiscan.io/address/", "tx": "https://arbiscan.io/tx/",
                 "etherscan_free": True, "blockscout": "https://arbitrum.blockscout.com/api", "wrapped": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1", "block_time": 0.25},
    "polygon": {"name": "Polygon", "kind": "evm", "chain_id": 137, "native": "POL", "kraken": "POLUSD", "dexscreener": "polygon", "gecko": "polygon_pos", "explorer_name": "PolygonScan", "gmgn": None, "explorer": "https://polygonscan.com/address/", "tx": "https://polygonscan.com/tx/",
                "etherscan_free": True, "blockscout": "https://polygon.blockscout.com/api", "wrapped": "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270", "block_time": 2},
    "robinhood": {"name": "Robinhood Chain", "kind": "evm", "chain_id": 4663, "native": "ETH", "kraken": "ETHUSD", "dexscreener": "robinhood", "gecko": "robinhood", "explorer_name": "Blockscout", "gmgn": None, "explorer": "https://robinhoodchain.blockscout.com/address/", "tx": "https://robinhoodchain.blockscout.com/tx/",
                  "etherscan_free": None, "blockscout": "https://robinhoodchain.blockscout.com/api", "blockscout_pro": True, "wrapped": None, "block_time": 0.1},
}

# stablecoins tratados como "quote" (se convierten a nativo con el precio USD)
STABLES = {
    "solana": {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT", "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB": "USD1"},
    "ethereum": {"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC", "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT"},
    "bsc": {"0x55d398326f99059ff775485246999027b3197955": "USDT", "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "USDC", "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": "USD1"},
    "base": {"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC"},
    "arbitrum": {"0xaf88d065e77c8cc2239327c5edb3a432268e5831": "USDC", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": "USDT"},
    "polygon": {"0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": "USDC", "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": "USDT"},
    "robinhood": {},
}

WSOL = "So11111111111111111111111111111111111111112"


def is_evm_address(a):
    return isinstance(a, str) and a.startswith("0x") and len(a) == 42


def is_sol_address(a):
    import re
    return isinstance(a, str) and bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", a))


def guess_chain(addr):
    if is_evm_address(addr):
        return "evm"
    if is_sol_address(addr):
        return "solana"
    return None
