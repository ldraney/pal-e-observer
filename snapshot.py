#!/usr/bin/env python3
"""
PAL-E Snapshot System
Extracts structured data from Palworld saves and detects changes between snapshots.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict
from palworld_save_tools.palsav import decompress_sav_to_gvas
from palworld_save_tools.gvas import GvasFile
from palworld_save_tools.paltypes import PALWORLD_CUSTOM_PROPERTIES


@dataclass
class SaveEvent:
    """Metadata about a save event for pattern learning."""
    timestamp: str
    file_path: str
    file_size: int
    file_size_delta: int  # vs previous save
    time_since_last: float  # seconds since last save
    save_type: str  # 'autosave', 'manual', 'unknown'
    events: list  # List of Event dicts from diff
    inferred_activity: str  # 'combat', 'catching', 'building', 'breeding', 'idle'
    snapshot: 'Snapshot' = None  # Reference to full snapshot

    def to_dict(self):
        d = {
            'timestamp': self.timestamp,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'file_size_delta': self.file_size_delta,
            'time_since_last': self.time_since_last,
            'save_type': self.save_type,
            'events': self.events,
            'inferred_activity': self.inferred_activity,
        }
        if self.snapshot:
            d['snapshot_summary'] = {
                'pal_count': self.snapshot.pal_count,
                'player_count': len(self.snapshot.players),
                'base_count': len(self.snapshot.bases),
            }
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            timestamp=d['timestamp'],
            file_path=d['file_path'],
            file_size=d['file_size'],
            file_size_delta=d['file_size_delta'],
            time_since_last=d['time_since_last'],
            save_type=d['save_type'],
            events=d['events'],
            inferred_activity=d['inferred_activity'],
            snapshot=None
        )


@dataclass
class Player:
    uid: str
    name: str
    level: int


@dataclass
class Pal:
    instance_id: str
    species: str
    level: int
    exp: int
    hp_iv: int
    def_iv: int
    atk_iv: int
    gender: str
    passives: list
    owner_uid: str
    nickname: Optional[str] = None


@dataclass
class Base:
    id: str
    name: str
    # Add more fields as we discover them


@dataclass
class Snapshot:
    timestamp: str
    file_path: str
    players: list  # List of Player dicts
    pals: list     # List of Pal dicts
    bases: list    # List of Base dicts
    pal_count: int
    game_time: Optional[int] = None
    world_id: Optional[str] = None
    host_player: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


def extract_value(obj, default=None):
    """Safely extract value from nested Palworld save structures."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        if 'value' in obj:
            return extract_value(obj['value'], default)
        return obj
    return obj


def is_host_uid(uid: str) -> bool:
    """
    Check if a player UID indicates they are the world host.
    Host players typically have UID 00000000-0000-0000-0000-000000000001.
    """
    if not uid:
        return False
    # Normalize and check for host pattern
    uid_clean = uid.lower().replace('-', '')
    return uid_clean == '00000000000000000000000000000001'


def extract_world_id(file_path: str) -> Optional[str]:
    """
    Extract WorldID from save file path.
    Path pattern: SaveGames/<SteamID>/<WorldID>/Level.sav
    """
    if not file_path:
        return None
    # Normalize path separators
    normalized = file_path.replace('\\', '/')
    parts = normalized.split('/')
    # Find Level.sav and get the parent directory (WorldID)
    for i, part in enumerate(parts):
        if part == 'Level.sav' and i > 0:
            return parts[i - 1]
    return None


def parse_save_to_json(save_path: str) -> dict:
    """Parse a save file to JSON structure using CLI tool."""
    import subprocess
    import tempfile

    # Use the CLI tool which handles parsing better
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ['palworld-save-tools', '--to-json', '--convert-nan-to-null', '--force', '-o', tmp_path, save_path],
            capture_output=True,
            text=True,
            timeout=300,
            input='y\n'  # Auto-confirm any prompts
        )

        if result.returncode != 0:
            raise Exception(f"Failed to parse save: {result.stderr}")

        with open(tmp_path, 'r') as f:
            return json.load(f)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def load_json_save(json_path: str) -> dict:
    """Load a pre-parsed JSON save file."""
    with open(json_path, 'r') as f:
        return json.load(f)


def create_snapshot(save_path: str, json_data: dict = None) -> Snapshot:
    """Create a snapshot from a save file or pre-parsed JSON."""
    if json_data is None:
        json_data = parse_save_to_json(save_path)

    world = json_data['properties']['worldSaveData']['value']

    # Extract players and pals
    players = []
    pals = []

    chars = world.get('CharacterSaveParameterMap', {}).get('value', [])

    for char in chars:
        key = char.get('key', {})
        instance_id = extract_value(key.get('InstanceId'))

        raw_data = char.get('value', {}).get('RawData', {}).get('value', {})
        obj = raw_data.get('object', {}).get('SaveParameter', {}).get('value', {})

        if not obj:
            continue

        is_player = extract_value(obj.get('IsPlayer'), False)

        if is_player:
            uid = str(extract_value(key.get('PlayerUId'), ''))
            players.append({
                'uid': uid,
                'name': extract_value(obj.get('NickName'), 'Unknown'),
                'level': extract_value(obj.get('Level'), 0),
                'is_host': is_host_uid(uid),
            })
        else:
            species = extract_value(obj.get('CharacterID'), 'Unknown')

            # Skip if no species (corrupted entry)
            if species == 'Unknown' or not species:
                continue

            pals.append({
                'instance_id': str(instance_id) if instance_id else '',
                'species': species,
                'level': extract_value(obj.get('Level'), 0),
                'exp': extract_value(obj.get('Exp'), 0),
                'hp_iv': extract_value(obj.get('Talent_HP'), 0),
                'def_iv': extract_value(obj.get('Talent_Defense'), 0),
                'atk_iv': extract_value(obj.get('Talent_Shot'), 0),
                'gender': extract_value(obj.get('Gender'), 'Unknown'),
                'passives': extract_value(obj.get('PassiveSkillList'), []),
                'owner_uid': str(extract_value(obj.get('OwnerPlayerUId'), '')),
                'nickname': extract_value(obj.get('NickName')),
            })

    # Extract bases
    bases = []
    base_camps = world.get('BaseCampSaveData', {}).get('value', [])
    for i, base in enumerate(base_camps):
        bases.append({
            'id': str(i),
            'name': f'Base {i+1}',  # Palworld doesn't seem to have base names
        })

    # Game time
    game_time_data = world.get('GameTimeSaveData', {}).get('value', {})
    game_time = extract_value(game_time_data.get('GameDateTimeTicks'))

    # Extract world ID from path
    world_id = extract_world_id(save_path)

    # Find host player
    host_player = None
    for p in players:
        if p.get('is_host'):
            host_player = p['name']
            break

    return Snapshot(
        timestamp=datetime.now().isoformat(),
        file_path=save_path,
        players=players,
        pals=pals,
        bases=bases,
        pal_count=len(pals),
        game_time=game_time,
        world_id=world_id,
        host_player=host_player,
    )


@dataclass
class Event:
    """Represents a detected change between snapshots."""
    type: str       # 'pal_caught', 'pal_released', 'pal_leveled', 'player_joined', etc.
    category: str   # 'pal', 'player', 'base', 'world'
    data: dict      # Event-specific data
    priority: int   # 1=high, 2=medium, 3=low
    message: str    # Human-readable description


def diff_snapshots(old: Snapshot, new: Snapshot) -> list:
    """Compare two snapshots and return list of Events."""
    events = []

    # Index old data for quick lookup
    old_pals = {p['instance_id']: p for p in old.pals if p['instance_id']}
    new_pals = {p['instance_id']: p for p in new.pals if p['instance_id']}
    old_players = {p['uid']: p for p in old.players if p['uid']}
    new_players = {p['uid']: p for p in new.players if p['uid']}

    # Check for new pals (caught)
    for pid, pal in new_pals.items():
        if pid not in old_pals:
            total_iv = pal['hp_iv'] + pal['def_iv'] + pal['atk_iv']
            events.append(Event(
                type='pal_caught',
                category='pal',
                data=pal,
                priority=1 if total_iv >= 200 else 2,
                message=f"Caught {pal['species']} Lv.{pal['level']} (IVs: {pal['hp_iv']}/{pal['def_iv']}/{pal['atk_iv']} = {total_iv})"
            ))

    # Check for released/lost pals
    for pid, pal in old_pals.items():
        if pid not in new_pals:
            events.append(Event(
                type='pal_released',
                category='pal',
                data=pal,
                priority=2,
                message=f"Released/Lost {pal['species']} Lv.{pal['level']}"
            ))

    # Check for pal level ups
    for pid, new_pal in new_pals.items():
        if pid in old_pals:
            old_pal = old_pals[pid]
            if new_pal['level'] > old_pal['level']:
                events.append(Event(
                    type='pal_leveled',
                    category='pal',
                    data={'old': old_pal, 'new': new_pal},
                    priority=3,
                    message=f"{new_pal['species']} leveled up: {old_pal['level']} -> {new_pal['level']}"
                ))

    # Check for new players
    for uid, player in new_players.items():
        if uid not in old_players:
            events.append(Event(
                type='player_joined',
                category='player',
                data=player,
                priority=1,
                message=f"{player['name']} joined the world (Lv.{player['level']})"
            ))

    # Check for players who left
    for uid, player in old_players.items():
        if uid not in new_players:
            events.append(Event(
                type='player_left',
                category='player',
                data=player,
                priority=1,
                message=f"{player['name']} left the world"
            ))

    # Check for player level ups
    for uid, new_player in new_players.items():
        if uid in old_players:
            old_player = old_players[uid]
            if new_player['level'] > old_player['level']:
                events.append(Event(
                    type='player_leveled',
                    category='player',
                    data={'old': old_player, 'new': new_player},
                    priority=2,
                    message=f"{new_player['name']} leveled up: {old_player['level']} -> {new_player['level']}"
                ))

    # Check for new bases
    if len(new.bases) > len(old.bases):
        events.append(Event(
            type='base_created',
            category='base',
            data={'count': len(new.bases)},
            priority=1,
            message=f"New base established! Total bases: {len(new.bases)}"
        ))

    # Pal count summary (if significant change)
    pal_diff = new.pal_count - old.pal_count
    if abs(pal_diff) >= 5:
        events.append(Event(
            type='pal_count_change',
            category='world',
            data={'old': old.pal_count, 'new': new.pal_count, 'diff': pal_diff},
            priority=3,
            message=f"Pal count: {old.pal_count} -> {new.pal_count} ({'+' if pal_diff > 0 else ''}{pal_diff})"
        ))

    # Sort by priority
    events.sort(key=lambda e: e.priority)

    return events


def classify_save_type(time_since_last: float) -> str:
    """
    Classify save type based on time interval.

    Palworld autosave interval is configurable, but defaults to ~10 minutes (600s).
    We use a range to account for variation.
    """
    if time_since_last <= 0:
        return 'unknown'  # First save or invalid

    # Autosave: typically 9-11 minutes (540-660 seconds)
    if 540 <= time_since_last <= 720:
        return 'autosave'

    # Very short interval: likely manual save after important event
    if time_since_last < 120:
        return 'manual'

    # Long interval: probably manual, or first save after break
    if time_since_last > 720:
        return 'manual'

    # Medium interval: unclear, could be either
    return 'unknown'


def infer_activity(events: list) -> str:
    """
    Infer what activity the player was doing based on detected events.
    """
    if not events:
        return 'idle'

    event_types = [e.type if hasattr(e, 'type') else e.get('type') for e in events]

    # Count event types
    level_ups = sum(1 for t in event_types if t == 'pal_leveled')
    catches = sum(1 for t in event_types if t == 'pal_caught')
    releases = sum(1 for t in event_types if t == 'pal_released')
    base_events = sum(1 for t in event_types if t == 'base_created')
    player_levels = sum(1 for t in event_types if t == 'player_leveled')

    # Determine primary activity
    if catches >= 2:
        return 'catching'
    if level_ups >= 3 or player_levels >= 1:
        return 'combat'
    if base_events >= 1:
        return 'building'
    if catches == 1 and releases == 0:
        return 'catching'
    if level_ups >= 1:
        return 'combat'
    if releases >= 1 and catches == 0:
        return 'managing'  # Releasing pals, organizing

    # Check for breeding (new pals with high IVs might indicate breeding)
    for e in events:
        if hasattr(e, 'type'):
            if e.type == 'pal_caught':
                data = e.data
        else:
            if e.get('type') == 'pal_caught':
                data = e.get('data', {})
        # Could check for breeding indicators here

    return 'exploring'  # Default: just playing around


def create_save_event(
    current_snapshot: Snapshot,
    previous_snapshot: Optional[Snapshot],
    file_path: str,
    previous_file_size: int = 0,
    previous_timestamp: str = None
) -> SaveEvent:
    """
    Create a SaveEvent by comparing current snapshot to previous.
    """
    # Get file info
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

    # Calculate time since last save
    time_since_last = 0.0
    if previous_timestamp:
        try:
            prev_dt = datetime.fromisoformat(previous_timestamp)
            curr_dt = datetime.fromisoformat(current_snapshot.timestamp)
            time_since_last = (curr_dt - prev_dt).total_seconds()
        except:
            pass

    # Get events from diff
    events = []
    if previous_snapshot:
        event_objs = diff_snapshots(previous_snapshot, current_snapshot)
        # Convert Event objects to dicts for serialization
        events = [{'type': e.type, 'category': e.category, 'message': e.message, 'priority': e.priority}
                  for e in event_objs]

    # Classify and infer
    save_type = classify_save_type(time_since_last)
    activity = infer_activity(events)

    return SaveEvent(
        timestamp=current_snapshot.timestamp,
        file_path=file_path,
        file_size=file_size,
        file_size_delta=file_size - previous_file_size,
        time_since_last=time_since_last,
        save_type=save_type,
        events=events,
        inferred_activity=activity,
        snapshot=current_snapshot
    )


def save_snapshot(snapshot: Snapshot, path: str):
    """Save snapshot to JSON file."""
    with open(path, 'w') as f:
        json.dump(snapshot.to_dict(), f, indent=2, default=str)


def load_snapshot(path: str) -> Snapshot:
    """Load snapshot from JSON file."""
    with open(path, 'r') as f:
        return Snapshot.from_dict(json.load(f))


# CLI for testing
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python snapshot.py <save_path_or_json> [previous_snapshot.json]")
        print("  save_path_or_json: Either a .sav file or a pre-parsed .json file")
        sys.exit(1)

    input_path = sys.argv[1]

    # Check if it's a JSON file (pre-parsed) or SAV file
    if input_path.endswith('.json'):
        print(f"Loading pre-parsed JSON: {input_path}")
        json_data = load_json_save(input_path)
        snapshot = create_snapshot(input_path, json_data)
    else:
        print(f"Parsing save: {input_path}")
        print("This may take a moment...")
        snapshot = create_snapshot(input_path)

    print(f"\n=== SNAPSHOT ===")
    print(f"Timestamp: {snapshot.timestamp}")
    if snapshot.world_id:
        print(f"World ID: {snapshot.world_id}")
    if snapshot.host_player:
        print(f"Host: {snapshot.host_player}")
    print(f"Players: {len(snapshot.players)}")
    for p in snapshot.players:
        host_marker = " [HOST]" if p.get('is_host') else ""
        print(f"  - {p['name']} (Lv.{p['level']}){host_marker}")
    print(f"Pals: {snapshot.pal_count}")
    print(f"Bases: {len(snapshot.bases)}")

    # If previous snapshot provided, show diff
    if len(sys.argv) >= 3:
        prev_path = sys.argv[2]
        print(f"\n=== DIFF from {prev_path} ===")
        old_snapshot = load_snapshot(prev_path)
        events = diff_snapshots(old_snapshot, snapshot)

        if events:
            for event in events:
                print(f"[{event.category.upper()}] {event.message}")
        else:
            print("No changes detected.")

    # Save current snapshot
    output_path = 'snapshot_latest.json'
    save_snapshot(snapshot, output_path)
    print(f"\nSnapshot saved to {output_path}")
