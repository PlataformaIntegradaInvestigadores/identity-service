from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from identity.company_profiles import CompanyProfileServiceUnavailable, fetch_legacy_company_identities
from identity.models import User


class Command(BaseCommand):
    help = "Import company credentials from the legacy social store into Identity."

    def handle(self, *args, **options):
        try:
            companies = fetch_legacy_company_identities()
        except CompanyProfileServiceUnavailable as exc:
            raise CommandError(str(exc.detail)) from exc

        created = 0
        updated = 0
        conflicts = 0
        for company in companies:
            company_id = str(company.get("id", ""))
            username = User.objects.normalize_email(company.get("username", ""))
            if not company_id or not username or not company.get("password"):
                conflicts += 1
                continue

            email_owner = User.objects.filter(
                username__iexact=username,
                account_type=User.AccountType.COMPANY,
            ).exclude(id=company_id).first()
            id_owner = User.objects.filter(id=company_id).first()
            if email_owner or (id_owner and id_owner.username.lower() != username.lower()):
                conflicts += 1
                continue

            defaults = {
                "username": username,
                "password": company["password"],
                "first_name": "",
                "last_name": "",
                "account_type": User.AccountType.COMPANY,
                "is_active": bool(company.get("is_active", True)),
                "is_staff": bool(company.get("is_staff", False)),
            }
            try:
                with transaction.atomic():
                    _, was_created = User.objects.update_or_create(id=company_id, defaults=defaults)
            except IntegrityError:
                conflicts += 1
                continue
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Company identity sync complete: created={created}, updated={updated}, conflicts={conflicts}."
            )
        )
        if conflicts:
            raise CommandError("Company identity sync finished with conflicts; review duplicate IDs or emails.")
