"""Password step of the login: lockout, credentials and which MFA step comes next."""

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import authenticate

from identity.domain.exceptions import AuthenticationRejected
from identity.login_lockout import (
    get_user_for_password_lockout,
    is_password_locked,
    record_password_failure,
    reset_password_failures,
)
from identity.mfa_services import GENERIC_MFA_ERROR, create_mfa_challenge
from identity.models import MFAChallenge, User, UserMFASettings
from identity.security_events import emit_security_event

UNAUTHORIZED = 401
OK = 200


@dataclass(frozen=True)
class MFAStep:
    """The password was right but a TOTP step still has to happen."""

    status: str  # "mfa_required" or "mfa_enrollment_required"
    challenge_token: str
    expires_in: int


@dataclass(frozen=True)
class PasswordAccepted:
    """No MFA is needed: the caller can issue the session."""

    user: User


def _log_blocked(request, user, reason):
    emit_security_event(
        event_type="account_locked",
        severity="warning",
        outcome="blocked",
        request=request,
        status_code=UNAUTHORIZED,
        user=user,
        reason=reason,
    )


def _mfa_step(user, request, *, purpose, status, event_type):
    challenge = create_mfa_challenge(user=user, purpose=purpose, request=request)
    emit_security_event(
        event_type=event_type,
        severity="info",
        outcome="pending",
        request=request,
        status_code=OK,
        user=user,
    )
    return MFAStep(
        status=status,
        challenge_token=challenge.token,
        expires_in=challenge.expires_in,
    )


def authenticate_credentials(*, username, password, account_type, request):
    """Check the password of an `account_type` account.

    Returns `MFAStep` or `PasswordAccepted`; raises `AuthenticationRejected` (one
    generic message for every cause) when the login must fail.
    """
    candidate = get_user_for_password_lockout(username, account_type)
    if candidate is not None and is_password_locked(candidate):
        _log_blocked(request, candidate, "password_lockout")
        raise AuthenticationRejected(GENERIC_MFA_ERROR)

    user = authenticate(
        request=request,
        **{
            User.USERNAME_FIELD: username,
            "password": password,
            "account_type": account_type,
        },
    )
    if user is None or not user.is_active or user.account_type != account_type:
        failure = None
        if user is None and candidate is not None and candidate.is_active:
            failure = record_password_failure(candidate)
        emit_security_event(
            event_type="login_failed",
            severity="warning",
            outcome="failure",
            request=request,
            status_code=UNAUTHORIZED,
            reason="invalid_credentials",
            username=username,
            failed_attempts=failure.failed_attempts if failure else None,
        )
        if failure and failure.locked_until is not None:
            _log_blocked(request, candidate, "password_lockout_threshold")
        raise AuthenticationRejected(GENERIC_MFA_ERROR)

    reset_password_failures(user)
    mfa_settings, _ = UserMFASettings.objects.get_or_create(user=user)
    if mfa_settings.is_locked:
        _log_blocked(request, user, "mfa_locked")
        raise AuthenticationRejected(GENERIC_MFA_ERROR)

    if mfa_settings.mfa_enabled:
        return _mfa_step(
            user,
            request,
            purpose=MFAChallenge.Purpose.LOGIN,
            status="mfa_required",
            event_type="mfa_required",
        )

    if settings.MFA_ENFORCEMENT_MODE in {"enrollment_required", "required"}:
        return _mfa_step(
            user,
            request,
            purpose=MFAChallenge.Purpose.ENROLLMENT,
            status="mfa_enrollment_required",
            event_type="mfa_enrollment_required",
        )

    return PasswordAccepted(user=user)
