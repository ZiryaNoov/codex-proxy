"""Context compaction — trim conversation history to fit within limits."""

from __future__ import annotations


def compact_messages(
    messages: list[dict], max_messages: int = 50, keep_last: int = 20,
) -> list[dict]:
    """Compact messages if the conversation exceeds max_messages.

    Strategy:
    - Always keep the system message (if present)
    - Keep the last `keep_last` messages
    - Drop messages in between, inserting a compaction notice

    Returns messages unchanged if under the limit.
    """
    if len(messages) <= max_messages:
        return messages

    system_msgs: list[dict] = []
    rest = messages
    if messages and messages[0].get("role") == "system":
        system_msgs = [messages[0]]
        rest = messages[1:]

    if len(rest) <= keep_last:
        return messages

    kept = rest[-keep_last:]
    dropped_count = len(rest) - keep_last

    compaction_notice = {
        "role": "system",
        "content": (
            f"[Context compacted: {dropped_count} earlier messages were "
            "dropped to fit context limits. Continue based on the "
            "remaining conversation.]"
        ),
    }

    return system_msgs + [compaction_notice] + kept
