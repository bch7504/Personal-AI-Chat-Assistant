"""Profile-owned prompts and handlers for specialist agents."""

from src.agents.profiles.product_delivery import PRODUCT_DELIVERY_PROMPT_VERSION
from src.agents.profiles.product_delivery_executor import ProductDeliveryReadOnlyExecutor
from src.agents.profiles.product_delivery_runner import (
    prepare_product_delivery_invocation,
    resolve_prepared_delivery_read_scope,
)
from src.agents.profiles.quality_assurance import QUALITY_ASSURANCE_PROMPT_VERSION
from src.agents.profiles.quality_assurance_executor import QualityReadOnlyExecutor
from src.agents.profiles.quality_assurance_runner import (
    prepare_quality_invocation,
    resolve_quality_read_scope,
)

__all__ = [
    "PRODUCT_DELIVERY_PROMPT_VERSION",
    "QUALITY_ASSURANCE_PROMPT_VERSION",
    "QualityReadOnlyExecutor",
    "ProductDeliveryReadOnlyExecutor",
    "prepare_product_delivery_invocation",
    "prepare_quality_invocation",
    "resolve_prepared_delivery_read_scope",
    "resolve_quality_read_scope",
]
