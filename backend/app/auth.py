from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

ph = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def password_hash(settings: Settings) -> str:
    if settings.admin_password_hash:
        return settings.admin_password_hash
    return ph.hash(settings.admin_password)


def verify_login(username: str, password: str, settings: Settings) -> bool:
    if username != settings.admin_username:
        return False
    try:
        return ph.verify(password_hash(settings), password)
    except VerifyMismatchError:
        return False


def create_token(username: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "iat": now, "exp": now + timedelta(hours=24)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    token = request.cookies.get("session")
    if not token and credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期") from exc
    if payload.get("sub") != settings.admin_username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效账号")
    return str(payload["sub"])

