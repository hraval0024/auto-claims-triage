"""Container entrypoint.

Railway mounts the volume at DATA_DIR (/data) owned by root, so the unprivileged app user can't
write to it (first deploy failed: "DATA_DIR '/data' is not writable"). This script starts as
root ONLY to hand the data directory to uid/gid 10001, then permanently drops privileges and
replaces itself with uvicorn. The app process never runs as root.

Python (not setpriv/gosu) because Python is guaranteed to be in the image.
"""

import os
import sys

APP_UID = APP_GID = 10001
UVICORN = "/app/.venv/bin/uvicorn"


def fix_ownership(data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    for root, dirs, files in os.walk(data_dir):  # os.walk does not descend into symlinked dirs
        os.chown(root, APP_UID, APP_GID, follow_symlinks=False)
        for name in dirs + files:
            os.chown(os.path.join(root, name), APP_UID, APP_GID, follow_symlinks=False)


def drop_privileges() -> None:
    os.setgroups([])
    os.setgid(APP_GID)
    os.setuid(APP_UID)  # irreversible: real, effective and saved uid all become 10001
    if os.getuid() == 0 or os.geteuid() == 0:
        sys.exit("entrypoint: failed to drop root privileges; refusing to start")


def uvicorn_args(environ: dict) -> list[str]:
    return ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", environ.get("PORT", "8000"),
            "--no-access-log", "--no-server-header"]


def main(environ: dict | None = None) -> None:
    environ = dict(os.environ if environ is None else environ)
    if os.geteuid() == 0:
        fix_ownership(environ.get("DATA_DIR", "/data"))
        drop_privileges()
    os.execv(UVICORN, uvicorn_args(environ))  # replaces this process: uvicorn becomes PID 1


if __name__ == "__main__":
    main()
