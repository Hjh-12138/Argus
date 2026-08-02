from core.redaction import redact, hmac_fingerprint


def test_redact_masks_secret_value():
    out = redact("api_key = 'sk-abc123xyz789'")
    assert "sk-abc123xyz789" not in out
    assert "***" in out


def test_redact_masks_sk_token():
    out = redact("token: sk-abcdefghijklmnop123456")
    assert "sk-abcdefghijklmnop123456" not in out


def test_redact_leaves_plain_text():
    text = "def add(a, b): return a + b"
    assert redact(text) == text


def test_hmac_fingerprint_not_raw():
    raw = "sk-abc123"
    fp = hmac_fingerprint(raw, salt=b"proj-salt")
    assert raw not in fp
    assert len(fp) == 64


def test_hmac_fingerprint_stable():
    fp1 = hmac_fingerprint("value", b"salt")
    fp2 = hmac_fingerprint("value", b"salt")
    assert fp1 == fp2


def test_hmac_fingerprint_salt_sensitive():
    assert hmac_fingerprint("value", b"a") != hmac_fingerprint("value", b"b")
