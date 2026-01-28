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
        if self.sampling:
            caps["sampling"] = {}
        if self.experimental:
            caps["experimental"] = self.experimental
        return caps


# ==================== Sampling Types ====================


@dataclass
class ModelHint:
    """Hint for model selection.

    Hints are treated as substrings that can match model names flexibly.

    Attributes:
        name: Model name hint (e.g., "claude-3-sonnet", "gpt-4").
    """

    name: str
    """Model name hint."""

    def to_dict(self) -> dict[str, str]:
        """Convert to dict."""
        return {"name": self.name}


@dataclass
class ModelPreferences:
    """Preferences for model selection in sampling.

    Servers express needs through priority values (0-1) and optional hints.

    Attributes:
        hints: Optional model hints in order of preference.
        costPriority: Higher values prefer cheaper models (0-1).
        speedPriority: Higher values prefer faster models (0-1).
        intelligencePriority: Higher values prefer more capable models (0-1).
    """

    hints: list[ModelHint] = field(default_factory=list)
    """Model hints in order of preference."""

    costPriority: float = 0.5
    """Cost priority (0-1). Higher = prefer cheaper."""

    speedPriority: float = 0.5
    """Speed priority (0-1). Higher = prefer faster."""

    intelligencePriority: float = 0.5
    """Intelligence priority (0-1). Higher = prefer more capable."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON-RPC."""
        result: dict[str, Any] = {}
        if self.hints:
            result["hints"] = [h.to_dict() for h in self.hints]
        if self.costPriority != 0.5:
            result["costPriority"] = self.costPriority
        if self.speedPriority != 0.5:
            result["speedPriority"] = self.speedPriority
        if self.intelligencePriority != 0.5:
            result["intelligencePriority"] = self.intelligencePriority
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelPreferences":
        """Create from dict."""
        hints = [
            ModelHint(name=h.get("name", ""))
            for h in data.get("hints", [])
        ]
        return cls(
            hints=hints,
            costPriority=data.get("costPriority", 0.5),
            speedPriority=data.get("speedPriority", 0.5),
            intelligencePriority=data.get("intelligencePriority", 0.5),
        )


@dataclass
class SamplingContent:
    """Content in a sampling message.

    Supports text and image content types.

    Attributes:
        type: Content type ("text" or "image").
        text: Text content (for type="text").
        data: Base64-encoded image data (for type="image").
        mimeType: MIME type for images.
    """

    type: str = "text"
    """Content type."""

    text: Optional[str] = None
    """Text content."""

    data: Optional[str] = None
    """Base64-encoded image data."""

    mimeType: Optional[str] = None
    """MIME type for images."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        result: dict[str, Any] = {"type": self.type}
        if self.type == "text" and self.text:
            result["text"] = self.text
        elif self.type == "image":
            if self.data:
                result["data"] = self.data
            if self.mimeType:
                result["mimeType"] = self.mimeType
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SamplingContent":
        """Create from dict."""
        return cls(
            type=data.get("type", "text"),
            text=data.get("text"),
            data=data.get("data"),
            mimeType=data.get("mimeType"),
        )

    @classmethod
    def text_content(cls, text: str) -> "SamplingContent":
        """Create text content."""
        return cls(type="text", text=text)


@dataclass
class SamplingMessage:
    """Message in a sampling request/response.

    Attributes:
        role: Message role ("user" or "assistant").
        content: Message content.
    """

    role: str
    """Message role."""

    content: SamplingContent
    """Message content."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "role": self.role,
            "content": self.content.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SamplingMessage":
        """Create from dict."""
        content_data = data.get("content", {})
        if isinstance(content_data, str):
            content = SamplingContent.text_content(content_data)
        else:
            content = SamplingContent.from_dict(content_data)
        return cls(
            role=data.get("role", "user"),
            content=content,
        )


@dataclass
class SamplingRequest:
    """Request for sampling/createMessage.

    Attributes:
        messages: Conversation messages.
        modelPreferences: Optional model selection preferences.
        systemPrompt: Optional system prompt.
        includeContext: Whether to include MCP context ("none", "thisServer", "allServers").
        temperature: Sampling temperature.
        maxTokens: Maximum tokens to generate.
        stopSequences: Optional stop sequences.
        metadata: Optional metadata.
    """

    messages: list[SamplingMessage]
    """Conversation messages."""

    modelPreferences: Optional[ModelPreferences] = None
    """Model selection preferences."""

    systemPrompt: Optional[str] = None
    """System prompt."""

    includeContext: str = "none"
    """Context inclusion mode."""

    temperature: Optional[float] = None
    """Sampling temperature."""

    maxTokens: int = 1024
    """Maximum tokens to generate."""

    stopSequences: Optional[list[str]] = None
    """Stop sequences."""

    metadata: Optional[dict[str, Any]] = None
    """Additional metadata."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON-RPC params."""
        result: dict[str, Any] = {
            "messages": [m.to_dict() for m in self.messages],
            "maxTokens": self.maxTokens,
        }
        if self.modelPreferences:
            result["modelPreferences"] = self.modelPreferences.to_dict()
        if self.systemPrompt:
            result["systemPrompt"] = self.systemPrompt
        if self.includeContext != "none":
            result["includeContext"] = self.includeContext
        if self.temperature is not None:
            result["temperature"] = self.temperature
        if self.stopSequences:
            result["stopSequences"] = self.stopSequences
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SamplingRequest":
        """Create from dict."""
        messages = [
            SamplingMessage.from_dict(m)
            for m in data.get("messages", [])
        ]
        model_prefs = None
        if "modelPreferences" in data:
            model_prefs = ModelPreferences.from_dict(data["modelPreferences"])
        return cls(
            messages=messages,
            modelPreferences=model_prefs,
            systemPrompt=data.get("systemPrompt"),
            includeContext=data.get("includeContext", "none"),
            temperature=data.get("temperature"),
            maxTokens=data.get("maxTokens", 1024),
            stopSequences=data.get("stopSequences"),
            metadata=data.get("metadata"),
        )


@dataclass
class SamplingResponse:
    """Response from sampling/createMessage.

    Attributes:
        role: Response role (usually "assistant").
        content: Response content.
        model: Model that generated the response.
        stopReason: Reason generation stopped.
    """

    role: str
    """Response role."""

    content: SamplingContent
    """Response content."""

    model: str = ""
    """Model that generated the response."""

    stopReason: str = "endTurn"
    """Reason generation stopped."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON-RPC result."""
        return {
            "role": self.role,
            "content": self.content.to_dict(),
            "model": self.model,
            "stopReason": self.stopReason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SamplingResponse":
        """Create from dict."""
        content_data = data.get("content", {})
        if isinstance(content_data, str):
            content = SamplingContent.text_content(content_data)
        else:
            content = SamplingContent.from_dict(content_data)
        return cls(
            role=data.get("role", "assistant"),
            content=content,
            model=data.get("model", ""),
            stopReason=data.get("stopReason", "endTurn"),
        )


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
    RATE_LIMIT_EXCEEDED = "RateLimitExceeded"


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
