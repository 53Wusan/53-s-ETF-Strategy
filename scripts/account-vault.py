"""Encrypt internal state; publish only the public paper-account view."""
import argparse
import json
import os
from pathlib import Path

from app.services.encrypted_data import decrypt, encrypt

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("unlock", "lock", "site"))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
folder = root / "account"
folder.mkdir(exist_ok=True)
password = os.environ.get("DESK_PASSWORD", "")
vault = folder / "state.enc.json"
if args.mode == "unlock":
    data = decrypt(json.loads(vault.read_text()), password)
    for name, value in data.items():
        if name not in ("config", "shadow"):
            raise ValueError("Unexpected account entry")
        (folder / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf8")
elif args.mode == "lock":
    data = {p.stem: json.loads(p.read_text(encoding="utf8")) for p in (folder/"config.json", folder/"shadow.json") if p.exists()}
    vault.write_text(json.dumps(encrypt(data, password)), encoding="utf8")
else:
    public = root / "frontend/public/data"
    public.mkdir(parents=True, exist_ok=True)
    # Never export the account configuration (broker, credentials, private notes).
    allowed = {"kind", "currency", "profile", "activation_date", "data_date", "fee_status",
               "share_basis", "initial_usd", "buy_budget_usd", "cash_usd", "equity_usd",
               "positions", "trades", "next_open_plan"}
    shadow = json.loads((folder/"shadow.json").read_text(encoding="utf8"))
    unknown = set(shadow) - allowed
    if unknown:
        raise ValueError("Unexpected account fields; review before public export")
    (public/"account.json").write_text(json.dumps(shadow, ensure_ascii=False), encoding="utf8")
    (public/"desk.enc.json").unlink(missing_ok=True)
print(f"Account data {args.mode} completed; credentials omitted")
