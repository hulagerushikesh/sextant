"""
MCP Client Package

This package provides client functionality for communicating with the MCP Server
in the Agentic RAG system.
"""

from .mcp_client import MCPClient, QueryResponse, send_query_to_server

__all__ = ['MCPClient', 'QueryResponse', 'send_query_to_server']
