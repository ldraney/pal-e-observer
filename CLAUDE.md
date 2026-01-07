# PAL-E Observer

Save file watching and observation layer for the PAL-E ecosystem.

## Overview

PAL-E Observer watches Palworld save files and detects changes in real-time. It's the "eyes" of the PAL-E system — observing gameplay through save file snapshots without any pre-loaded game knowledge.

**Part of the [PAL-E Ecosystem](https://github.com/ldraney/pal-e)**

## Philosophy

- **Observation over assumption** — Learns from what it sees, not datamined tables
- **Event-driven** — Detects changes between saves and broadcasts events
- **Quantitative** — Extracts actual numbers (IVs, levels, counts) from saves

## What Observer Detects

Save files update every ~30 seconds. Observer detects:

- **Pals**: Catches, releases, deaths, level changes
- **Players**: Joins, leaves, level ups
- **Bases**: New base creation
- **Stats**: IV values, passives, species

## Data Extracted

**Per Pal:**
- Species, Level, Experience
- IVs (HP, Defense, Attack)
- Gender, Passives
- Owner UID, Instance ID

**Per Player:**
- Name, Level, UID
- Host status (detected via UID pattern)

**Per World:**
- World ID (from save path)
- Base count
- Game time

## Save Intelligence

Observer classifies saves and infers activity:

| Save Type | Detection |
|-----------|-----------|
| `autosave` | 9-12 min interval |
| `manual` | <2 min or >12 min |

| Activity | Detection |
|----------|-----------|
| `combat` | Level ups detected |
| `catching` | New Pals in roster |
| `building` | Base count changed |
| `managing` | Releases, no catches |

## Files

| File | Purpose |
|------|---------|
| `snapshot.py` | Deep save parsing, diff detection, SaveEvent tracking |
| `parse_save.py` | Lightweight save parser (faster, less detail) |
| `history.py` | Persistent save history, pattern learning |
| `save_history.json` | Stored history data |

## Usage

```bash
# Parse a save file
python snapshot.py "path/to/Level.sav"

# Compare two snapshots
python snapshot.py "path/to/Level.sav" previous_snapshot.json
```

## Output Example

```
=== SNAPSHOT ===
World ID: 55DCC9DE4A0032EC82005DA5B3C8C801
Host: devopsphilosopher
Players: 2
  - devopsphilosopher (Lv.49) [HOST]
  - JameyJam (Lv.18)
Pals: 260
Bases: 3
```

## Dependencies

- Python 3.8+
- `palworld-save-tools` (MRHRTZ fork for Oodle decompression)

```bash
pip install palworld-save-tools
```

## Integration

Observer is designed to be consumed by:
- **pal-e dashboard** — Displays world state in browser
- **pal-e-expert** — Could query observation data for coaching context

## Future

- [ ] Standalone watcher service (Node.js with WebSocket)
- [ ] REST API for querying current state
- [ ] Event streaming to dashboard
- [ ] Pattern learning from save history

## Save Location

```
%LOCALAPPDATA%\Pal\Saved\SaveGames\<SteamID>\<WorldID>\Level.sav
```

## Multiplayer Notes

| Role | Save Files Available |
|------|---------------------|
| **Host** | `Level.sav` + `LocalData.sav` — Full world parsing |
| **Client** | Only `LocalData.sav` — Limited data |

Host detection uses UID pattern: hosts have `00000000-0000-0000-0000-000000000001`.
