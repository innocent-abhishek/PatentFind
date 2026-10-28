from pydantic import BaseModel, ConfigDict, Field


class UserRegisterRequest(BaseModel):
    """
    Public registration request schema.
    Strictly forbids extra fields (e.g. role) so callers cannot attempt privilege escalation.
    """
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        ...,
        min_length=3,
        max_length=30,
        description="Desired unique username (alphanumeric, underscore, hyphen)"
    )
    email: str = Field(
        ...,
        min_length=5,
        max_length=100,
        description="Valid email address"
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=72,
        description="Password (min 8 characters, max 72 bytes)"
    )


class UserRegisterResponse(BaseModel):
    """
    Safe public response schema for registration.
    Excludes hashed_password to prevent any credential leakage.
    """
    id: str = Field(..., description="Unique user ObjectId string")
    username: str = Field(..., description="Normalized username")
    email: str = Field(..., description="Normalized email address")
    role: str = Field(..., description="Assigned user role (always 'user' for public registration)")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    message: str = Field(..., description="Informational success message")


class UserLoginRequest(BaseModel):
    """
    User login request schema.
    Accepts either username or email as the identifier.
    Strictly forbids extra fields to avoid unexpected inputs.
    """
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="Username or email address"
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=72,
        description="User password"
    )


class UserInfo(BaseModel):
    """
    Public representation of authenticated user details.
    """
    id: str = Field(..., description="Unique user ObjectId string")
    username: str = Field(..., description="Normalized username")
    email: str = Field(..., description="Normalized email address")
    role: str = Field(..., description="User role ('user' or 'admin')")


class UserLoginResponse(BaseModel):
    """
    Successful login response schema containing the signed JWT access token.
    """
    access_token: str = Field(..., description="Signed JWT access token")
    token_type: str = Field(default="bearer", description="Token type, always 'bearer'")
    expires_in: int = Field(..., description="Token lifespan in seconds")
    user: UserInfo = Field(..., description="Authenticated user summary")
    message: str = Field(default="Login successful.", description="Status message")
