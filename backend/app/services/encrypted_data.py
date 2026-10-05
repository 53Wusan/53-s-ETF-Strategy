"""Password-encrypted account state and browser data; AES-GCM authenticates bytes."""
import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 310000


def key(password: str, salt: bytes, iterations: int) -> bytes:
    if len(password) < 16:
        raise ValueError("Use a password of at least 16 characters")
    return PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=iterations).derive(password.encode())


def encrypt(value: dict, password: str) -> dict:
    salt, nonce = os.urandom(16), os.urandom(12)
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ciphertext = AESGCM(key(password, salt, ITERATIONS)).encrypt(nonce, data, None)
    return {"version": 1, "iterations": ITERATIONS,
            **{name: base64.b64encode(raw).decode() for name, raw in
               (("salt", salt), ("nonce", nonce), ("ciphertext", ciphertext))}}


def decrypt(envelope: dict, password: str) -> dict:
    if envelope.get("version") != 1 or envelope.get("iterations") != ITERATIONS:
        raise ValueError("Unsupported encrypted data format")
    salt, nonce, ciphertext = (base64.b64decode(envelope[k], validate=True) for k in ("salt", "nonce", "ciphertext"))
    data = AESGCM(key(password, salt, ITERATIONS)).decrypt(nonce, ciphertext, None)
    return json.loads(data)
