import logging

from rest_framework.exceptions import PermissionDenied, ValidationError

from ..domain.exceptions import (
    DomainPermissionDenied,
    DomainValidationError,
)

logger = logging.getLogger(__name__)


def raise_drf_domain_exception(exc):
    if isinstance(exc, DomainPermissionDenied):
        raise PermissionDenied(str(exc)) from exc
    if isinstance(exc, DomainValidationError):
        raise ValidationError({"detail": str(exc)}) from exc
    raise exc
