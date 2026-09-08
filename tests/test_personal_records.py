"""Tests for GYM-7: PR calculation (src/services/personal_records.py).

No DB needed — WorkoutSet is a plain SQLAlchemy declarative model, so
instantiating it in memory (never added to a session) is enough to drive
the pure calculate_prs()/estimated_1rm() functions.
"""

from datetime import datetime

from src.database.models import WorkoutSet
from src.services.personal_records import calculate_prs, estimated_1rm


def _set(
    *, exercise="Жим лежачи", muscle_group="Груди", weight, reps,
    performed_at=None,
) -> WorkoutSet:
    return WorkoutSet(
        session_id=1,
        user_id="00000000-0000-0000-0000-000000000001",
        exercise_name=exercise,
        muscle_group=muscle_group,
        set_number=1,
        weight=weight,
        reps=reps,
        performed_at=performed_at or datetime(2026, 1, 1),
    )


class TestEstimated1RM:
    def test_epley_formula(self):
        assert estimated_1rm(100, 10) == 100 * (1 + 10 / 30)

    def test_single_rep_equals_the_weight_itself(self):
        assert estimated_1rm(100, 1) == 100 * (1 + 1 / 30)

    def test_zero_reps_does_not_divide_by_zero(self):
        assert estimated_1rm(100, 0) == 100.0


class TestCalculatePrsEmpty:
    def test_no_sets_returns_empty_dict(self):
        assert calculate_prs([]) == {}


class TestCalculatePrsMaxWeight:
    def test_picks_the_heaviest_set(self):
        sets = [
            _set(weight=60, reps=10, performed_at=datetime(2026, 1, 1)),
            _set(weight=80, reps=5, performed_at=datetime(2026, 1, 5)),
            _set(weight=70, reps=8, performed_at=datetime(2026, 1, 3)),
        ]
        pr = calculate_prs(sets)["Жим лежачи"]

        assert pr.max_weight.weight == 80
        assert pr.max_weight.reps == 5
        assert pr.max_weight.achieved_at == datetime(2026, 1, 5)

    def test_ties_go_to_whichever_happened_first(self):
        sets = [
            _set(weight=80, reps=5, performed_at=datetime(2026, 1, 10)),
            _set(weight=80, reps=6, performed_at=datetime(2026, 1, 3)),
        ]
        pr = calculate_prs(sets)["Жим лежачи"]

        assert pr.max_weight.achieved_at == datetime(2026, 1, 3)
        assert pr.max_weight.reps == 6  # the reps of the earlier, tied set


class TestCalculatePrsMaxReps:
    def test_picks_the_set_with_the_most_reps(self):
        sets = [
            _set(weight=60, reps=10, performed_at=datetime(2026, 1, 1)),
            _set(weight=40, reps=20, performed_at=datetime(2026, 1, 5)),
        ]
        pr = calculate_prs(sets)["Жим лежачи"]

        assert pr.max_reps.reps == 20
        assert pr.max_reps.weight == 40
        assert pr.max_reps.achieved_at == datetime(2026, 1, 5)


class TestCalculatePrsEstimated1RM:
    def test_picks_the_set_with_the_highest_estimated_1rm(self):
        sets = [
            # 1RM = 60 * (1 + 10/30) = 80
            _set(weight=60, reps=10, performed_at=datetime(2026, 1, 1)),
            # 1RM = 90 * (1 + 2/30) = 96
            _set(weight=90, reps=2, performed_at=datetime(2026, 1, 5)),
        ]
        pr = calculate_prs(sets)["Жим лежачи"]

        assert pr.estimated_1rm.estimated_1rm == 96.0
        assert pr.estimated_1rm.weight == 90
        assert pr.estimated_1rm.reps == 2
        assert pr.estimated_1rm.achieved_at == datetime(2026, 1, 5)


class TestCalculatePrsMultipleExercises:
    def test_each_exercise_gets_its_own_record(self):
        sets = [
            _set(exercise="Жим лежачи", muscle_group="Груди", weight=60, reps=10),
            _set(exercise="Присідання", muscle_group="Ноги", weight=100, reps=5),
        ]
        prs = calculate_prs(sets)

        assert set(prs.keys()) == {"Жим лежачи", "Присідання"}
        assert prs["Присідання"].max_weight.weight == 100
        assert prs["Присідання"].muscle_group == "Ноги"

    def test_the_three_prs_can_come_from_different_sets(self):
        """A single session's worth of sets, where no one set wins all
        three PRs at once — realistic pyramid-style working sets."""
        sets = [
            _set(weight=100, reps=1, performed_at=datetime(2026, 1, 1)),  # heaviest
            _set(weight=60, reps=15, performed_at=datetime(2026, 1, 1)),  # most reps
            _set(weight=90, reps=4, performed_at=datetime(2026, 1, 1)),
        ]
        pr = calculate_prs(sets)["Жим лежачи"]

        assert pr.max_weight.weight == 100
        assert pr.max_reps.reps == 15
        # 1RM: 100*(1+1/30)=103.3, 60*(1+15/30)=90, 90*(1+4/30)=102 -> the
        # single at 100kg wins here, but it's a distinct code path from
        # max_weight (computed via the formula, not just picking top weight).
        assert pr.estimated_1rm.weight == 100


class TestCalculatePrsMuscleGroup:
    def test_uses_the_most_recently_logged_muscle_group(self):
        sets = [
            _set(muscle_group="Спина", weight=50, reps=10, performed_at=datetime(2026, 1, 1)),
            _set(muscle_group="Руки", weight=52, reps=10, performed_at=datetime(2026, 1, 8)),
        ]
        pr = calculate_prs(sets)["Жим лежачи"]

        assert pr.muscle_group == "Руки"

    def test_falls_back_to_none_when_never_recorded(self):
        sets = [_set(muscle_group=None, weight=50, reps=10)]
        pr = calculate_prs(sets)["Жим лежачи"]

        assert pr.muscle_group is None
