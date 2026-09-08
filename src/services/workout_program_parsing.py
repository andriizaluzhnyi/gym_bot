"""Pure helpers for the workout-program `sets_reps` field (GYM-30).

Extracted from the bot's program-creation FSM
(``src/bot/handlers/workout_program.py``: ``process_sets_text``,
``process_comment``) so the same validation/combination rule can be reused
by ``POST /api/workout/program/exercise`` — previously that rule only
existed as inline control flow inside the bot handler, with no shared
place a second caller could reuse. Behavior for the bot is unchanged.
"""

import re

# The fixed set of muscle groups a program day/exercise can belong to.
# Originally lived only in ``src/bot/keyboards.py`` (which still
# re-exports it from here for backward compatibility — existing bot code
# and tests import it as ``keyboards.MUSCLE_GROUPS``); moved here so
# ``POST /api/workout/program/exercise`` (GYM-30) can validate against the
# same list without the webapp importing from the bot package.
MUSCLE_GROUPS = ["🦴 Спина", "💪 Руки", "🎯 Плечі", "🏋️ Груди", "🦵 Ноги"]

# Combined "sets/reps" or "sets|reps" — e.g. "3/10", "4|8". Whitespace
# around the separator is tolerated (a human might type "3 / 10").
_COMBINED_RE = re.compile(r"^\d+\s*[/|]\s*\d+$")
# A bare number — e.g. "3" — matches what the bot's two-step flow allows:
# sets entered alone (without "/" or "|"), then reps collected separately
# and joined with `combine_sets_reps`. The *final* stored value from that
# flow is never a bare number by itself (it's always joined with reps
# first) — this pattern exists so `is_valid_sets_reps` still accepts a
# lone number for a caller (like the webapp form) that only has a single
# free-text field and wants to allow "just sets, no reps recorded".
_BARE_NUMBER_RE = re.compile(r"^\d+$")


def looks_like_combined_sets_reps(text: str) -> bool:
    """True if `text` already contains a "/" or "|" separator — the bot's
    ``process_sets_text`` uses this to decide whether manual sets input is
    already a complete "sets/reps" answer (skip the separate reps step) or
    just the sets half (continue to ask for reps).
    """
    return "/" in text or "|" in text


def combine_sets_reps(sets: str, reps: str = "") -> str:
    """Join the bot flow's separately-collected `sets`/`reps` into the
    final string stored on a program row.

    If `reps` is empty, `sets` is returned as-is — it's already a complete
    answer (either a combined "N/M"/"N|M" string the user typed directly,
    per :func:`looks_like_combined_sets_reps`, or free text taken
    verbatim). Otherwise returns ``f"{sets}/{reps}"``, matching
    ``process_comment``'s previous inline behavior exactly.
    """
    sets = sets.strip()
    reps = reps.strip()
    return sets if not reps else f"{sets}/{reps}"


def is_valid_sets_reps(value: str) -> bool:
    """True if `value` is a format the workout-program flow accepts as a
    final ``sets_reps``: combined "N/M" or "N|M" (:data:`_COMBINED_RE`),
    or a bare number (:data:`_BARE_NUMBER_RE`).

    Used by ``POST /api/workout/program/exercise`` (GYM-30) to reject
    obviously-malformed input from the webapp's free-text field — the bot
    FSM never needed this check because its keyboards constrain the input
    shape already; a webapp text field doesn't have that guardrail.
    """
    value = value.strip()
    return bool(_COMBINED_RE.match(value) or _BARE_NUMBER_RE.match(value))
