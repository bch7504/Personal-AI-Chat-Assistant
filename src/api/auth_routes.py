import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from src.auth import google_oauth
from src.auth.dependencies import get_current_user
from src.auth.security import create_access_token, hash_password, verify_password
from src.config import get_settings
from src.db.models import AgentWorkspace, AgentWorkspaceMembership, GoogleIdentity, User
from src.db.session import get_db
from src.models.auth_schemas import (
    AuthResponse,
    ChangePasswordRequest,
    DemoAccountPublic,
    DemoLoginRequest,
    GoogleAuthRequest,
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserPublic,
)
from src.services import reminder_service
from src.services.company_service import ensure_open_test_chat_membership
from src.services.workspace_service import ensure_personal_workspace

router = APIRouter()


_DEMO_ACCOUNTS = {
    "delivery_lead": {
        "email": "delivery-demo-lead@example.com",
        "business_role": "lead",
        "channel_name": None,
    },
    "apollo_member": {
        "email": "delivery-demo-member@example.com",
        "business_role": "member",
        "channel_name": "Apollo Platform",
    },
    "release_member": {
        "email": "delivery-demo-mai@example.com",
        "business_role": "member",
        "channel_name": "Release 34",
    },
    "portal_member": {
        "email": "delivery-demo-an@example.com",
        "business_role": "member",
        "channel_name": "Customer Portal",
    },
}


def _require_demo_login_enabled() -> None:
    settings = get_settings()
    production_demo_allowed = (
        settings.app_env != "production" or settings.allow_demo_login_in_production
    )
    if not settings.demo_login_enabled or not production_demo_allowed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo login is unavailable")


async def _resolve_demo_user(
    db: AsyncSession,
    account_key: str,
) -> tuple[User, dict[str, str | None]] | None:
    spec = _DEMO_ACCOUNTS.get(account_key)
    if spec is None:
        return None
    user = (
        await db.execute(select(User).where(User.email == str(spec["email"])))
    ).scalar_one_or_none()
    if user is None or not user.is_active or (user.preferences or {}).get("fixture_namespace") != "delivery-demo":
        return None
    membership = (
        await db.execute(
            select(AgentWorkspaceMembership)
            .join(AgentWorkspace, AgentWorkspace.id == AgentWorkspaceMembership.agent_workspace_id)
            .where(
                AgentWorkspace.key == "delivery-demo",
                AgentWorkspace.agent_profile == "product_delivery",
                AgentWorkspace.status == "active",
                AgentWorkspaceMembership.user_id == user.id,
                AgentWorkspaceMembership.status == "active",
                AgentWorkspaceMembership.business_role == spec["business_role"],
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        return None
    return user, spec


@router.get("/demo-accounts", response_model=list[DemoAccountPublic])
async def list_demo_accounts(db: AsyncSession = Depends(get_db)) -> list[DemoAccountPublic]:
    """List deliberately public Product Delivery test identities, never their credentials."""

    _require_demo_login_enabled()
    accounts: list[DemoAccountPublic] = []
    for account_key in _DEMO_ACCOUNTS:
        resolved = await _resolve_demo_user(db, account_key)
        if resolved is None:
            continue
        user, spec = resolved
        accounts.append(
            DemoAccountPublic(
                account_key=account_key,
                display_name=user.display_name,
                email=user.email,
                business_role=str(spec["business_role"]),
                channel_name=spec["channel_name"],
                job_title=user.job_title,
            )
        )
    return accounts


@router.post("/demo-login", response_model=AuthResponse)
async def demo_login(request: DemoLoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    """Issue a normal user token for one explicitly allow-listed synthetic account."""

    _require_demo_login_enabled()
    resolved = await _resolve_demo_user(db, request.account_key)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo account is unavailable")
    user, _ = resolved
    await ensure_personal_workspace(db, user)
    await db.commit()
    return AuthResponse(access_token=create_access_token(user.id), user=_to_public(user))


def _to_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        platform_role=user.platform_role,
        job_title=user.job_title,
        timezone=user.timezone,
        preferences=user.preferences,
    )


def _initial_role_for(email: str) -> str:
    """The first account registered with INITIAL_ADMIN_EMAIL (any auth method) bootstraps as
    admin - shared by /register and /google so the rule isn't duplicated/drifting between them."""
    initial_admin_email = get_settings().initial_admin_email.strip().lower()
    return "admin" if initial_admin_email and email.lower() == initial_admin_email else "user"


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserPublic:
    normalized_email = str(request.email).lower()
    existing = (await db.execute(select(User).where(User.email == normalized_email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    role = _initial_role_for(normalized_email)
    user = User(
        email=normalized_email,
        password_hash=hash_password(request.password),
        display_name=request.display_name,
        role=role,
        platform_role="platform_admin" if role == "admin" else "user",
    )
    db.add(user)
    await db.flush()
    await ensure_personal_workspace(db, user)
    await ensure_open_test_chat_membership(db, user)
    await db.commit()
    await db.refresh(user)

    return _to_public(user)


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    user = (await db.execute(select(User).where(User.email == request.email.lower()))).scalar_one_or_none()
    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account has been disabled")

    # Repair accounts created by legacy imports or direct admin/demo provisioning.
    # Personal APIs can then resolve their private namespace from the JWT alone.
    await ensure_personal_workspace(db, user)
    await ensure_open_test_chat_membership(db, user)
    await db.commit()
    token = create_access_token(user.id)
    return AuthResponse(access_token=token, user=_to_public(user))


@router.post("/google", response_model=AuthResponse)
async def google_auth(request: GoogleAuthRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    """Sign in (or sign up on first use) with a Google ID token from the frontend's <GoogleLogin/>
    button. One endpoint handles both login and signup transparently - there's nothing to
    distinguish client-side, same as the button itself is identical on /login and /register."""
    try:
        claims = await run_in_threadpool(google_oauth.verify_google_id_token, request.id_token)
    except google_oauth.GoogleTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token") from None

    google_sub = claims["sub"]
    email = claims.get("email", "").lower()
    email_verified = claims.get("email_verified", False)
    if not email or not email_verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email is not verified")

    identity = (
        await db.execute(select(GoogleIdentity).where(GoogleIdentity.google_sub == google_sub))
    ).scalar_one_or_none()

    if identity is not None:
        user = await db.get(User, identity.user_id)
    else:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is not None and not email_verified:
            # Don't silently attach a Google identity to an existing account on the strength of an
            # email Google itself won't vouch for - that would be an account-takeover vector.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email not verified by Google; sign in with your password instead",
            )
        if user is None:
            role = _initial_role_for(email)
            user = User(
                email=email,
                # Unusable, never-shared password - password_hash stays NOT NULL without adding a
                # nullable column to `users`. Password login on this account will just always 401
                # (correct: nobody ever set a password for it) until/unless they set one later.
                password_hash=hash_password(secrets.token_urlsafe(32)),
                display_name=claims.get("name") or email.split("@")[0],
                role=role,
                platform_role="platform_admin" if role == "admin" else "user",
            )
            db.add(user)
            await db.flush()
            await ensure_personal_workspace(db, user)
        db.add(GoogleIdentity(user_id=user.id, google_sub=google_sub, email=email))

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account has been disabled")

    # Existing Google identities and email-linked accounts need the same
    # invariant repair as password logins.
    await ensure_personal_workspace(db, user)
    await ensure_open_test_chat_membership(db, user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(user.id)
    return AuthResponse(access_token=token, user=_to_public(user))


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return _to_public(current_user)


@router.patch("/me", response_model=UserPublic)
async def update_me(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPublic:
    updates = request.model_dump(exclude_unset=True)
    previous_preferences = dict(current_user.preferences or {})
    for field, value in updates.items():
        setattr(current_user, field, value)
    await db.commit()
    await db.refresh(current_user)
    current_preferences = current_user.preferences or {}
    reminder_preferences_changed = any(
        previous_preferences.get(key) != current_preferences.get(key)
        for key in (
            "auto_task_reminders",
            "default_reminder_lead_minutes",
            "default_reminder_lead",
        )
    )
    if reminder_preferences_changed:
        await reminder_service.reconcile_user_task_reminders(current_user.id)
    return _to_public(current_user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    current_user.password_hash = hash_password(request.new_password)
    await db.commit()
