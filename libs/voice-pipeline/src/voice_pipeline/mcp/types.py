"""MCP type definitions.

Defines the core types used in the Model Context Protocol,
following the official MCP specification.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union


class TransportType(str, Enum):
    """MCP transport mechanisms."""

    STDIO = "stdio"
    """Standard input/output (for CLI tools)."""

    HTTP = "http"
    """Streamable HTTP (recommended for web)."""

    SSE = "sse"
    """Server-Sent Events."""

    WEBSOCKET = "websocket"
    """WebSocket connection."""


@dataclass
class MCPToolParameter:
    """Parameter definition for an MCP tool.

    Attributes:
        name: Parameter name.
        param_type: JSON Schema type (string, number, boolean, etc.).
        description: Parameter description.
        required: Whether parameter is required.
        default: Default value if not required.
        enum: Allowed values (for enum types).
    """

    name: str
    """Parameter name."""

    param_type: str = "string"
    """JSON Schema type."""

    description: str = ""
    """Parameter description."""

    required: bool = True
    """Whether parameter is required."""

    default: Any = None
    """Default value."""

    enum: Optional[list[str]] = None
    """Allowed values."""

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema property.

        Returns:
            JSON Schema property dict.
        """
        schema: dict[str, Any] = {"type": self.param_type}
        if self.description:
            schema["description"] = self.description
        if self.default is not None:
            schema["default"] = self.default
        if self.enum:
            schema["enum"] = self.enum
        return schema


@dataclass
class MCPTool:
    """MCP Tool definition.

    Tools enable LLMs to perform actions and computations.
    They follow the MCP tool specification with JSON Schema
    for parameter definitions.

    Attributes:
        name: Unique tool identifier.
        description: What the tool does.
        parameters: Tool parameters as JSON Schema.
        returns: Return type schema.
    """

    name: str
    """Unique tool identifier."""

    description: str = ""
    """What the tool does."""

    parameters: dict[str, Any] = field(default_factory=dict)
    """JSON Schema for input parameters."""

    returns: Optional[dict[str, Any]] = None
    """JSON Schema for return value."""

    def to_mcp_schema(self) -> dict[str, Any]:
        """Convert to MCP tool schema.

        Returns:
            MCP-compliant tool schema.
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.parameters,
        }

    @classmethod
    def from_mcp_schema(cls, schema: dict[str, Any]) -> "MCPTool":
        """Create from MCP tool schema.

        Args:
            schema: MCP tool schema dict.

        Returns:
            MCPTool instance.
        """
        return cls(
            name=schema.get("name", ""),
            description=schema.get("description", ""),
            parameters=schema.get("inputSchema", {}),
        )


@dataclass
class MCPToolCall:
    """A call to an MCP tool.

    Represents a request to execute a tool with arguments.

    Attributes:
        name: Tool name to call.
        arguments: Tool arguments.
        call_id: Unique call identifier.
    """

    name: str
    """Tool name to call."""

    arguments: dict[str, Any] = field(default_factory=dict)
    """Tool arguments."""

    call_id: Optional[str] = None
    """Unique call identifier."""

    def to_mcp_request(self) -> dict[str, Any]:
        """Convert to MCP call request.

        Returns:
            MCP call request dict.
        """
        request = {
            "name": self.name,
            "arguments": self.arguments,
        }
        if self.call_id:
            request["_meta"] = {"progressToken": self.call_id}
        return request


@dataclass
class MCPResult:
    """Result from an MCP tool call.

    Attributes:
        content: Result content (text or structured).
        is_error: Whether result is an error.
        metadata: Additional result metadata.
    """

    content: Union[str, dict[str, Any], list[Any]]
    """Result content."""

    is_error: bool = False
    """Whether this is an error result."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata."""

    def to_mcp_response(self) -> dict[str, Any]:
        """Convert to MCP response format.

        Returns:
            MCP response dict.
        """
        if isinstance(self.content, str):
            content = [{"type": "text", "text": self.content}]
        elif isinstance(self.content, dict):
            content = [{"type": "text", "text": str(self.content)}]
        else:
            content = [{"type": "text", "text": str(item)} for item in self.content]

        return {
            "content": content,
            "isError": self.is_error,
        }


@dataclass
class MCPResource:
    """MCP Resource definition.

    Resources expose data without performing significant computation.
    They're analogous to GET endpoints - read-only data access.

    Attributes:
        uri: Resource URI (e.g., "file://docs/{name}").
        name: Human-readable name.
        description: What the resource provides.
        mime_type: Content MIME type.
    """

    uri: str
    """Resource URI template."""

    name: str = ""
    """Human-readable name."""

    description: str = ""
    """What the resource provides."""

    mime_type: str = "text/plain"
    """Content MIME type."""

    def to_mcp_schema(self) -> dict[str, Any]:
        """Convert to MCP resource schema.

        Returns:
            MCP-compliant resource schema.
        """
        return {
            "uri": self.uri,
            "name": self.name or self.uri,
            "description": self.description,
            "mimeType": self.mime_type,
        }


@dataclass
class MCPPrompt:
    """MCP Prompt definition.

    Prompts are reusable templates for LLM interactions.

    Attributes:
        name: Prompt identifier.
        description: What the prompt does.
        arguments: Prompt arguments schema.
    """

    name: str
    """Prompt identifier."""

    description: str = ""
    """What the prompt does."""

    arguments: list[dict[str, Any]] = field(default_factory=list)
    """Prompt argument definitions."""

    def to_mcp_schema(self) -> dict[str, Any]:
        """Convert to MCP prompt schema.

        Returns:
            MCP-compliant prompt schema.
        """
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
        }


@dataclass
class MCPCapabilities:
    """MCP server/client capabilities.

    Declares what features are supported.

    Attributes:
        tools: Supports tools.
        resources: Supports resources.
        prompts: Supports prompts.
        logging: Supports logging.
        sampling: Supports sampling.
    """

    tools: bool = True
    """Supports tools."""

    resources: bool = False
    """Supports resources."""

    prompts: bool = False
    """Supports prompts."""

    logging: bool = False
    """Supports logging."""

    sampling: bool = False
    """Supports sampling."""

    experimental: dict[str, Any] = field(default_factory=dict)
    """Experimental capabilities."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to capabilities dict.

        Returns:
            Capabilities dict.
        """
        caps: dict[str, Any] = {}
        if self.tools:
            caps["tools"] = {}
        if self.resources:
            caps["resources"] = {}
        if self.prompts:
            caps["prompts"] = {}
        if self.logging:
            caps["logging"] = {}
        if self.experimental:
            caps["experimental"] = self.experimental
        return caps


class MCPErrorCode(str, Enum):
    """MCP error codes."""

    PARSE_ERROR = "ParseError"
    INVALID_REQUEST = "InvalidRequest"
    METHOD_NOT_FOUND = "MethodNotFound"
    INVALID_PARAMS = "InvalidParams"
    INTERNAL_ERROR = "InternalError"
    TOOL_NOT_FOUND = "ToolNotFound"
    RESOURCE_NOT_FOUND = "ResourceNotFound"
    CONNECTION_ERROR = "ConnectionError"
    TIMEOUT = "Timeout"


@dataclass
class MCPError(Exception):
    """MCP error.

    Attributes:
        code: Error code.
        message: Error message.
        data: Additional error data.
    """

    code: MCPErrorCode
    """Error code."""

    message: str
    """Error message."""

    data: Optional[dict[str, Any]] = None
    """Additional error data."""

    def __str__(self) -> str:
        return f"MCPError({self.code}): {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to error dict.

        Returns:
            Error dict.
        """
        result = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.data:
            result["data"] = self.data
        return result
