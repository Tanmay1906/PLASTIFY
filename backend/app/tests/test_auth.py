"""Tests for Authentication, JWT Lifecycle, and User Management."""

import pytest
from httpx import AsyncClient

from app.models.user import UserRole


@pytest.mark.asyncio
async def test_user_registration_success(client: AsyncClient):
    """Test successful user registration."""
    payload = {
        "email": "collector1@plastify.io",
        "password": "StrongPassword123!",
        "first_name": "Carlos",
        "last_name": "Collector",
        "role": UserRole.COLLECTOR.value,
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "collector1@plastify.io"
    assert data["role"] == "COLLECTOR"
    assert "id" in data
    assert "hashed_password" not in data  # Never expose password hash!
    assert "password" not in data


@pytest.mark.asyncio
async def test_user_registration_duplicate_email(client: AsyncClient, create_user):
    """Test registration with an already registered email returns 409 Conflict."""
    await create_user(email="duplicate@plastify.io")

    payload = {
        "email": "duplicate@plastify.io",
        "password": "AnotherPassword123!",
        "first_name": "Jane",
        "last_name": "Doe",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "RESOURCE_CONFLICT"


@pytest.mark.asyncio
async def test_user_registration_short_password(client: AsyncClient):
    """Test registration with password under 8 characters fails validation."""
    payload = {
        "email": "shortpass@plastify.io",
        "password": "short",
        "first_name": "Test",
        "last_name": "User",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_user_login_success(client: AsyncClient, create_user):
    """Test successful login returns access and refresh token pair."""
    await create_user(email="login@plastify.io", password="CorrectPassword123!")

    payload = {
        "email": "login@plastify.io",
        "password": "CorrectPassword123!",
    }
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_user_login_invalid_credentials(client: AsyncClient, create_user):
    """Test login with incorrect password returns 401 Unauthorized."""
    await create_user(email="valid@plastify.io", password="CorrectPassword123!")

    # Bad password
    res1 = await client.post(
        "/api/v1/auth/login",
        json={"email": "valid@plastify.io", "password": "WrongPassword!"},
    )
    assert res1.status_code == 401
    assert res1.json()["error"]["code"] == "UNAUTHORIZED"

    # Non-existent email
    res2 = await client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@plastify.io", "password": "AnyPassword!"},
    )
    assert res2.status_code == 401


@pytest.mark.asyncio
async def test_user_login_inactive_account(client: AsyncClient, create_user):
    """Test login with deactivated account returns 403 Forbidden."""
    await create_user(
        email="inactive@plastify.io",
        password="ValidPassword123!",
        is_active=False,
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@plastify.io", "password": "ValidPassword123!"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_get_current_user_profile(client: AsyncClient, create_user, auth_headers):
    """Test GET /api/v1/auth/me returns current authenticated user profile."""
    user = await create_user(
        email="profile@plastify.io",
        first_name="Alice",
        last_name="Green",
        role=UserRole.VERIFIER,
    )
    headers = auth_headers(user)

    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "profile@plastify.io"
    assert data["user"]["role"] == "VERIFIER"
    assert data["user"]["first_name"] == "Alice"


@pytest.mark.asyncio
async def test_token_validation_failure(client: AsyncClient):
    """Test accessing protected endpoint without token or with invalid token returns 401."""
    # 1. No token
    res1 = await client.get("/api/v1/auth/me")
    assert res1.status_code == 401

    # 2. Malformed token
    res2 = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.garbage"}
    )
    assert res2.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation(client: AsyncClient, create_user):
    """Test refresh token rotation issues new access and refresh tokens."""
    await create_user(email="rotate@plastify.io", password="Password123!")

    # 1. Login to get initial tokens
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "rotate@plastify.io", "password": "Password123!"},
    )
    orig_refresh = login_res.json()["refresh_token"]

    # 2. Refresh tokens
    refresh_res = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": orig_refresh}
    )
    assert refresh_res.status_code == 200
    new_data = refresh_res.json()
    assert "access_token" in new_data
    assert "refresh_token" in new_data
    assert new_data["refresh_token"] != orig_refresh  # Token rotated!

    # 3. Old refresh token cannot be reused (rotation security)
    replay_res = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": orig_refresh}
    )
    assert replay_res.status_code == 401


@pytest.mark.asyncio
async def test_user_logout(client: AsyncClient, create_user):
    """Test logout revokes the refresh token."""
    await create_user(email="logout@plastify.io", password="Password123!")

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "logout@plastify.io", "password": "Password123!"},
    )
    refresh_token = login_res.json()["refresh_token"]

    # Logout
    logout_res = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh_token}
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True

    # Attempting to refresh after logout must fail
    try_refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert try_refresh.status_code == 401


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient, create_user, auth_headers):
    """Test changing password and logging in with the new password."""
    user = await create_user(email="changepwd@plastify.io", password="OldPassword123!")
    headers = auth_headers(user)

    # Change password
    change_res = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={
            "current_password": "OldPassword123!",
            "new_password": "BrandNewPassword123!",
        },
    )
    assert change_res.status_code == 200
    assert change_res.json()["success"] is True

    # Login with new password
    new_login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "changepwd@plastify.io",
            "password": "BrandNewPassword123!",
        },
    )
    assert new_login.status_code == 200

    # Old password no longer works
    old_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "changepwd@plastify.io", "password": "OldPassword123!"},
    )
    assert old_login.status_code == 401


@pytest.mark.asyncio
async def test_user_deactivation_and_activation(client: AsyncClient, create_user, auth_headers):
    """Test Super Admin activating and deactivating a user account."""
    admin = await create_user(email="superadmin@plastify.io", role=UserRole.SUPER_ADMIN)
    target = await create_user(email="target@plastify.io", is_active=True)

    admin_headers = auth_headers(admin)

    # 1. Deactivate target user
    deact_res = await client.patch(
        f"/api/v1/auth/users/{target.id}/status",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deact_res.status_code == 200
    assert deact_res.json()["is_active"] is False

    # 2. Deactivated user cannot access protected endpoints
    target_headers = auth_headers(target)
    blocked_res = await client.get("/api/v1/auth/me", headers=target_headers)
    assert blocked_res.status_code == 403

    # 3. Reactivate target user
    act_res = await client.patch(
        f"/api/v1/auth/users/{target.id}/status",
        headers=admin_headers,
        json={"is_active": True},
    )
    assert act_res.status_code == 200
    assert act_res.json()["is_active"] is True
