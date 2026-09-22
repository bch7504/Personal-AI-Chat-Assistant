from pydantic import BaseModel


class UsageStatusOut(BaseModel):
    tokens_used_today: int
    daily_token_budget: int
    used_pct: float
