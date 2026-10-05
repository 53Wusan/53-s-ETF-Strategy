import pytest
from cryptography.exceptions import InvalidTag
from app.services.encrypted_data import encrypt, decrypt


def test_vault_rejects_wrong_password_and_tampering():
    password = "sample-test-passphrase-123"
    data = {"config": {"initial_usd": 60000}}
    vault = encrypt(data, password)
    assert decrypt(vault, password) == data
    assert "60000" not in str(vault)
    with pytest.raises(InvalidTag):
        decrypt(vault, "different-test-password-123")
    vault["nonce"] = "AAAAAAAAAAAAAAAA"
    with pytest.raises(InvalidTag):
        decrypt(vault, password)
