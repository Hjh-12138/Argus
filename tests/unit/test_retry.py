from core.retry import run_with_retry


def test_success_on_first_attempt():
    outcome = run_with_retry(lambda: "ok", attempts=3, delay_s=0)
    assert outcome.ok
    assert outcome.value == "ok"
    assert outcome.attempts_used == 1


def test_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "recovered"

    outcome = run_with_retry(flaky, attempts=3, delay_s=0)
    assert outcome.ok
    assert outcome.value == "recovered"
    assert outcome.attempts_used == 3


def test_exhausts_retries_and_circuit_opens():
    def always_fails():
        raise ValueError("boom")

    outcome = run_with_retry(always_fails, attempts=3, delay_s=0)
    assert not outcome.ok
    assert outcome.attempts_used == 3
    assert isinstance(outcome.error, ValueError)


def test_no_retry_beyond_attempts():
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise RuntimeError("boom")

    run_with_retry(always_fails, attempts=2, delay_s=0)
    assert calls["n"] == 2
