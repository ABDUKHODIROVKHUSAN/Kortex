from typing import Literal

from pydantic import BaseModel, Field


class UpgradeTierRequest(BaseModel):
    tier: Literal["free", "pro", "business"] = Field(description="Target subscription tier")


class UpgradeTierResponse(BaseModel):
    success: bool
    message: str
    userTier: str
