import pytest

from identity.domain.lockout import lockout_minutes

SCHEDULE = [5, 15, 30]


@pytest.mark.parametrize(
    "failures, expected",
    [(0, None), (4, None), (5, 5), (9, 5), (10, 15), (14, 15), (15, 30), (99, 30)],
)
def test_lockout_escalates_every_threshold_and_repeats_the_last_step(
    failures, expected
):
    assert lockout_minutes(failures, 5, SCHEDULE) == expected


@pytest.mark.parametrize("threshold", [0, -1])
def test_a_non_positive_threshold_never_locks(threshold):
    assert lockout_minutes(10, threshold, SCHEDULE) is None


def test_an_empty_schedule_never_locks():
    assert lockout_minutes(10, 5, []) is None
