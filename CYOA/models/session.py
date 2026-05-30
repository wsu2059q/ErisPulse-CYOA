from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class GameSession:
    story_id: str = ""
    user_id: str = ""
    group_id: Optional[str] = None
    platform: str = ""
    ink_state: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    saved_slot: int = 0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.updated_at == 0.0:
            self.updated_at = time.time()

    @property
    def save_key(self) -> str:
        slot = self.saved_slot or 1
        parts = [self.user_id]
        if self.group_id:
            parts.append(self.group_id)
        return f"saves.{'.'.join(parts)}.{self.story_id}.{slot}"

    @staticmethod
    def save_key_pattern(user_id: str, story_id: str, group_id: Optional[str] = None) -> str:
        parts = [user_id]
        if group_id:
            parts.append(group_id)
        return f"saves.{'.'.join(parts)}.{story_id}"

    def to_dict(self) -> dict:
        return {
            "story_id": self.story_id,
            "user_id": self.user_id,
            "group_id": self.group_id,
            "platform": self.platform,
            "ink_state": self.ink_state,
            "saved_slot": self.saved_slot,
            "saved_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameSession":
        return cls(
            story_id=d.get("story_id", ""),
            user_id=d.get("user_id", ""),
            group_id=d.get("group_id"),
            platform=d.get("platform", ""),
            ink_state=d.get("ink_state"),
            created_at=d.get("created_at", d.get("saved_at", 0.0)),
            saved_slot=d.get("saved_slot", 0),
        )

    def touch(self):
        self.updated_at = time.time()
