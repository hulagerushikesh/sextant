#!/usr/bin/env python3
"""
Startup script to run both MCP Server and MCP Client Server
"""

import subprocess
import sys
import time
import os
from pathlib import Path

def run_command(command, cwd=None, background=False):
    """Run a command in the specified directory"""
    if background:
        return subprocess.Popen(command, shell=True, cwd=cwd)
    else:
        return subprocess.run(command, shell=True, cwd=cwd)

def main():
    """Start both servers and initialize with sample data"""
    print("Starting Agentic RAG System...")
    print("=" * 50)
    
    # Get project root directory
    project_root = Path(__file__).parent
    
    # Start MCP Server (port 8000)
    print("Starting MCP Server on port 8000...")
    mcp_server_process = run_command(
        "python main.py",
        cwd=project_root / "mcp_server",
        background=True
    )
    
    # Wait a moment for MCP Server to start
    time.sleep(3)
    
    # Start MCP Client Server (port 5000)
    print("Starting MCP Client Server on port 5000...")
    mcp_client_process = run_command(
        "python server.py",
        cwd=project_root / "mcp_client",
        background=True
    )
    
    # Wait a moment for MCP Client to start
    time.sleep(2)
    
    # Initialize with sample documents
    print("Initializing with sample documents...")
    try:
        import requests
        from sample_documents import get_sample_documents
        
        # Wait for server to be ready
        time.sleep(2)
        
        # Ingest sample documents
        sample_docs = get_sample_documents()
        response = requests.post(
            "http://localhost:8000/ingest",
            json={
                "documents": sample_docs,
                "client_id": "startup_initialization"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Ingested {result['documents_added']} sample documents")
            print(f"📚 Collection now has {result['collection_size']} documents")
        else:
            print("⚠️  Failed to ingest sample documents (server may not be ready)")
            
    except Exception as e:
        print(f"⚠️  Could not initialize sample documents: {e}")
        print("   You can manually ingest documents via the frontend")
    
    print("\n" + "=" * 50)
    print("Servers started successfully!")
    print("=" * 50)
    print("MCP Server: http://localhost:8000")
    print("MCP Client: http://localhost:5001")
    print("Frontend: http://localhost:3000 (run 'cd frontend && npm run dev')")
    print("\nAPI Documentation:")
    print("- MCP Server docs: http://localhost:8000/docs")
    print("- MCP Client docs: http://localhost:5001/docs")
    print("\nPress Ctrl+C to stop all servers")
    
    try:
        # Keep the script running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down servers...")
        mcp_server_process.terminate()
        mcp_client_process.terminate()
        print("All servers stopped.")

if __name__ == "__main__":
    main()
