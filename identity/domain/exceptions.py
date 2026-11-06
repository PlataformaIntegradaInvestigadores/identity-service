class DomainRuleViolation(Exception):
    """Raised when a domain invariant or permission rule is violated."""


class DomainPermissionDenied(DomainRuleViolation):
    pass


class DomainValidationError(DomainRuleViolation):
    pass


class AuthenticationRejected(DomainRuleViolation):
    """Credentials, lockout or MFA state do not allow the login to continue."""
