"""Tests for context compaction."""

from codex_proxy.compaction import compact_messages


class TestNoCompaction:
    def test_under_limit(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        result = compact_messages(msgs, max_messages=50)
        assert result is msgs

    def test_exactly_at_limit(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(50)]
        result = compact_messages(msgs, max_messages=50)
        assert result is msgs

    def test_empty_list(self):
        result = compact_messages([], max_messages=50)
        assert result == []


class TestCompaction:
    def test_compacts_over_limit(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        result = compact_messages(msgs, max_messages=50, keep_last=20)
        assert len(result) == 21  # 1 compaction notice + 20 kept

    def test_compaction_notice_content(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        result = compact_messages(msgs, max_messages=50, keep_last=20)
        assert result[0]["role"] == "system"
        assert "40 earlier messages" in result[0]["content"]

    def test_keeps_last_n(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        result = compact_messages(msgs, max_messages=50, keep_last=20)
        assert result[1]["content"] == "msg40"
        assert result[-1]["content"] == "msg59"

    def test_keep_last_count(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        result = compact_messages(msgs, max_messages=50, keep_last=10)
        kept = [m for m in result if m["role"] == "user"]
        assert len(kept) == 10
        assert kept[0]["content"] == "msg50"


class TestSystemMessage:
    def test_preserves_system_message(self):
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        result = compact_messages(msgs, max_messages=50, keep_last=20)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are helpful"

    def test_system_plus_compaction_notice(self):
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        result = compact_messages(msgs, max_messages=50, keep_last=20)
        assert result[1]["role"] == "system"
        assert "compacted" in result[1]["content"]

    def test_no_system_message(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        result = compact_messages(msgs, max_messages=50, keep_last=20)
        assert result[0]["role"] == "system"  # compaction notice only
