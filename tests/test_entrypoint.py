"""Container entrypoint: root path fixes /data ownership then drops privileges before exec;
non-root path just execs. OS calls are recorded, not performed."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("entrypoint", ROOT / "docker/entrypoint.py")
ep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ep)


@pytest.fixture
def calls(monkeypatch):
    log = []
    state = {"uid": 0}
    monkeypatch.setattr(ep.os, "geteuid", lambda: state["uid"])
    monkeypatch.setattr(ep.os, "getuid", lambda: state["uid"])
    monkeypatch.setattr(ep.os, "chown", lambda p, u, g, follow_symlinks=True: log.append(("chown", Path(p).name, u, g, follow_symlinks)))
    monkeypatch.setattr(ep.os, "setgroups", lambda g: log.append(("setgroups", g)))
    monkeypatch.setattr(ep.os, "setgid", lambda g: log.append(("setgid", g)))

    def setuid(u):
        log.append(("setuid", u))
        state["uid"] = u

    monkeypatch.setattr(ep.os, "setuid", setuid)
    monkeypatch.setattr(ep.os, "execv", lambda path, args: log.append(("execv", path, args)))
    return log, state


def test_root_fixes_ownership_then_drops_privileges_before_exec(calls, tmp_path):
    log, _ = calls
    data = tmp_path / "data"
    (data / "sub").mkdir(parents=True)
    (data / "app.db").write_text("x")
    ep.main({"DATA_DIR": str(data), "PORT": "1234"})
    kinds = [c[0] for c in log]
    assert kinds.index("setuid") < kinds.index("execv")  # privileges dropped before uvicorn starts
    assert kinds.index("setgroups") < kinds.index("setgid") < kinds.index("setuid")
    chowned = {c[1] for c in log if c[0] == "chown"}
    assert {"data", "sub", "app.db"} <= chowned
    assert all(c[2] == c[3] == 10001 and c[4] is False for c in log if c[0] == "chown")  # never follows symlinks
    path, args = log[-1][1], log[-1][2]
    assert path == "/app/.venv/bin/uvicorn" and args[args.index("--port") + 1] == "1234"
    assert "--no-access-log" in args and "--no-server-header" in args


def test_non_root_just_execs(calls, tmp_path):
    log, state = calls
    state["uid"] = 10001
    ep.main({"DATA_DIR": str(tmp_path)})
    assert [c[0] for c in log] == ["execv"]


def test_refuses_to_start_if_still_root(calls, tmp_path, monkeypatch):
    log, state = calls
    monkeypatch.setattr(ep.os, "setuid", lambda u: log.append(("setuid-ignored", u)))  # uid stays 0
    with pytest.raises(SystemExit, match="refusing to start"):
        ep.main({"DATA_DIR": str(tmp_path / "d")})
    assert "execv" not in [c[0] for c in log]


def test_dockerfile_wires_the_entrypoint():
    d = (ROOT / "Dockerfile").read_text()
    assert "COPY docker/entrypoint.py" in d and 'CMD ["/app/.venv/bin/python", "/app/docker/entrypoint.py"]' in d
    assert "--gid 10001" in d and "--uid 10001" in d and "\nUSER " not in d
    assert "docker/" not in (ROOT / ".dockerignore").read_text()
