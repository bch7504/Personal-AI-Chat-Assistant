from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    display_name: str = Field(..., min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class DemoLoginRequest(BaseModel):
    account_key: Literal["delivery_lead", "apollo_member", "release_member", "portal_member"]


class DemoAccountPublic(BaseModel):
    account_key: str
    display_name: str
    email: EmailStr
    business_role: Literal["lead", "member"]
    channel_name: str | None = None
    job_title: str = ""


class GoogleAuthRequest(BaseModel):
    id_token: str


class UserPublic(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    platform_role: Literal["user", "platform_admin"]
    job_title: str = ""
    timezone: str = "Asia/Ho_Chi_Minh"
    preferences: dict = Field(default_factory=dict)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    job_title: str | None = Field(default=None, max_length=80)
    timezone: str | None = None
    preferences: dict | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserPublic
