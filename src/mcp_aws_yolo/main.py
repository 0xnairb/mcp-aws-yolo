"""Main MCP AWS YOLO server implementation."""

import logging
import asyncio
import sys
import time
from typing import Dict, Any, Optional

from mcp.server import FastMCP
from pydantic import BaseModel

from .config import config
from .vector_store import get_vector_store, close_vector_store
from .llm_client import get_llm_client
from .mcp_client import get_mcp_manager, cleanup_mcp_manager
from .registry import MCPServerRegistry

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)],
    force=True
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP(config.server_name)

# Global instances
registry: Optional[MCPServerRegistry] = None


async def initialize_services():
    """Initialize all services."""
    global registry
    
    logger.info("Initializing MCP AWS YOLO services...")
    
    # Initialize vector store
    await get_vector_store()
    
    # Initialize MCP server registry
    registry = MCPServerRegistry(config.mcp_registry_file)
    await registry.load_registry()
    
    # Index servers in vector store
    # await registry.index_all_servers()
    
    logger.info("All services initialized successfully")


async def cleanup_services():
    """Cleanup all services."""
    logger.info("Cleaning up services...")
    
    try:
        await cleanup_mcp_manager()
        await close_vector_store()
        logger.info("Services cleaned up successfully")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")


@mcp.tool()
async def get_intention(prompt: str, user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Analyze user prompt using LLM and vector store to find the best matched MCP server.
    
    Args:
        prompt: User's natural language prompt
        user_context: Optional context about the user and their environment
    
    Returns:
        Dict containing the best MCP server and its available tools
    """
    if not prompt or not prompt.strip():
        return {
            "error": "Empty prompt provided",
            "server_id": None,
            "available_tools": []
        }
    
    try:
        start_time = time.time()
        logger.info(f"Analyzing user intention for prompt: '{prompt}'")
        
        # Step 1: Use LLM to analyze user intent
        llm_client = get_llm_client()
        user_intent = await llm_client.analyze_user_intent(prompt)
        
        logger.debug(f"User intent analysis: {user_intent}")
        
        # Step 2: Search vector store for candidate servers
        vector_store = await get_vector_store()
        candidates = await vector_store.search_servers(
            query=prompt,
            limit=config.search_limit,
            score_threshold=config.similarity_threshold
        )
        
        if not candidates:
            # Try with expanded keywords from intent analysis
            expanded_query = f"{prompt} {' '.join(user_intent.get('keywords', []))}"
            candidates = await vector_store.search_servers(
                query=expanded_query,
                limit=config.search_limit,
                score_threshold=config.similarity_threshold * 0.8  # Lower threshold
            )
        
        if not candidates:
            return {
                "error": "No suitable MCP servers found for this request",
                "server_id": None,
                "available_tools": [],
                "user_intent": user_intent,
                "execution_time": time.time() - start_time
            }
        
        logger.info(f"Found {len(candidates)} candidate servers")
        
        # Step 3: Use LLM to select the best candidate
        best_candidate = await llm_client.select_best_server(
            user_intent, candidates, prompt
        )
        
        if not best_candidate:
            return {
                "error": "LLM could not select a suitable server from candidates",
                "server_id": None,
                "available_tools": [],
                "candidates": [c.server_id for c in candidates],
                "user_intent": user_intent,
                "execution_time": time.time() - start_time
            }
        
        # Step 4: Get detailed server configuration
        if registry is None:
            logger.error("Registry is not initialized. Attempting to initialize now...")
            try:
                # Try to initialize services if not already done
                await initialize_services()
                if registry is None:
                    return {
                        "error": "Registry initialization failed",
                        "server_id": best_candidate.server_id,
                        "available_tools": [],
                        "execution_time": time.time() - start_time
                    }
            except Exception as e:
                logger.error(f"Failed to initialize services: {e}")
                return {
                    "error": f"Service initialization failed: {str(e)}",
                    "server_id": best_candidate.server_id,
                    "available_tools": [],
                    "execution_time": time.time() - start_time
                }
        
        server_config = registry.get_server_config(best_candidate.server_id)
        if not server_config:
            return {
                "error": f"Server configuration not found: {best_candidate.server_id}",
                "server_id": best_candidate.server_id,
                "available_tools": [],
                "execution_time": time.time() - start_time
            }
        
        # Step 5: Connect to server and get live tools (if needed)
        available_tools = best_candidate.tools
        if not available_tools and server_config.get("dynamic_discovery", True):
            try:
                mcp_manager = get_mcp_manager()
                available_tools = await mcp_manager.list_tools(server_config)
                logger.info(f"Discovered {len(available_tools)} tools dynamically")
            except Exception as e:
                logger.warning(f"Dynamic tool discovery failed: {e}")
                available_tools = best_candidate.tools
        
        execution_time = time.time() - start_time
        confidence = best_candidate.metadata.get("llm_confidence", best_candidate.similarity_score)
        
        result = {
            "server_id": best_candidate.server_id,
            "server_name": best_candidate.name,
            "server_description": best_candidate.description,
            "confidence": confidence,
            "similarity_score": best_candidate.similarity_score,
            "available_tools": available_tools,
            "recommended_tool": best_candidate.metadata.get("recommended_tool"),
            "llm_reasoning": best_candidate.metadata.get("llm_reasoning"),
            "user_intent": user_intent,
            "execution_time": execution_time,
            "next_step": "Use take_action(server_id, tool_name, parameters) to execute a tool"
        }
        
        logger.info(f"Successfully selected server: {best_candidate.server_id} (confidence: {confidence:.3f}, time: {execution_time:.2f}s)")
        return result
        
    except Exception as e:
        logger.exception(f"Error in get_intention: {e}")
        return {
            "error": f"Internal error: {str(e)}",
            "server_id": None,
            "available_tools": [],
            "execution_time": time.time() - start_time if 'start_time' in locals() else 0
        }


@mcp.tool()
async def take_action(
    server_id: str, 
    tool_name: str, 
    parameters: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Execute a tool on the specified MCP server.
    
    Args:
        server_id: ID of the MCP server to use
        tool_name: Name of the tool to execute
        parameters: Tool parameters (optional if auto_fill_params is True)
    
    Returns:
        Tool execution results
    """
    start_time = time.time()
    
    try:        
        logger.info(f"Executing tool '{tool_name}' on server '{server_id}'")
        
        # Get server configuration
        if registry is None:
            logger.error("Registry is not initialized. Attempting to initialize now...")
            try:
                # Try to initialize services if not already done
                await initialize_services()
                if registry is None:
                    return {
                        "success": False,
                        "error": "Registry initialization failed",
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "execution_time": time.time() - start_time
                    }
            except Exception as e:
                logger.error(f"Failed to initialize services: {e}")
                return {
                    "success": False,
                    "error": f"Service initialization failed: {str(e)}",
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "execution_time": time.time() - start_time
                }
        
        server_config = registry.get_server_config(server_id)
        if not server_config:
            return {
                "success": False,
                "error": f"Server configuration not found: {server_id}",
                "server_id": server_id,
                "tool_name": tool_name,
                "execution_time": time.time() - start_time
            }
        
        # Get MCP manager
        mcp_manager = get_mcp_manager()
        
        # Get available tools to validate and get schema using ephemeral connection
        available_tools = await mcp_manager.list_tools(server_config)
        tool_schema = None
        
        for tool in available_tools:
            if tool["name"] == tool_name:
                tool_schema = tool.get("input_schema", {})
                break
        
        if not tool_schema:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' not found on server '{server_id}'",
                "server_id": server_id,
                "tool_name": tool_name,
                "available_tools": [t["name"] for t in available_tools],
                "execution_time": time.time() - start_time
            }
        
        # Execute the tool using ephemeral connection
        result = await mcp_manager.execute_tool(
            server_config, tool_name, parameters
        )
        
        result["execution_time"] = time.time() - start_time
        logger.info(f"Tool execution completed in {result['execution_time']:.2f}s")
        return result
        
    except Exception as e:
        execution_time = time.time() - start_time
        logger.exception(f"Error in take_action: {e}")
        return {
            "success": False,
            "error": f"Internal error: {str(e)}",
            "server_id": server_id,
            "tool_name": tool_name,
            "execution_time": execution_time
        }


@mcp.tool()
async def list_available_servers() -> Dict[str, Any]:
    """List all available MCP servers in the registry."""
    
    try:
        if registry is None:
            return {"error": "Registry not initialized", "servers": []}
        
        servers = registry.list_servers()
        return {
            "total_servers": len(servers),
            "servers": [
                {
                    "server_id": server["server_id"],
                    "name": server["name"],
                    "description": server["description"],
                    "capabilities": server.get("capabilities", []),
                    "tools": [tool["name"] for tool in server.get("tools", [])],
                }
                for server in servers
            ]
        }
        
    except Exception as e:
        logger.exception(f"Error listing servers: {e}")
        return {"error": str(e), "servers": []}


@mcp.tool()
async def health_check() -> Dict[str, Any]:
    """Check health of all services."""
    
    status = {
        "server": "healthy",
        "vector_store": "unknown",
        "llm": "unknown",
        "registry": "unknown",
        "timestamp": time.time()
    }
    
    # Check vector store
    try:
        vector_store = await get_vector_store()
        collection_info = await vector_store.get_collection_info()
        status["vector_store"] = "healthy"
        status["vector_store_info"] = collection_info
    except Exception as e:
        status["vector_store"] = f"error: {str(e)}"
    
    # Check LLM
    try:
        llm_client = get_llm_client()
        await llm_client.analyze_user_intent("test prompt")
        status["llm"] = "healthy"
    except Exception as e:
        status["llm"] = f"error: {str(e)}"
    
    # Check registry
    try:
        if registry is not None:
            servers = registry.list_servers()
            status["registry"] = "healthy"
            status["registry_info"] = {"server_count": len(servers)}
        else:
            status["registry"] = "not initialized"
    except Exception as e:
        status["registry"] = f"error: {str(e)}"
    
    return status


def main():
    """Main entry point."""
    logger.info(f"Starting MCP AWS YOLO server v{config.__dict__}")
    
    async def startup():
        await initialize_services()
    
    async def shutdown():
        await cleanup_services()
    
    # Set startup and shutdown handlers
    mcp.on_startup = startup
    mcp.on_shutdown = shutdown
    
    try:
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        logger.info("MCP AWS YOLO server shutdown complete")


if __name__ == "__main__":
    main()