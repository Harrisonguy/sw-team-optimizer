SW Team Optimizer
=================

Desktop optimizer for Summoners War accounts, focused on team-level rune
allocation, dungeon planning, account analytics, and sell recommendations.

Current Status
--------------

The app currently includes:

- SWEX JSON import into SQLite
- Multiple retained account profiles with in-app switching
- Rune, monster, and artifact inventory views
- Rune sell analysis and actionable account progression analytics
- Ranked dungeon farming plans from set, slot, speed, grind, and artifact gaps
- Single-monster rune optimization
- Joint team rune search where every state optimizes against remaining runes
- Cooperative cancellation and live progress for rune, team, artifact, and simulation work
- Bounded, context-safe optimizer caches with real-account performance profiling
- Context-aware artifact pair recommendations for individual monsters
- Conflict-free artifact allocation across optimized teams
- Account-relative artifact efficiency, upgrade potential, and sell review guidance
- Bundled dungeon wave/stat viewer with optional custom data import
- Dungeon wave damage and one-shot analysis using structured artifact effects
- Dungeon-aware team scoring and reproducible turn-by-turn clear simulation
- Skill cooldowns, activation rates, buffs, debuffs, brand, control, healing, and enemy turns
- Imported monster skill levels with automatic supported damage formulas and skill-ups
- Per-profile Summoner Skill, guild skill, guild level, and decoration progression storage
- Arena, Siege, Guild War, and World Arena planning with speed-contest estimates
- Leader-aware turn tuning, ATB cut checks, draft coverage, defense risks, and saved PvP plans
- Desktop menus and keyboard navigation, restored window state, and safe optimizer shutdown
- Bundle-safe resource loading and a gated Windows release/installer pipeline

Run The App
-----------

Install runtime dependencies, then start the PySide desktop app:

```powershell
pip install -r requirements_desktop.txt
python run_desktop.py
```

Run Tests
---------

```powershell
python -m unittest discover -s tests
python -m compileall -q .
```

Build A Windows Release
-----------------------

Install Inno Setup 6, then run:

```powershell
.\build_release.ps1
```

The release build runs tests, creates the portable PyInstaller application,
launches a packaged smoke test, captures a UI screenshot, and produces both a
portable zip and Windows installer. See `packaging/README.md` for details.

Development Roadmap
-------------------

Highest-priority remaining work:

1. Build the release artifacts on a host with PySide6, PyInstaller, and Inno Setup available.
2. Inspect every major page at desktop and compact resolutions and correct visual defects.
3. Expand support for nonlinear skill formulas that depend on live combat state.
