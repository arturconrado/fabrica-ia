from unittest.mock import patch

from app.auth import dependencies


def setup_function() -> None:
    dependencies.invalidate_authorization_cache()


def teardown_function() -> None:
    dependencies.invalidate_authorization_cache()


def test_authorization_cache_is_scoped_by_tenant_and_subject() -> None:
    with patch.object(dependencies, "monotonic", return_value=10.0):
        dependencies._remember_authorization("tenant-a", "subject-a", "user-a", "owner")

    with patch.object(dependencies, "monotonic", return_value=10.5):
        cached = dependencies._cached_authorization("tenant-a", "subject-a")
        assert cached is not None
        assert (cached.user_id, cached.role) == ("user-a", "owner")
        assert dependencies._cached_authorization("tenant-b", "subject-a") is None
        assert dependencies._cached_authorization("tenant-a", "subject-b") is None


def test_authorization_cache_expires_and_can_be_invalidated_immediately() -> None:
    with patch.object(dependencies, "monotonic", return_value=20.0):
        dependencies._remember_authorization(
            "tenant-a", "subject-a", "user-a", "engagement_manager"
        )
        dependencies._remember_authorization(
            "tenant-a", "subject-b", "user-b", "owner"
        )

    dependencies.invalidate_authorization_cache(tenant_id="tenant-a", subject="subject-a")
    with patch.object(dependencies, "monotonic", return_value=20.5):
        assert dependencies._cached_authorization("tenant-a", "subject-a") is None
        assert dependencies._cached_authorization("tenant-a", "subject-b") is not None

    with patch.object(
        dependencies,
        "monotonic",
        return_value=20.0 + dependencies._AUTHORIZATION_TTL_SECONDS + 0.1,
    ):
        assert dependencies._cached_authorization("tenant-a", "subject-b") is None
