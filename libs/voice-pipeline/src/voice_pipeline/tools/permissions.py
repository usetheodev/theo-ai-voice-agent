"""Tool permission system for security and access control.

This module provides a permission model for controlling tool execution,
allowing fine-grained access control over what tools can do.

Example:
    >>> from voice_pipeline.tools.permissions import (
    ...     PermissionLevel,
    ...     PermissionPolicy,
    ...     ToolPermissionChecker,
    ... )
    >>>
    >>> # Create a restrictive policy
    >>> policy = PermissionPolicy(
    ...     default_level=PermissionLevel.SAFE,
    ...     blocked_tools={"dangerous_tool"},
    ...     require_confirmation_for={PermissionLevel.DANGEROUS},
    ... )
    >>>
    >>> checker = ToolPermissionChecker(policy)
    >>>
    >>> # Check if tool can execute
    >>> result = checker.check("safe_tool", {"arg": "value"})
    >>> if result.allowed:
    ...     await tool.execute(**args)
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Optional, Set


class PermissionLevel(IntEnum):
    """Permission levels for tools, from most to least restrictive.

    Tools are categorized by their potential impact:
    - SAFE: Read-only operations, no side effects
    - MODERATE: Limited side effects, reversible actions
    - SENSITIVE: Access to personal data or external services
    - DANGEROUS: Destructive or irreversible operations

    Higher values indicate more dangerous operations.
    """

    SAFE = 0
    """Read-only, no side effects (e.g., get_time, get_weather)."""

    MODERATE = 1
    """Limited side effects (e.g., send_message, create_note)."""

    SENSITIVE = 2
    """Accesses personal data or external services (e.g., read_email, api_call)."""

    DANGEROUS = 3
    """Destructive or irreversible (e.g., delete_file, execute_code)."""


@dataclass
class PermissionCheckResult:
    """Result of a permission check.

    Attributes:
        allowed: Whether the tool is allowed to execute.
        requires_confirmation: Whether user confirmation is needed.
        reason: Explanation for the decision.
        suggested_action: What to do if not allowed.
    """

    allowed: bool
    """Whether execution is allowed."""

    requires_confirmation: bool = False
    """Whether user confirmation is required before execution."""

    reason: str = ""
    """Explanation for the decision."""

    suggested_action: Optional[str] = None
    """Suggested action if not allowed."""


@dataclass
class ToolPermission:
    """Permission configuration for a specific tool.

    Attributes:
        tool_name: Name of the tool.
        level: Permission level.
        allowed_args: If set, only these argument names are allowed.
        blocked_args: Arguments that are never allowed.
        validators: Custom validation functions for arguments.
    """

    tool_name: str
    """Name of the tool."""

    level: PermissionLevel = PermissionLevel.SAFE
    """Permission level for this tool."""

    allowed_args: Optional[Set[str]] = None
    """If set, only these arguments are allowed."""

    blocked_args: Set[str] = field(default_factory=set)
    """Arguments that are blocked."""

    validators: dict[str, Callable[[Any], bool]] = field(default_factory=dict)
    """Custom validators for specific arguments. Key is arg name, value is validator."""

    max_calls_per_session: Optional[int] = None
    """Maximum number of calls allowed per session."""

    def validate_args(self, args: dict[str, Any]) -> PermissionCheckResult:
        """Validate arguments against this permission.

        Args:
            args: Arguments to validate.

        Returns:
            PermissionCheckResult indicating if args are valid.
        """
        # Check allowed args
        if self.allowed_args is not None:
            extra_args = set(args.keys()) - self.allowed_args
            if extra_args:
                return PermissionCheckResult(
                    allowed=False,
                    reason=f"Arguments not allowed: {extra_args}",
                    suggested_action="Remove disallowed arguments",
                )

        # Check blocked args
        blocked = set(args.keys()) & self.blocked_args
        if blocked:
            return PermissionCheckResult(
                allowed=False,
                reason=f"Blocked arguments used: {blocked}",
                suggested_action="Remove blocked arguments",
            )

        # Run custom validators
        for arg_name, validator in self.validators.items():
            if arg_name in args:
                try:
                    if not validator(args[arg_name]):
                        return PermissionCheckResult(
                            allowed=False,
                            reason=f"Validation failed for argument '{arg_name}'",
                            suggested_action=f"Provide valid value for '{arg_name}'",
                        )
                except Exception as e:
                    return PermissionCheckResult(
                        allowed=False,
                        reason=f"Validator error for '{arg_name}': {e}",
                    )

        return PermissionCheckResult(allowed=True)


@dataclass
class PermissionPolicy:
    """Policy defining permission rules for tool execution.

    A policy controls which tools can execute and under what conditions.

    Attributes:
        default_level: Default permission level for unlisted tools.
        max_allowed_level: Maximum permission level allowed.
        blocked_tools: Tools that are completely blocked.
        allowed_tools: If set, only these tools are allowed.
        tool_permissions: Specific permissions per tool.
        require_confirmation_for: Levels that require user confirmation.
        confirmation_handler: Async function to request user confirmation.

    Example:
        >>> policy = PermissionPolicy(
        ...     default_level=PermissionLevel.SAFE,
        ...     max_allowed_level=PermissionLevel.MODERATE,
        ...     blocked_tools={"execute_code", "delete_all"},
        ...     require_confirmation_for={PermissionLevel.MODERATE},
        ... )
    """

    default_level: PermissionLevel = PermissionLevel.SAFE
    """Default level for tools without explicit permission."""

    max_allowed_level: PermissionLevel = PermissionLevel.DANGEROUS
    """Maximum level allowed. Tools above this are blocked."""

    blocked_tools: Set[str] = field(default_factory=set)
    """Tool names that are completely blocked."""

    allowed_tools: Optional[Set[str]] = None
    """If set, only these tools are allowed (allowlist mode)."""

    tool_permissions: dict[str, ToolPermission] = field(default_factory=dict)
    """Specific permissions for individual tools."""

    require_confirmation_for: Set[PermissionLevel] = field(default_factory=set)
    """Permission levels that require user confirmation."""

    confirmation_handler: Optional[Callable[[str, dict], bool]] = None
    """Async handler to request confirmation. Args: (tool_name, args) -> allowed."""

    def get_tool_permission(self, tool_name: str) -> ToolPermission:
        """Get permission config for a tool.

        Args:
            tool_name: Name of the tool.

        Returns:
            ToolPermission for this tool.
        """
        if tool_name in self.tool_permissions:
            return self.tool_permissions[tool_name]

        # Return default permission
        return ToolPermission(
            tool_name=tool_name,
            level=self.default_level,
        )


class ToolPermissionChecker:
    """Checks tool permissions against a policy.

    Use this to validate tool calls before execution.

    Attributes:
        policy: The permission policy to enforce.
        call_counts: Tracks calls per tool per session.

    Example:
        >>> checker = ToolPermissionChecker(policy)
        >>> result = checker.check("my_tool", {"arg": "value"})
        >>> if result.allowed:
        ...     if result.requires_confirmation:
        ...         confirmed = await ask_user("Allow tool execution?")
        ...         if confirmed:
        ...             await tool.execute(**args)
        ...     else:
        ...         await tool.execute(**args)
        ... else:
        ...     print(f"Blocked: {result.reason}")
    """

    def __init__(self, policy: Optional[PermissionPolicy] = None):
        """Initialize the checker.

        Args:
            policy: Permission policy to use. If None, uses a permissive default.
        """
        self.policy = policy or PermissionPolicy(
            max_allowed_level=PermissionLevel.DANGEROUS
        )
        self.call_counts: dict[str, int] = {}

    def check(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_level: Optional[PermissionLevel] = None,
    ) -> PermissionCheckResult:
        """Check if a tool call is allowed.

        Args:
            tool_name: Name of the tool to call.
            args: Arguments for the tool call.
            tool_level: Permission level of the tool (if known).

        Returns:
            PermissionCheckResult with the decision.
        """
        policy = self.policy

        # Check if tool is blocked
        if tool_name in policy.blocked_tools:
            return PermissionCheckResult(
                allowed=False,
                reason=f"Tool '{tool_name}' is blocked by policy",
                suggested_action="Use a different tool",
            )

        # Check allowlist mode
        if policy.allowed_tools is not None:
            if tool_name not in policy.allowed_tools:
                return PermissionCheckResult(
                    allowed=False,
                    reason=f"Tool '{tool_name}' is not in allowed list",
                    suggested_action="Use an allowed tool",
                )

        # Get tool permission
        permission = policy.get_tool_permission(tool_name)
        effective_level = tool_level if tool_level is not None else permission.level

        # Check against max allowed level
        if effective_level > policy.max_allowed_level:
            return PermissionCheckResult(
                allowed=False,
                reason=(
                    f"Tool '{tool_name}' has level {effective_level.name} "
                    f"which exceeds max allowed level {policy.max_allowed_level.name}"
                ),
                suggested_action="Use a less privileged tool",
            )

        # Validate arguments
        arg_result = permission.validate_args(args)
        if not arg_result.allowed:
            return arg_result

        # Check call limits
        if permission.max_calls_per_session is not None:
            current_calls = self.call_counts.get(tool_name, 0)
            if current_calls >= permission.max_calls_per_session:
                return PermissionCheckResult(
                    allowed=False,
                    reason=(
                        f"Tool '{tool_name}' has reached max calls "
                        f"({permission.max_calls_per_session}) for this session"
                    ),
                    suggested_action="Wait for next session or use different tool",
                )

        # Check if confirmation is needed
        requires_confirmation = effective_level in policy.require_confirmation_for

        return PermissionCheckResult(
            allowed=True,
            requires_confirmation=requires_confirmation,
            reason="Tool call permitted" + (
                " (confirmation required)" if requires_confirmation else ""
            ),
        )

    def record_call(self, tool_name: str) -> None:
        """Record that a tool was called (for rate limiting).

        Args:
            tool_name: Name of the tool that was called.
        """
        self.call_counts[tool_name] = self.call_counts.get(tool_name, 0) + 1

    def reset_session(self) -> None:
        """Reset call counts for a new session."""
        self.call_counts.clear()

    async def check_with_confirmation(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_level: Optional[PermissionLevel] = None,
    ) -> PermissionCheckResult:
        """Check permissions and handle confirmation if needed.

        This is the recommended method for full permission checking
        including user confirmation when required.

        Args:
            tool_name: Name of the tool.
            args: Tool arguments.
            tool_level: Permission level if known.

        Returns:
            Final PermissionCheckResult after any confirmation.
        """
        result = self.check(tool_name, args, tool_level)

        if not result.allowed:
            return result

        if result.requires_confirmation:
            if self.policy.confirmation_handler:
                try:
                    confirmed = self.policy.confirmation_handler(tool_name, args)
                    if not confirmed:
                        return PermissionCheckResult(
                            allowed=False,
                            reason="User denied confirmation",
                            suggested_action="Request was rejected by user",
                        )
                except Exception as e:
                    return PermissionCheckResult(
                        allowed=False,
                        reason=f"Confirmation handler error: {e}",
                    )
            else:
                # No handler but confirmation required - deny by default
                return PermissionCheckResult(
                    allowed=False,
                    requires_confirmation=True,
                    reason="Confirmation required but no handler configured",
                    suggested_action="Configure a confirmation handler",
                )

        return result


# Convenience function to create common policies
def create_safe_policy() -> PermissionPolicy:
    """Create a restrictive policy that only allows safe operations.

    Returns:
        PermissionPolicy that blocks dangerous tools.
    """
    return PermissionPolicy(
        default_level=PermissionLevel.SAFE,
        max_allowed_level=PermissionLevel.SAFE,
    )


def create_moderate_policy() -> PermissionPolicy:
    """Create a moderate policy with confirmation for sensitive ops.

    Returns:
        PermissionPolicy that requires confirmation for sensitive operations.
    """
    return PermissionPolicy(
        default_level=PermissionLevel.SAFE,
        max_allowed_level=PermissionLevel.SENSITIVE,
        require_confirmation_for={PermissionLevel.SENSITIVE},
    )


def create_permissive_policy() -> PermissionPolicy:
    """Create a permissive policy that allows most operations.

    Returns:
        PermissionPolicy that allows most operations with confirmation for dangerous.
    """
    return PermissionPolicy(
        default_level=PermissionLevel.MODERATE,
        max_allowed_level=PermissionLevel.DANGEROUS,
        require_confirmation_for={PermissionLevel.DANGEROUS},
    )
