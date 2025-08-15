"""Vector store service for MCP server similarity search."""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

import ollama
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException

from .config import config

logger = logging.getLogger(__name__)


@dataclass
class MCPServerCandidate:
    """MCP server candidate with similarity score."""
    server_id: str
    name: str
    description: str
    similarity_score: float
    tools: List[Dict[str, Any]]
    capabilities: List[str]
    metadata: Dict[str, Any]


class VectorStore:
    """Vector store for MCP server embeddings and search."""
    
    def __init__(self):
        self.client: Optional[AsyncQdrantClient] = None
        self.ollama_client = ollama.AsyncClient()
        self._embedding_dim: Optional[int] = None
        
    async def initialize(self):
        """Initialize vector store and embedding model."""
        try:
            # Initialize Qdrant client
            self.client = AsyncQdrantClient(
                url=config.qdrant_url,
                api_key=config.qdrant_api_key,
                timeout=30.0
            )
            
            # Test Ollama connection and get embedding dimension
            logger.info(f"Testing Ollama embedding model: {config.embedding_model}")
            test_embedding = await self._create_embedding("test")
            self._embedding_dim = len(test_embedding)
            
            logger.info(f"Ollama embedding model loaded: {config.embedding_model} (dim: {self._embedding_dim})")
            
            # Use existing collection (setup.py should have created it)
            await self._verify_collection()
            
            logger.info("Vector store initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize vector store: {e}")
            raise
            
    async def _initialize_for_setup(self):
        """Initialize vector store for setup.py (creates fresh collection)."""
        try:
            # Initialize Qdrant client
            self.client = AsyncQdrantClient(
                url=config.qdrant_url,
                api_key=config.qdrant_api_key,
                timeout=30.0
            )
            
            # Test Ollama connection and get embedding dimension
            logger.info(f"Testing Ollama embedding model: {config.embedding_model}")
            test_embedding = await self._create_embedding("test")
            self._embedding_dim = len(test_embedding)
            
            logger.info(f"Ollama embedding model loaded: {config.embedding_model} (dim: {self._embedding_dim})")
            
            # Create fresh collection
            await self._ensure_collection()
            
            logger.info("Vector store initialized successfully for setup")
            
        except Exception as e:
            logger.error(f"Failed to initialize vector store for setup: {e}")
            raise
            
    async def close(self):
        """Close vector store connections."""
        if self.client:
            await self.client.close()
            
    async def _verify_collection(self):
        """Verify that the MCP servers collection exists."""
        if not self.client:
            raise RuntimeError("Vector store not initialized")
            
        collection_name = config.vector_collection_name
        
        try:
            # Check if collection exists
            collections = await self.client.get_collections()
            collection_exists = any(
                collection.name == collection_name 
                for collection in collections.collections
            )
            
            if not collection_exists:
                raise RuntimeError(f"Collection '{collection_name}' not found. Please run setup.py first.")
            
            logger.info(f"Using existing Qdrant collection: {collection_name}")
                
        except ResponseHandlingException as e:
            logger.error(f"Failed to verify collection: {e}")
            raise
            
    async def _ensure_collection(self):
        """Ensure the MCP servers collection exists (used in setup.py)."""
        if not self.client or not self._embedding_dim:
            raise RuntimeError("Vector store not initialized")
            
        collection_name = config.vector_collection_name
        
        try:
            # Create collection (setup.py will delete any existing one first)
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=self._embedding_dim,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(f"Created Qdrant collection: {collection_name} (dim: {self._embedding_dim})")
                
        except ResponseHandlingException as e:
            logger.error(f"Failed to create collection: {e}")
            raise
            
    async def _create_embedding(self, text: str) -> List[float]:
        """Create embedding for text using Ollama."""
        try:
            response = await self.ollama_client.embeddings(
                model=config.embedding_model,
                prompt=text
            )
            return response['embedding']
        except Exception as e:
            logger.error(f"Failed to create embedding with Ollama: {e}")
            raise RuntimeError(f"Ollama embedding failed: {e}")
        
    def _create_server_text(self, server_data: Dict[str, Any]) -> str:
        """Create comprehensive text for embedding."""
        name = server_data.get("name", "")
        description = server_data.get("description", "")
        tools_text = " ".join([
            f"{tool.get('name', '')} {tool.get('description', '')}"
            for tool in server_data.get("tools", [])
        ])
        capabilities_text = " ".join(server_data.get("capabilities", []))
        
        server_text = f"""
        Server: {name}
        Purpose: {description}
        Tools: {tools_text}
        Capabilities: {capabilities_text}
        """.strip()
        
        return server_text
        
    async def index_mcp_server(self, server_data: Dict[str, Any]):
        """Index a single MCP server."""
        if not self.client:
            raise RuntimeError("Vector store not initialized")
            
        try:
            # Create server text for embedding
            server_text = self._create_server_text(server_data)
            
            # Create embedding
            embedding = await self._create_embedding(server_text)
            
            # Create Qdrant point
            point = models.PointStruct(
                id=server_data["id"],
                vector=embedding,
                payload=server_data
            )
            
            # Upsert point
            await self.client.upsert(
                collection_name=config.vector_collection_name,
                points=[point]
            )
            
            logger.info(f"Indexed MCP server: {server_data['server_id']}")
            
        except Exception as e:
            logger.error(f"Failed to index server {server_data.get('server_id', 'unknown')}: {e}")
            raise
            
    async def get_collection_info(self) -> Dict[str, Any]:
        """Get information about the collection."""
        if not self.client:
            raise RuntimeError("Vector store not initialized")
        
        try:
            # Get collection info from Qdrant
            collection_info = await self.client.get_collection(config.vector_collection_name)
            
            return {
                "points_count": collection_info.points_count,
                "vectors_count": collection_info.vectors_count if hasattr(collection_info, 'vectors_count') else collection_info.points_count,
                "status": collection_info.status.value if hasattr(collection_info.status, 'value') else str(collection_info.status)
            }
            
        except Exception as e:
            logger.error(f"Failed to get collection info: {e}")
            return {
                "points_count": "unknown",
                "vectors_count": "unknown", 
                "status": "unknown"
            }

    async def search_servers(
        self, 
        query: str, 
        limit: int = None,
        score_threshold: float = None
    ) -> List[MCPServerCandidate]:
        """Search for relevant MCP servers."""
        if not self.client:
            raise RuntimeError("Vector store not initialized")
            
        limit = limit or config.search_limit
        score_threshold = score_threshold or config.similarity_threshold
        
        try:
            # Create query embedding
            query_embedding = await self._create_embedding(query)
            
            # Search in Qdrant
            search_results = await self.client.search(
                collection_name=config.vector_collection_name,
                query_vector=query_embedding,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False
            )
            
            # Convert to MCPServerCandidate objects
            candidates = []
            for result in search_results:
                payload = result.payload or {}
                candidate = MCPServerCandidate(
                    server_id=payload.get("server_id", "unknown"),
                    name=payload.get("name", "Unknown Server"),
                    description=payload.get("description", ""),
                    similarity_score=result.score,
                    tools=payload.get("tools", []),
                    capabilities=payload.get("capabilities", []),
                    metadata=payload
                )
                candidates.append(candidate)
                
            logger.info(f"Found {len(candidates)} server candidates for query: {query}")
            return candidates
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []


# Global instance
_vector_store: Optional[VectorStore] = None


async def get_vector_store() -> VectorStore:
    """Get or create global vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
        await _vector_store.initialize()
    return _vector_store


async def get_vector_store_for_setup() -> VectorStore:
    """Get vector store instance for setup.py (creates fresh collection)."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
        await _vector_store._initialize_for_setup()
    return _vector_store


async def close_vector_store():
    """Close global vector store instance."""
    global _vector_store
    if _vector_store:
        await _vector_store.close()
        _vector_store = None