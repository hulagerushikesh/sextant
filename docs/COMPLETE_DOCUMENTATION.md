# MCP-Powered Agentic RAG System - Complete Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [System Architecture](#system-architecture)
3. [Quick Start Guide](#quick-start-guide)
4. [API Reference](#api-reference)
5. [Development Guide](#development-guide)
6. [Enhanced Query Processing](#enhanced-query-processing)
7. [Folder Structure](#folder-structure)
8. [File Descriptions](#file-descriptions)
9. [Integration Guide](#integration-guide)
10. [Troubleshooting](#troubleshooting)

## Project Overview

### Purpose
A Model Context Protocol (MCP) powered Retrieval-Augmented Generation (RAG) system that provides intelligent query processing with enhanced filtering for technical content.

### Key Features
- **Intelligent Query Processing**: Automatically detects technical vs general queries
- **Enhanced Web Search Filtering**: Prioritizes coding, C++, and algorithm content
- **Vector Database Integration**: ChromaDB for semantic document search
- **Real-time Web Search**: DuckDuckGo API integration with contextual fallback
- **Clean UI**: Professional interface without emojis or symbols
- **Modular Architecture**: Separate frontend, client, server, and tools

### System Components
- **Frontend**: React.js application (Port 3000)
- **MCP Client**: API mediation layer (Port 5001)
- **MCP Server**: Core agent logic (Port 8000)
- **Vector DB Tool**: ChromaDB integration
- **Web Search Tool**: DuckDuckGo API with filtering

## System Architecture

```
User Query → Frontend → MCP Client → MCP Server → Tools → Response
     ↓           ↓           ↓            ↓         ↓        ↓
  React UI → FastAPI → FastAPI → Vector DB → Web Search → Enhanced Response
```

### Data Flow
1. User submits query through React frontend
2. Frontend sends request to MCP Client (Port 5001)
3. MCP Client forwards to MCP Server (Port 8000)
4. MCP Server analyzes query type (Technical vs General)
5. Vector DB search first (especially for technical queries)
6. Web search fallback with enhanced filtering
7. Results formatted with relevance analysis
8. Response sent back through the chain

## Quick Start Guide

### Prerequisites
- Python 3.8+
- Node.js 16+
- npm or yarn

### Installation

1. **Clone and Setup**
```bash
cd /Users/rushikeshhulage/Documents/ProWithSudhanshu/AgenticRAG
```

2. **Install Dependencies**
```bash
# Frontend dependencies
cd frontend && npm install

# Python dependencies
pip install -r mcp_client/requirements.txt
pip install -r mcp_server/requirements.txt
pip install -r tools/vector_db/requirements.txt
pip install -r tools/web_search/requirements.txt
```

3. **Start Services**
```bash
# Option 1: Automated startup
python start_servers.py

# Option 2: Manual startup
# Terminal 1: MCP Server
cd mcp_server && python main.py

# Terminal 2: MCP Client  
cd mcp_client && python server.py

# Terminal 3: Frontend
cd frontend && npm run dev
```

4. **Access Application**
- Frontend: http://localhost:3000
- MCP Client API: http://localhost:5001
- MCP Server API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

## API Reference

### MCP Client Endpoints (Port 5001)

#### Health Check
```
GET /health
```
**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

#### Query Processing
```
POST /query
```
**Request:**
```json
{
  "query": "How to implement binary search in C++?"
}
```
**Response:**
```json
{
  "success": true,
  "response": "Enhanced response with search process explanation...",
  "sources_used": ["vector_db"],
  "processing_time": 1.23,
  "query_received": "How to implement binary search in C++?",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### MCP Server Endpoints (Port 8000)

#### Health Check
```
GET /health
```

#### Query Processing
```
POST /query
```

#### Document Ingestion
```
POST /ingest
```
**Request:**
```json
{
  "documents": [
    {
      "content": "Binary search algorithm implementation...",
      "metadata": {"type": "algorithm", "language": "c++"}
    }
  ]
}
```

## Development Guide

### Project Structure
```
AgenticRAG/
├── frontend/                 # React.js application
│   ├── src/
│   │   ├── App.jsx          # Main application component
│   │   ├── App.css          # Component styles
│   │   ├── api/
│   │   │   └── client.js    # API service
│   │   └── main.jsx         # Application entry point
│   ├── package.json         # Dependencies and scripts
│   └── vite.config.js       # Vite configuration
├── mcp_client/              # API mediation layer
│   ├── server.py            # FastAPI server
│   ├── mcp_client.py        # Client implementation
│   └── requirements.txt     # Python dependencies
├── mcp_server/             # Core agent logic
│   ├── main.py              # FastAPI application
│   └── requirements.txt     # Python dependencies
├── tools/                   # Search and processing tools
│   ├── vector_db/           # Vector database tool
│   │   ├── vector_search.py # ChromaDB integration
│   │   └── requirements.txt # Dependencies
│   └── web_search/          # Web search tool
│       ├── web_search.py     # DuckDuckGo API integration
│       └── requirements.txt # Dependencies
├── start_servers.py          # Automated startup script
├── sample_documents.py      # Sample data
└── test_enhanced_queries.py # Testing script
```

### Development Workflow

1. **Code Changes**: Modify files in respective directories
2. **Auto-reload**: Services automatically reload on file changes
3. **Testing**: Use test script to verify functionality
4. **Documentation**: Update this file for any architectural changes

### Key Dependencies

**Frontend:**
- React 18.2.0
- Vite 4.4.0
- Fetch API for HTTP requests

**Backend:**
- FastAPI for API servers
- ChromaDB for vector database
- DuckDuckGo API for web search
- Sentence Transformers for embeddings

## Enhanced Knowledge Base

### Default Knowledge Base
The system includes 30 pre-loaded documents covering:

**AI/ML Technical Content (10 documents):**
- Machine Learning fundamentals and applications
- Deep Learning concepts and frameworks
- Natural Language Processing techniques
- Computer Vision applications
- Data Science workflows and tools
- Python programming for AI
- Vector databases and embeddings
- RAG systems and MCP protocols

**Scientific Concepts (10 documents):**
- Biology: Photosynthesis, Evolution, DNA and Genetics
- Physics: Newton's Laws, Theory of Relativity
- Chemistry: Periodic Table of Elements
- Earth Science: Water Cycle, Climate Change
- Astronomy: Solar System, Big Bang Theory

**General Knowledge (10 documents):**
- Political Science: Democracy and governance
- History: Renaissance Period and historical concepts
- Social Sciences: Economics, Psychology, Philosophy
- Academic Disciplines: Mathematics, Literature, Arts
- Technology and Health concepts

### Knowledge Base Benefits
- **Comprehensive Coverage**: Scientific, technical, and general knowledge
- **Educational Value**: Provides learning opportunities for various topics
- **Fallback Content**: Ensures relevant responses even for general queries
- **Semantic Search**: Uses vector embeddings for intelligent content matching

## Enhanced Query Processing

### Query Analysis
The system automatically detects query types:
- **Technical Queries**: Coding, programming, algorithms, C++
- **General Queries**: Non-technical information requests

### Search Strategy
1. **Technical Queries**: Vector DB first, then filtered web search
2. **General Queries**: Vector DB, then standard web search
3. **Content Filtering**: Web results filtered for technical relevance
4. **Response Formatting**: Clean, professional responses with relevance analysis

### Technical Content Filtering
- **Coding Keywords**: 25+ programming and C++ specific terms
- **Algorithm Keywords**: 20+ algorithm and problem-solving terms
- **Generic Filtering**: Excludes commercial/educational content unless highly relevant
- **Relevance Scoring**: Detailed analysis of technical content relevance

## Folder Structure

### Frontend (`/frontend/`)
React.js application providing the user interface.

**Key Files:**
- `src/App.jsx`: Main application component with query interface
- `src/api/client.js`: API service for MCP Client communication
- `package.json`: Dependencies and build scripts

### MCP Client (`/mcp_client/`)
API mediation layer between frontend and MCP server.

**Key Files:**
- `server.py`: FastAPI server handling frontend requests
- `mcp_client.py`: Client implementation for MCP Server communication

### MCP Server (`/mcp_server/`)
Core agent logic and query processing.

**Key Files:**
- `main.py`: FastAPI application with enhanced query processing
- Enhanced filtering for technical content
- Document ingestion endpoints

### Tools (`/tools/`)
Search and processing tools.

**Vector DB (`/tools/vector_db/`):**
- `vector_search.py`: ChromaDB integration with semantic search
- Supports document ingestion and similarity search

**Web Search (`/tools/web_search/`):**
- `web_search.py`: DuckDuckGo API integration
- Contextual fallback for reliable results

## File Descriptions

### Core Application Files
- `start_servers.py`: Automated startup script for all services
- `sample_documents.py`: Sample documents for testing
- `test_enhanced_queries.py`: Testing script for query processing

### Configuration Files
- `frontend/package.json`: React dependencies and scripts
- `frontend/vite.config.js`: Vite build configuration
- `*/requirements.txt`: Python dependencies for each component

### Documentation Files
- `Project_Aim.txt`: Original project objectives
- `COMPLETE_DOCUMENTATION.md`: This comprehensive guide

## Integration Guide

### Adding New Tools
1. Create tool directory in `/tools/`
2. Implement tool interface in Python
3. Add tool to MCP Server in `main.py`
4. Update documentation

### Extending Query Processing
1. Modify `_is_technical_query()` for new query types
2. Update `_filter_technical_content()` for new filtering criteria
3. Enhance response formatting as needed

### Customizing Frontend
1. Modify `src/App.jsx` for UI changes
2. Update `src/App.css` for styling
3. Extend `src/api/client.js` for new API endpoints

## Troubleshooting

### Common Issues

**Port Conflicts:**
```bash
# Check port usage
lsof -i :3000 -i :5001 -i :8000

# Kill conflicting processes
kill -9 <PID>
```

**Service Not Starting:**
```bash
# Check logs for specific errors
cd mcp_server && python main.py
cd mcp_client && python server.py
cd frontend && npm run dev
```

**Dependencies Missing:**
```bash
# Install all requirements
pip install -r mcp_client/requirements.txt
pip install -r mcp_server/requirements.txt
pip install -r tools/vector_db/requirements.txt
pip install -r tools/web_search/requirements.txt
```

**ChromaDB Issues:**
- Ensure ChromaDB is properly initialized
- Check collection exists and has documents
- Verify embedding model is loaded

### Performance Optimization
- Vector DB: Use appropriate embedding models
- Web Search: Implement caching for repeated queries
- Frontend: Optimize bundle size with Vite

### Security Considerations
- CORS configuration for cross-origin requests
- Input validation for all API endpoints
- Rate limiting for production deployment

## Status
**Production Ready**: All components are functional and tested.

**Last Updated**: Current session with enhanced filtering and clean documentation.
