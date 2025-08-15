"""Configuration management for MCP AWS YOLO."""

import os
from typing import Optional, Dict, Any
from pydantic_settings import BaseSettings
from pydantic import Field


class MCPAWSYoloConfig(BaseSettings):
    """Configuration for MCP AWS YOLO server."""
    
    # Server configuration
    server_name: str = Field(default="MCP AWS YOLO", description="MCP server name")
    log_level: str = Field(default="INFO", description="Logging level")
    
    # LLM configuration
    llm_model: str = Field(default="ollama/gpt-oss:20b", description="LLM model for analysis")
    llm_base_url: str = Field(default="http://localhost:11434", description="LLM API base URL")
    llm_api_key: Optional[str] = Field(default=None, description="LLM API key if required")
    
    # Vector store configuration
    qdrant_url: str = Field(default="http://localhost:6333", description="Qdrant vector store URL")
    qdrant_api_key: Optional[str] = Field(default=None, description="Qdrant API key")
    vector_collection_name: str = Field(default="mcp_servers", description="Vector collection name")
    embedding_model: str = Field(default="all-minilm", description="Ollama embedding model")
    
    # MCP server registry
    mcp_registry_file: str = Field(default="mcp_registry.json", description="MCP server registry file")
    
    # Search and routing parameters
    search_limit: int = Field(default=5, description="Vector search result limit")
    similarity_threshold: float = Field(default=0.3, description="Similarity score threshold")
    confidence_threshold: float = Field(default=0.5, description="Confidence threshold for routing")
    
    class Config:
        env_prefix = "MCP_AWS_YOLO_"
        env_file = ".env"


# Global configuration instance
config = MCPAWSYoloConfig()