#!/usr/bin/env python3
"""
PAL-E History System
Stores save events over time and learns patterns from observation.
"""

import json
import os
from datetime import datetime
from typing import Optional, List
from collections import Counter
from dataclasses import dataclass, asdict

from snapshot import SaveEvent, Snapshot, load_snapshot, create_save_event


@dataclass
class SessionSummary:
    """Summary of a play session."""
    start_time: str
    end_time: str
    duration_minutes: float
    save_count: int
    pals_caught: int
    pals_released: int
    level_ups: int
    bases_built: int
    primary_activity: str  # Most common inferred activity


class SaveHistory:
    """
    Persistent storage for save events and pattern learning.
    """

    def __init__(self, history_file: str = 'save_history.json', max_events: int = 100):
        self.history_file = history_file
        self.max_events = max_events
        self.events: List[dict] = []
        self.patterns: dict = {}
        self.load()

    def load(self):
        """Load history from file."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    self.events = data.get('events', [])
                    self.patterns = data.get('patterns', {})
            except Exception as e:
                print(f"Warning: Could not load history: {e}")
                self.events = []
                self.patterns = {}

    def save(self):
        """Save history to file."""
        # Trim to max_events
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

        with open(self.history_file, 'w') as f:
            json.dump({
                'events': self.events,
                'patterns': self.patterns,
                'last_updated': datetime.now().isoformat(),
            }, f, indent=2, default=str)

    def add_event(self, save_event: SaveEvent):
        """Add a new save event to history."""
        self.events.append(save_event.to_dict())
        self._update_patterns()
        self.save()

    def _update_patterns(self):
        """Update learned patterns from event history."""
        if len(self.events) < 3:
            return

        # Calculate average time between saves by type
        autosave_intervals = []
        manual_intervals = []

        for event in self.events:
            interval = event.get('time_since_last', 0)
            if interval > 0:
                if event.get('save_type') == 'autosave':
                    autosave_intervals.append(interval)
                elif event.get('save_type') == 'manual':
                    manual_intervals.append(interval)

        # Activity frequency
        activities = Counter(e.get('inferred_activity', 'unknown') for e in self.events)

        # Event type frequency
        all_events = []
        for save_event in self.events:
            all_events.extend(save_event.get('events', []))
        event_types = Counter(e.get('type', 'unknown') for e in all_events)

        self.patterns = {
            'avg_autosave_interval': sum(autosave_intervals) / len(autosave_intervals) if autosave_intervals else 0,
            'avg_manual_interval': sum(manual_intervals) / len(manual_intervals) if manual_intervals else 0,
            'activity_distribution': dict(activities),
            'event_type_distribution': dict(event_types),
            'total_saves': len(self.events),
        }

    def get_recent_events(self, count: int = 10) -> List[dict]:
        """Get most recent save events."""
        return self.events[-count:]

    def get_session_summary(self) -> Optional[SessionSummary]:
        """
        Summarize the current/recent play session.
        A session is defined as saves within 30 minutes of each other.
        """
        if not self.events:
            return None

        # Find session boundaries (gaps > 30 min)
        session_events = []
        for event in reversed(self.events):
            if session_events:
                last_time = datetime.fromisoformat(session_events[-1]['timestamp'])
                this_time = datetime.fromisoformat(event['timestamp'])
                gap = (last_time - this_time).total_seconds()
                if gap > 1800:  # 30 minutes
                    break
            session_events.append(event)

        session_events.reverse()

        if not session_events:
            return None

        # Calculate summary
        start_time = session_events[0]['timestamp']
        end_time = session_events[-1]['timestamp']
        duration = (datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)).total_seconds() / 60

        # Count events
        pals_caught = 0
        pals_released = 0
        level_ups = 0
        bases_built = 0
        activities = []

        for save_event in session_events:
            activities.append(save_event.get('inferred_activity', 'unknown'))
            for event in save_event.get('events', []):
                event_type = event.get('type')
                if event_type == 'pal_caught':
                    pals_caught += 1
                elif event_type == 'pal_released':
                    pals_released += 1
                elif event_type in ('pal_leveled', 'player_leveled'):
                    level_ups += 1
                elif event_type == 'base_created':
                    bases_built += 1

        # Most common activity
        activity_counts = Counter(activities)
        primary_activity = activity_counts.most_common(1)[0][0] if activity_counts else 'unknown'

        return SessionSummary(
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration,
            save_count=len(session_events),
            pals_caught=pals_caught,
            pals_released=pals_released,
            level_ups=level_ups,
            bases_built=bases_built,
            primary_activity=primary_activity,
        )

    def get_stats(self) -> dict:
        """Get overall statistics."""
        if not self.events:
            return {'message': 'No history yet'}

        total_events = []
        for save_event in self.events:
            total_events.extend(save_event.get('events', []))

        event_counts = Counter(e.get('type') for e in total_events)

        return {
            'total_saves': len(self.events),
            'total_pals_caught': event_counts.get('pal_caught', 0),
            'total_pals_released': event_counts.get('pal_released', 0),
            'total_level_ups': event_counts.get('pal_leveled', 0) + event_counts.get('player_leveled', 0),
            'total_bases_built': event_counts.get('base_created', 0),
            'patterns': self.patterns,
        }

    def detect_trends(self) -> List[str]:
        """
        Detect trends in recent activity.
        Returns list of observation strings.
        """
        trends = []

        if len(self.events) < 5:
            return ["Not enough data yet to detect trends"]

        recent = self.events[-10:]

        # Activity trend
        recent_activities = [e.get('inferred_activity') for e in recent]
        activity_counts = Counter(recent_activities)
        top_activity, count = activity_counts.most_common(1)[0]
        if count >= 5:
            trends.append(f"You've been mostly {top_activity} lately ({count}/10 saves)")

        # Event trend
        recent_events = []
        for save_event in recent:
            recent_events.extend(save_event.get('events', []))

        event_counts = Counter(e.get('type') for e in recent_events)
        if event_counts.get('pal_caught', 0) >= 3:
            trends.append(f"Catching spree! {event_counts['pal_caught']} pals caught recently")
        if event_counts.get('pal_leveled', 0) >= 5:
            trends.append(f"Training hard! {event_counts['pal_leveled']} level ups recently")

        # File size trend
        sizes = [e.get('file_size', 0) for e in recent if e.get('file_size')]
        if len(sizes) >= 3:
            if sizes[-1] > sizes[0] * 1.1:
                trends.append("Your world is growing (save file size increasing)")

        return trends if trends else ["Playing steadily, no strong trends detected"]


# CLI for testing
if __name__ == '__main__':
    import sys

    history = SaveHistory()

    if len(sys.argv) > 1 and sys.argv[1] == 'stats':
        print("=== SAVE HISTORY STATS ===")
        stats = history.get_stats()
        for key, value in stats.items():
            if key != 'patterns':
                print(f"  {key}: {value}")

        print("\n=== PATTERNS ===")
        for key, value in stats.get('patterns', {}).items():
            print(f"  {key}: {value}")

        print("\n=== TRENDS ===")
        for trend in history.detect_trends():
            print(f"  - {trend}")

    elif len(sys.argv) > 1 and sys.argv[1] == 'session':
        summary = history.get_session_summary()
        if summary:
            print("=== SESSION SUMMARY ===")
            print(f"  Duration: {summary.duration_minutes:.1f} minutes")
            print(f"  Saves: {summary.save_count}")
            print(f"  Pals caught: {summary.pals_caught}")
            print(f"  Level ups: {summary.level_ups}")
            print(f"  Primary activity: {summary.primary_activity}")
        else:
            print("No session data available")

    else:
        print(f"History file: {history.history_file}")
        print(f"Total events: {len(history.events)}")
        print("\nUsage:")
        print("  python history.py stats    - Show statistics")
        print("  python history.py session  - Show current session summary")
