"""
Vector DB Search Tool - In-Memory Implementation

This module provides vector database search functionality for the Agentic RAG system.
Currently uses in-memory text entries with simple string similarity search.
TODO: Replace with real vector database (ChromaDB, Pinecone, FAISS, etc.)
"""

from typing import List, Dict, Any, Optional
import asyncio
import time
from datetime import datetime
import re
from difflib import SequenceMatcher

# Real vector database imports
try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("ChromaDB not available, falling back to in-memory search")


class VectorSearchTool:
    """Vector database search tool with in-memory implementation"""
    
    def __init__(self, db_url: str = "in-memory://vector-db", collection_name: str = "documents"):
        """
        Initialize Vector Search Tool
        
        Args:
            db_url: Vector database connection URL (placeholder for real DB)
            collection_name: Name of the document collection (placeholder for real DB)
        """
        self.db_url = db_url
        self.collection_name = collection_name
        self.is_connected = False
        self.use_chromadb = CHROMADB_AVAILABLE
        
        # Initialize vector database connection
        if self.use_chromadb:
            self._initialize_chromadb()
        else:
            # Fallback to in-memory implementation
            self.text_entries = self._initialize_text_entries()
    
    def _initialize_chromadb(self):
        """
        Initialize ChromaDB client and collection
        
        This replaces the in-memory implementation with real vector database
        """
        try:
            # Initialize ChromaDB client
            self.client = chromadb.Client()
            
            # Get or create collection
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "Agentic RAG document collection"}
            )
            
            # Initialize sentence transformer for embeddings
            self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
            
            print(f"ChromaDB initialized with collection: {self.collection_name}")
            
        except Exception as e:
            print(f"ChromaDB initialization failed: {e}")
            self.use_chromadb = False
            self.text_entries = self._initialize_text_entries()
    
    def _initialize_text_entries(self) -> List[Dict[str, Any]]:
        """
        Initialize in-memory text entries for semantic search
        
        Returns:
            List of text entries with metadata
        """
        return [
            {
                "id": "doc_001",
                "title": "Introduction to Machine Learning",
                "content": "Machine learning is a subset of artificial intelligence that focuses on algorithms that can learn from data without being explicitly programmed. It involves training models on datasets to make predictions or decisions.",
                "category": "AI/ML",
                "source": "ml_handbook.pdf",
                "page": 1
            },
            {
                "id": "doc_002",
                "title": "Deep Learning Fundamentals",
                "content": "Deep learning uses neural networks with multiple layers to model complex patterns in data. It has revolutionized fields like computer vision, natural language processing, and speech recognition.",
                "category": "AI/ML",
                "source": "deep_learning_guide.pdf",
                "page": 15
            },
            {
                "id": "doc_003",
                "title": "Natural Language Processing",
                "content": "NLP combines computational linguistics with machine learning to process and understand human language. It enables applications like chatbots, translation, and sentiment analysis.",
                "category": "AI/ML",
                "source": "nlp_textbook.pdf",
                "page": 42
            },
            {
                "id": "doc_004",
                "title": "Computer Vision Applications",
                "content": "Computer vision enables machines to interpret and understand visual information from images and videos. Applications include object detection, facial recognition, and medical imaging.",
                "category": "AI/ML",
                "source": "cv_applications.pdf",
                "page": 8
            },
            {
                "id": "doc_005",
                "title": "Reinforcement Learning",
                "content": "Reinforcement learning is an area of machine learning concerned with how agents make decisions in an environment to maximize cumulative reward. It's used in robotics, gaming, and autonomous systems.",
                "category": "AI/ML",
                "source": "rl_theory.pdf",
                "page": 23
            },
            {
                "id": "doc_006",
                "title": "Data Science Workflow",
                "content": "Data science involves collecting, cleaning, analyzing, and interpreting data to extract insights. The typical workflow includes data exploration, feature engineering, model building, and validation.",
                "category": "Data Science",
                "source": "data_science_guide.pdf",
                "page": 12
            },
            {
                "id": "doc_007",
                "title": "Python Programming for AI",
                "content": "Python is the most popular programming language for artificial intelligence and machine learning. Key libraries include NumPy, Pandas, Scikit-learn, TensorFlow, and PyTorch.",
                "category": "Programming",
                "source": "python_ai_guide.pdf",
                "page": 5
            }
        ]
    
    async def connect(self) -> bool:
        """
        Connect to vector database (in-memory implementation)
        
        Returns:
            bool: Always returns True for in-memory setup
        """
        # TODO: Replace with actual vector DB connection
        # Example for ChromaDB:
        # import chromadb
        # self.client = chromadb.Client()
        # self.collection = self.client.get_or_create_collection(self.collection_name)
        
        await asyncio.sleep(0.1)  # Simulate connection delay
        self.is_connected = True
        return True
    
    async def search(self, query: str, limit: int = 50, similarity_threshold: float = 0.1) -> Dict[str, Any]:
        """
        Search vector database using ChromaDB or fallback to in-memory search
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            similarity_threshold: Minimum similarity score (0.0-1.0)
            
        Returns:
            Dict containing search results and metadata
        """
        start_time = time.time()
        
        print(f"DEBUG: Vector search for query: '{query}'")
        print(f"DEBUG: Using ChromaDB: {self.use_chromadb}")
        print(f"DEBUG: Similarity threshold: {similarity_threshold}")
        
        if self.use_chromadb:
            # Use real vector database search
            search_results = await self._search_chromadb(query, limit, similarity_threshold)
            database_type = "chromadb"
            print(f"DEBUG: ChromaDB search returned {len(search_results)} results")
        else:
            # Fallback to in-memory search
            search_results = self._perform_similarity_search(query, limit, similarity_threshold)
            database_type = "in-memory_vector_db"
            print(f"DEBUG: In-memory search returned {len(search_results)} results")
        
        processing_time = time.time() - start_time
        
        return {
            "success": True,
            "query": query,
            "results": search_results,
            "total_found": len(search_results),
            "processing_time": processing_time,
            "similarity_threshold": similarity_threshold,
            "database": database_type,
            "collection": self.collection_name,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _search_chromadb(self, query: str, limit: int, similarity_threshold: float) -> List[Dict[str, Any]]:
        """
        Search using ChromaDB vector database
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            similarity_threshold: Minimum similarity score (0.0-1.0)
            
        Returns:
            List of search results from ChromaDB
        """
        try:
            # Check if collection has any documents
            collection_count = self.collection.count()
            print(f"DEBUG: ChromaDB collection has {collection_count} documents")
            
            if collection_count == 0:
                print("DEBUG: ChromaDB collection is empty, returning no results")
                return []
            
            # Generate embedding for the query
            query_embedding = self.embedder.encode([query]).tolist()[0]
            
            # Search in ChromaDB collection
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                include=['documents', 'metadatas', 'distances']
            )
            
            # Format results
            search_results = []
            if results['documents'] and results['documents'][0]:
                for i, (doc, metadata, distance) in enumerate(zip(
                    results['documents'][0],
                    results['metadatas'][0],
                    results['distances'][0]
                )):
                    # Convert distance to similarity score (ChromaDB uses distance, we want similarity)
                    similarity_score = 1 - distance
                    
                    if similarity_score >= similarity_threshold:
                        search_results.append({
                            "id": metadata.get("id", f"doc_{i}"),
                            "title": metadata.get("title", "Document"),
                            "content": doc,
                            "similarity_score": similarity_score,
                            "source": metadata.get("source", "unknown"),
                            "page": metadata.get("page", 1),
                            "category": metadata.get("category", "general")
                        })
            
            return search_results
            
        except Exception as e:
            print(f"ChromaDB search error: {e}")
            # Fallback to in-memory search
            return self._perform_similarity_search(query, limit, similarity_threshold)
    
    def _perform_similarity_search(self, query: str, limit: int, similarity_threshold: float) -> List[Dict[str, Any]]:
        """
        Perform similarity search on in-memory text entries
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            similarity_threshold: Minimum similarity score (0.0-1.0)
            
        Returns:
            List of document results with similarity scores
        """
        query_lower = query.lower()
        scored_results = []
        
        for entry in self.text_entries:
            # Calculate similarity score using multiple methods
            similarity_score = self._calculate_similarity(query_lower, entry)
            
            # Only include results above threshold
            if similarity_score >= similarity_threshold:
                result = {
                    "id": entry["id"],
                    "title": entry["title"],
                    "content": entry["content"],
                    "similarity_score": similarity_score,
                    "source": entry["source"],
                    "page": entry["page"],
                    "category": entry["category"]
                }
                scored_results.append(result)
        
        # Sort by similarity score (highest first)
        scored_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        # Return top results up to limit
        return scored_results[:limit]
    
    def _calculate_similarity(self, query: str, entry: Dict[str, Any]) -> float:
        """
        Calculate similarity score between query and text entry
        
        Args:
            query: Lowercase search query
            entry: Text entry dictionary
            
        Returns:
            float: Similarity score between 0.0 and 1.0
        """
        # Combine title and content for similarity calculation
        text_to_search = f"{entry['title']} {entry['content']}".lower()
        
        # Method 1: Substring matching (exact matches get high scores)
        substring_score = 0.0
        query_words = query.split()
        for word in query_words:
            if word in text_to_search:
                substring_score += 0.3  # Boost for exact word matches
        
        # Method 2: Sequence similarity using difflib
        sequence_score = SequenceMatcher(None, query, text_to_search).ratio()
        
        # Method 3: Keyword density (how many query words appear)
        keyword_density = 0.0
        if query_words:
            matches = sum(1 for word in query_words if word in text_to_search)
            keyword_density = matches / len(query_words)
        
        # Combine scores with weights
        final_score = (
            substring_score * 0.4 +      # Exact matches get priority
            sequence_score * 0.4 +       # Overall text similarity
            keyword_density * 0.2        # Keyword coverage
        )
        
        # Cap at 1.0
        return min(final_score, 1.0)
    
    async def get_document_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific document by ID from in-memory entries
        
        Args:
            doc_id: Document identifier
            
        Returns:
            Dict containing document data or None if not found
        """
        # TODO: Replace with actual document retrieval from vector DB
        # Example for ChromaDB:
        # result = self.collection.get(ids=[doc_id])
        # if result['ids']:
        #     return result['metadatas'][0]
        
        await asyncio.sleep(0.1)
        
        # Search in-memory entries
        for entry in self.text_entries:
            if entry["id"] == doc_id:
                return {
                    "id": entry["id"],
                    "title": entry["title"],
                    "content": entry["content"],
                    "source": entry["source"],
                    "page": entry["page"],
                    "category": entry["category"],
                    "metadata": {
                        "created_at": "2024-01-01T00:00:00Z",
                        "updated_at": "2024-01-01T00:00:00Z",
                        "database": "in-memory_vector_db"
                    }
                }
        
        return None
    
    async def add_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Add documents to the vector database
        
        Args:
            documents: List of documents with 'content', 'title', 'metadata'
            
        Returns:
            Dict containing addition results
        """
        if not self.use_chromadb:
            return {
                "success": False,
                "message": "ChromaDB not available, cannot add documents",
                "documents_added": 0
            }
        
        try:
            print(f"DEBUG: Adding {len(documents)} documents to ChromaDB")
            
            # Extract content and metadata
            texts = [doc["content"] for doc in documents]
            metadatas = []
            ids = []
            
            for i, doc in enumerate(documents):
                metadata = {
                    "id": doc.get("id", f"doc_{i}"),
                    "title": doc.get("title", "Untitled"),
                    "source": doc.get("source", "unknown"),
                    "page": doc.get("page", 1),
                    "category": doc.get("category", "general")
                }
                metadatas.append(metadata)
                ids.append(metadata["id"])
            
            print(f"DEBUG: Generated {len(texts)} texts, {len(metadatas)} metadatas, {len(ids)} ids")
            
            # Generate embeddings
            embeddings = self.embedder.encode(texts).tolist()
            print(f"DEBUG: Generated {len(embeddings)} embeddings")
            
            # Add to ChromaDB collection
            self.collection.add(
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
                ids=ids
            )
            
            print(f"DEBUG: Successfully added documents to ChromaDB")
            
            return {
                "success": True,
                "message": f"Successfully added {len(documents)} documents",
                "documents_added": len(documents),
                "collection_size": self.collection.count()
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error adding documents: {str(e)}",
                "documents_added": 0
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check vector database health (in-memory implementation)
        
        Returns:
            Dict containing health status
        """
        return {
            "status": "healthy",
            "database": "in-memory_vector_db",
            "connected": self.is_connected,
            "entries_count": len(self.text_entries),
            "collection": self.collection_name,
            "timestamp": datetime.now().isoformat()
        }


# Convenience function for direct search
async def search_vector_db(query: str, limit: int = 50) -> Dict[str, Any]:
    """
    Convenience function to search vector database
    
    Args:
        query: Search query string
        limit: Maximum number of results
        
    Returns:
        Dict containing search results
    """
    tool = VectorSearchTool()
    await tool.connect()
    return await tool.search(query, limit)


# Example usage and testing
if __name__ == "__main__":
    async def test_vector_search():
        """Test the Vector Search Tool"""
        tool = VectorSearchTool()
        
        # Test connection
        connected = await tool.connect()
        print(f"Connected: {connected}")
        
        # Test health check
        health = await tool.health_check()
        print(f"Health: {health}")
        
        # Test search with various similarity scenarios
        test_queries = [
            "machine learning",           # Should match ML documents
            "neural networks",           # Should match deep learning
            "python programming",        # Should match Python guide
            "data science workflow",     # Should match data science
            "computer vision",           # Should match CV document
            "artificial intelligence"    # Should match multiple documents
        ]
        
        for query in test_queries:
            print(f"\nSearching for: {query}")
            results = await tool.search(query, limit=3)
            print(f"Found {results['total_found']} results")
            for i, doc in enumerate(results['results'], 1):
                print(f"  {i}. {doc['title']} (score: {doc['similarity_score']})")
    
    # Run the test
    asyncio.run(test_vector_search())
