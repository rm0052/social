"""Reddit MCP Streamable HTTP Client

A client for interacting with the Reddit MCP server, which provides tools for fetching
Reddit content such as hot threads from subreddits and detailed post information with comments.

"""

import argparse
import asyncio
import sys
import traceback
from typing import Optional
from contextlib import AsyncExitStack

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    print("Successfully imported MCP modules")
except ImportError as e:
    print(f"Error importing MCP modules: {e}")
    sys.exit(1)

try:
    from anthropic import Anthropic
    print("Successfully imported Anthropic module")
except ImportError as e:
    print(f"Error importing Anthropic module: {e}")
    sys.exit(1)


class MCPClient:
    """Reddit MCP Client for interacting with the Reddit MCP Streamable HTTP server
    
    This client provides methods to:
    1. Connect to the Reddit MCP server
    2. Process general queries using Claude and available tools
    3. Run an interactive command-line interface
    """

    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic()
        # Initialize context attributes to None to avoid attribute errors
        self._session_context = None
        self._streams_context = None

    async def connect_to_streamable_http_server(
        self, server_url: str, headers: Optional[dict] = None
    ):
        """Connect to an MCP server running with HTTP Streamable transport"""
        try:
            print(f"Connecting to MCP server at {server_url}")
            # Ensure we have headers dictionary
            headers = headers or {}
            
            # Log headers (with sensitive values redacted)
            redacted_headers = {
                k: (v[:5] + "..." if k.startswith("REDDIT-") and v else v) 
                for k, v in headers.items()
            }
            print(f"Using headers: {redacted_headers}")
            
            # Create streamable HTTP client context and properly manage it with AsyncExitStack
            # Note: streamablehttp_client doesn't accept api_key or auth_token as parameters
            # It automatically extracts authentication from headers
            # Explicitly omit the Authorization header to avoid authentication method resolution issues
            # We need to use an empty string instead of None for the Authorization header
            if "Authorization" not in headers:
                headers["Authorization"] = ""  # Explicitly omit Authorization header with empty string
            
            # Ensure X-Api-Key is present for authentication
            if "X-Api-Key" not in headers:
                raise ValueError("X-Api-Key header is required for authentication")
            
            # Log the authentication method being used
            print(f"Using API key: {headers.get('X-Api-Key')}")
            
            # Create streamable HTTP client context
            # The streamablehttp_client function automatically extracts authentication from headers
            streams_context = streamablehttp_client(
                url=server_url,
                headers=headers,
            )
            print("Created streamablehttp_client context")
            
            # Use AsyncExitStack to manage the context
            read_stream, write_stream, _ = await self.exit_stack.enter_async_context(streams_context)
            print("Entered streams context")

            # Create and enter the client session
            session_context = ClientSession(read_stream, write_stream)
            print("Created ClientSession")
            
            self.session = await self.exit_stack.enter_async_context(session_context)
            print("Entered session context")

            # Initialize the session
            await self.session.initialize()
            print("Session initialized successfully")
            
            # Verify connection by listing available tools
            tools = await self.session.list_tools()
            print(f"Available tools: {[tool.name for tool in tools.tools]}")
        except Exception as e:
            print(f"Error connecting to MCP server: {e}")
            traceback.print_exc()
            raise
    
    async def _process_tool_response(self, content, context_description: str) -> str:
        """
        Process response content from tool calls, handling different response types
        
        Args:
            content: The response content from a tool call
            context_description: Description of the context for error messages
            
        Returns:
            Processed string response
        """
        # Check if it's a TextContent object with a string representation of an async generator
        if hasattr(content, "text") and isinstance(content.text, str) and "<async_generator" in content.text:
            # This is a TextContent object containing a string representation of an async generator
            # We can't directly consume it, so we'll return a more user-friendly message
            return f"Streaming content for {context_description} (server response is streaming but client can't consume it directly)"
        
        # Check if it's an actual async generator
        elif hasattr(content, "__aiter__"):
            # This is an async generator, we need to consume it
            content_parts = []
            async for part in content:
                content_parts.append(part)
            return "\n".join(content_parts)
        
        # Check if it's a list
        elif isinstance(content, list):
            # Already a list, join the elements
            return "\n".join(str(item) for item in content)
        
        # Regular content, return as is
        else:
            return content

    async def chat_loop(self):
      try:
          print(f"Fetching hot threads from r/{subreddit}...")
          result = await self.session.call_tool(
              "fetch_reddit_hot_threads", 
              {"subreddit": subreddit, "limit": limit}
          )
          
          # Process the response from the server using the helper method
          response = await self._process_tool_response(result.content, f"r/{subreddit}")
          
          return response
      except Exception as e:
          error_msg = f"Error fetching Reddit threads: {str(e)}"
          print(error_msg)

    async def cleanup(self):
        """Properly clean up the session and streams"""
        # Using AsyncExitStack to properly close all resources
        await self.exit_stack.aclose()
        self.session = None


def get_client():
    global _client
    if _client is None:
        _client = MCPClient()
    return _client
