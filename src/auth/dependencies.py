import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.security import decode_access_token
from src.db.models import User
from src.db.session import get_db
from src.services.authorization_service import require_platform_admin as authorize_platform_admin

security = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise credentials_error
    try:
        user_id = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise credentials_error

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise credentials_error
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account has been disabled")
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    return authorize_platform_admin(current_user)


async def require_platform_admin(current_user: User = Depends(get_current_user)) -> User:
    return authorize_platform_admin(current_user)
