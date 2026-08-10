"""Password hashing — spec §8."""
from app.security import hash_password, verify_password


def test_hash_password_uses_argon2id():
    assert hash_password("correct-horse-battery").startswith("$argon2id$")


def test_verify_password_round_trip():
    stored = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", stored)


def test_verify_password_rejects_wrong_password():
    stored = hash_password("correct-horse-battery")
    assert not verify_password("wrong-password", stored)


def test_verify_password_rejects_garbage_hash():
    """A malformed or foreign stored value must fail closed, not raise."""
    for garbage in ("", "not-a-hash", "pbkdf2_sha256$390000$abc$def"):
        assert not verify_password("correct-horse-battery", garbage)


def test_hash_password_is_salted():
    """Two hashes of the same password must differ (per-hash random salt)."""
    assert hash_password("correct-horse-battery") != hash_password(
        "correct-horse-battery"
    )
