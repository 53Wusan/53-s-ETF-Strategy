"""Only ciphertext is committed; plaintext account files stay on the runner."""
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
password = os.environ["DESK_PASSWORD"]
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
    data = {p.name: json.loads(p.read_text(encoding="utf8")) for p in public.glob("*.json") if p.name != "desk.enc.json"}
    if (folder/"shadow.json").exists():
        data["account.json"] = json.loads((folder/"shadow.json").read_text(encoding="utf8"))
    encrypted = encrypt(data, password)
    for p in public.glob("*.json"):
        p.unlink()
    (public/"desk.enc.json").write_text(json.dumps(encrypted), encoding="utf8")
print(f"Encrypted data {args.mode} completed; password and account values omitted")
