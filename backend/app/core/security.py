from datetime import datetime, timedelta, timezone
import re
from typing import Optional, Tuple
import bcrypt
import jwt

from app.core.config import settings

# Regex patterns for input validation
USERNAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

# Security constants
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # Bcrypt algorithm maximum password length limit


def hash_password(password: str) -> str:
    """
    Hashes a plain text password using bcrypt with a securely generated salt.
    
    Why bcrypt:
    - Actively maintained and fully compatible with Python 3.12 without deprecation warnings.
    - Uses an adaptive cost factor (key stretching) that resists brute-force and GPU attacks.
    - Standard in modern web security.
    """
    if not isinstance(password, str):
        raise ValueError("Password must be a string.")

    password_bytes = password.encode("utf-8")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(password_bytes) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must not exceed {MAX_PASSWORD_BYTES} bytes to prevent truncation."
        )

    # Generate salt and hash the password
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies that a plain text password matches a stored bcrypt hash.
    Returns True if valid, False otherwise. Never throws on invalid hashes.
    """
    if not isinstance(plain_password, str) or not isinstance(hashed_password, str):
        return False

    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        # Protect against malformed hashes or decoding issues
        return False


def validate_registration_input(username: str, email: str, password: str) -> Tuple[str, str]:
    """
    Validates and normalizes registration input:
    - Normalizes username and email to lowercase with whitespace stripped.
    - Validates username characters and length (3 to 30 characters).
    - Validates email format and length (5 to 100 characters).
    - Validates password length (8 to 72 bytes).
    
    Returns normalized (clean_username, clean_email) tuple.
    Raises ValueError with descriptive message if validation fails.
    """
    # 1. Validate and normalize username
    if not username or not isinstance(username, str):
        raise ValueError("Username is required and cannot be empty.")
    clean_username = username.strip().lower()
    if len(clean_username) < 3 or len(clean_username) > 30:
        raise ValueError("Username must be between 3 and 30 characters.")
    if not USERNAME_PATTERN.match(clean_username):
        raise ValueError(
            "Username can only contain alphanumeric characters, underscores, and hyphens."
        )

    # 2. Validate and normalize email
    if not email or not isinstance(email, str):
        raise ValueError("Email is required and cannot be empty.")
    clean_email = email.strip().lower()
    if len(clean_email) < 5 or len(clean_email) > 100:
        raise ValueError("Email must be between 5 and 100 characters.")
    if not EMAIL_PATTERN.match(clean_email):
        raise ValueError("Invalid email format.")

    # 3. Validate password
    if not password or not isinstance(password, str):
        raise ValueError("Password is required and cannot be empty.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must not exceed {MAX_PASSWORD_BYTES} bytes to prevent truncation."
        )

    return clean_username, clean_email


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a signed JWT access token containing the provided payload data.
    Automatically adds 'exp' (expiration) and 'iat' (issued at) claims.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": now
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decodes and verifies a JWT access token.
    Returns the decoded claims dictionary if valid, or None if expired or malformed.
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
    except (jwt.PyJWTError, Exception):
        return None
