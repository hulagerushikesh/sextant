# MCP-Powered Agentic RAG System

## Overview

A Model Context Protocol (MCP) powered Retrieval-Augmented Generation (RAG) system that provides intelligent query processing with enhanced filtering for technical content.

## Quick Start

### 1. Install Dependencies
```bash
# Frontend dependencies
cd frontend && npm install

# Python dependencies
pip install -r mcp_client/requirements.txt
pip install -r mcp_server/requirements.txt
pip install -r tools/vector_db/requirements.txt
pip install -r tools/web_search/requirements.txt
```

### 2. Start Services
```bash
# Automated startup
python start_servers.py
```

### 3. Access Application
- Frontend: http://localhost:3000
- MCP Client API: http://localhost:5001
- MCP Server API: http://localhost:8000

## Key Features

- **Intelligent Query Processing**: Automatically detects technical vs general queries
- **Enhanced Web Search Filtering**: Prioritizes coding, C++, and algorithm content
- **Vector Database Integration**: ChromaDB for semantic document search
- **Real-time Web Search**: DuckDuckGo API integration with contextual fallback
- **Clean UI**: Professional interface without emojis or symbols
- **Modular Architecture**: Separate frontend, client, server, and tools

## Complete Documentation

For detailed information about system architecture, API reference, development guide, and troubleshooting, see:

**[COMPLETE_DOCUMENTATION.md](./COMPLETE_DOCUMENTATION.md)**

This comprehensive guide includes:
- System architecture and data flow
- Complete API reference
- Development workflow and best practices
- Enhanced query processing details
- Folder structure and file descriptions
- Integration guide and troubleshooting

## Status
**Production Ready**