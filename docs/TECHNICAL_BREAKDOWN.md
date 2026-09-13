# TECHNICAL BREAKDOWN - AGENTIC RAG SYSTEM

## PROJECT STRUCTURE

```
AgenticRAG/
├── frontend/                 # React UI
├── mcp_client/              # API Gateway
├── mcp_server/              # Core Processing Engine
├── tools/                   # Search Tools
│   ├── vector_db/          # Vector Database Tool
│   └── web_search/         # Web Search Tool
├── sample_documents.py     # Sample Data
├── start_servers.py        # Service Launcher
└── documentation files
```

---

## FRONTEND FOLDER (/frontend/)

### Purpose
React-based user interface for query submission and response display.

### Key Files

#### src/App.jsx
- **Main React Component**
- **State Management**: query, response, loading, documents
- **Functions**:
  - `handleSubmit()`: Sends query to MCP Client
  - `handleDocumentUpload()`: Uploads documents to vector DB
  - `addDocument()`: Adds document to local state
  - `removeDocument()`: Removes document from state
- **UI Elements**: Query input, submit button, response area, document management

#### src/App.css
- **Styling**: Component-specific CSS
- **Classes**: .query-section, .response-section, .document-section
- **Layout**: Responsive design for query and document management

#### src/api/client.js
- **API Client**: HTTP communication with MCP Client
- **Base URL**: http://localhost:5001
- **Functions**:
  - `submitQuery()`: POST query to /query endpoint
  - `uploadDocument()`: POST document to /ingest endpoint
- **Error Handling**: Connection error management

#### package.json
- **Dependencies**: React, Vite, dependencies
- **Scripts**: dev (start development server)
- **Build Tool**: Vite for fast development

---

## MCP CLIENT FOLDER (/mcp_client/)

### Purpose
API Gateway between frontend and MCP server. Handles CORS and request routing.

### Key Files

#### server.py
- **FastAPI Server**: Runs on port 5001
- **Endpoints**:
  - `POST /query`: Forwards queries to MCP server
  - `POST /ingest`: Forwards document uploads to MCP server
  - `GET /health`: Health check endpoint
- **Functions**:
  - `forward_query()`: HTTP request to MCP server
  - `forward_ingest()`: Document upload to MCP server
- **CORS**: Enables cross-origin requests from frontend

#### requirements.txt
- **Dependencies**: FastAPI, uvicorn, requests
- **Purpose**: MCP Client service dependencies

---

## MCP SERVER FOLDER (/mcp_server/)

### Purpose
Core processing engine that orchestrates tools and generates responses.

### Key Files

#### main.py
- **FastAPI Server**: Runs on port 8000
- **Core Functions**:
  - `_process_query_with_tools()`: Main query processing logic
  - `_is_technical_query()`: Determines query type
  - `_search_vector_db()`: Vector database search
  - `_search_web()`: Web search coordination
  - `_filter_technical_content()`: Filters web results for relevance
  - `_format_enhanced_response()`: Formats final response
  - `_generate_general_answer()`: Language model fallback

#### Query Processing Flow
1. **Query Analysis**: Determines if technical or general query
2. **Vector DB Search**: Searches knowledge base first
3. **Web Search**: If vector DB fails, searches web
4. **Content Filtering**: Filters results for relevance
5. **Response Formatting**: Formats and returns response
6. **Fallback**: Language model if all else fails

#### Endpoints
- `POST /query`: Main query processing endpoint
- `POST /ingest`: Document ingestion endpoint
- `GET /health`: Health check

---

## TOOLS FOLDER (/tools/)

### Purpose
Contains search and processing tools used by MCP server.

---

## VECTOR DB TOOL (/tools/vector_db/)

### Purpose
Semantic search using ChromaDB and sentence transformers.

### Key Files

#### vector_search.py
- **Class**: `VectorSearchTool`
- **Core Functions**:
  - `__init__()`: Initializes ChromaDB or in-memory fallback
  - `search()`: Performs semantic similarity search
  - `add_documents()`: Adds documents to vector database
  - `_initialize_chromadb()`: Sets up ChromaDB collection
  - `_search_chromadb()`: ChromaDB similarity search
  - `_search_in_memory()`: Fallback in-memory search

#### Dependencies
- **ChromaDB**: Vector database for document storage
- **Sentence Transformers**: For generating embeddings
- **Fallback**: In-memory search if ChromaDB fails

#### requirements.txt
- **Dependencies**: chromadb, sentence-transformers, numpy
- **Purpose**: Vector database and embedding dependencies

---

## WEB SEARCH TOOL (/tools/web_search/)

### Purpose
Real-time web search using DuckDuckGo HTML scraping.

### Key Files

#### web_search.py
- **Class**: `WebSearchTool`
- **Core Functions**:
  - `search()`: Main search coordination
  - `_search_duckduckgo_html()`: DuckDuckGo HTML scraping
  - `_generate_basic_web_answer()`: Fallback response
- **HTML Parsing**: BeautifulSoup for content extraction
- **Result Processing**: Title, URL, snippet extraction

#### requirements.txt
- **Dependencies**: requests, beautifulsoup4, lxml
- **Purpose**: Web scraping and HTML parsing

---

## ROOT FILES

### sample_documents.py
- **Purpose**: Sample documents for vector database
- **Content**: AI/ML related documents
- **Function**: `get_sample_documents()`: Returns sample data
- **Usage**: Initial knowledge base population

### start_servers.py
- **Purpose**: Automated service launcher
- **Functions**:
  - `start_mcp_server()`: Starts MCP server
  - `start_mcp_client()`: Starts MCP client
  - `start_frontend()`: Starts React frontend
  - `ingest_sample_documents()`: Populates vector DB
- **Process Management**: Subprocess handling for multiple services

---

## DATA FLOW

### Query Processing
1. **Frontend** → User submits query
2. **MCP Client** → Receives query, forwards to MCP Server
3. **MCP Server** → Analyzes query, coordinates tools
4. **Vector DB Tool** → Semantic search in knowledge base
5. **Web Search Tool** → Real-time web search (if needed)
6. **MCP Server** → Formats response, adds source attribution
7. **MCP Client** → Returns response to frontend
8. **Frontend** → Displays response to user

### Document Ingestion
1. **Frontend** → User uploads document
2. **MCP Client** → Forwards to MCP Server
3. **MCP Server** → Calls vector DB tool
4. **Vector DB Tool** → Processes and stores document
5. **Response** → Confirmation back to user

---

## TECHNICAL ARCHITECTURE

### Communication Flow
```
Frontend (React) 
    ↓ HTTP (localhost:3000)
MCP Client (FastAPI)
    ↓ HTTP (localhost:5001)
MCP Server (FastAPI)
    ↓ Tool Calls
Vector DB Tool / Web Search Tool
    ↓ Results
MCP Server
    ↓ Formatted Response
MCP Client
    ↓ JSON Response
Frontend
```

### Error Handling
- **Connection Errors**: Frontend shows "Failed to fetch"
- **Tool Failures**: Fallback to alternative tools
- **No Results**: Language model generates general answer
- **Service Down**: Health checks and error messages

### Performance
- **Vector Search**: Fast semantic similarity
- **Web Search**: Real-time DuckDuckGo scraping
- **Caching**: ChromaDB for document storage
- **Async**: Non-blocking tool calls

---

## DEPLOYMENT

### Local Development
- **Frontend**: npm run dev (port 3000)
- **MCP Client**: python server.py (port 5001)
- **MCP Server**: python main.py (port 8000)
- **Automated**: python start_servers.py

### Dependencies
- **Python**: FastAPI, ChromaDB, BeautifulSoup
- **Node.js**: React, Vite
- **System**: All services run locally

### Configuration
- **Ports**: 3000 (frontend), 5001 (client), 8000 (server)
- **CORS**: Enabled for cross-origin requests
- **Logging**: Debug information for troubleshooting
