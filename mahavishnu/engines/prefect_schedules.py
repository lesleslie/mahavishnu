"""Schedule models for Prefect deployments.

This module provides Pydantic models for defining schedules in Prefect deployments.
Supports cron, interval, and RRULE schedule types with validation.

Also provides convenience helper functions for common schedule patterns.

Example:
    ```python
    from mahavishnu.engines.prefect_schedules import CronSchedule, IntervalSchedule
    from mahavishnu.engines.prefect_schedules import (
        create_hourly_schedule,
        create_daily_schedule,
        create_weekly_schedule,
        create_monthly_schedule,
    )

    # Cron schedule
    cron = CronSchedule(cron="0 9 * * *", timezone="America/New_York")

    # Interval schedule
    interval = IntervalSchedule(interval_seconds=3600)  # Every hour

    # Convenience helpers
    hourly = create_hourly_schedule(minute=30)  # Every hour at minute 30
    daily = create_daily_schedule(hour=9, minute=0)  # Every day at 9:00 AM
    weekly = create_weekly_schedule(day_of_week=1, hour=9)  # Every Monday at 9 AM
    monthly = create_monthly_schedule(day_of_month=1, hour=0)  # 1st of month at midnight
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


# =============================================================================
# Schedule Helper Functions (Phase 3)
# =============================================================================


def create_hourly_schedule(minute: int = 0) -> IntervalSchedule:
    """Create an hourly schedule.

    Creates an interval schedule that runs every hour. The minute parameter
    determines the offset within the hour for the first run.

    Note: This returns an IntervalSchedule. For cron-based hourly schedules
    (e.g., "at minute X of every hour"), use CronSchedule directly.

    Args:
        minute: Minute offset within the hour (0-59). Defaults to 0.
            This sets the anchor for the interval.

    Returns:
        IntervalSchedule configured for hourly execution

    Raises:
        ValueError: If minute is not in range 0-59

    Example:
        ```python
        from mahavishnu.engines.prefect_schedules import create_hourly_schedule

        # Run every hour on the hour
        schedule = create_hourly_schedule()

        # Run every hour at minute 30
        schedule = create_hourly_schedule(minute=30)

        # Use with deployment
        deployment = await adapter.create_deployment(
            flow_name="my-flow",
            deployment_name="hourly",
            schedule=schedule,
        )
        ```
    """
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be between 0 and 59, got {minute}")

    # Use anchor date to align to specific minute
    anchor = datetime(2024, 1, 1, 0, minute, 0)

    return IntervalSchedule(
        interval_seconds=3600,  # 1 hour in seconds
        anchor_date=anchor,
    )


def create_daily_schedule(
    hour: int,
    minute: int = 0,
    timezone: str = "UTC",
) -> CronSchedule:
    """Create a daily schedule.

    Creates a cron schedule that runs once per day at the specified time.

    Args:
        hour: Hour of day (0-23)
        minute: Minute of hour (0-59). Defaults to 0.
        timezone: Timezone for schedule execution. Defaults to "UTC".

    Returns:
        CronSchedule configured for daily execution

    Raises:
        ValueError: If hour or minute is out of valid range

    Example:
        ```python
        from mahavishnu.engines.prefect_schedules import create_daily_schedule

        # Run every day at midnight UTC
        schedule = create_daily_schedule(hour=0)

        # Run every day at 9:30 AM EST
        schedule = create_daily_schedule(
            hour=9,
            minute=30,
            timezone="America/New_York",
        )

        # Use with deployment
        deployment = await adapter.create_deployment(
            flow_name="etl-flow",
            deployment_name="daily-etl",
            schedule=schedule,
        )
        ```
    """
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be between 0 and 23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be between 0 and 59, got {minute}")

    cron_expr = f"{minute} {hour} * * *"

    return CronSchedule(cron=cron_expr, timezone=timezone)


def create_weekly_schedule(
    day_of_week: int,
    hour: int,
    minute: int = 0,
    timezone: str = "UTC",
) -> CronSchedule:
    """Create a weekly schedule.

    Creates a cron schedule that runs once per week on the specified day.

    Args:
        day_of_week: Day of week (0=Sunday, 1=Monday, ..., 6=Saturday)
        hour: Hour of day (0-23)
        minute: Minute of hour (0-59). Defaults to 0.
        timezone: Timezone for schedule execution. Defaults to "UTC".

    Returns:
        CronSchedule configured for weekly execution

    Raises:
        ValueError: If day_of_week, hour, or minute is out of valid range

    Example:
        ```python
        from mahavishnu.engines.prefect_schedules import create_weekly_schedule

        # Run every Monday at 9 AM UTC
        schedule = create_weekly_schedule(day_of_week=1, hour=9)

        # Run every Friday at 5 PM EST
        schedule = create_weekly_schedule(
            day_of_week=5,
            hour=17,
            timezone="America/New_York",
        )

        # Use with deployment
        deployment = await adapter.create_deployment(
            flow_name="weekly-report",
            deployment_name="weekly",
            schedule=schedule,
        )
        ```
    """
    if not 0 <= day_of_week <= 6:
        raise ValueError(f"day_of_week must be between 0 (Sunday) and 6 (Saturday), got {day_of_week}")
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be between 0 and 23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be between 0 and 59, got {minute}")

    cron_expr = f"{minute} {hour} * * {day_of_week}"

    return CronSchedule(cron=cron_expr, timezone=timezone)


def create_monthly_schedule(
    day_of_month: int,
    hour: int,
    minute: int = 0,
    timezone: str = "UTC",
) -> CronSchedule:
    """Create a monthly schedule.

    Creates a cron schedule that runs once per month on the specified day.

    Note: If day_of_month is greater than the number of days in a month,
    the schedule will not run in shorter months (e.g., day 31 won't run in February).

    Args:
        day_of_month: Day of month (1-31)
        hour: Hour of day (0-23)
        minute: Minute of hour (0-59). Defaults to 0.
        timezone: Timezone for schedule execution. Defaults to "UTC".

    Returns:
        CronSchedule configured for monthly execution

    Raises:
        ValueError: If day_of_month, hour, or minute is out of valid range

    Example:
        ```python
        from mahavishnu.engines.prefect_schedules import create_monthly_schedule

        # Run on the 1st of every month at midnight UTC
        schedule = create_monthly_schedule(day_of_month=1, hour=0)

        # Run on the 15th of every month at noon PST
        schedule = create_monthly_schedule(
            day_of_month=15,
            hour=12,
            timezone="America/Los_Angeles",
        )

        # Use with deployment
        deployment = await adapter.create_deployment(
            flow_name="monthly-billing",
            deployment_name="monthly",
            schedule=schedule,
        )
        ```
    """
    if not 1 <= day_of_month <= 31:
        raise ValueError(f"day_of_month must be between 1 and 31, got {day_of_month}")
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be between 0 and 23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be between 0 and 59, got {minute}")

    cron_expr = f"{minute} {hour} {day_of_month} * *"

    return CronSchedule(cron=cron_expr, timezone=timezone)


__all__ = [
    "CronSchedule",
    "IntervalSchedule",
    "RRuleSchedule",
    "ScheduleConfig",
    "schedule_to_prefect_dict",
    # Schedule helper functions (Phase 3)
    "create_hourly_schedule",
    "create_daily_schedule",
    "create_weekly_schedule",
    "create_monthly_schedule",
]
