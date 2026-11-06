"""Token claims and the session every successful login ends in."""

from dataclasses import dataclass

from rest_framework_simplejwt.tokens import RefreshToken

from identity.auth_sessions import create_auth_session
from identity.models import AuthSession, User
from identity.security_events import emit_security_event


def principal_response_data(user):
    """The id the clients read, keyed by account type."""
    if user.account_type == User.AccountType.COMPANY:
        return {"company_id": user.id, "user_type": "company"}
    return {"user_id": user.id, "user_type": "user"}


def build_refresh_token(user):
    token = RefreshToken.for_user(user)
    token["user_type"] = (
        "company" if user.account_type == User.AccountType.COMPANY else "user"
    )
    if user.account_type == User.AccountType.COMPANY:
        token["company_id"] = user.id
    else:
        token["user_id"] = user.id
    # Other services (e.g. social-service's consensus snapshots) only see
    # the user through this token's claims -- without these, every
    # downstream display name fell back to the raw email.
    token["first_name"] = user.first_name
    token["last_name"] = user.last_name
    return token


@dataclass(frozen=True)
class IssuedSession:
    refresh: str
    access: str
    principal: dict
    auth_session: AuthSession


def issue_session(*, user, request, mfa_verified):
    """Create the refresh/access pair and the server-side session, and log it.

    `mfa_verified` marks tokens issued right after a TOTP check; they also carry
    the account email and an `mfa` claim.
    """
    refresh = build_refresh_token(user)
    if mfa_verified:
        refresh["email"] = user.username
        refresh["mfa"] = True
    raw_refresh = str(refresh)

    auth_session = create_auth_session(
        user=user, raw_refresh_token=raw_refresh, request=request
    )
    emit_security_event(
        event_type="login_success",
        severity="info",
        outcome="success",
        request=request,
        status_code=200,
        user=user,
        auth_session_id=str(auth_session.id),
    )
    return IssuedSession(
        refresh=raw_refresh,
        access=str(refresh.access_token),
        principal=principal_response_data(user),
        auth_session=auth_session,
    )
