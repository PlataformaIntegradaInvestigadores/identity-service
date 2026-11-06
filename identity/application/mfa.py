"""MFA enrollment and the TOTP check that completes a login.

Confirming an enrollment and verifying a login run the same protocol (lock the
challenge, check the code, count failures, lock the account); only the challenge
purpose, the secret that is checked and what happens on success differ.
"""

from dataclasses import dataclass
from http import HTTPStatus

from django.db import transaction

from identity.domain.exceptions import DomainValidationError
from identity.mfa_services import (
    GENERIC_MFA_ERROR,
    MFAEnrollmentSecret,
    MFALockedError,
    MFAServiceError,
    activate_pending_mfa_secret,
    create_pending_enrollment_secret,
    get_active_totp_secret,
    get_pending_totp_secret,
    hash_challenge_token,
    mark_challenge_used,
    record_mfa_failure,
    record_mfa_success,
    validate_totp_code,
)
from identity.models import MFAChallenge, User, UserMFASettings
from identity.security_events import emit_security_event

BAD_REQUEST = HTTPStatus.BAD_REQUEST.value


class MFAChallengeRejected(DomainValidationError):
    """The challenge or the code is not acceptable (one generic message)."""

    def __init__(self):
        super().__init__(GENERIC_MFA_ERROR)


@dataclass(frozen=True)
class EnrollmentStarted:
    user: User
    secret: MFAEnrollmentSecret


def _log_failure(request, user, event_type, severity="warning", **fields):
    emit_security_event(
        event_type=event_type,
        severity=severity,
        outcome="blocked" if event_type == "account_locked" else "failure",
        request=request,
        status_code=BAD_REQUEST,
        user=user,
        **fields,
    )


def _lock_challenge(raw_token, purpose, request=None):
    challenge = (
        MFAChallenge.objects.select_for_update()
        .select_related("user")
        .filter(
            challenge_token_hash=hash_challenge_token(raw_token),
            purpose=purpose,
        )
        .first()
    )
    if challenge is None:
        raise MFAChallengeRejected()
    if not challenge.is_active:
        if challenge.used_at is not None:
            _log_failure(
                request,
                challenge.user,
                "mfa_challenge_reused",
                reason="challenge_used",
            )
        elif challenge.is_expired:
            _log_failure(
                request,
                challenge.user,
                "mfa_challenge_expired",
                reason="challenge_expired",
            )
        raise MFAChallengeRejected()
    return challenge


def _lock_settings(user):
    mfa_settings, _ = UserMFASettings.objects.select_for_update().get_or_create(
        user=user
    )
    return mfa_settings


def begin_enrollment(*, raw_challenge, request=None):
    """Generate the pending TOTP secret for the account that owns the challenge."""
    with transaction.atomic():
        challenge = _lock_challenge(
            raw_challenge, MFAChallenge.Purpose.ENROLLMENT, request=request
        )
        if _lock_settings(challenge.user).mfa_enabled:
            raise MFAChallengeRejected()
        return EnrollmentStarted(
            user=challenge.user,
            secret=create_pending_enrollment_secret(challenge.user),
        )


def _check_code(*, raw_challenge, code, purpose, secret_for, on_valid, request):
    failed = False
    with transaction.atomic():
        challenge = _lock_challenge(raw_challenge, purpose, request=request)
        mfa_settings = _lock_settings(challenge.user)

        try:
            validation = validate_totp_code(
                mfa_settings=mfa_settings,
                code=code,
                secret=secret_for(mfa_settings),
                prevent_reuse=True,
            )
        except MFALockedError:
            _log_failure(request, challenge.user, "account_locked", reason="mfa_locked")
            raise MFAChallengeRejected() from None
        except MFAServiceError:
            _log_failure(
                request, challenge.user, "mfa_failed", reason="mfa_secret_error"
            )
            raise MFAChallengeRejected() from None

        if validation.valid:
            on_valid(mfa_settings, validation.timestep)
            mark_challenge_used(challenge)
            return challenge.user

        failure = record_mfa_failure(mfa_settings=mfa_settings, challenge=challenge)
        _log_failure(
            request,
            challenge.user,
            "mfa_failed",
            reason="invalid_totp",
            failed_attempts=failure.failed_attempts,
            challenge_failed_attempts=failure.challenge_failed_attempts,
        )
        if failure.locked_until is not None:
            _log_failure(
                request,
                challenge.user,
                "account_locked",
                reason="mfa_lockout_threshold",
            )
        failed = True

    # Raised outside the transaction so the recorded failure is committed.
    if failed:
        raise MFAChallengeRejected()


def confirm_enrollment(*, raw_challenge, code, request=None):
    """Activate MFA with the first valid code; returns the account."""
    return _check_code(
        raw_challenge=raw_challenge,
        code=code,
        purpose=MFAChallenge.Purpose.ENROLLMENT,
        secret_for=get_pending_totp_secret,
        on_valid=lambda mfa_settings, timestep: activate_pending_mfa_secret(
            mfa_settings=mfa_settings, timestep=timestep
        ),
        request=request,
    )


def verify_login_code(*, raw_challenge, code, request=None):
    """Second step of a login with MFA on; returns the account."""
    return _check_code(
        raw_challenge=raw_challenge,
        code=code,
        purpose=MFAChallenge.Purpose.LOGIN,
        secret_for=get_active_totp_secret,
        on_valid=lambda mfa_settings, timestep: record_mfa_success(
            mfa_settings=mfa_settings, timestep=timestep
        ),
        request=request,
    )
