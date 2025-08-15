"""MCP client for executing tools on remote MCP servers."""

import json
import logging
import asyncio
import os
import re
from typing import Dict, Any, Optional, List
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import config

logger = logging.getLogger(__name__)


def _load_aws_config() -> Dict[str, str]:
    """Load AWS configuration from aws_config.json."""
    
    # Try to find aws_config.json in the current working directory or project root
    config_paths = [
        "aws_config.json",
        os.path.join(os.path.dirname(__file__), "..", "..", "aws_config.json"),
        os.path.join(os.getcwd(), "aws_config.json")
    ]
    
    for config_path in config_paths:
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    aws_config = json.load(f)
                logger.info(f"Loaded AWS config from: {config_path}")
                return aws_config
            except Exception as e:
                logger.warning(f"Failed to load AWS config from {config_path}: {e}")
                continue
    
    logger.warning("Could not find aws_config.json, using empty configuration")
    return {}


def _replace_env_templates(data: Any, aws_config: Dict[str, str]) -> Any:
    """Recursively replace {{env:param_name}} templates with values from aws_config."""
    
    if isinstance(data, str):
        # Replace {{env:param_name}} patterns
        def replace_template(match):
            param_name = match.group(1)
            value = aws_config.get(param_name, "")
            logger.debug(f"Replacing {{{{env:{param_name}}}}} with '{value}'")
            return value
        
        return re.sub(r'\{\{env:([^}]+)\}\}', replace_template, data)
    
    elif isinstance(data, list):
        return [_replace_env_templates(item, aws_config) for item in data]
    
    elif isinstance(data, dict):
        return {key: _replace_env_templates(value, aws_config) for key, value in data.items()}
    
    else:
        return data


class MCPClientManager:
    """Manager for MCP client connections and tool execution."""
    
    def __init__(self):
        self.active_sessions: Dict[str, ClientSession] = {}
        self.session_stacks: Dict[str, AsyncExitStack] = {}
        
    async def _create_ephemeral_connection(self, server_config: Dict[str, Any]):
        """Create a temporary connection to an MCP server for a single operation."""
        
        # Load AWS configuration
        aws_config = _load_aws_config()
        
        # Process server configuration to replace env templates
        processed_config = _replace_env_templates(server_config, aws_config)
        
        # Filter out empty arguments and environment variables
        processed_args = [arg for arg in processed_config.get("args", []) if arg.strip()]
        processed_env = {k: v for k, v in processed_config.get("env", {}).items() if v.strip()}
        
        # Create server parameters
        server_params = StdioServerParameters(
            command=processed_config["command"],
            args=processed_args,
            env=processed_env
        )
        
        logger.debug(f"Creating ephemeral connection to {server_config['server_id']}")
        logger.debug(f"  Command: {processed_config['command']}")
        logger.debug(f"  Args: {processed_args}")
        logger.debug(f"  Env vars: {len(processed_env)} variables")
        
        return server_params
    
    async def list_tools(self, server_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """List tools using an ephemeral connection."""
        
        server_params = await self._create_ephemeral_connection(server_config)
        server_id = server_config["server_id"]
        
        async with AsyncExitStack() as stack:
            try:
                # Connect to server
                read, write = await stack.enter_async_context(
                    stdio_client(server_params)
                )
                
                # Initialize client session
                session = await stack.enter_async_context(
                    ClientSession(read, write)
                )
                
                # Initialize the session
                logger.debug("Initializing MCP session...")
                await session.initialize()
                logger.debug("MCP session initialized successfully")
                
                logger.debug(f"Listing tools for server: {server_id}")
                tools_result = await session.list_tools()
                
                tools = []
                for tool in tools_result.tools:
                    tool_info = {
                        "name": tool.name,
                        "description": getattr(tool, 'description', 'No description available'),
                        "input_schema": getattr(tool, 'inputSchema', {}),
                    }
                    
                    # Add parameter details if available
                    if hasattr(tool, 'inputSchema') and tool.inputSchema:
                        schema = tool.inputSchema
                        if isinstance(schema, dict):
                            properties = schema.get('properties', {})
                            required = schema.get('required', [])
                            
                            tool_info.update({
                                "parameters": properties,
                                "required_parameters": required,
                                "parameter_types": {
                                    param: prop.get('type', 'string') 
                                    for param, prop in properties.items()
                                },
                                "parameter_descriptions": {
                                    param: prop.get('description', 'No description')
                                    for param, prop in properties.items()
                                }
                            })
                    
                    tools.append(tool_info)
                    
                logger.info(f"Found {len(tools)} tools on server {server_id}")
                return tools
                
            except Exception as e:
                logger.error(f"Failed to list tools for server {server_id}: {e}")
                raise
    
    async def execute_tool(
        self, 
        server_config: Dict[str, Any],
        tool_name: str, 
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a tool using an ephemeral connection."""
        
        server_params = await self._create_ephemeral_connection(server_config)
        server_id = server_config["server_id"]
        
        async with AsyncExitStack() as stack:
            try:
                logger.info(f"Executing tool '{tool_name}' on server '{server_id}' with parameters: {parameters}")
                
                # Connect to server
                read, write = await stack.enter_async_context(
                    stdio_client(server_params)
                )
                
                # Initialize client session
                session = await stack.enter_async_context(
                    ClientSession(read, write)
                )
                
                # Initialize the session
                logger.debug("Initializing MCP session...")
                await session.initialize()
                logger.debug("MCP session initialized successfully")
                
                # Execute the tool with parameters
                logger.debug(f"Calling tool '{tool_name}' with parameters: {parameters}")
                
                # Use the MCP session to call the tool
                tool_result = await session.call_tool(
                    name=tool_name,
                    arguments=parameters
                )
                
                logger.info(f"Tool execution completed successfully")
                logger.debug(f"Tool result: {tool_result}")
                
                # Extract result content (following mcp-registry pattern)
                result_content = None
                if hasattr(tool_result, 'content') and tool_result.content:
                    # Handle different content types
                    if len(tool_result.content) == 1:
                        content_item = tool_result.content[0]
                        if hasattr(content_item, 'text'):
                            result_content = content_item.text
                        else:
                            result_content = str(content_item)
                    else:
                        # Multiple content items
                        result_content = [
                            item.text if hasattr(item, 'text') else str(item)
                            for item in tool_result.content
                        ]
                
                # Format result
                return {
                    "success": True,
                    "result": result_content,
                    "tool_name": tool_name,
                    "server_id": server_id,
                    "parameters": parameters,
                    "metadata": {
                        "tool_result_type": str(type(tool_result)),
                        "content_items": len(tool_result.content) if hasattr(tool_result, 'content') else 0
                    }
                }
                
            except Exception as e:
                logger.error(f"Tool execution failed: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "tool_name": tool_name,
                    "server_id": server_id,
                    "parameters": parameters
                }
        
    async def connect_to_server(self, server_config: Dict[str, Any]) -> str:
        """Connect to an MCP server and return session ID."""
        
        server_id = server_config["server_id"]
        
        # Check if already connected
        if server_id in self.active_sessions:
            # Verify the session is still valid
            try:
                session = self.active_sessions[server_id]
                # Test the session with a simple ping if available
                logger.info(f"Using existing connection to {server_id}")
                return server_id
            except Exception as e:
                logger.warning(f"Existing session for {server_id} appears invalid, reconnecting: {e}")
                # Clean up the invalid session
                await self.disconnect_server(server_id)
            
        try:
            # Load AWS configuration
            aws_config = _load_aws_config()
            
            # Process server configuration to replace env templates
            processed_config = _replace_env_templates(server_config, aws_config)
            
            # Filter out empty arguments (common when templates resolve to empty strings)
            processed_args = [arg for arg in processed_config.get("args", []) if arg.strip()]
            
            # Filter out empty environment variables
            processed_env = {k: v for k, v in processed_config.get("env", {}).items() if v.strip()}
            
            logger.debug(f"Processed server config for {server_id}:")
            logger.debug(f"  Command: {processed_config['command']}")
            logger.debug(f"  Args: {processed_args}")
            logger.debug(f"  Env vars: {len(processed_env)} variables")
            
            # Create server parameters with processed configuration
            server_params = StdioServerParameters(
                command=processed_config["command"],
                args=processed_args,
                env=processed_env
            )
            
            # Create async exit stack for this session
            exit_stack = AsyncExitStack()
            self.session_stacks[server_id] = exit_stack
            
            logger.debug(f"Connecting to MCP server: {server_params.command} {server_params.args}")
            
            # Connect to server
            read, write = await exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            logger.debug("stdio_client connected successfully")
            
            # Initialize client session
            session = await exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            logger.debug("ClientSession created successfully")
            
            # Initialize the session
            logger.debug("Initializing MCP session...")
            await session.initialize()
            logger.debug("MCP session initialized successfully")
            
            # Store active session
            self.active_sessions[server_id] = session
            
            logger.info(f"Successfully connected to MCP server: {server_id}")
            return server_id
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {server_id}: {e}")
            # Cleanup on failure
            if server_id in self.session_stacks:
                try:
                    await self.session_stacks[server_id].aclose()
                except Exception as cleanup_error:
                    logger.warning(f"Error during connection cleanup for {server_id}: {cleanup_error}")
                del self.session_stacks[server_id]
            
            # Also cleanup any partial session
            if server_id in self.active_sessions:
                del self.active_sessions[server_id]
            raise
    
    async def disconnect_server(self, server_id: str):
        """Disconnect from an MCP server."""
        
        if server_id in self.active_sessions:
            try:
                # Try to close the session gracefully first
                session = self.active_sessions[server_id]
                if hasattr(session, 'close'):
                    await session.close()
            except Exception as e:
                logger.warning(f"Error closing session for {server_id}: {e}")
            del self.active_sessions[server_id]
            
        if server_id in self.session_stacks:
            try:
                # Close the exit stack more carefully
                stack = self.session_stacks[server_id]
                await stack.aclose()
            except Exception as e:
                logger.warning(f"Error closing session stack for {server_id}: {e}")
                # Don't re-raise - just log and continue cleanup
            del self.session_stacks[server_id]
            
        logger.info(f"Disconnected from MCP server: {server_id}")
    
    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        
        for server_id in list(self.active_sessions.keys()):
            await self.disconnect_server(server_id)
        
        logger.info("Disconnected from all MCP servers")


# Global instance
_mcp_manager: Optional[MCPClientManager] = None


def get_mcp_manager() -> MCPClientManager:
    """Get or create global MCP manager instance."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPClientManager()
    return _mcp_manager


async def cleanup_mcp_manager():
    """Cleanup global MCP manager instance."""
    global _mcp_manager
    if _mcp_manager:
        await _mcp_manager.disconnect_all()
        _mcp_manager = None