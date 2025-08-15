#!/usr/bin/env python3
"""
Setup script for MCP AWS YOLO - downloads models and initializes data.
Run this after starting the infrastructure services.
"""

import asyncio
import logging
import sys
import subprocess

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_services():
    """Check if required services are running."""
    import httpx
    
    services = {
        "Ollama": "http://localhost:11434/",
        "Qdrant": "http://localhost:6333/healthz"
    }
    
    logger.info("Checking required services...")
    
    for service_name, url in services.items():
        try:
            response = httpx.get(url, timeout=10.0)
            if response.status_code == 200:
                logger.info(f"✓ {service_name} is running")
            else:
                logger.error(f"✗ {service_name} returned status {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"✗ {service_name} is not accessible: {e}")
            logger.error(f"  Please ensure Docker services are running: docker-compose up -d")
            return False
    
    return True


def setup_ollama_model():
    """Download and setup Ollama model."""
    import httpx
    import json
    
    logger.info("Setting up Ollama model...")
    
    model_name = "gpt-oss:20b"
    
    try:
        # Check if model exists via HTTP API
        logger.info("Checking if model exists...")
        response = httpx.get("http://localhost:11434/api/tags", timeout=30.0)
        
        if response.status_code == 200:
            models_data = response.json()
            existing_models = [model.get("name", "") for model in models_data.get("models", [])]
            
            # Check if our model is already available
            model_exists = any(model_name in model for model in existing_models)
            
            if model_exists:
                logger.info(f"✓ Model {model_name} already exists")
                return True
                
            logger.info(f"Model {model_name} not found. Available models: {existing_models}")
        else:
            logger.warning(f"Could not check existing models (HTTP {response.status_code})")
            
        # Pull model using local Ollama
        logger.info(f"Downloading model {model_name} via local Ollama... (this may take several minutes)")
        logger.info("This will download several GB of data, please be patient...")
        
        result = subprocess.run([
            "ollama", "pull", model_name
        ], timeout=3600)  # 60 minutes timeout for large model
        
        if result.returncode == 0:
            logger.info(f"✓ Model {model_name} downloaded successfully")
            
            # Verify the model was downloaded
            try:
                response = httpx.get("http://localhost:11434/api/tags", timeout=10.0)
                if response.status_code == 200:
                    models_data = response.json()
                    existing_models = [model.get("name", "") for model in models_data.get("models", [])]
                    model_exists = any(model_name in model for model in existing_models)
                    
                    if model_exists:
                        logger.info(f"✓ Verified model {model_name} is now available")
                        return True
                    else:
                        logger.warning(f"Model download completed but {model_name} not found in model list")
                        return False
                        
            except Exception as e:
                logger.warning(f"Could not verify model download: {e}")
                return True  # Assume success if docker command succeeded
            
            return True
        else:
            logger.error(f"✗ Failed to download model {model_name}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("✗ Ollama model download timed out (this can happen with large models)")
        logger.error("  You can continue the download manually with:")
        logger.error(f"  ollama pull {model_name}")
        return False
    except FileNotFoundError:
        logger.error("✗ Ollama CLI not found. Please install Ollama first:")
        logger.error("  https://ollama.com/download")
        return False
    except Exception as e:
        logger.error(f"✗ Failed to setup Ollama model: {e}")
        logger.error(f"  You can try manually with:")
        logger.error(f"  ollama pull {model_name}")
        return False


def setup_ollama_embedding_model():
    """Download and setup Ollama embedding model."""
    import httpx
    import json
    
    logger.info("Setting up Ollama embedding model...")
    
    embedding_model_name = "all-minilm"
    
    try:
        # Check if embedding model exists via HTTP API
        logger.info("Checking if embedding model exists...")
        response = httpx.get("http://localhost:11434/api/tags", timeout=30.0)
        
        if response.status_code == 200:
            models_data = response.json()
            existing_models = [model.get("name", "") for model in models_data.get("models", [])]
            
            # Check if our embedding model is already available
            model_exists = any(embedding_model_name in model for model in existing_models)
            
            if model_exists:
                logger.info(f"✓ Embedding model {embedding_model_name} already exists")
                return True
                
            logger.info(f"Embedding model {embedding_model_name} not found. Available models: {existing_models}")
        else:
            logger.warning(f"Could not check existing models (HTTP {response.status_code})")
            
        # Pull embedding model using local Ollama
        logger.info(f"Downloading embedding model {embedding_model_name}... (this may take a few minutes)")
        
        result = subprocess.run([
            "ollama", "pull", embedding_model_name
        ], timeout=1800)  # 30 minutes timeout for embedding model
        
        if result.returncode == 0:
            logger.info(f"✓ Embedding model {embedding_model_name} downloaded successfully")
            
            # Verify the model was downloaded
            try:
                response = httpx.get("http://localhost:11434/api/tags", timeout=10.0)
                if response.status_code == 200:
                    models_data = response.json()
                    existing_models = [model.get("name", "") for model in models_data.get("models", [])]
                    model_exists = any(embedding_model_name in model for model in existing_models)
                    
                    if model_exists:
                        logger.info(f"✓ Verified embedding model {embedding_model_name} is now available")
                        return True
                    else:
                        logger.warning(f"Embedding model download completed but {embedding_model_name} not found in model list")
                        return False
                        
            except Exception as e:
                logger.warning(f"Could not verify embedding model download: {e}")
                return True  # Assume success if ollama command succeeded
            
            return True
        else:
            logger.error(f"✗ Failed to download embedding model {embedding_model_name}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("✗ Ollama embedding model download timed out")
        logger.error("  You can continue the download manually with:")
        logger.error(f"  ollama pull {embedding_model_name}")
        return False
    except FileNotFoundError:
        logger.error("✗ Ollama CLI not found. Please install Ollama first:")
        logger.error("  https://ollama.com/download")
        return False
    except Exception as e:
        logger.error(f"✗ Failed to setup Ollama embedding model: {e}")
        logger.error(f"  You can try manually with:")
        logger.error(f"  ollama pull {embedding_model_name}")
        return False


async def setup_vector_store():
    """Initialize vector store and index servers."""
    logger.info("Setting up vector store and indexing MCP servers...")
    
    try:
        # Import here to avoid issues if packages aren't installed yet
        from src.mcp_aws_yolo.vector_store import get_vector_store_for_setup
        from src.mcp_aws_yolo.registry import MCPServerRegistry
        from src.mcp_aws_yolo.config import config
        
        # Initialize vector store with fresh collection
        logger.info("Initializing vector store...")
        
        # First, delete existing collection if it exists
        try:
            from qdrant_client import AsyncQdrantClient
            qdrant_client = AsyncQdrantClient(url=config.qdrant_url, api_key=config.qdrant_api_key)
            
            # Check if collection exists and delete it
            collections = await qdrant_client.get_collections()
            collection_exists = any(
                collection.name == config.vector_collection_name 
                for collection in collections.collections
            )
            
            if collection_exists:
                await qdrant_client.delete_collection(config.vector_collection_name)
                logger.info(f"Deleted existing collection: {config.vector_collection_name}")
            
            await qdrant_client.close()
        except Exception as e:
            logger.warning(f"Could not delete existing collection: {e}")
        
        # Now initialize vector store (will create fresh collection)
        vector_store = await get_vector_store_for_setup()
        
        # Load MCP server registry
        logger.info("Loading MCP server registry...")
        registry = MCPServerRegistry(config.mcp_registry_file)
        await registry.load_registry()
        
        # Index servers in vector store
        logger.info("Indexing MCP servers in vector store...")
        await registry.index_all_servers()
        
        # Get collection info
        collection_info = await vector_store.get_collection_info()
        logger.info(f"✓ Vector store setup complete:")
        logger.info(f"  - Points: {collection_info.get('points_count', 'unknown')}")
        logger.info(f"  - Vectors: {collection_info.get('vectors_count', 'unknown')}")
        
        return True
        
    except ImportError as e:
        logger.error(f"✗ Missing dependencies: {e}")
        logger.error("  Please install the package first: uv sync")
        return False
    except FileNotFoundError as e:
        logger.error(f"✗ Registry file not found: {e}")
        logger.error("  Please ensure mcp_registry.json exists in the current directory")
        return False
    except Exception as e:
        logger.error(f"✗ Failed to setup vector store: {e}")
        return False


def main():
    """Main setup function."""
    logger.info("🚀 Starting MCP AWS YOLO setup...")
    
    # Check if services are running
    if not check_services():
        logger.error("❌ Setup failed: Required services are not running")
        logger.info("Please start services with: docker-compose up -d")
        sys.exit(1)
    
    # Setup Ollama models
    if not setup_ollama_model():
        logger.error("❌ Setup failed: Could not setup Ollama LLM model")
        sys.exit(1)
    
    if not setup_ollama_embedding_model():
        logger.error("❌ Setup failed: Could not setup Ollama embedding model")
        sys.exit(1)
    
    # Setup vector store (async)
    success = asyncio.run(setup_vector_store())
    if not success:
        logger.error("❌ Setup failed: Could not setup vector store")
        sys.exit(1)
    
    logger.info("🎉 MCP AWS YOLO setup completed successfully!")
    logger.info("")
    logger.info("Next steps:")
    logger.info("1. Run the MCP server: uvx --from . mcp-aws-yolo")
    logger.info("2. Or for development: python -m src.mcp_aws_yolo.main")
    logger.info("")
    logger.info("Services available at:")
    logger.info("- Ollama API: http://localhost:11434")
    logger.info("- Qdrant API: http://localhost:6333")


if __name__ == "__main__":
    main()