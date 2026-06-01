"""Tests for key rotation module."""


from codex_proxy.key_rotation import KeyRotator, _mask_key


class TestMaskKey:
    def test_short_key(self):
        assert _mask_key("abc") == "***"

    def test_long_key(self):
        assert _mask_key("sk-longapikey1234") == "sk-...1234"


class TestKeyRotatorRoundRobin:
    def test_single_key(self):
        kr = KeyRotator(["key1"])
        assert kr.next_key() == "key1"
        assert kr.next_key() == "key1"

    def test_two_keys(self):
        kr = KeyRotator(["key1", "key2"])
        assert kr.next_key() == "key1"
        assert kr.next_key() == "key2"
        assert kr.next_key() == "key1"

    def test_three_keys(self):
        kr = KeyRotator(["a", "b", "c"])
        assert [kr.next_key() for _ in range(6)] == ["a", "b", "c", "a", "b", "c"]

    def test_empty_raises(self):
        import pytest
        with pytest.raises(ValueError):
            KeyRotator([])


class TestKeyRotatorCircuit:
    def test_skip_open_circuit(self):
        kr = KeyRotator(["k1", "k2"], failure_threshold=1, recovery_timeout=300.0)
        kr.record_failure("k1", 401)
        assert kr.next_key() == "k2"

    def test_all_open_falls_back(self):
        kr = KeyRotator(["k1", "k2"], failure_threshold=1, recovery_timeout=300.0)
        kr.record_failure("k1", 401)
        kr.record_failure("k2", 401)
        key = kr.next_key()
        assert key in ("k1", "k2")

    def test_success_resets_circuit(self):
        kr = KeyRotator(["k1", "k2"], failure_threshold=1, recovery_timeout=300.0)
        kr.record_failure("k1", 401)
        # k1 circuit is open, so next should be k2
        assert kr.next_key() == "k2"
        # Record success for k1 (resets its per-key circuit breaker)
        kr.record_success("k1")
        # Both keys should be available now — next in round-robin after k2
        key = kr.next_key()
        assert key in ("k1", "k2")


class TestKeyRotatorFailure:
    def test_401_trips_circuit(self):
        kr = KeyRotator(["k1"], failure_threshold=1, recovery_timeout=300.0)
        kr.record_failure("k1", 401)
        status = kr.get_status()
        assert status[0]["state"] == "open"

    def test_429_trips_circuit(self):
        kr = KeyRotator(["k1"], failure_threshold=1, recovery_timeout=300.0)
        kr.record_failure("k1", 429)
        status = kr.get_status()
        assert status[0]["state"] == "open"

    def test_500_does_not_trip(self):
        kr = KeyRotator(["k1"], failure_threshold=1, recovery_timeout=300.0)
        kr.record_failure("k1", 500)
        status = kr.get_status()
        assert status[0]["state"] == "closed"
        assert status[0]["errors"] == 1


class TestKeyRotatorStatus:
    def test_get_status_structure(self):
        kr = KeyRotator(["sk-longapikey1234", "sk-anotherkey5678"])
        status = kr.get_status()
        assert len(status) == 2
        assert "key" in status[0]
        assert "state" in status[0]
        assert "errors" in status[0]
        assert status[0]["key"] == "sk-...1234"

    def test_reset_rebuilds_pool(self):
        kr = KeyRotator(["k1", "k2"])
        kr.record_failure("k1", 401)
        kr.reset(["k3", "k4", "k5"])
        assert len(kr.get_status()) == 3
        assert kr.next_key() == "k3"
