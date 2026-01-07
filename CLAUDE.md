# PAL-E Observer

Save file watching and event broadcasting service for the PAL-E ecosystem.

**Part of the [PAL-E Ecosystem](https://github.com/ldraney/pal-e)**

## Overview

PAL-E Observer is a standalone Node.js service that watches Palworld save files and broadcasts events via WebSocket. It's the "eyes" of the PAL-E system — observing gameplay through save file snapshots and detecting changes in real-time.

## Quick Start

```bash
npm install
npm start
```

**Endpoints:**
- WebSocket: `ws://localhost:8765`
- REST API: `http://localhost:8764`

## Architecture

```
Save files change
       ↓
observer.js (file watcher)
       ↓
python snapshot.py --json --diff
       ↓
Compare to previous snapshot
       ↓
Broadcast events via WebSocket
       ↓
Dashboard displays events
```

## What Observer Detects

Save files update on autosave (~10 min) or manual save. Observer detects:

- **Pals**: Catches, releases, level changes
- **Players**: Joins, leaves, level ups
- **Bases**: New base creation
- **Files**: Any .sav file change

## Files

| File | Purpose |
|------|---------|
| `observer.js` | Node.js service - file watcher, WebSocket server, REST API |
| `snapshot.py` | Deep save parsing, diff detection, JSON output |
| `parse_save.py` | Lightweight save parser (faster, less detail) |
| `history.py` | Persistent save history, pattern learning |

## REST API

| Endpoint | Description |
|----------|-------------|
| `GET /status` | Current world state and uptime |
| `GET /history` | Recent event history |
| `GET /health` | Health check |

## WebSocket Events

```javascript
// On connect - greeting with current state
{ type: 'greeting', worldState: {...}, recentEvents: [...] }

// Game events from Level.sav diff
{ type: 'game_event', eventType: 'pal_caught', message: 'Caught Lamball Lv.5', worldState: {...} }

// Other .sav file changes
{ type: 'file_changed', file: 'LocalData.sav', fileType: 'local', message: 'local updated' }
```

## CLI Usage

```bash
# Parse a save file (human-readable)
python snapshot.py "path/to/Level.sav"

# Parse with JSON output (for Node.js)
python snapshot.py "path/to/Level.sav" --json

# Parse and diff against previous snapshot
python snapshot.py "path/to/Level.sav" --json --diff previous.json

# Skip saving snapshot file
python snapshot.py "path/to/Level.sav" --json --no-save
```

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
- Pal count

## Dependencies

**Node.js:**
```bash
npm install  # installs chokidar, ws
```

**Python:**
```bash
pip install palworld-save-tools
```

## Save File Structure

```
%LOCALAPPDATA%\Pal\Saved\SaveGames\
├── UserOption.sav
└── <SteamID>/
    ├── GlobalPalStorage.sav
    └── <WorldID>/
        ├── Level.sav          ← Deep parsed
        ├── LevelMeta.sav
        ├── LocalData.sav
        ├── WorldOption.sav
        └── Players/
            └── *.sav
```

## Multiplayer Notes

| Role | Save Files Available |
|------|---------------------|
| **Host** | `Level.sav` + all files — Full world parsing |
| **Client** | Only `LocalData.sav` — Limited data |

Host detection uses UID pattern: hosts have `00000000-0000-0000-0000-000000000001`.

## Integration

Observer broadcasts to:
- **pal-e dashboard** — Displays world state in browser
- **pal-e-expert** — Could query observation data for coaching context

## Configuration

Environment variables:
- `OBSERVER_WS_PORT` — WebSocket port (default: 8765)
- `OBSERVER_HTTP_PORT` — REST API port (default: 8764)
