"""Hot wallets públicas de exchanges (CEX). Lista inicial editable: añade direcciones en state/cex_extra.json
con formato {"solana": {"DIRECCION": "Binance"}, "evm": {"0x...": "MEXC"}}.
Además de esta lista, el programa detecta "hubs": wallets que fondean a muchas wallets de la base."""
import json, os
from .config import STATE_DIR

SOLANA = {
    # Binance
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "Binance",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance",
    "3yFwqXBfZY4jBVUafQ1YEXw189y2dN3V5KQq9uzBDy1E": "Binance",
    "2ojv9BAiHUrvsm9gxDe7fJSzbNZSJcxZvf8dqmWGHG8S": "Binance",
    # Coinbase
    "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS": "Coinbase",
    "2AQdpHJ2JpcEgPiATUXjQxA8QmafFegfQwSLWSprPicm": "Coinbase",
    "GJRs4FwHtemZ5ZE9x3FNvJ8TMwitKTh21yxdRPqn7npE": "Coinbase",
    "D89hHJT5Aqyx1trP6EnGY9jJUB3whgnq3aUvvCqedvzf": "Coinbase",
    # OKX
    "5VCwKtCXgCJ6kit5FybXjvriW3xELsFDhYrPSqtJNmcD": "OKX",
    "9un5wqE3q4oCjyrDkwsdD48KteCJitQX5978Vh7KKxHo": "OKX",
    # Bybit
    "AC5RDfQFmDS1deWZos921JfqscXdByf8BKHs5ACWjtW2": "Bybit",
    # KuCoin
    "BmFdpraQhkiDQE6SnfG5omcA1VwzqfXrwtNYBwWTymy6": "KuCoin",
    # MEXC
    "ASTyfSima4LLAdDgoFGkgqoKowG1LZFDr9fAQrg7iaJZ": "MEXC",
    "5PAhQiYdLBd6SVdjzBQDxUAEFyDdF5ExNPQfcscnPRj5": "MEXC",
    # Gate.io
    "u6PJ8DtQuPFnfmwHbGFULQ4u4EgjDiyYKjVEsynXq2w": "Gate.io",
    # Bitget
    "A77HErqtfN1hLLpvZ9pCtu66FEtM8BveoaKbbMoZ4RiR": "Bitget",
    # Kraken
    "FWznbcNXWQuHTawe9RxvQ2LdCENssh12dsznf4RiouN5": "Kraken",
}

EVM = {k.lower(): v for k, v in {
    "0x28C6c06298d514Db089934071355E5743bf21d60": "Binance",
    "0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549": "Binance",
    "0xDFd5293D8e347dFe59E90eFd55b2956a1343963d": "Binance",
    "0xF977814e90dA44bFA03b6295A0616a897441aceC": "Binance",
    "0x8894E0a0c962CB723c1976a4421c95949bE2D4E3": "Binance",
    "0xe2fc31F816A9b94326492132018C3aEcC4a93aE1": "Binance",
    "0x71660c4005BA85c37ccec55d0C4493E66Fe775d3": "Coinbase",
    "0x503828976D22510aad0201ac7EC88293211D23Da": "Coinbase",
    "0xA9D1e08C7793af67e9d92fe308d5697FB81d3E43": "Coinbase",
    "0x6cC5F688a315f3dC28A7781717a9A798a59fDA7b": "OKX",
    "0x5041ed759Dd4aFc3a72b8192C143F72f4724081A": "OKX",
    "0xf89d7b9c864f589bbF53a82105107622B35EaA40": "Bybit",
    "0xD6216fC19DB775Df9774a6E33526131dA7D19a2c": "KuCoin",
    "0x75e89d5979E4f6Fba9F97c104c2F0AFB3F1dcB88": "MEXC",
    "0x3cC936b795A188F0e246cBB2D74C5Bd190aeCF18": "MEXC",
    "0x0D0707963952f2fBA59dD06f2b425ace40b492Fe": "Gate.io",
    "0x1C4b70a3968436B9A0a9cf5205c787eb81Bb558c": "Gate.io",
    "0x5bdf85216ec1e38D6458C870992A69e38e03F7Ef": "Bitget",
    "0x0639556F03714A74a5fEEaF5736a4A64fF70D206": "Bitget",
    "0x2910543Af39abA0Cd09dBb2D50200b3E800A63D2": "Kraken",
}.items()}

_extra = None


def _load_extra():
    global _extra
    if _extra is None:
        p = os.path.join(STATE_DIR, "cex_extra.json")
        try:
            _extra = json.load(open(p))
        except Exception:
            _extra = {}
    return _extra


def label(chain, address):
    if not address:
        return None
    ex = _load_extra()
    if chain == "solana":
        return SOLANA.get(address) or ex.get("solana", {}).get(address)
    a = address.lower()
    return EVM.get(a) or {k.lower(): v for k, v in ex.get("evm", {}).items()}.get(a)
