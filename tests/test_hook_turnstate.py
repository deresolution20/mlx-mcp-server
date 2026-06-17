from mlx_mcp_server.hook import turnstate


def test_stamp_then_read_roundtrip(tmp_path):
    p = str(tmp_path / "ts.json")
    turnstate.stamp("2026-06-17T22:00:00+00:00", path=p)
    assert turnstate.started_ts(path=p) == "2026-06-17T22:00:00+00:00"


def test_missing_file_returns_none(tmp_path):
    assert turnstate.started_ts(path=str(tmp_path / "nope.json")) is None


def test_garbage_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert turnstate.started_ts(path=str(p)) is None


def test_stamp_never_raises_on_bad_path():
    turnstate.stamp("x", path="/nonexistent-root/cannot/write.json")  # no exception
