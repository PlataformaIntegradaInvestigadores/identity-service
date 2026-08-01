import requests
from django.conf import settings
from rest_framework.exceptions import APIException


class CompanyProfileServiceUnavailable(APIException):
    status_code = 503
    default_detail = "Company profile service is temporarily unavailable."
    default_code = "company_profile_unavailable"


class CompanyProfileConflict(APIException):
    status_code = 409
    default_detail = "A company profile with this email already exists."
    default_code = "company_profile_conflict"


def _service_configuration():
    base_url = settings.COMPANY_PROFILE_SERVICE_URL.rstrip("/")
    token = settings.COMPANY_PROFILE_SYNC_TOKEN
    if not base_url or not token:
        raise CompanyProfileServiceUnavailable()
    return base_url, token


def provision_company_profile(company_id, profile_data):
    base_url, token = _service_configuration()
    payload = {**profile_data, "id": str(company_id)}
    payload.pop("password", None)
    payload.pop("confirm_password", None)
    try:
        response = requests.post(
            f"{base_url}/internal/profile-sync/company-identities/",
            json=payload,
            headers={"X-Profile-Sync-Token": token},
            timeout=5,
        )
    except requests.RequestException as exc:
        raise CompanyProfileServiceUnavailable() from exc
    if response.status_code == 409:
        raise CompanyProfileConflict()
    if response.status_code not in {200, 201}:
        raise CompanyProfileServiceUnavailable()


def fetch_legacy_company_identities():
    base_url, token = _service_configuration()
    try:
        response = requests.get(
            f"{base_url}/internal/profile-sync/company-identities/",
            headers={"X-Profile-Sync-Token": token},
            timeout=10,
        )
        response.raise_for_status()
    except (requests.RequestException, ValueError) as exc:
        raise CompanyProfileServiceUnavailable() from exc
    return response.json().get("companies", [])
