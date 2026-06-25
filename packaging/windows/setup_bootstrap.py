"""Bootstrap installer for the Windows setup executable."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


APP_NAME = "SW Team Optimizer"


def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Install {APP_NAME}.")
    parser.add_argument("--quiet", action="store_true", help="Install without launching the app afterward.")
    args = parser.parse_args(argv)

    root = bundle_dir()
    log_path = Path(os.environ.get("TEMP", ".")) / "SWTeamOptimizer-Setup.log"
    install_script = root / "install.ps1"
    archive = root / "SWTeamOptimizer-1.0.0-win64.zip"
    uninstall_script = root / "uninstall.ps1"

    def log(message: str) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    log(f"bundle={root}")
    missing = [str(path) for path in (install_script, archive, uninstall_script) if not path.exists()]
    if missing:
        log("missing=" + ", ".join(missing))
        print("Installer payload is incomplete:", ", ".join(missing), file=sys.stderr)
        return 2

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(install_script),
    ]
    if args.quiet:
        command.append("-NoLaunch")

    log("command=" + " ".join(command))
    completed = subprocess.run(command, cwd=str(root), check=False, capture_output=True, text=True)
    if completed.stdout:
        log("stdout=" + completed.stdout.rstrip())
    if completed.stderr:
        log("stderr=" + completed.stderr.rstrip())
    log(f"returncode={completed.returncode}")
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
