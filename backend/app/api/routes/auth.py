import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.config import settings
from app.core.security import (
    hash_password,
    validate_registration_input,
    verify_password,
    create_access_token
)
from app.db.mongodb import db
from app.schemas.auth import (
    UserRegisterRequest,
    UserRegisterResponse,
    UserLoginRequest,
    UserLoginResponse,
    UserInfo
)

logger = logging.getLogger("patentfind.api.auth")
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new regular user"
)
def register(payload: UserRegisterRequest) -> UserRegisterResponse:
    """
    Registers a new regular user:
    - Normalizes and validates username, email, and password.
    - Hashes the password using bcrypt.
    - Persists the record permanently in MongoDB users collection.
    - Always assigns role="user" on the server.
    - Returns a safe response excluding the password hash.
    """
    # 1. Normalize and validate input values
    try:
        clean_username, clean_email = validate_registration_input(
            username=payload.username,
            email=payload.email,
            password=payload.password
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        )

    # 2. Hash the password with bcrypt
    try:
        hashed = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        )

    # 3. Construct user document (role is strictly hardcoded to "user")
    created_timestamp = datetime.now(timezone.utc).isoformat()
    user_doc = {
        "username": clean_username,
        "email": clean_email,
        "hashed_password": hashed,
        "role": "user",
        "created_at": created_timestamp
    }

    # 4. Insert into MongoDB with duplicate detection
    users_col = db[settings.USERS_COLLECTION]
    try:
        insert_result = users_col.insert_one(user_doc)
    except DuplicateKeyError as exc:
        err_str = str(exc)
        if "unique_username" in err_str or "username" in err_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{clean_username}' is already registered."
            )
        elif "unique_email" in err_str or "email" in err_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{clean_email}' is already registered."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this username or email already exists."
            )
    except PyMongoError as exc:
        logger.error("Database error during user registration: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while registering the user."
        )

    return UserRegisterResponse(
        id=str(insert_result.inserted_id),
        username=clean_username,
        email=clean_email,
        role="user",
        created_at=created_timestamp,
        message="User registered successfully."
    )


@router.post(
    "/login",
    response_model=UserLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user and obtain JWT access token"
)
def login(payload: UserLoginRequest) -> UserLoginResponse:
    """
    Authenticates a user via username (or email) and password:
    - Normalizes the identifier (username or email).
    - Verifies the password using bcrypt.
    - Emits a signed JWT access token.
    - Prevents user enumeration by returning identical 401 messages for nonexistent users and wrong passwords.
    """
    clean_identifier = payload.username.strip().lower()
    if not clean_identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email cannot be empty."
        )

    users_col = db[settings.USERS_COLLECTION]
    try:
        user = users_col.find_one({
            "$or": [
                {"username": clean_identifier},
                {"email": clean_identifier}
            ]
        })
    except PyMongoError as exc:
        logger.error("Database error during user lookup: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred during login."
        )

    # Identical 401 detail prevents username harvesting
    invalid_credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password.",
        headers={"WWW-Authenticate": "Bearer"}
    )

    if not user:
        raise invalid_credentials_exc

    stored_hash = user.get("hashed_password", "")
    if not verify_password(payload.password, stored_hash):
        raise invalid_credentials_exc

    # Generate signed JWT token
    token_claims = {
        "sub": str(user["_id"]),
        "username": user["username"],
        "email": user["email"],
        "role": user.get("role", "user")
    }
    access_token = create_access_token(data=token_claims)
    expires_in_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    return UserLoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in_seconds,
        user=UserInfo(
            id=str(user["_id"]),
            username=user["username"],
            email=user["email"],
            role=user.get("role", "user")
        ),
        message="Login successful."
    )
