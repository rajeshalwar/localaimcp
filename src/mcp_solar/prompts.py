"""MCP prompts -- the server ships the prompt engineering, not just the functions."""
from __future__ import annotations


def register(mcp) -> None:
    @mcp.prompt()
    def solar_assessment(address: str) -> str:
        """Ask for a full, plain-English solar assessment of a property."""
        return (
            f"Assess the solar potential of {address}.\n\n"
            "Use the available tools to get real data -- never estimate production "
            "or savings from memory. Then explain the result to a homeowner in plain "
            "English: roughly how much electricity the array would make in a year, "
            "what that is worth annually, and how long it takes to pay back. "
            "State the assumptions you used, and mention that the figures ignore "
            "rate inflation and panel degradation."
        )
