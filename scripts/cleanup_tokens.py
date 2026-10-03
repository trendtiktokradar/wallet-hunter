"""Borra coins escaneados y todo lo que existe solo por ellos (misma lógica que «Borrar coin» en la web).
Las wallets que también participaron en otros coins escaneados (o están en ⭐) se quedan, solo con los datos de esos coins.
Hace copia de seguridad automática (data/backups, se guardan las 10 últimas).
Uso: python3 scripts/cleanup_tokens.py [--block] chain:CA [chain:CA ...]"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wallethunter import db, delete, export


def main(args):
    block = "--block" in args
    c = db.connect()
    out = []
    for spec in [a for a in args if not a.startswith("--")]:
        ch, ca = spec.split(":", 1)
        out.append(delete.delete_token(c, ch, ca, block=block))
    export.write(c)
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
