#!/usr/bin/env python3
"""
Palworld Save Parser for Devy Butler
Extracts player, pal, and world data from Level.sav files.
"""

import sys
import os
import re
import json
from pathlib import Path
from io import StringIO

# Suppress library debug output
class SuppressOutput:
    def __enter__(self):
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        return self

    def __exit__(self, *args):
        sys.stdout = self._stdout
        sys.stderr = self._stderr

def parse_level_sav(save_path):
    """Parse a Level.sav file and return structured data."""
    try:
        from palworld_save_tools.palsav import decompress_sav_to_gvas
    except ImportError:
        return {"error": "palworld-save-tools not installed"}

    if not os.path.exists(save_path):
        return {"error": f"File not found: {save_path}"}

    try:
        with open(save_path, 'rb') as f:
            data = f.read()
        # Suppress library debug output during decompression
        with SuppressOutput():
            raw_gvas, _ = decompress_sav_to_gvas(data)
    except Exception as e:
        return {"error": f"Decompression failed: {str(e)}"}

    # Extract world_id from path
    # Pattern: SaveGames/<SteamID>/<WorldID>/Level.sav
    world_id = None
    path_parts = save_path.replace('\\', '/').split('/')
    for i, part in enumerate(path_parts):
        if part == 'Level.sav' and i > 0:
            world_id = path_parts[i - 1]
            break

    result = {
        "success": True,
        "file": save_path,
        "world_id": world_id,
        "file_size_kb": round(os.path.getsize(save_path) / 1024, 1),
        "raw_size_mb": round(len(raw_gvas) / 1024 / 1024, 1),
        "players": [],
        "pal_count": 0,
        "guild_name": None,
        "host_player": None,
    }

    # Extract player names
    player_pattern = rb'NickName\x00\x0c\x00\x00\x00StrProperty\x00[\x00-\xff]{4}\x00\x00\x00\x00\x00[\x00-\xff]{4}([\x20-\x7e]+)\x00'
    for m in re.finditer(player_pattern, raw_gvas):
        try:
            name = m.group(1).decode('utf-8', errors='ignore').strip()
            if name and len(name) > 2 and name not in result['players']:
                result['players'].append(name)
        except:
            pass

    # Try to detect host player by looking for PlayerUId pattern
    # Host typically has UID 00000000-0000-0000-0000-000000000001
    # Look for IsPlayer=True followed by PlayerUId with the host pattern
    host_uid_pattern = rb'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'  # Host UID in binary
    if host_uid_pattern in raw_gvas:
        # If host UID found and we have players, first player is often the host
        # Note: This is a heuristic - the full snapshot.py parser is more accurate
        if result['players']:
            result['host_player'] = result['players'][0]

    # Count character/pal saves
    result['pal_count'] = raw_gvas.count(b'PalIndividualCharacterSaveParameter')

    # Extract guild name
    guild_pattern = rb'GuildName\x00\x0c\x00\x00\x00StrProperty\x00[\x00-\xff]{4}\x00\x00\x00\x00\x00[\x00-\xff]{4}([\x20-\x7e]+)\x00'
    guild_match = re.search(guild_pattern, raw_gvas)
    if guild_match:
        try:
            result['guild_name'] = guild_match.group(1).decode('utf-8', errors='ignore').strip()
        except:
            pass

    # Count bases (look for WorkSaveData which indicates active bases)
    result['work_entries'] = raw_gvas.count(b'WorkSaveData')

    # Count items in storage
    result['item_container_count'] = raw_gvas.count(b'ItemContainerSaveData')

    return result


def main():
    if len(sys.argv) < 2:
        # Default path
        save_path = os.path.expanduser(
            '~/AppData/Local/Pal/Saved/SaveGames'
        )
        # Find most recent Level.sav
        level_files = list(Path(save_path).rglob('Level.sav'))
        if not level_files:
            print(json.dumps({"error": "No Level.sav files found"}))
            return
        # Get most recently modified
        save_path = str(max(level_files, key=lambda p: p.stat().st_mtime))
    else:
        save_path = sys.argv[1]

    result = parse_level_sav(save_path)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
