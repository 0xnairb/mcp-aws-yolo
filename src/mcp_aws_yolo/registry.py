"""MCP Server Registry for managing server configurations and metadata."""

import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

from .vector_store import get_vector_store
from .config import config

logger = logging.getLogger(__name__)


class MCPServerRegistry:
    """Registry for managing MCP server configurations."""
    
    def __init__(self, registry_file: str = None):
        self.registry_file = registry_file or config.mcp_registry_file
        self.servers: Dict[str, Dict[str, Any]] = {}
        
    async def load_registry(self):
        """Load server registry from JSON file."""
        try:
            registry_path = Path(self.registry_file)
            if not registry_path.exists():
                logger.error(f"Registry file not found: {self.registry_file}")
                raise FileNotFoundError(f"Registry file not found: {self.registry_file}")
            
            with open(registry_path, 'r') as f:
                data = json.load(f)
            
            self.servers = {}
            for server in data.get("servers", []):
                server_id = server["server_id"]
                self.servers[server_id] = server
            
            logger.info(f"Loaded {len(self.servers)} servers from registry")
            
        except Exception as e:
            logger.error(f"Failed to load registry: {e}")
            raise
    
    async def index_all_servers(self):
        """Index all servers in the vector store."""
        try:
            vector_store = await get_vector_store()
            
            for server_id, server_data in self.servers.items():
                await vector_store.index_mcp_server(server_data)
            
            logger.info(f"Indexed {len(self.servers)} servers in vector store")
            
        except Exception as e:
            logger.error(f"Failed to index servers: {e}")
            raise
    
    def get_server_config(self, server_id: str) -> Optional[Dict[str, Any]]:
        """Get server configuration by ID."""
        return self.servers.get(server_id)
    
    def list_servers(self) -> List[Dict[str, Any]]:
        """List all servers."""
        return list(self.servers.values())
    
    def add_server(self, server_data: Dict[str, Any]):
        """Add a new server to the registry."""
        server_id = server_data["server_id"]
        self.servers[server_id] = server_data
        logger.info(f"Added server to registry: {server_id}")
    
    def remove_server(self, server_id: str) -> bool:
        """Remove server from registry."""
        if server_id in self.servers:
            del self.servers[server_id]
            logger.info(f"Removed server from registry: {server_id}")
            return True
        return False
    
    async def save_registry(self):
        """Save registry to file."""
        try:
            registry_data = {"servers": list(self.servers.values())}
            with open(self.registry_file, 'w') as f:
                json.dump(registry_data, f, indent=2)
            logger.info(f"Saved registry with {len(self.servers)} servers")
        except Exception as e:
            logger.error(f"Failed to save registry: {e}")
            raise