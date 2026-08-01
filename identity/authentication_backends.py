from django.contrib.auth.backends import ModelBackend

from .models import User


class EmailAccountBackend(ModelBackend):
    """Authenticate the selected account type without conflating company and person accounts."""

    def authenticate(self, request, username=None, password=None, account_type=None, **kwargs):
        if username is None or password is None:
            return None
        selected_type = account_type or User.AccountType.RESEARCHER
        try:
            user = User.objects.get(
                username__iexact=User.objects.normalize_email(username),
                account_type=selected_type,
            )
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
