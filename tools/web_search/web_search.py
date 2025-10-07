import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List
import requests
import os

class WebSearchTool:
    """
    Professional web search tool using official APIs.
    Supports SerpAPI, Brave Search API, and Exa for clean, reliable results.
    """

    def __init__(self):
        self.is_configured = False
        self.api_priority = ['brave', 'serpapi', 'exa']

    async def configure(self) -> bool:
        await asyncio.sleep(0.1)
        self.is_configured = True
        return True

    async def search(self, query: str, num_results: int = 5, language: str = "en") -> Dict[str, Any]:
        start_time = time.time()
        try:
            results = await self._search_with_apis(query, num_results)
            formatted_results = self._format_results(results)
            
            return {
                "success": True,
                "formatted_results": formatted_results,
                "results": results,
                "total_results": len(results),
                "query": query,
                "search_time": time.time() - start_time,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "formatted_results": "An error occurred while searching.",
                "results": [],
                "total_results": 0,
                "query": query,
                "search_time": time.time() - start_time,
                "timestamp": datetime.now().isoformat()
            }

    async def _search_with_apis(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Try multiple search APIs in priority order."""
        for api_name in self.api_priority:
            try:
                if api_name == 'brave':
                    results = await self._search_brave_api(query, num_results)
                    if results:
                        return results
                elif api_name == 'serpapi':
                    results = await self._search_serpapi(query, num_results)
                    if results:
                        return results
                elif api_name == 'exa':
                    results = await self._search_exa_api(query, num_results)
                    if results:
                        return results
            except Exception as e:
                print(f"DEBUG: {api_name} API error: {e}")
                continue
        
        # If no APIs work, return empty results
        return []
    
    async def _search_brave_api(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Search using Brave Search API."""
        brave_api_key = os.getenv('BRAVE_API_KEY')
        if not brave_api_key:
            return []
            
        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": brave_api_key
            }
            params = {
                "q": query,
                "count": num_results,
                "safesearch": "moderate",
                "freshness": "all"
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            if 'web' in data and 'results' in data['web']:
                for item in data['web']['results']:
                    results.append({
                        "title": item.get('title', ''),
                        "url": item.get('url', ''),
                        "snippet": self._clean_snippet(item.get('description', '')),
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
            
            return results
            
        except Exception as e:
            print(f"DEBUG: Brave API error: {e}")
            return []
    
    async def _search_serpapi(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Search using SerpAPI."""
        serpapi_key = os.getenv('SERPAPI_KEY')
        if not serpapi_key:
            return []
            
        try:
            url = "https://serpapi.com/search"
            params = {
                "q": query,
                "api_key": serpapi_key,
                "num": num_results,
                "safe": "active"
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            if 'organic_results' in data:
                for item in data['organic_results']:
                    results.append({
                        "title": item.get('title', ''),
                        "url": item.get('link', ''),
                        "snippet": self._clean_snippet(item.get('snippet', '')),
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
            
            return results
            
        except Exception as e:
            print(f"DEBUG: SerpAPI error: {e}")
            return []
    
    async def _search_exa_api(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Search using Exa API."""
        exa_api_key = os.getenv('EXA_API_KEY')
        if not exa_api_key:
            return []
            
        try:
            url = "https://api.exa.ai/search"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": exa_api_key
            }
            data = {
                "query": query,
                "numResults": num_results,
                "type": "search"
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            if 'results' in data:
                for item in data['results']:
                    results.append({
                        "title": item.get('title', ''),
                        "url": item.get('url', ''),
                        "snippet": self._clean_snippet(item.get('text', '')),
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
            
            return results
            
        except Exception as e:
            print(f"DEBUG: Exa API error: {e}")
            return []

    def _clean_snippet(self, snippet: str) -> str:
        # Remove HTML tags, URLs and typical ad/SEO noise, truncate at nice sentence boundary
        import re
        
        # Remove HTML tags
        snippet = re.sub(r'<[^>]+>', '', snippet)
        
        # Remove URLs
        snippet = re.sub(r'https?://\S+', '', snippet)
        snippet = re.sub(r'www\.\S+', '', snippet)
        
        # Clean up whitespace
        snippet = ' '.join(snippet.split())
        
        # Remove common noise patterns
        snippet = re.sub(r'\s+', ' ', snippet)
        snippet = re.sub(r'\.{2,}', '.', snippet)
        
        # Don't truncate - return full snippet
        
        return snippet.strip()

    def _format_results(self, results: List[Dict[str, Any]]) -> str:
        """Format search results as a clean, comprehensive answer."""
        if not results:
            return "No relevant web results found for your query. Please try rephrasing or making your question more specific."
        
        # Clean and combine snippets into a comprehensive answer
        combined_info = []
        
        for result in results:
            snippet = result.get('snippet', 'No description available')
            
            # Clean the snippet
            snippet = self._clean_snippet(snippet)
            if snippet and len(snippet) > 20:  # Only use substantial snippets
                combined_info.append(snippet)
        
        if not combined_info:
            return "No relevant web results found for your query. Please try rephrasing or making your question more specific."
        
        # Combine all information into one coherent answer
        all_text = " ".join(combined_info)
        
        # Clean up the combined text
        all_text = self._clean_snippet(all_text)
        
        # Return the full text without truncation
        return all_text.strip()
