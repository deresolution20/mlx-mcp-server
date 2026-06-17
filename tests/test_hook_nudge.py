from mlx_mcp_server.hook import logs
from mlx_mcp_server.hook import __main__ as entry


def test_decisions_today_filters_by_prefix(tmp_path):
    p = tmp_path / "dec.jsonl"
    p.write_text(
        '{"ts":"2026-06-17T01:00:00","decision":"missed_offload"}\n'
        '{"ts":"2026-06-17T02:00:00","decision":"offloaded"}\n'
        '{"ts":"2026-06-16T05:00:00","decision":"missed_offload"}\n'
    )
    assert logs.decisions_today("2026-06-17", path=str(p)) == {"missed_offload": 1, "offloaded": 1}


def test_decisions_today_missing_file(tmp_path):
    assert logs.decisions_today("2026-06-17", path=str(tmp_path / "none")) == {}


def test_nudge_none_when_no_misses(monkeypatch):
    monkeypatch.setattr(logs, "decisions_today", lambda *a, **k: {"offloaded": 3})
    assert entry._nudge_text() is None


def test_nudge_text_when_misses(monkeypatch):
    monkeypatch.setattr(logs, "decisions_today", lambda *a, **k: {"missed_offload": 2, "offloaded": 1})
    t = entry._nudge_text()
    assert "2 missed-offload" in t and "iterate" in t
