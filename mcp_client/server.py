"""
MCP Client Server - FastAPI server to handle frontend requests
and forward them to the MCP Server
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
import uvicorn
import requests
import asyncio
from datetime import datetime


# Request/Response Models
class QueryRequest(BaseModel):
    """Request model from frontend"""
    query: str
    timestamp: Optional[str] = None
    client_id: Optional[str] = None


class QueryResponse(BaseModel):
    """Response model to frontend"""
    success: bool
    response: str
    sources_used: list
    processing_time: float
    error: Optional[str] = None


# Initialize FastAPI app
app = FastAPI(
    title="MCP Client Server",
    description="API mediation layer between frontend and MCP Server",
    version="1.0.0"
)

# Add CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MCP Server configuration
MCP_SERVER_URL = "http://localhost:8000"


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "MCP Client Server is running",
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "mcp_server_url": MCP_SERVER_URL
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "client": "MCP Client Server",
        "mcp_server_available": await _check_mcp_server_health()
    }


@app.post("/query", response_model=QueryResponse)
async def process_query(request: QueryRequest):
    """
    Process query from frontend and forward to MCP Server
    
    Args:
        request: QueryRequest from frontend
        
    Returns:
        QueryResponse: Response from MCP Server
    """
    start_time = datetime.now()
    
    try:
        # Validate query
        if not request.query or not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )
        
        # Forward query to MCP Server
        server_response = await _forward_to_mcp_server(request)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return QueryResponse(
            success=server_response.get("success", False),
            response=server_response.get("response", ""),
            sources_used=server_response.get("sources_used", []),
            processing_time=processing_time,
            error=server_response.get("error")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds()
        return QueryResponse(
            success=False,
            response="",
            sources_used=[],
            processing_time=processing_time,
            error=f"Client error: {str(e)}"
        )


async def _forward_to_mcp_server(request: QueryRequest) -> Dict[str, Any]:
    """
    Forward query to MCP Server
    
    Args:
        request: QueryRequest from frontend
        
    Returns:
        Dict: Response from MCP Server
    """
    try:
        # Prepare payload for MCP Server
        payload = {
            "query": request.query,
            "timestamp": request.timestamp or datetime.now().isoformat(),
            "client_id": request.client_id or "mcp_client"
        }
        
        # Make request to MCP Server
        response = requests.post(
            f"{MCP_SERVER_URL}/query",
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "success": False,
                "response": "",
                "sources_used": [],
                "error": f"MCP Server error: {response.status_code}"
            }
            
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "response": "",
            "sources_used": [],
            "error": "Cannot connect to MCP Server. Please ensure it's running on port 8000."
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "response": "",
            "sources_used": [],
            "error": "MCP Server request timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "response": "",
            "sources_used": [],
            "error": f"Request error: {str(e)}"
        }


async def _check_mcp_server_health() -> bool:
    """
    Check if MCP Server is available
    
    Returns:
        bool: True if server is healthy
    """
    try:
        response = requests.get(f"{MCP_SERVER_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False


# Development server runner
if __name__ == "__main__":
    print("Starting MCP Client Server...")
    print("Server will be available at: http://localhost:5000")
    print("Frontend should connect to: http://localhost:5000")
    print("MCP Server should be running at: http://localhost:8000")
    
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=5001,
        reload=True,
        log_level="info"
    )
