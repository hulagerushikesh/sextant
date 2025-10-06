/**
 * API Client for communicating with MCP Client
 * Handles HTTP requests to the MCP Client service
 */

const API_BASE_URL = 'http://localhost:5001'; // MCP Client will run on port 5001

/**
 * Send a query to the MCP Client
 * @param {string} query - The user's query string
 * @returns {Promise<Object>} Response from MCP Client
 */
export const sendQuery = async (query) => {
  try {
    const response = await fetch(`${API_BASE_URL}/query`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query: query,
        timestamp: new Date().toISOString(),
        client_id: 'frontend_ui'
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error sending query to MCP Client:', error);
    throw error;
  }
};

/**
 * Check if MCP Client is available
 * @returns {Promise<boolean>} True if client is healthy
 */
export const checkClientHealth = async () => {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);
    return response.ok;
  } catch (error) {
    console.error('MCP Client health check failed:', error);
    return false;
  }
};
