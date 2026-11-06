"""Escalating lockout rule shared by password and MFA failures."""


def lockout_minutes(failed_attempts, threshold, schedule):
    """Minutes an account stays locked after `failed_attempts` failures.

    The first lockout happens at `threshold` failures; every further `threshold`
    failures moves one step up `schedule` (the last step repeats). Returns None
    while the account must not be locked.
    """
    if threshold <= 0 or failed_attempts < threshold or not schedule:
        return None

    step = min((failed_attempts - threshold) // threshold, len(schedule) - 1)
    return schedule[step]
