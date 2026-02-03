# Dead Letter Queue Configuration Addition
# This file contains the DLQ configuration to add to MahavishnuSettings

# Add these fields to MahavishnuSettings class in mahavishnu/core/config.py
# Insert after line 406 (after subscription_auth_expire_minutes field)

DLQ_CONFIG_FIELDS = """
    # Dead Letter Queue configuration
    dlq_enabled: bool = Field(
        default=True,
        description="Enable Dead Letter Queue for failed workflow reprocessing",
    )
    dlq_max_size: int = Field(
        default=10000,
        ge=100,
        le=100000,
        description="Maximum number of tasks in DLQ (100-100000)",
    )
    dlq_default_retry_policy: str = Field(
        default="exponential",
        description="Default retry policy (never, linear, exponential, immediate)",
    )
    dlq_default_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Default maximum retry attempts (0-10)",
    )
    dlq_retry_processor_enabled: bool = Field(
        default=True,
        description="Enable automatic DLQ retry processor",
    )
    dlq_retry_interval_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="DLQ retry processor check interval in seconds (10-3600)",
    )

    @field_validator("dlq_default_retry_policy")
    @classmethod
    def validate_dlq_retry_policy(cls, v: str) -> str:
        '''Validate DLQ retry policy value.'''
        valid_policies = ["never", "linear", "exponential", "immediate"]
        if v not in valid_policies:
            raise ValueError(
                f"dlq_default_retry_policy must be one of {valid_policies}, got '{v}'"
            )
        return v
"""

# Example YAML configuration for settings/mahavishnu.yaml
DLQ_YAML_CONFIG = """
# Dead Letter Queue configuration
dlq_enabled: true
dlq_max_size: 10000
dlq_default_retry_policy: exponential  # Options: never, linear, exponential, immediate
dlq_default_max_retries: 3
dlq_retry_processor_enabled: true
dlq_retry_interval_seconds: 60  # Check for retries every minute
"""

# Example environment variables
DLQ_ENV_VARS = """
# Dead Letter Queue environment variables
MAHAVISHNU_DLQ_ENABLED=true
MAHAVISHNU_DLQ_MAX_SIZE=10000
MAHAVISHNU_DLQ_DEFAULT_RETRY_POLICY=exponential
MAHAVISHNU_DLQ_DEFAULT_MAX_RETRIES=3
MAHAVISHNU_DLQ_RETRY_PROCESSOR_ENABLED=true
MAHAVISHNU_DLQ_RETRY_INTERVAL_SECONDS=60
"""
