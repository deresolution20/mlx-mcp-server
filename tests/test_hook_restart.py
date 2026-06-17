import subprocess
from mlx_mcp_server.hook.restart import restart_omlx, RestartOutcome


class _Run:
    def __init__(self, diagnose_out="diag-output"):
        self.calls = []
        self.diagnose_out = diagnose_out
    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = self.diagnose_out if "diagnose" in cmd else "restarted"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


def test_restart_healthy_after_restart():
    run = _Run()
    out = restart_omlx("http://x", run_fn=run, health_fn=lambda b: True)
    assert out.healthy is True
    assert any("restart" in c for c in run.calls)
    # diagnose is NOT run when healthy
    assert not any("diagnose" in c for c in run.calls)


def test_restart_still_down_captures_diagnose():
    run = _Run(diagnose_out="port 8000 not listening")
    out = restart_omlx("http://x", run_fn=run, health_fn=lambda b: False)
    assert out.healthy is False
    assert "port 8000 not listening" in out.detail


def test_restart_never_raises_when_run_fn_explodes():
    def boom(cmd, **kw):
        raise OSError("omlx not found")
    out = restart_omlx("http://x", run_fn=boom, health_fn=lambda b: False)
    assert isinstance(out, RestartOutcome) and out.healthy is False
