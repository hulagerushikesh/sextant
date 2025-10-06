"""
Simple Web Search Tool
Performs real web search through DuckDuckGo and returns formatted results
"""

import asyncio
import time
import requests
from datetime import datetime
from typing import Dict, List, Any
from bs4 import BeautifulSoup


class WebSearchTool:
    """
    Simple web search tool that performs real web searches
    """
    
    def __init__(self):
        """Initialize the web search tool"""
        self.is_configured = True
    
    async def configure(self) -> bool:
        """Configure web search tool"""
        await asyncio.sleep(0.1)
        self.is_configured = True
        return True
    
    async def search(self, query: str, num_results: int = 5, language: str = "en") -> Dict[str, Any]:
        """
        Perform real web search and return results
        
        Args:
            query: Search query string
            num_results: Number of results to return
            language: Language for search results
            
        Returns:
            Dict containing search results and metadata
        """
        start_time = time.time()
        
        try:
            # Perform real web search
            results = await self._search_duckduckgo_html(query, num_results)
            
            processing_time = time.time() - start_time
            
            return {
                "success": True,
                "query": query,
                "results": results,
                "total_found": len(results),
                "processing_time": processing_time,
                "search_engine": "DuckDuckGo",
                "language": language,
                "timestamp": datetime.now().isoformat(),
                "source": "real_web_search"
            }
            
        except Exception as e:
            processing_time = time.time() - start_time
            return {
                "success": False,
                "query": query,
                "results": [],
                "total_found": 0,
                "processing_time": processing_time,
                "search_engine": "DuckDuckGo",
                "language": language,
                "timestamp": datetime.now().isoformat(),
                "source": "search_failed",
                "error": str(e)
            }
    
    async def _search_duckduckgo_html(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """
        Search using DuckDuckGo HTML (more reliable than API)
        
        Args:
            query: Search query string
            num_results: Number of results to return
            
        Returns:
            List of search results
        """
        try:
            # Use DuckDuckGo HTML search
            search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(search_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Parse HTML results
            soup = BeautifulSoup(response.text, 'html.parser')
            results = []
            
            # Debug: Print the HTML structure
            print(f"DEBUG: Found {len(soup.find_all('div', class_='result'))} result containers")
            
            # Find search result containers
            result_containers = soup.find_all('div', class_='result')
            
            for i, container in enumerate(result_containers[:num_results]):
                # Find title and URL
                title_link = container.find('a', class_='result__a')
                if not title_link:
                    print(f"DEBUG: No title link found in container {i}")
                    continue
                    
                title = title_link.get_text().strip()
                url = title_link.get('href', '')
                
                # Find snippet - try different selectors
                snippet = ""
                
                # Try multiple snippet selectors
                snippet_selectors = [
                    'a.result__snippet',
                    'div.result__snippet', 
                    'span.result__snippet',
                    '.result__snippet',
                    'a[class*="snippet"]',
                    'div[class*="snippet"]'
                ]
                
                for selector in snippet_selectors:
                    snippet_elem = container.select_one(selector)
                    if snippet_elem:
                        snippet = snippet_elem.get_text().strip()
                        print(f"DEBUG: Found snippet with selector {selector}: {snippet[:50]}...")
                        break
                
                # If still no snippet, get any text from the container
                if not snippet:
                    all_text = container.get_text().strip()
                    # Remove the title from the text to get snippet
                    snippet = all_text.replace(title, '').strip()
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "..."
                    print(f"DEBUG: Using fallback snippet: {snippet[:50]}...")
                
                if not snippet:
                    snippet = f"Information about: {title}"
                
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "rank": i + 1,
                    "source": "DuckDuckGo",
                    "date": datetime.now().strftime("%Y-%m-%d")
                })
            
            print(f"DEBUG: Returning {len(results)} results")
            return results
            
        except Exception as e:
            print(f"DuckDuckGo search error: {e}")
            return []