"""
MCP Server - FastAPI backend for Agentic RAG system

This server acts as the core agent that makes intelligent decisions about
tool usage and orchestrates responses from Vector DB and Web Search tools.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import uvicorn
from datetime import datetime
import time
import sys
import os

# Load environment variables from .env file
def load_env():
    """Load environment variables from .env file"""
    env_file = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        print(f"Loaded environment variables from {env_file}")
    else:
        print(f"No .env file found at {env_file}")

# Load .env file
load_env()

# Add tools directory to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'tools'))

# Import tool classes
from vector_db.vector_search import VectorSearchTool
from web_search.web_search import WebSearchTool


# Request/Response Models
class QueryRequest(BaseModel):
    """Request model for query endpoint"""
    query: str
    timestamp: Optional[str] = None
    client_id: Optional[str] = None


class QueryResponse(BaseModel):
    """Response model for query endpoint"""
    success: bool
    response: str
    sources_used: List[str]
    processing_time: float
    query_received: str
    timestamp: str
    error: Optional[str] = None


class DocumentRequest(BaseModel):
    """Request model for document ingestion"""
    documents: List[Dict[str, Any]]
    client_id: Optional[str] = None


class DocumentResponse(BaseModel):
    """Response model for document ingestion"""
    success: bool
    message: str
    documents_added: int
    collection_size: int
    error: Optional[str] = None


# Initialize FastAPI app
app = FastAPI(
    title="MCP Server - Agentic RAG",
    description="Core agent server for intelligent query processing",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5001"],  # Frontend and MCP Client URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize tools
vector_tool = VectorSearchTool()
web_tool = WebSearchTool()


@app.get("/")
async def root():
    """Root endpoint - basic health check"""
    return {
        "message": "MCP Server is running",
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "query": "/query (POST)",
            "health": "/health (GET)",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "server": "MCP Agent Server",
        "version": "1.0.0"
    }


@app.post("/ingest", response_model=DocumentResponse)
async def ingest_documents(request: DocumentRequest):
    """
    Ingest documents into the vector database
    
    Args:
        request: DocumentRequest containing documents to add
        
    Returns:
        DocumentResponse: Results of document ingestion
    """
    try:
        # Validate documents
        if not request.documents:
            raise HTTPException(
                status_code=400,
                detail="No documents provided"
            )
        
        # Add documents to vector database
        result = await vector_tool.add_documents(request.documents)
        
        return DocumentResponse(
            success=result["success"],
            message=result["message"],
            documents_added=result["documents_added"],
            collection_size=result.get("collection_size", 0),
            error=result.get("error")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return DocumentResponse(
            success=False,
            message="",
            documents_added=0,
            collection_size=0,
            error=f"Server error: {str(e)}"
        )


@app.post("/query", response_model=QueryResponse)
async def process_query(request: QueryRequest):
    """
    Process user queries and return intelligent responses
    
    Currently echoes back the query as a placeholder implementation.
    Future implementation will include intelligent tool selection and response aggregation.
    """
    start_time = time.time()
    
    try:
        # Validate query
        if not request.query or not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )
        
        # Process query using tools: Vector DB first, then Web Search if empty
        response_data = await _process_query_with_tools(request.query)
        
        processing_time = time.time() - start_time
        
        return QueryResponse(
            success=response_data["success"],
            response=response_data["response"],
            sources_used=response_data["sources_used"],
            processing_time=processing_time,
            query_received=request.query,
            timestamp=datetime.now().isoformat(),
            error=response_data.get("error")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = time.time() - start_time
        return QueryResponse(
            success=False,
            response="",
            sources_used=[],
            processing_time=processing_time,
            query_received=request.query,
            timestamp=datetime.now().isoformat(),
            error=f"Server error: {str(e)}"
        )


async def _process_query_with_tools(query: str) -> Dict[str, Any]:
    """
    Enhanced query processing with technical content prioritization and explicit search explanations
    
    Args:
        query: The user's query string
        
    Returns:
        Dict containing response data and metadata
    """
    try:
        # Initialize search process explanation
        search_process = []
        
        # Step 1: Analyze query type and determine search strategy
        is_technical_query = _is_technical_query(query)
        search_process.append(f"Query Analysis: {'Technical/Coding' if is_technical_query else 'General'} query detected")
        
        # Step 2: Search Vector DB first (especially for technical queries)
        search_process.append("Step 1: Searching Vector Database for relevant documents...")
        vector_result = await _search_vector_db(query)
        
        if vector_result["success"] and vector_result["total_found"] > 0:
            search_process.append(f"Vector DB Results: Found {vector_result['total_found']} relevant documents")
            
            # For technical queries, prioritize Vector DB results
            if is_technical_query:
                search_process.append("Technical Query: Prioritizing Vector DB results for code/technical content")
                return {
                    "success": True,
                    "response": _format_enhanced_response(vector_result, search_process, "vector_db", is_technical_query),
                    "sources_used": ["vector_db"],
                    "error": None
                }
            else:
                # For general queries, use Vector DB if results are good
                return {
                    "success": True,
                    "response": _format_enhanced_response(vector_result, search_process, "vector_db", is_technical_query),
                    "sources_used": ["vector_db"],
                    "error": None
                }
        
        search_process.append("Vector DB Results: No relevant documents found")
        
        # Step 3: If Vector DB is empty, try Web Search
        search_process.append("Step 2: Searching Web for current information...")
        web_result = await _search_web(query)
        
        if web_result["success"]:
            # Use web search results (even if total_results is 0, the formatted_results might contain useful info)
            search_process.append(f"Web Search Results: Found {web_result.get('total_results', 0)} results")
            if web_result.get("formatted_results"):
                # Use the formatted results from web search (includes API setup messages)
                return {
                    "success": True,
                    "response": web_result["formatted_results"],
                    "sources_used": ["web_search"],
                    "error": None
                }
            elif web_result.get("total_results", 0) > 0:
                # Use enhanced response formatting for actual results
                return {
                    "success": True,
                    "response": _format_enhanced_response(web_result["results"], search_process, "web_search", is_technical_query),
                    "sources_used": ["web_search"],
                    "error": None
                }
            else:
                search_process.append("Web Search Results: No results found")
        else:
            search_process.append("Web Search Results: No results found")
        
        # Step 4: If both tools return empty, return no results found
        search_process.append("No relevant information found from any source")
        return {
            "success": True,
            "response": "I don't have specific information about this topic in my current knowledge base. For detailed and up-to-date information, I recommend consulting reliable sources, official documentation, or specialized resources related to your topic of interest.",
            "sources_used": ["vector_db", "web_search"],
            "error": None
        }
        
    except Exception as e:
        search_process.append(f"Error: {str(e)}")
        return {
            "success": False,
            "response": "",
            "sources_used": [],
            "error": f"Tool processing error: {str(e)}"
        }


async def _search_vector_db(query: str) -> Dict[str, Any]:
    """
    Search vector database for relevant documents
    
    Args:
        query: Search query string
        
    Returns:
        Dict containing vector search results
    """
    try:
        print(f"DEBUG: MCP Server - Searching vector DB for query: '{query}'")
        
        # Connect to vector DB (placeholder)
        await vector_tool.connect()
        
        # Search for relevant documents
        result = await vector_tool.search(query)
        print(f"DEBUG: MCP Server - Vector search result: {result}")
        return result
    except Exception as e:
        return {
            "success": False,
            "query": query,
            "results": [],
            "total_found": 0,
            "error": str(e)
        }


async def _search_web(query: str) -> Dict[str, Any]:
    """
    Search web for current information
    
    Args:
        query: Search query string
        
    Returns:
        Dict containing web search results
    """
    try:
        print(f"DEBUG: MCP Server - Searching web for query: '{query}'")
        
        # Configure web search tool (placeholder)
        await web_tool.configure()
        
        # Search for current information
        result = await web_tool.search(query, num_results=3)
        print(f"DEBUG: MCP Server - Web search result: {result}")
        return result
    except Exception as e:
        return {
            "success": False,
            "query": query,
            "results": [],
            "total_found": 0,
            "error": str(e)
        }


def _is_technical_query(query: str) -> bool:
    """
    This function is kept for compatibility but no longer filters queries.
    All queries are treated equally.
    
    Args:
        query: The user's query string
        
    Returns:
        bool: Always returns False to allow all queries through
    """
    return False


def _format_enhanced_response(results, search_process: List[str], source: str, is_technical: bool) -> str:
    """
    Format clean, user-friendly response with source attribution
    
    Args:
        results: Search results from vector DB or web search
        search_process: List of search process steps
        source: Source of the results (vector_db, web_search, etc.)
        is_technical: Whether the query is technical (unused now)
        
    Returns:
        Formatted response string
    """
    if source == "vector_db":
        response = _format_vector_response(results)
        source_info = "📚 **Source: Knowledge Base** (Vector Database)"
    elif source == "web_search":
        response = _format_web_response(results)
        source_info = "🌐 **Source: Web Search** (Current Information)"
    else:
        response = str(results) if results else "No information available"
        source_info = f"📄 **Source: {source.replace('_', ' ').title()}**"
    
    return f"{response}\n\n---\n{source_info}"
    
    # More lenient technical keywords for fallback
    lenient_coding_keywords = [
        'code', 'programming', 'function', 'class', 'method', 'algorithm',
        'python', 'javascript', 'java', 'c++', 'html', 'css', 'react',
        'development', 'software', 'application', 'program', 'script',
        'data', 'database', 'api', 'web', 'frontend', 'backend'
    ]
    
    # General relevance keywords
    general_keywords = [
        'solution', 'help', 'guide', 'tutorial', 'example', 'how to',
        'implementation', 'best practice', 'tips', 'tricks', 'explanation'
    ]
    
    for result in web_result["results"]:
        content = result.get("content", "").lower()
        title = result.get("title", "").lower()
        
        # Calculate lenient relevance scores
        coding_score = sum(1 for keyword in lenient_coding_keywords if keyword in content or keyword in title)
        general_score = sum(1 for keyword in general_keywords if keyword in content or keyword in title)
        
        # Much more lenient filtering - include results with any relevance
        if coding_score > 0 or general_score > 0 or not is_technical_query:
            result["coding_score"] = coding_score
            result["general_score"] = general_score
            result["total_score"] = coding_score + general_score
            result["relevance_analysis"] = f"Lenient match: Coding concepts: {coding_score}, General relevance: {general_score}"
            closest_results.append(result)
    
    # Sort by total relevance score and return top 3
    closest_results.sort(key=lambda x: x.get("total_score", 0), reverse=True)
    return closest_results


def _get_minimal_relevant_snippets(web_result: Dict[str, Any], is_technical_query: bool) -> List[Dict[str, Any]]:
    """
    Get minimal relevant snippets when even lenient filtering fails
    Uses very basic keyword matching to ensure we return something useful
    
    Args:
        web_result: Results from web search
        is_technical_query: Whether the query is technical
        
    Returns:
        List of minimally relevant results
    """
    if not web_result.get("results"):
        return []
    
    minimal_results = []
    
    # Very basic keywords for minimal filtering
    basic_keywords = [
        'information', 'about', 'related', 'topic', 'subject', 'matter',
        'details', 'facts', 'data', 'content', 'text', 'article',
        'discussion', 'explanation', 'description', 'overview'
    ]
    
    for result in web_result["results"]:
        content = result.get("content", "").lower()
        title = result.get("title", "").lower()
        
        # Calculate basic relevance score
        basic_score = sum(1 for keyword in basic_keywords if keyword in content or keyword in title)
        
        # Include any result that has some basic relevance or if it's not a technical query
        if basic_score > 0 or not is_technical_query:
            result["basic_score"] = basic_score
            result["total_score"] = basic_score
            result["relevance_analysis"] = f"Minimal match: Basic relevance score: {basic_score}"
            minimal_results.append(result)
    
    # Sort by basic score and return top 3
    minimal_results.sort(key=lambda x: x.get("basic_score", 0), reverse=True)
    return minimal_results


def _create_summary_from_all_results(web_result: Dict[str, Any], is_technical_query: bool) -> List[Dict[str, Any]]:
    """
    Create a summary from all available web results when all filtering fails
    This ensures we never return zero results if web search found anything
    
    Args:
        web_result: Results from web search
        is_technical_query: Whether the query is technical
        
    Returns:
        List containing a summary of all results
    """
    if not web_result.get("results"):
        return []
    
    # Create a summary result from all available content
    all_content = []
    all_titles = []
    all_urls = []
    
    for result in web_result["results"]:
        content = result.get("content", result.get("snippet", ""))
        title = result.get("title", "")
        url = result.get("url", "")
        
        if content:
            all_content.append(content)  # Use full content
        if title:
            all_titles.append(title)
        if url:
            all_urls.append(url)
    
    if not all_content:
        return []
    
    # Create a summary result
    summary_result = {
        "title": f"Summary of {len(all_titles)} search results",
        "content": "Based on available web search results: " + " ".join(all_content),  # Combine all results
        "url": all_urls[0] if all_urls else "",
        "source": "Web Search Summary",
        "date": "",
        "summary_score": len(all_content),
        "total_score": len(all_content),
        "relevance_analysis": f"Summary generated from {len(all_content)} available results"
    }
    
    return [summary_result]


def _filter_technical_content(web_result: Dict[str, Any], is_technical_query: bool) -> List[Dict[str, Any]]:
    """
    Enhanced filtering for coding/C++/algorithms content with detailed relevance analysis
    
    Args:
        web_result: Results from web search
        is_technical_query: Whether the query is technical
        
    Returns:
        List of filtered and ranked results with relevance analysis
    """
    if not web_result.get("results"):
        return []
    
    filtered_results = []
    
    # Enhanced technical keywords for coding/C++/algorithms
    coding_keywords = [
        'code', 'function', 'class', 'method', 'algorithm', 'implementation', 'example',
        'c++', 'cpp', 'programming', 'syntax', 'variable', 'loop', 'array', 'pointer',
        'recursion', 'iteration', 'optimization', 'complexity', 'data structure',
        'binary search', 'sorting', 'tree', 'graph', 'hash', 'stack', 'queue',
        'template', 'namespace', 'inheritance', 'polymorphism', 'encapsulation',
        'debug', 'error', 'exception', 'try', 'catch', 'throw', 'const', 'static',
        'inline', 'virtual', 'override', 'final', 'auto', 'decltype', 'lambda'
    ]
    
    # Problem-solving and algorithm keywords
    algorithm_keywords = [
        'algorithm', 'solution', 'approach', 'technique', 'pattern', 'strategy',
        'optimization', 'efficiency', 'performance', 'time complexity', 'space complexity',
        'big o', 'o(n)', 'o(log n)', 'o(1)', 'worst case', 'best case', 'average case',
        'dynamic programming', 'greedy', 'backtring', 'divide and conquer',
        'two pointers', 'sliding window', 'hash map', 'binary search', 'merge sort',
        'quick sort', 'heap', 'priority queue', 'union find', 'trie', 'segment tree'
    ]
    
    for result in web_result["results"]:
        content = result.get("content", "").lower()
        title = result.get("title", "").lower()
        url = result.get("url", "").lower()
        
        # Calculate detailed relevance scores
        coding_score = sum(1 for keyword in coding_keywords if keyword in content or keyword in title)
        algorithm_score = sum(1 for keyword in algorithm_keywords if keyword in content or keyword in title)
        
        # Check for generic/unrelated content indicators
        generic_indicators = [
            'buy now', 'shop', 'price', 'discount', 'sale', 'advertisement',
            'news', 'blog', 'forum', 'discussion', 'opinion', 'review',
            'tutorial', 'course', 'book', 'ebook', 'pdf', 'download'
        ]
        
        is_generic = any(indicator in content or indicator in title for indicator in generic_indicators)
        
        # Calculate total relevance score
        total_score = coding_score + algorithm_score
        
        # Exclude generic content unless it has high technical relevance
        if is_generic and total_score < 3:
            continue
            
        # Include results with sufficient technical content
        if total_score > 0 or is_technical_query:
            result["coding_score"] = coding_score
            result["algorithm_score"] = algorithm_score
            result["total_score"] = total_score
            result["is_generic"] = is_generic
            result["relevance_analysis"] = _analyze_relevance(result, coding_keywords, algorithm_keywords)
            filtered_results.append(result)
    
    # Sort by total relevance score, then by coding score
    filtered_results.sort(key=lambda x: (x.get("total_score", 0), x.get("coding_score", 0)), reverse=True)
    return filtered_results  # Return all relevant results


def _analyze_relevance(result: Dict[str, Any], coding_keywords: List[str], algorithm_keywords: List[str]) -> str:
    """
    Analyze and describe the relevance of a search result
    
    Args:
        result: Search result dictionary
        coding_keywords: List of coding-related keywords
        algorithm_keywords: List of algorithm-related keywords
        
    Returns:
        String describing the relevance analysis
    """
    content = result.get("content", "").lower()
    title = result.get("title", "").lower()
    
    found_coding = [kw for kw in coding_keywords if kw in content or kw in title]
    found_algorithms = [kw for kw in algorithm_keywords if kw in content or kw in title]
    
    analysis_parts = []
    
    if found_coding:
        analysis_parts.append(f"Coding concepts: {', '.join(found_coding)}")
    if found_algorithms:
        analysis_parts.append(f"Algorithm concepts: {', '.join(found_algorithms)}")
    
    if not analysis_parts:
        return "General technical content"
    
    return "; ".join(analysis_parts)


def _format_enhanced_response(results, search_process: List[str], source: str, is_technical: bool) -> str:
    """
    Format clean, user-friendly response with source attribution
    
    Args:
        results: Search results (can be dict or list)
        search_process: List of search process steps (not used in output)
        source: Source of results (vector_db or web_search)
        is_technical: Whether query is technical
        
    Returns:
        Formatted response string with source information
    """
    if source == "vector_db":
        response = _format_vector_response(results)
        source_info = "📚 **Source: Knowledge Base** (Vector Database)"
    elif source == "web_search":
        response = _format_web_response(results)
        source_info = "🌐 **Source: Web Search** (Current Information)"
    else:
        response = str(results) if results else "No information available"
        source_info = f"📄 **Source: {source.replace('_', ' ').title()}**"
    
    # Add source attribution at the end
    return f"{response}\n\n---\n{source_info}"










def _format_vector_response(vector_result: Dict[str, Any]) -> str:
    """
    Format vector database results into clean, user-friendly response
    
    Args:
        vector_result: Results from vector search
        
    Returns:
        str: Clean, formatted response text
    """
    if not vector_result.get("results"):
        return "I don't have specific information about this topic in my knowledge base."
    
    # For definitions, provide the most relevant content directly
    best_doc = max(vector_result["results"], key=lambda x: x.get("similarity_score", 0))
    
    if any(word in best_doc.get("content", "").lower() for word in ["definition", "define", "meaning", "is a", "refers to"]):
        return best_doc["content"]
    
    # For other queries, provide a clean summary
    response_parts = []
    for doc in vector_result["results"]:  # Use all results
        content = doc.get("content", "")
        if content:
            response_parts.append(content)
    
    if response_parts:
        return "\n\n".join(response_parts)
    else:
        return "I found some relevant information but couldn't provide a clear answer."


def _format_web_response(web_result) -> str:
    """
    Format web search results in a clean, user-friendly way
    
    Args:
        web_result: Results from web search (can be dict with results key or list)
        
    Returns:
        str: Clean, formatted response text
    """
    # Handle both dict and list inputs
    if isinstance(web_result, dict):
        results = web_result.get("results", [])
    elif isinstance(web_result, list):
        results = web_result
    else:
        return "I couldn't find specific information about your query. Let me provide a general answer based on what I know."
    
    if not results:
        return "I couldn't find specific information about your query. Let me provide a general answer based on what I know."
    
    # Get the best snippet from the results
    best_snippet = ""
    for result in results:
        snippet = result.get("snippet", "")
        if snippet and len(snippet) > len(best_snippet):
            best_snippet = snippet
    
    if best_snippet:
        # Clean up the snippet
        cleaned = best_snippet.strip()
        
        # Remove URLs, dates, and other noise
        import re
        cleaned = re.sub(r'https?://\S+', '', cleaned)
        cleaned = re.sub(r'www\.\S+', '', cleaned)
        cleaned = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+', '', cleaned)
        cleaned = re.sub(r'\d{4}-\d{2}-\d{2}', '', cleaned)
        
        # Remove common redundant patterns
        if cleaned.lower().startswith('the '):
            cleaned = cleaned[4:]
        
        # Clean up multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Ensure proper sentence structure
        if cleaned and not cleaned.endswith(('.', '!', '?')):
            cleaned += '.'
        
        return cleaned
    else:
        return "I couldn't find specific information about your query. Let me provide a general answer based on what I know."


def _clean_web_content(content: str) -> str:
    """
    Clean web search content to remove redundant questions and improve readability
    
    Args:
        content: Raw content from web search
        
    Returns:
        Cleaned content without redundant questions
    """
    if not content:
        return content
    
    # Remove common question patterns from the beginning
    question_patterns = [
        r'^What is [^?]+\?',
        r'^What are [^?]+\?',
        r'^How does [^?]+\?',
        r'^How do [^?]+\?',
        r'^Why is [^?]+\?',
        r'^Why are [^?]+\?',
        r'^When is [^?]+\?',
        r'^When are [^?]+\?',
        r'^Where is [^?]+\?',
        r'^Where are [^?]+\?',
        r'^Who is [^?]+\?',
        r'^Who are [^?]+\?',
    ]
    
    import re
    cleaned = content
    
    # Remove question patterns from the beginning
    for pattern in question_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()
    
    # Remove leading question marks and clean up
    cleaned = cleaned.lstrip('?').strip()
    
    # If the content starts with the same word repeated, remove it
    words = cleaned.split()
    if len(words) > 1 and words[0].lower() == words[1].lower():
        cleaned = ' '.join(words[1:])
    
    # Remove redundant "is" at the beginning
    if cleaned.lower().startswith('is '):
        cleaned = cleaned[3:].strip()
    
    # Remove "Information about:" patterns
    if cleaned.lower().startswith('information about:'):
        cleaned = cleaned[18:].strip()
    
    # Remove redundant title patterns
    if ':' in cleaned and len(cleaned.split(':')) == 2:
        parts = cleaned.split(':')
        if len(parts[0]) < 50:  # If the part before colon is short, it's likely a title
            cleaned = parts[1].strip()
    
    # Capitalize the first letter
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    
    return cleaned


# Development server runner
if __name__ == "__main__":
    print("Starting MCP Server...")
    print("Server will be available at: http://localhost:8000")
    print("API documentation at: http://localhost:8000/docs")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
