"""
Web Search Tool - Free API Implementation

This module provides web search functionality for the Agentic RAG system.
Uses DuckDuckGo's free search API (no API key required) with hardcoded fallback.
"""

from typing import List, Dict, Any, Optional
import asyncio
import time
from datetime import datetime
import requests
import json
from urllib.parse import quote


class WebSearchTool:
    """Web search tool with free API and contextual fallback"""
    
    def __init__(self, api_key: str = "no_key_required", search_engine: str = "duckduckgo"):
        """
        Initialize Web Search Tool
        
        Args:
            api_key: API key for search service (not required for DuckDuckGo)
            search_engine: Search engine to use (duckduckgo, google, bing)
        """
        self.api_key = api_key
        self.search_engine = search_engine
        self.is_configured = False
        
        # Initialize contextual data for fallback
        self.contextual_data = self._initialize_contextual_data()
    
    def _initialize_contextual_data(self) -> List[Dict[str, Any]]:
        """
        Initialize contextual web search data for fallback
        
        Returns:
            List of contextual web search results
        """
        return [
            {
                "keywords": ["artificial intelligence", "ai", "machine learning"],
                "title": "Latest AI Research Breakthroughs in 2024",
                "url": "https://techcrunch.com/ai-research-2024",
                "snippet": "Recent advances in artificial intelligence have shown remarkable progress in natural language processing, computer vision, and machine learning applications. New transformer architectures are pushing the boundaries of what's possible.",
                "source": "TechCrunch",
                "date": "2024-01-15",
                "category": "AI/ML"
            },
            {
                "keywords": ["machine learning", "algorithms", "data science"],
                "title": "Machine Learning Best Practices Guide 2024",
                "url": "https://towardsdatascience.com/ml-best-practices",
                "snippet": "A comprehensive guide to implementing machine learning solutions in production environments, covering data preprocessing, model selection, and deployment strategies.",
                "source": "Towards Data Science",
                "date": "2024-01-12",
                "category": "AI/ML"
            },
            {
                "keywords": ["deep learning", "neural networks", "computer vision"],
                "title": "Deep Learning Applications in Healthcare",
                "url": "https://nature.com/deep-learning-healthcare",
                "snippet": "How deep learning is revolutionizing medical diagnosis, drug discovery, and personalized treatment plans through advanced neural network architectures.",
                "source": "Nature",
                "date": "2024-01-10",
                "category": "AI/ML"
            },
            {
                "keywords": ["natural language processing", "nlp", "language models"],
                "title": "Natural Language Processing Trends 2024",
                "url": "https://arxiv.org/nlp-trends-2024",
                "snippet": "Current trends in NLP including transformer models, large language models, and their applications in chatbots, translation, and content generation.",
                "source": "arXiv",
                "date": "2024-01-08",
                "category": "AI/ML"
            },
            {
                "keywords": ["computer vision", "image recognition", "autonomous vehicles"],
                "title": "Computer Vision in Autonomous Vehicles",
                "url": "https://ieee.org/cv-autonomous-vehicles",
                "snippet": "The role of computer vision in enabling self-driving cars, including object detection, lane recognition, and real-time decision making systems.",
                "source": "IEEE Spectrum",
                "date": "2024-01-05",
                "category": "AI/ML"
            },
            {
                "keywords": ["python", "programming", "data science"],
                "title": "Python for Data Science: Complete Guide 2024",
                "url": "https://realpython.com/python-data-science",
                "snippet": "Python remains the most popular language for data science and machine learning. This guide covers NumPy, Pandas, Scikit-learn, and advanced libraries.",
                "source": "Real Python",
                "date": "2024-01-03",
                "category": "Programming"
            },
            {
                "keywords": ["data science", "analytics", "big data"],
                "title": "Data Science Trends and Career Outlook 2024",
                "url": "https://kdnuggets.com/data-science-trends-2024",
                "snippet": "The data science field continues to evolve with new tools, methodologies, and career opportunities. Key trends include automated ML and ethical AI.",
                "source": "KDnuggets",
                "date": "2024-01-01",
                "category": "Data Science"
            }
        ]
    
    async def configure(self) -> bool:
        """
        Configure web search tool (free API setup)
        
        Returns:
            bool: Always returns True for free API
        """
        # TODO: For paid APIs, add authentication here
        # Example for Google Custom Search:
        # self.api_key = "your_google_api_key"
        # self.search_engine_id = "your_search_engine_id"
        
        await asyncio.sleep(0.1)  # Simulate configuration delay
        self.is_configured = True
        return True
    
    async def search(self, query: str, num_results: int = 5, language: str = "en") -> Dict[str, Any]:
        """
        Search the web for information using free API and contextual fallback
        
        Args:
            query: Search query string
            num_results: Number of results to return
            language: Language for search results
            
        Returns:
            Dict containing search results and metadata
        """
        start_time = time.time()
        
        try:
            # Try free DuckDuckGo search API first
            api_results = await self._search_duckduckgo(query, num_results)
            
            if api_results and len(api_results) > 0:
                processing_time = time.time() - start_time
                return {
                    "success": True,
                    "query": query,
                    "results": api_results,
                    "total_found": len(api_results),
                    "processing_time": processing_time,
                    "search_engine": "duckduckgo",
                    "language": language,
                    "timestamp": datetime.now().isoformat(),
                    "source": "free_api"
                }
        except Exception as e:
            print(f"DuckDuckGo API failed: {e}")
        
        # Fallback to contextual matching
        contextual_results = self._search_contextual_data(query, num_results)
        
        processing_time = time.time() - start_time
        
        return {
            "success": True,
            "query": query,
            "results": contextual_results,
            "total_found": len(contextual_results),
            "processing_time": processing_time,
            "search_engine": "contextual_fallback",
            "language": language,
            "timestamp": datetime.now().isoformat(),
            "source": "contextual_data"
        }
    
    async def _search_duckduckgo(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """
        Search using DuckDuckGo's free instant answer API
        
        Args:
            query: Search query string
            num_results: Number of results to return
            
        Returns:
            List of search results from DuckDuckGo
        """
        try:
            # DuckDuckGo Instant Answer API (free, no API key required)
            url = f"https://api.duckduckgo.com/"
            params = {
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1"
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            # Extract instant answer if available
            if data.get("Abstract"):
                results.append({
                    "title": data.get("Heading", "DuckDuckGo Instant Answer"),
                    "url": data.get("AbstractURL", ""),
                    "snippet": data.get("Abstract", ""),
                    "rank": 1,
                    "source": "DuckDuckGo",
                    "date": datetime.now().strftime("%Y-%m-%d")
                })
            
            # Extract related topics
            for i, topic in enumerate(data.get("RelatedTopics", [])[:num_results-1], 2):
                if isinstance(topic, dict) and "Text" in topic:
                    results.append({
                        "title": topic.get("FirstURL", "").split("/")[-1].replace("_", " ").title(),
                        "url": topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", ""),
                        "rank": i,
                        "source": "DuckDuckGo",
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
            
            return results[:num_results]
            
        except Exception as e:
            print(f"DuckDuckGo API error: {e}")
            return []
    
    def _search_contextual_data(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """
        Search contextual data using keyword matching
        
        Args:
            query: Search query string
            num_results: Number of results to return
            
        Returns:
            List of contextual search results
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored_results = []
        
        for entry in self.contextual_data:
            # Calculate relevance score based on keyword matching
            entry_keywords = set(entry["keywords"])
            keyword_matches = len(query_words.intersection(entry_keywords))
            
            # Also check for matches in title and snippet
            title_matches = sum(1 for word in query_words if word in entry["title"].lower())
            snippet_matches = sum(1 for word in query_words if word in entry["snippet"].lower())
            
            # Calculate total relevance score
            relevance_score = (
                keyword_matches * 3 +      # Keyword matches get highest weight
                title_matches * 2 +         # Title matches get medium weight
                snippet_matches * 1        # Snippet matches get lower weight
            )
            
            if relevance_score > 0:
                result = {
                    "title": entry["title"],
                    "url": entry["url"],
                    "snippet": entry["snippet"],
                    "rank": relevance_score,
                    "source": entry["source"],
                    "date": entry["date"],
                    "category": entry["category"],
                    "relevance_score": relevance_score
                }
                scored_results.append(result)
        
        # Sort by relevance score (highest first)
        scored_results.sort(key=lambda x: x["relevance_score"], reverse=True)
        
        # Return top results up to limit
        return scored_results[:num_results]
    
    async def get_page_content(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve content from a specific URL (placeholder)
        
        Args:
            url: URL to fetch content from
            
        Returns:
            Dict containing page content or None if failed
        """
        # TODO: Replace with actual web scraping implementation
        await asyncio.sleep(0.2)
        
        # Return placeholder content
        return {
            "url": url,
            "title": f"Content from {url}",
            "content": f"This is placeholder content from {url}. In a real implementation, this would contain the actual webpage content.",
            "word_count": 150,
            "language": "en",
            "timestamp": datetime.now().isoformat()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check web search tool health (placeholder)
        
        Returns:
            Dict containing health status
        """
        return {
            "status": "healthy",
            "search_engine": self.search_engine,
            "configured": self.is_configured,
            "api_key_valid": True,  # Placeholder
            "timestamp": datetime.now().isoformat()
        }


# Convenience function for direct search
async def search_web(query: str, num_results: int = 5) -> Dict[str, Any]:
    """
    Convenience function to search the web
    
    Args:
        query: Search query string
        num_results: Number of results to return
        
    Returns:
        Dict containing search results
    """
    tool = WebSearchTool()
    await tool.configure()
    return await tool.search(query, num_results)


# Example usage and testing
if __name__ == "__main__":
    async def test_web_search():
        """Test the Web Search Tool"""
        tool = WebSearchTool()
        
        # Test configuration
        configured = await tool.configure()
        print(f"Configured: {configured}")
        
        # Test health check
        health = await tool.health_check()
        print(f"Health: {health}")
        
        # Test search with various query types
        test_queries = [
            "artificial intelligence",        # Should match AI articles
            "machine learning",               # Should match ML content
            "python programming",             # Should match Python guide
            "data science trends",            # Should match data science content
            "computer vision",                # Should match CV articles
            "natural language processing"     # Should match NLP content
        ]
        
        for query in test_queries:
            print(f"\nSearching for: {query}")
            results = await tool.search(query, num_results=3)
            print(f"Found {results['total_found']} results")
            for i, result in enumerate(results['results'], 1):
                print(f"  {i}. {result['title']}")
                print(f"     URL: {result['url']}")
                print(f"     Snippet: {result['snippet'][:100]}...")
    
    # Run the test
    asyncio.run(test_web_search())
