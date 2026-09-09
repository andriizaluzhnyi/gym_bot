"""Pure helpers for the workout-program `sets_reps` field (GYM-30, GYM-46).

Extracted from the bot's program-creation FSM
(``src/bot/handlers/workout_program.py``: ``process_sets_text``,
``process_comment``) so the same validation/combination rule can be reused
by ``POST /api/workout/program/exercise`` — previously that rule only
existed as inline control flow inside the bot handler, with no shared
place a second caller could reuse. Behavior for the bot is unchanged.

GYM-46 adds support for a *list* of "sets/reps" blocks separated by commas
(e.g. ``"2/12, 4/6"`` — two warm-up sets of 12, then four working sets of
6), via :func:`parse_sets_reps`/:func:`normalize_sets_reps`, and rebuilds
:func:`is_valid_sets_reps` on top of them.
"""

import re

# The fixed set of muscle groups a program day/exercise can belong to.
# Originally lived only in ``src/bot/keyboards.py`` (which still
# re-exports it from here for backward compatibility — existing bot code
# and tests import it as ``keyboards.MUSCLE_GROUPS``); moved here so
# ``POST /api/workout/program/exercise`` (GYM-30) can validate against the
# same list without the webapp importing from the bot package.
MUSCLE_GROUPS = ["🦴 Спина", "💪 Руки", "🎯 Плечі", "🏋️ Груди", "🦵 Ноги"]

# ``WorkoutProgramExercise.sets_reps`` is a ``String(50)`` column
# (``src/database/models.py``) — enforced here too so a too-long value is
# rejected with a clear `400` instead of failing at the DB with a `500`.
MAX_SETS_REPS_LENGTH = 50

# One "sets/reps" block — e.g. "3/10", "4|8", "4x10", "4х10" (the last
# with a Cyrillic "х", a common typo/IME artifact for the Latin "x" on a
# Ukrainian keyboard). Whitespace around the separator is tolerated (a
# human might type "3 / 10").
_ELEMENT_RE = re.compile(r"^(\d+)\s*[/|xXхХ]\s*(\d+)$")
# A bare number — e.g. "3" — matches what the bot's two-step flow allows:
# sets entered alone (without a separator), then reps collected separately
# and joined with `combine_sets_reps`. Only meaningful as the *sole*
# element of a `parse_sets_reps` list — "3, 4/6" is not "3 sets (reps
# unknown) then 4/6", it's rejected outright (see `parse_sets_reps`).
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


def parse_sets_reps(value: str) -> list[tuple[int, int]] | None:
    """Parse `value` into an ordered list of ``(sets, reps)`` pairs.

    Accepts a comma-separated list of blocks, each ``N/M``, ``N|M``,
    ``NxM`` or ``NхM`` (see :data:`_ELEMENT_RE`) — e.g. ``"2/12, 4/6"`` is
    two blocks, ``[(2, 12), (4, 6)]``. A bare number (``"3"``, no
    separator) is accepted **only** when it is the value's sole element —
    ``"3, 4/6"`` is invalid, not "3 sets of unknown reps, then 4/6"; a
    lone bare number parses as ``[(3, 0)]`` (``reps=0`` is this module's
    convention for "sets recorded, reps not").

    Returns ``None`` if the value is empty/blank, any block fails to
    parse, or any parsed ``sets``/``reps`` is ``0`` (a block can't have
    zero sets, and a non-bare block can't claim zero reps either).
    """
    if not value or not value.strip():
        return None

    parts = [p.strip() for p in value.split(",")]
    if any(not p for p in parts):
        return None

    if len(parts) == 1 and _BARE_NUMBER_RE.match(parts[0]):
        sets = int(parts[0])
        return None if sets == 0 else [(sets, 0)]

    result: list[tuple[int, int]] = []
    for part in parts:
        match = _ELEMENT_RE.match(part)
        if not match:
            return None
        sets, reps = int(match.group(1)), int(match.group(2))
        if sets == 0 or reps == 0:
            return None
        result.append((sets, reps))
    return result


def normalize_sets_reps(value: str) -> str | None:
    """Canonical rendering of `value`, or ``None`` if it isn't a valid
    ``sets_reps`` string (see :func:`parse_sets_reps`).

    Each parsed block renders as ``"N/M"``; a lone bare-number block (no
    reps recorded) renders as just ``"N"``, matching what
    :func:`combine_sets_reps` has always stored for that case. Multiple
    blocks join with ``", "`` (comma + space) regardless of how the
    original separators/spacing looked — e.g. ``"2/12,4x6"`` normalizes to
    ``"2/12, 4/6"``.
    """
    parsed = parse_sets_reps(value)
    if parsed is None:
        return None
    return ", ".join(
        str(sets) if reps == 0 else f"{sets}/{reps}" for sets, reps in parsed
    )


def is_valid_sets_reps(value: str) -> bool:
    """True if `value` is a format the workout-program flow accepts as a
    final ``sets_reps`` — parses via :func:`parse_sets_reps` **and** fits
    the ``sets_reps`` column once normalized (:data:`MAX_SETS_REPS_LENGTH`).

    Used by ``POST``/``PATCH /api/workout/program/exercise`` to reject
    obviously-malformed input from the webapp's free-text field — the bot
    FSM never needed this check because its keyboards constrain the input
    shape already; a webapp text field doesn't have that guardrail.
    """
    normalized = normalize_sets_reps(value)
    return normalized is not None and len(normalized) <= MAX_SETS_REPS_LENGTH
