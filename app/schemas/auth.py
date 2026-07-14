import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


_PASSWORD_RULE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


def validate_password_strength(password: str) -> str:
    if not _PASSWORD_RULE.match(password):
        raise ValueError(
            "Your password is weak. Use at least 8 characters with both letters and numbers."
        )
    return password


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def password_must_be_strong(cls, value: str) -> str:
        return validate_password_strength(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    phone: str | None = None
    avatar_url: str | None = None
    subscription_tier: str = "free"
    is_admin: bool = False


class UpdateProfileRequest(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1)
    phone: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
