"""Personal-record (PR) calculation for workout sets (GYM-7).

Pure, DB-free logic on purpose: :func:`calculate_prs` takes whatever sets
the caller already has in memory and does no I/O itself, so it works both
for "what are my current PRs" (pass a user's full history) and for "did
this session just set a PR" (GYM-9: pass the full history, then check
whether any PR's ``achieved_at`` falls within the session just saved).

Not named ``statistics.py`` — that would shadow the standard library's
``statistics`` module (flake8-builtins ``A005``), the same reason
``src/bot/handlers/workout_statistics.py`` isn't ``statistics.py`` either.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from src.database.models import WorkoutSet


def estimated_1rm(weight: float, reps: int) -> float:
    """Estimated one-rep max via the Epley formula: ``weight * (1 + reps/30)``."""
    return weight * (1 + reps / 30)


@dataclass(frozen=True)
class SetRecord:
    """A logged set that is the current max-weight or max-reps PR."""

    weight: float
    reps: int
    achieved_at: datetime


@dataclass(frozen=True)
class EstimatedOneRepMaxRecord:
    """The best estimated 1RM, and the set that produced it."""

    estimated_1rm: float
    weight: float
    reps: int
    achieved_at: datetime


@dataclass(frozen=True)
class PRRecord:
    """One exercise's personal records: heaviest weight, most reps in a
    single set, and best estimated 1RM — each may have been set on a
    different date, hence each carries its own ``achieved_at``.
    """

    exercise_name: str
    muscle_group: str | None
    max_weight: SetRecord
    max_reps: SetRecord
    estimated_1rm: EstimatedOneRepMaxRecord


def _pick_best(
    sets: Sequence[WorkoutSet], value_of: Callable[[WorkoutSet], float]
) -> tuple[float, WorkoutSet]:
    """Pick the set with the highest ``value_of(set)``.

    Ties go to whichever happened first — the record has held since then,
    a later set merely matching it doesn't set a new one.
    """
    best_value = float('-inf')
    best_set: WorkoutSet | None = None

    for workout_set in sets:
        value = value_of(workout_set)
        if (
            best_set is None
            or value > best_value
            or (value == best_value and workout_set.performed_at < best_set.performed_at)
        ):
            best_value = value
            best_set = workout_set

    assert best_set is not None  # sets is non-empty per caller
    return best_value, best_set


def _latest_muscle_group(sets: Sequence[WorkoutSet]) -> str | None:
    """The most recently-recorded ``muscle_group`` for these sets, in case
    it drifted across logs (same convention as
    ``WorkoutSetRepository.get_distinct_exercises``, GYM-5a).
    """
    latest: str | None = None
    for workout_set in sorted(sets, key=lambda s: s.performed_at):
        if workout_set.muscle_group is not None:
            latest = workout_set.muscle_group
    return latest


def calculate_prs(sets: Sequence[WorkoutSet]) -> dict[str, PRRecord]:
    """Compute each exercise's personal records across the given sets.

    Keyed by ``exercise_name``. Exercises with no sets in the input simply
    don't appear — an empty ``sets`` returns ``{}``, never an error.
    """
    by_exercise: dict[str, list[WorkoutSet]] = {}
    for workout_set in sets:
        by_exercise.setdefault(workout_set.exercise_name, []).append(workout_set)

    records: dict[str, PRRecord] = {}
    for exercise_name, exercise_sets in by_exercise.items():
        _, weight_set = _pick_best(exercise_sets, lambda s: s.weight)
        _, reps_set = _pick_best(exercise_sets, lambda s: s.reps)
        rm_value, rm_set = _pick_best(
            exercise_sets, lambda s: estimated_1rm(s.weight, s.reps)
        )

        records[exercise_name] = PRRecord(
            exercise_name=exercise_name,
            muscle_group=_latest_muscle_group(exercise_sets),
            max_weight=SetRecord(
                weight=weight_set.weight,
                reps=weight_set.reps,
                achieved_at=weight_set.performed_at,
            ),
            max_reps=SetRecord(
                weight=reps_set.weight,
                reps=reps_set.reps,
                achieved_at=reps_set.performed_at,
            ),
            estimated_1rm=EstimatedOneRepMaxRecord(
                estimated_1rm=rm_value,
                weight=rm_set.weight,
                reps=rm_set.reps,
                achieved_at=rm_set.performed_at,
            ),
        )

    return records
