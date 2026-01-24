"""Datetime-related tools.

Provides tools for getting current time, date, and timezone information.
"""

from datetime import datetime, timezone
from typing import Optional

from voice_pipeline.tools.base import ToolParameter, ToolResult, VoiceTool
from voice_pipeline.tools.decorator import voice_tool


@voice_tool(description="Get the current time in HH:MM format")
def get_current_time() -> str:
    """Get the current time."""
    return datetime.now().strftime("%H:%M")


@voice_tool(description="Get the current date in YYYY-MM-DD format")
def get_current_date() -> str:
    """Get the current date."""
    return datetime.now().strftime("%Y-%m-%d")


@voice_tool(description="Get current date and time in ISO format")
def get_datetime() -> str:
    """Get current date and time."""
    return datetime.now().isoformat()


@voice_tool(description="Get the current day of the week (Monday, Tuesday, etc.)")
def get_day_of_week() -> str:
    """Get the day of the week."""
    return datetime.now().strftime("%A")


@voice_tool(description="Get the current UTC time")
def get_utc_time() -> str:
    """Get current UTC time."""
    return datetime.now(timezone.utc).strftime("%H:%M UTC")


class FormatDateTimeTool(VoiceTool):
    """Tool to format a date/time string."""

    name = "format_datetime"
    description = "Format a datetime string according to a specified format"
    parameters = [
        ToolParameter(
            name="datetime_str",
            type="string",
            description="ISO format datetime string (e.g., 2024-01-15T14:30:00)",
            required=True,
        ),
        ToolParameter(
            name="format",
            type="string",
            description="Output format (e.g., '%Y-%m-%d', '%H:%M', '%A %B %d')",
            required=True,
        ),
    ]

    async def execute(
        self,
        datetime_str: str,
        format: str,
    ) -> ToolResult:
        """Format a datetime string.

        Args:
            datetime_str: ISO format datetime string.
            format: strftime format string.

        Returns:
            Formatted datetime string.
        """
        try:
            dt = datetime.fromisoformat(datetime_str)
            formatted = dt.strftime(format)
            return ToolResult(success=True, output=formatted)
        except ValueError as e:
            return ToolResult(success=False, output=None, error=str(e))


class TimeDifferenceTool(VoiceTool):
    """Tool to calculate time difference."""

    name = "time_difference"
    description = "Calculate the difference between two times or dates"
    parameters = [
        ToolParameter(
            name="from_datetime",
            type="string",
            description="Start datetime in ISO format",
            required=True,
        ),
        ToolParameter(
            name="to_datetime",
            type="string",
            description="End datetime in ISO format (defaults to now)",
            required=False,
        ),
    ]

    async def execute(
        self,
        from_datetime: str,
        to_datetime: Optional[str] = None,
    ) -> ToolResult:
        """Calculate time difference.

        Args:
            from_datetime: Start datetime.
            to_datetime: End datetime (defaults to now).

        Returns:
            Human-readable time difference.
        """
        try:
            from_dt = datetime.fromisoformat(from_datetime)

            if to_datetime:
                to_dt = datetime.fromisoformat(to_datetime)
            else:
                to_dt = datetime.now()

            diff = to_dt - from_dt
            total_seconds = int(diff.total_seconds())

            if total_seconds < 0:
                return ToolResult(
                    success=True,
                    output=f"{-total_seconds} seconds in the future",
                )

            days = diff.days
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60

            parts = []
            if days:
                parts.append(f"{days} days")
            if hours:
                parts.append(f"{hours} hours")
            if minutes:
                parts.append(f"{minutes} minutes")
            if seconds and not days:
                parts.append(f"{seconds} seconds")

            result = ", ".join(parts) if parts else "0 seconds"
            return ToolResult(success=True, output=result)

        except ValueError as e:
            return ToolResult(success=False, output=None, error=str(e))


# Instances of class-based tools
format_datetime_tool = FormatDateTimeTool()
time_difference_tool = TimeDifferenceTool()

# All datetime tools
DATETIME_TOOLS = [
    get_current_time,
    get_current_date,
    get_datetime,
    get_day_of_week,
    get_utc_time,
    format_datetime_tool,
    time_difference_tool,
]
