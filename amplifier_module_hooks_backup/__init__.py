"""
Transcript backup hook module for Amplifier.
Saves conversation transcripts before compaction and at session end.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Optional

from amplifier_core import HookRegistry
from amplifier_core import HookResult
from amplifier_core import ModuleCoordinator

logger = logging.getLogger(__name__)


async def mount(coordinator: ModuleCoordinator, config: dict[str, Any] | None = None):
    """
    Mount the transcript backup hook.

    Args:
        coordinator: Module coordinator
        config: Hook configuration

    Returns:
        Optional cleanup function
    """
    config = config or {}
    hook = TranscriptBackupHook(config)

    # Get hook registry
    hooks = coordinator.get("hooks")
    if not hooks:
        logger.warning("No hook registry found")
        return None

    # Register for relevant events
    unregister_funcs = []

    # Backup before compaction
    unregister_funcs.append(
        hooks.register(
            HookRegistry.CONTEXT_PRE_COMPACT, hook.on_pre_compact, priority=10, name="transcript-backup-compact"
        )
    )

    # Backup at session end
    unregister_funcs.append(
        hooks.register(HookRegistry.SESSION_END, hook.on_session_end, priority=100, name="transcript-backup-end")
    )

    logger.info("Mounted TranscriptBackupHook")

    # Return cleanup function
    def cleanup():
        for unregister in unregister_funcs:
            unregister()

    return cleanup


class TranscriptBackupHook:
    """Backs up conversation transcripts at key lifecycle points."""

    def __init__(self, config: dict[str, Any]):
        """
        Initialize backup hook.

        Args:
            config: Hook configuration
        """
        self.config = config
        self.backup_dir = Path(config.get("backup_dir", ".amplifier/transcripts"))
        self.format = config.get("format", "jsonl")  # json or jsonl
        self.include_metadata = config.get("include_metadata", True)

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def on_pre_compact(self, event: str, data: dict[str, Any]) -> HookResult:
        """
        Handle pre-compact event - save transcript before compaction.

        Args:
            event: Event name
            data: Event data with messages

        Returns:
            Hook result
        """
        try:
            # Get messages from event data
            messages = data.get("messages", [])
            if not messages:
                logger.warning("No messages to backup in pre-compact")
                return HookResult(action="continue")

            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"transcript_compact_{timestamp}.{self.format}"
            filepath = self.backup_dir / filename

            # Save transcript
            await self._save_transcript(
                filepath, messages, {"event": "pre_compact", "timestamp": timestamp, "message_count": len(messages)}
            )

            logger.info(f"Backed up {len(messages)} messages to {filepath}")

            # Add backup location to event data
            modified_data = data.copy()
            modified_data["backup_location"] = str(filepath)

            return HookResult(action="modify", data=modified_data)

        except Exception as e:
            logger.error(f"Failed to backup transcript: {e}")
            # Don't block compaction on backup failure
            return HookResult(action="continue")

    async def on_session_end(self, event: str, data: dict[str, Any]) -> HookResult:
        """
        Handle session end event - save final transcript.

        Args:
            event: Event name
            data: Event data

        Returns:
            Hook result
        """
        try:
            # Try to get context from coordinator to save final state
            # This is a simplified version - in production would need proper access

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"transcript_final_{timestamp}.{self.format}"
            filepath = self.backup_dir / filename

            # Save minimal session info if no messages available
            await self._save_transcript(
                filepath, [], {"event": "session_end", "timestamp": timestamp, "response": data.get("response", "")}
            )

            logger.info(f"Saved session end transcript to {filepath}")

            return HookResult(action="continue")

        except Exception as e:
            logger.error(f"Failed to save session transcript: {e}")
            return HookResult(action="continue")

    async def _save_transcript(self, filepath: Path, messages: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
        """
        Save transcript to file.

        Args:
            filepath: Path to save transcript
            messages: List of messages
            metadata: Additional metadata
        """
        if self.format == "jsonl":
            # Save as JSONL (one message per line)
            with open(filepath, "w", encoding="utf-8") as f:
                if self.include_metadata:
                    f.write(json.dumps({"metadata": metadata}) + "\n")

                for msg in messages:
                    f.write(json.dumps(msg) + "\n")

        elif self.format == "json":
            # Save as single JSON object
            transcript: dict[str, Any] = {"messages": messages}

            if self.include_metadata:
                transcript["metadata"] = metadata

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(transcript, f, indent=2, ensure_ascii=False)

        else:
            raise ValueError(f"Unknown format: {self.format}")
