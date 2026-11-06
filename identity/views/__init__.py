"""HTTP views, one module per responsibility."""

from .auth import (
    CompanyRegisterView,
    CompanyTokenObtainPairView,
    CustomTokenRefreshView,
    LogoutView,
    RegisterView,
    UserTokenObtainPairView,
    ValidateTokenView,
    clear_refresh_cookie,
    issue_final_auth_response,
    set_refresh_cookie,
)
from .groups import (
    GroupDeleteView,
    GroupDetailView,
    GroupLeaveView,
    GroupListCreateView,
    GroupMemberDetailView,
    RemoveMemberView,
    UserGroupsListView,
)
from .mfa import (
    MFAConfirmView,
    MFASetupView,
    MFAStatusView,
    MFAVerifyView,
)
from .profile import (
    ProfileInformationDetailView,
    PublicProfileInformationDetailView,
)
from .system import (
    HealthLiveView,
    MetricsView,
)
from .users import (
    UserDetailView,
    UserListView,
    UserUpdateView,
)

__all__ = [
    "HealthLiveView",
    "MetricsView",
    "UserListView",
    "UserUpdateView",
    "UserDetailView",
    "UserTokenObtainPairView",
    "CompanyTokenObtainPairView",
    "CustomTokenRefreshView",
    "LogoutView",
    "ValidateTokenView",
    "issue_final_auth_response",
    "set_refresh_cookie",
    "clear_refresh_cookie",
    "RegisterView",
    "CompanyRegisterView",
    "MFASetupView",
    "MFAConfirmView",
    "MFAVerifyView",
    "MFAStatusView",
    "ProfileInformationDetailView",
    "PublicProfileInformationDetailView",
    "GroupListCreateView",
    "UserGroupsListView",
    "GroupDeleteView",
    "GroupLeaveView",
    "GroupMemberDetailView",
    "GroupDetailView",
    "RemoveMemberView",
]
