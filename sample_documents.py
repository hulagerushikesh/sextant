#!/usr/bin/env python3
"""
Sample Documents for Agentic RAG Demonstration

This script provides a minimal set of sample documents for testing purposes only.
The system is designed to handle any user query dynamically through web search and language model responses.
"""

SAMPLE_DOCUMENTS = [
    {
        "id": "doc_001",
        "title": "System Information",
        "content": "This is a Model Context Protocol (MCP) powered RAG system that can answer any user query through intelligent web search and language model responses. The system automatically detects query types and provides relevant information from multiple sources.",
        "source": "system_info.md",
        "page": 1,
        "category": "System"
    }
]


def get_sample_documents():
    """
    Get minimal sample documents for system initialization
    
    Returns:
        List of minimal sample documents
    """
    return SAMPLE_DOCUMENTS


def ingest_sample_documents():
    """
    Ingest minimal sample documents into the vector database
    
    This function can be called to initialize the system with basic information
    """
    import requests
    import json
    
    try:
        response = requests.post(
            "http://localhost:8000/ingest",
            json={
                "documents": SAMPLE_DOCUMENTS,
                "client_id": "system_initialization"
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"Successfully initialized system with {result['documents_added']} documents")
            print(f"Collection now has {result['collection_size']} documents")
        else:
            print(f"Failed to initialize system: {response.text}")
            
    except Exception as e:
        print(f"Error initializing system: {e}")


if __name__ == "__main__":
    print("MCP-Powered RAG System")
    print("=" * 30)
    print("This system handles any user query dynamically through:")
    print("- Intelligent web search with filtering")
    print("- Language model responses for comprehensive answers")
    print("- No predefined static content limitations")
    print("\nTo initialize the system, run:")
    print("python sample_documents.py --init")
    
    import sys
    if "--init" in sys.argv:
        print("\nInitializing system...")
        ingest_sample_documents()
