"""Schedule models for Prefect deployments.

This module provides Pydantic models for defining schedules in Prefect deployments.
Supports cron, interval, and RRULE schedule types with validation.

Example:
    ```python
    from mahavishnu.engines.prefect_schedules import CronSchedule, IntervalSchedule

    # Cron schedule
    cron = CronSchedule(cron="0 9 * * *", timezone="America/New_York")

    # Interval schedule
    interval = IntervalSchedule(interval_seconds=3600)  # Every hour
    ```
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CronSchedule(BaseModel):
    """Cron-based schedule configuration.

    Uses standard cron expression format with 5 fields:
    minute hour day-of-month month day-of-week

    Attributes:
        cron: Cron expression (e.g., "0 9 * * *" for daily at 9 AM)
        timezone: Timezone for schedule execution (default: UTC)
        day_or: Use OR logic for day-of-month and day-of-week (default: True)

    Example:
        ```python
        # Run every day at 9 AM UTC
        schedule = CronSchedule(cron="0 9 * * *")

        # Run every Monday at 9 AM EST
        schedule = CronSchedule(
            cron="0 9 * * 1",
            timezone="America/New_York"
        )
        ```
    """

    type: Literal["cron"] = "cron"
    cron: str = Field(
        ...,
        description="Cron expression (e.g., '0 9 * * *' for daily at 9 AM)",
    )
    timezone: str = Field(
        default="UTC",
        description="Timezone for schedule execution",
    )
    day_or: bool = Field(
        default=True,
        description="Use OR logic for day-of-month and day-of-week",
    )

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        """Validate cron expression syntax.

        Args:
            v: Cron expression string

        Returns:
            Validated cron expression

        Raises:
            ValueError: If cron expression is invalid
        """
        try:
            import croniter

            croniter.croniter(v)
        except ImportError:
            # croniter not installed, skip validation
            pass
        except (ValueError, Exception) as e:
            raise ValueError(f"Invalid cron expression '{v}': {e}") from e
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate timezone string.

        Args:
            v: Timezone string

        Returns:
            Validated timezone string

        Raises:
            ValueError: If timezone is invalid
        """
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(v)
        except ImportError:
            # zoneinfo not available (Python < 3.9), skip validation
            pass
        except Exception as e:
            raise ValueError(f"Invalid timezone '{v}': {e}") from e
        return v


class IntervalSchedule(BaseModel):
    """Interval-based schedule configuration.

    Runs at fixed intervals (e.g., every hour, every 30 minutes).

    Attributes:
        interval_seconds: Interval in seconds between runs (1 second to 1 year)
        anchor_date: Optional anchor date for interval alignment

    Example:
        ```python
        # Run every hour
        schedule = IntervalSchedule(interval_seconds=3600)

        # Run every 30 minutes starting from a specific time
        schedule = IntervalSchedule(
            interval_seconds=1800,
            anchor_date=datetime(2024, 1, 1, 0, 0, 0)
        )
        ```
    """

    type: Literal["interval"] = "interval"
    interval_seconds: int = Field(
        ...,
        ge=1,
        le=31536000,  # Max 1 year in seconds
        description="Interval in seconds between runs (1 second to 1 year)",
    )
    anchor_date: datetime | None = Field(
        default=None,
        description="Optional anchor date for interval alignment",
    )


class RRuleSchedule(BaseModel):
    """RRule-based schedule configuration using iCalendar recurrence rules.

    Supports complex recurrence patterns that cannot be expressed with cron.

    Attributes:
        rrule: iCalendar RRULE string (e.g., "FREQ=DAILY;BYDAY=MO,WE,FR")
        timezone: Timezone for schedule execution (default: UTC)

    Example:
        ```python
        # Run every Monday, Wednesday, and Friday
        schedule = RRuleSchedule(rrule="FREQ=DAILY;BYDAY=MO,WE,FR")

        # Run every 2 weeks on Tuesday
        schedule = RRuleSchedule(rrule="FREQ=WEEKLY;INTERVAL=2;BYDAY=TU")
        ```
    """

    type: Literal["rrule"] = "rrule"
    rrule: str = Field(
        ...,
        description="iCal RRULE string (e.g., 'FREQ=DAILY;BYDAY=MO,WE,FR')",
    )
    timezone: str = Field(
        default="UTC",
        description="Timezone for schedule execution",
    )

    @field_validator("rrule")
    @classmethod
    def validate_rrule(cls, v: str) -> str:
        """Validate RRULE string syntax.

        Args:
            v: RRULE string

        Returns:
            Validated RRULE string

        Raises:
            ValueError: If RRULE string is invalid
        """
        try:
            from dateutil.rrule import rrulestr

            # rrulestr requires a starting DTSTART, so we add one for validation
            rrulestr(f"DTSTART:20240101T000000Z\nRRULE:{v}")
        except ImportError:
            # python-dateutil not installed, skip validation
            pass
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid RRULE expression '{v}': {e}") from e
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate timezone string.

        Args:
            v: Timezone string

        Returns:
            Validated timezone string

        Raises:
            ValueError: If timezone is invalid
        """
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(v)
        except ImportError:
            # zoneinfo not available, skip validation
            pass
        except Exception as e:
            raise ValueError(f"Invalid timezone '{v}': {e}") from e
        return v


# Union type for all schedule types
ScheduleConfig = CronSchedule | IntervalSchedule | RRuleSchedule


def schedule_to_prefect_dict(schedule: ScheduleConfig) -> dict:
    """Convert a ScheduleConfig to Prefect API format.

    Args:
        schedule: Schedule configuration (CronSchedule, IntervalSchedule, or RRuleSchedule)

    Returns:
        Dictionary in Prefect API format
    """
    if isinstance(schedule, CronSchedule):
        return {
            "cron": schedule.cron,
            "timezone": schedule.timezone,
            "day_or": schedule.day_or,
        }
    elif isinstance(schedule, IntervalSchedule):
        result: dict = {"interval": schedule.interval_seconds}
        if schedule.anchor_date:
            result["anchor_date"] = schedule.anchor_date.isoformat()
        return result
    elif isinstance(schedule, RRuleSchedule):
        return {
            "rrule": schedule.rrule,
            "timezone": schedule.timezone,
        }
    else:
        raise ValueError(f"Unknown schedule type: {type(schedule)}")


__all__ = [
    "CronSchedule",
    "IntervalSchedule",
    "RRuleSchedule",
    "ScheduleConfig",
    "schedule_to_prefect_dict",
]
