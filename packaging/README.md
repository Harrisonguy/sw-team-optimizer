# Windows release build

The release pipeline creates and validates three artifacts:

- `dist/SWTeamOptimizer/` — portable one-folder application
- `release/SWTeamOptimizer-1.0.0-win64.zip` — portable archive
- `release/SWTeamOptimizer-Setup-1.0.0.exe` — Windows installer

Requirements:

- uv with a 64-bit Python 3.10 or newer toolchain
- Internet access for the isolated build environment's first dependency install
- Inno Setup 6 for the preferred installer executable; if it is not installed,
  the build falls back to a PyInstaller-based per-user setup executable

From PowerShell at the project root:

```powershell
.\build_release.ps1
```

For a manual environment setup, uv manages installation directly; a uv-created
environment does not need the `pip` module:

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r requirements_build.txt
```

The build is intentionally gated. It runs the complete unit suite, compiles all
Python modules, imports the sample SWEX account into an isolated database,
launches the packaged application in offscreen smoke-test mode, captures all
nine pages at 1400×900 plus five compact 1100×720 views, validates those images,
and creates a contact sheet before producing the archive and installer. Use
`-SkipInstaller` only when producing the portable archive without a setup
executable.
