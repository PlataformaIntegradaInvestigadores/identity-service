"""The login and MFA use cases, exercised without HTTP or serializers."""

from datetime import timedelta
from unittest.mock import patch

import pyotp
import pytest
from django.test import TestCase, override_settings
from django.utils import timezone

from identity.application.authentication import (
    MFAStep,
    PasswordAccepted,
    authenticate_credentials,
)
from identity.application.mfa import (
    MFAChallengeRejected,
    begin_enrollment,
    confirm_enrollment,
    verify_login_code,
)
from identity.application.tokens import build_refresh_token, issue_session
from identity.application.use_cases import register_company
from identity.company_profiles import CompanyProfileServiceUnavailable
from identity.domain.exceptions import AuthenticationRejected
from identity.mfa_services import create_mfa_challenge
from identity.models import AuthSession, MFAChallenge, User, UserMFASettings

PASSWORD = "StrongPass123"
RESEARCHER = User.AccountType.RESEARCHER
COMPANY = User.AccountType.COMPANY


def totp(secret, steps=0):
    moment = timezone.now() + timedelta(seconds=30 * steps)
    return pyotp.TOTP(secret, interval=30).at(moment)


def make_user(username="ana@example.com", **extra):
    return User.objects.create_user(
        username=username,
        password=PASSWORD,
        first_name="Ana",
        last_name="Perez",
        **extra,
    )


@override_settings(
    MFA_ENFORCEMENT_MODE="optional",
    AUTH_PASSWORD_LOCKOUT_FAILURE_THRESHOLD=2,
    AUTH_PASSWORD_LOCKOUT_MINUTES=[5],
)
class TestAuthenticateCredentials(TestCase):
    def login(self, username="ana@example.com", password=PASSWORD, kind=RESEARCHER):
        return authenticate_credentials(
            username=username, password=password, account_type=kind, request=None
        )

    def test_without_mfa_the_password_is_enough(self):
        user = make_user()

        outcome = self.login()

        self.assertEqual(outcome, PasswordAccepted(user=user))

    def test_wrong_password_is_rejected(self):
        make_user()

        with self.assertRaises(AuthenticationRejected):
            self.login(password="nope")

    def test_unknown_user_is_rejected_with_the_same_error(self):
        with self.assertRaises(AuthenticationRejected) as caught:
            self.login(username="ghost@example.com")

        make_user()
        with self.assertRaises(AuthenticationRejected) as wrong_password:
            self.login(password="nope")
        self.assertEqual(str(caught.exception), str(wrong_password.exception))

    def test_an_account_of_the_other_type_cannot_log_in(self):
        make_user("co@example.com", account_type=COMPANY)

        with self.assertRaises(AuthenticationRejected):
            self.login("co@example.com", kind=RESEARCHER)

    def test_repeated_failures_lock_the_account_even_for_the_right_password(self):
        make_user()
        for _ in range(2):
            with self.assertRaises(AuthenticationRejected):
                self.login(password="nope")

        with self.assertRaises(AuthenticationRejected):
            self.login()

    def test_a_correct_password_clears_the_failure_count(self):
        user = make_user()
        with self.assertRaises(AuthenticationRejected):
            self.login(password="nope")

        self.login()

        user.refresh_from_db()
        self.assertEqual(user.failed_login_attempts, 0)

    def test_with_mfa_enabled_the_next_step_is_a_login_challenge(self):
        user = make_user()
        UserMFASettings.objects.create(user=user, mfa_enabled=True)

        outcome = self.login()

        self.assertIsInstance(outcome, MFAStep)
        self.assertEqual(outcome.status, "mfa_required")
        self.assertTrue(
            MFAChallenge.objects.filter(
                user=user, purpose=MFAChallenge.Purpose.LOGIN
            ).exists()
        )

    @override_settings(MFA_ENFORCEMENT_MODE="enrollment_required")
    def test_enforced_mfa_without_enrollment_asks_to_enroll(self):
        user = make_user()

        outcome = self.login()

        self.assertEqual(outcome.status, "mfa_enrollment_required")
        self.assertTrue(
            MFAChallenge.objects.filter(
                user=user, purpose=MFAChallenge.Purpose.ENROLLMENT
            ).exists()
        )

    def test_an_mfa_locked_account_is_rejected(self):
        user = make_user()
        UserMFASettings.objects.create(
            user=user, locked_until=timezone.now() + timedelta(minutes=5)
        )

        with self.assertRaises(AuthenticationRejected):
            self.login()


@override_settings(MFA_LOCKOUT_FAILURE_THRESHOLD=2, MFA_LOCKOUT_MINUTES=[5])
class TestMFAUseCases(TestCase):
    def setUp(self):
        self.user = make_user()

    def enrollment(self):
        issue = create_mfa_challenge(
            user=self.user, purpose=MFAChallenge.Purpose.ENROLLMENT
        )
        started = begin_enrollment(raw_challenge=issue.token)
        return issue.token, started.secret.secret

    def enrolled_secret(self):
        token, secret = self.enrollment()
        confirm_enrollment(raw_challenge=token, code=totp(secret))
        return secret

    def test_begin_enrollment_keeps_the_secret_pending(self):
        _, secret = self.enrollment()

        settings_row = UserMFASettings.objects.get(user=self.user)
        self.assertFalse(settings_row.mfa_enabled)
        self.assertTrue(settings_row.pending_mfa_secret_encrypted)
        self.assertTrue(secret)

    def test_begin_enrollment_with_an_unknown_challenge_is_rejected(self):
        with self.assertRaises(MFAChallengeRejected):
            begin_enrollment(raw_challenge="unknown")

    def test_a_login_challenge_cannot_start_an_enrollment(self):
        issue = create_mfa_challenge(user=self.user, purpose=MFAChallenge.Purpose.LOGIN)

        with self.assertRaises(MFAChallengeRejected):
            begin_enrollment(raw_challenge=issue.token)

    def test_confirming_with_a_valid_code_enables_mfa_and_burns_the_challenge(self):
        token, secret = self.enrollment()

        user = confirm_enrollment(raw_challenge=token, code=totp(secret))

        self.assertEqual(user, self.user)
        row = UserMFASettings.objects.get(user=self.user)
        self.assertTrue(row.mfa_enabled)
        self.assertIsNotNone(row.mfa_confirmed_at)
        with self.assertRaises(MFAChallengeRejected):
            confirm_enrollment(raw_challenge=token, code=totp(secret))

    def test_a_wrong_code_is_rejected_but_the_failure_is_persisted(self):
        token, _ = self.enrollment()

        with self.assertRaises(MFAChallengeRejected):
            confirm_enrollment(raw_challenge=token, code="000000")

        self.assertEqual(UserMFASettings.objects.get(user=self.user).failed_attempts, 1)
        self.assertEqual(MFAChallenge.objects.get(user=self.user).failed_attempts, 1)

    def test_enough_wrong_codes_lock_the_account(self):
        secret = self.enrolled_secret()
        for _ in range(2):
            issue = create_mfa_challenge(
                user=self.user, purpose=MFAChallenge.Purpose.LOGIN
            )
            with self.assertRaises(MFAChallengeRejected):
                verify_login_code(raw_challenge=issue.token, code="000000")

        self.assertTrue(UserMFASettings.objects.get(user=self.user).is_locked)
        issue = create_mfa_challenge(user=self.user, purpose=MFAChallenge.Purpose.LOGIN)
        with self.assertRaises(MFAChallengeRejected):
            verify_login_code(raw_challenge=issue.token, code=totp(secret, 1))

    def test_verify_login_accepts_a_fresh_code_and_refuses_its_replay(self):
        secret = self.enrolled_secret()
        code = totp(secret, 1)
        first = create_mfa_challenge(user=self.user, purpose=MFAChallenge.Purpose.LOGIN)
        second = create_mfa_challenge(
            user=self.user, purpose=MFAChallenge.Purpose.LOGIN
        )

        self.assertEqual(
            verify_login_code(raw_challenge=first.token, code=code), self.user
        )
        with self.assertRaises(MFAChallengeRejected):
            verify_login_code(raw_challenge=second.token, code=code)

    def test_an_enrollment_challenge_cannot_complete_a_login(self):
        token, secret = self.enrollment()

        with self.assertRaises(MFAChallengeRejected):
            verify_login_code(raw_challenge=token, code=totp(secret))


class TestIssueSession(TestCase):
    def test_researcher_tokens_carry_the_user_claims(self):
        user = make_user()

        token = build_refresh_token(user)

        self.assertEqual(token["user_type"], "user")
        self.assertEqual(token["user_id"], user.id)
        self.assertNotIn("company_id", token)
        self.assertEqual(token["first_name"], "Ana")

    def test_company_tokens_carry_the_company_claims(self):
        company = make_user("co@example.com", account_type=COMPANY)

        token = build_refresh_token(company)

        self.assertEqual(token["user_type"], "company")
        self.assertEqual(token["company_id"], company.id)
        self.assertNotIn("user_id", token)

    def test_issue_session_stores_the_session_and_describes_the_principal(self):
        user = make_user()

        issued = issue_session(user=user, request=None, mfa_verified=False)

        self.assertEqual(issued.principal, {"user_id": user.id, "user_type": "user"})
        self.assertTrue(AuthSession.objects.filter(pk=issued.auth_session.pk).exists())
        self.assertNotEqual(issued.refresh, issued.access)

    def test_mfa_verified_sessions_mark_the_refresh_token(self):
        user = make_user()

        plain = issue_session(user=user, request=None, mfa_verified=False)
        verified = issue_session(user=user, request=None, mfa_verified=True)

        from rest_framework_simplejwt.tokens import RefreshToken

        self.assertNotIn("mfa", RefreshToken(plain.refresh))
        self.assertIs(RefreshToken(verified.refresh)["mfa"], True)
        self.assertEqual(RefreshToken(verified.refresh)["email"], user.username)


class TestRegisterCompany(TestCase):
    DATA = {"username": "co@example.com", "password": PASSWORD, "company_name": "Acme"}

    def test_creates_the_account_and_asks_social_for_the_profile(self):
        with patch("identity.application.use_cases.provision_company_profile") as sync:
            company = register_company(dict(self.DATA))

        self.assertEqual(company.account_type, COMPANY)
        sync.assert_called_once()
        self.assertEqual(sync.call_args.args[0], company.id)

    def test_no_account_is_left_behind_when_the_profile_cannot_be_created(self):
        with patch(
            "identity.application.use_cases.provision_company_profile",
            side_effect=CompanyProfileServiceUnavailable(),
        ):
            with pytest.raises(CompanyProfileServiceUnavailable):
                register_company(dict(self.DATA))

        self.assertFalse(User.objects.filter(username="co@example.com").exists())
