"""LLM client for intent analysis and server selection."""

import logging
from typing import Dict, List, Any, Optional
import json

import litellm
from litellm import acompletion

from .config import config
from .vector_store import MCPServerCandidate

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for LLM operations."""
    
    def __init__(self):
        self.model = config.llm_model
        self.base_url = config.llm_base_url
        self.api_key = config.llm_api_key
        
    async def analyze_user_intent(self, prompt: str) -> Dict[str, Any]:
        """Analyze user prompt to extract intent and requirements."""
        
        system_prompt = """
You are an AI assistant that analyzes user prompts to extract intent and requirements.
Given a user prompt, extract:
1. Primary intent/goal
2. Required capabilities
3. Domain/category
4. Key parameters or constraints
5. Urgency level

Return a JSON object with these fields (NO ADDITIONAL FORMATTING, NO EXPLANATIONS, JUST JSON):
- intent: string describing the main goal
- capabilities: list of required capabilities
- domain: string describing the domain/category
- parameters: dict of key parameters
- urgency: "low", "medium", or "high"
- keywords: list of important keywords from the prompt

Example:
User: "I need to deploy a new web application on AWS with auto-scaling"
Response: {
  "intent": "deploy web application with auto-scaling",
  "capabilities": ["deployment", "infrastructure", "auto-scaling", "aws"],
  "domain": "cloud-infrastructure",
  "parameters": {
    "platform": "aws",
    "service_type": "web-application",
    "scaling": "auto"
  },
  "urgency": "medium",
  "keywords": ["deploy", "web", "application", "aws", "auto-scaling"]
}
"""
        
        try:
            response = await acompletion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                base_url=self.base_url,
                api_key=self.api_key,
                temperature=0.1,
            )
            
            content = response.choices[0].message.content
            return json.loads(content)
            
        except Exception as e:
            logger.error(f"LLM intent analysis failed: {e}")
            # Return fallback analysis
            return {
                "intent": prompt,
                "capabilities": [],
                "domain": "general",
                "parameters": {},
                "urgency": "medium",
                "keywords": prompt.split()[:5]
            }
    
    async def select_best_server(
        self, 
        user_intent: Dict[str, Any],
        candidates: List[MCPServerCandidate],
        original_prompt: str
    ) -> Optional[MCPServerCandidate]:
        """Use LLM to select the best MCP server from candidates."""
        
        if not candidates:
            return None
            
        # Prepare candidate information for LLM
        candidates_info = []
        for i, candidate in enumerate(candidates):
            tools_info = []
            for tool in candidate.tools:
                tools_info.append({
                    "name": tool.get("name", ""),
                    "description": tool.get("description", "")
                })
            
            candidates_info.append({
                "index": i,
                "server_id": candidate.server_id,
                "name": candidate.name,
                "description": candidate.description,
                "similarity_score": candidate.similarity_score,
                "tools": tools_info,
                "capabilities": candidate.capabilities
            })
        
        system_prompt = f"""
You are an AI assistant that selects the best MCP server for a user's request.

User Intent Analysis: {json.dumps(user_intent, indent=2)}
Original Prompt: "{original_prompt}"

Available MCP Server Candidates:
{json.dumps(candidates_info, indent=2)}

Select the best server that matches the user's intent and requirements.
Consider:
1. Relevance to user intent
2. Tool availability and functionality
3. Server capabilities
4. Similarity score

Return a JSON object (NO ADDITIONAL FORMATTING, NO EXPLANATIONS, JUST JSON) with:
- selected_index: index of the best server (0-{len(candidates)-1})
- confidence: confidence score 0.0-1.0
- reasoning: explanation for the selection
- recommended_tool: name of the most relevant tool to use

If no server is suitable, return selected_index: -1
"""
        
        try:
            response = await acompletion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt}
                ],
                base_url=self.base_url,
                api_key=self.api_key,
                temperature=0.1,
            )
            
            content = response.choices[0].message.content
            selection = json.loads(content)
            
            selected_index = selection.get("selected_index", -1)
            if 0 <= selected_index < len(candidates):
                selected_candidate = candidates[selected_index]
                # Update confidence based on LLM assessment
                selected_candidate.metadata["llm_confidence"] = selection.get("confidence", 0.5)
                selected_candidate.metadata["llm_reasoning"] = selection.get("reasoning", "")
                selected_candidate.metadata["recommended_tool"] = selection.get("recommended_tool", "")
                
                logger.info(f"LLM selected server: {selected_candidate.server_id} with confidence: {selection.get('confidence', 0.5)}")
                return selected_candidate
            else:
                logger.info("LLM determined no suitable server found")
                return None
                
        except Exception as e:
            logger.error(f"LLM server selection failed: {e}")
            # Fallback to highest similarity score
            if candidates:
                return candidates[0]
            return None


# Global instance
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create global LLM client instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client