from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arbvoy.journal.db import JournalDB


@dataclass(slots=True)
class JournalWriter:
    db: JournalDB

    async def write_event(self, event_type: str, payload: dict[str, Any]) -> None:
        await self.db.record_audit_event(event_type, payload)

