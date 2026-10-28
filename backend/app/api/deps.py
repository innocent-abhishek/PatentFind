import logging
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from app.core.config import settings

logger = logging.getLogger("patentfind.api.deps")

# HTTPBearer scheme adds the 'Authorize' button in Swagger UI (/docs)
http_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user_claims(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer_scheme)
) -> dict:
    """
    Extracts and validates the JWT Bearer token from the Authorization header.
    Returns the decoded token claims dictionary.
    Raises HTTP 401 if the token is missing, invalid, or expired.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: Missing Bearer token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except jwt.PyJWTError as exc:
        logger.warning("Invalid JWT token received: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"}
        )


def require_admin(claims: dict = Depends(get_current_user_claims)) -> dict:
    """
    Ensures the authenticated user possesses the 'admin' role.
    Raises HTTP 403 Forbidden if the user's role is not 'admin'.
    """
    role = claims.get("role")
    if role != "admin":
        logger.warning("User '%s' with role '%s' attempted admin-restricted operation.", claims.get("username"), role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Administrator privileges required."
        )
    return claims
