"""Restore checked public research snapshots; never contains actual account data."""
import base64
import hashlib
import io
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
folder = root / "runtime-bundle"
payload = b"".join(base64.b64decode(p.read_text(), validate=True) for p in sorted(folder.glob("*.b64")))
expected = (folder / "sha256.txt").read_text().strip()
if hashlib.sha256(payload).hexdigest() != expected:
    raise RuntimeError("Runtime snapshot checksum mismatch")
with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as archive:
    for member in archive.getmembers():
        target = (root / member.name).resolve()
        if not target.is_relative_to(root / "research/output") or not member.isfile():
            raise RuntimeError("Unexpected runtime snapshot path")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
print("Research runtime restored and checksum verified")
