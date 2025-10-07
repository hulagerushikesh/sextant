import React, { useState } from 'react'
import './App.css'
import { sendQuery } from './api/client'

function App() {
  const [query, setQuery] = useState('')
  const [response, setResponse] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [documents, setDocuments] = useState([])
  const [isUploading, setIsUploading] = useState(false)
  const [uploadMessage, setUploadMessage] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    
    setIsLoading(true)
    setResponse('') // Clear previous response
    
    try {
      // Send query to MCP Client
      const result = await sendQuery(query)
      
      if (result.success) {
        setResponse(result.response)
      } else {
        setResponse(`Error: ${result.error || 'Unknown error occurred'}`)
      }
    } catch (error) {
      console.error('Query failed:', error)
      setResponse(`Connection error: ${error.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleDocumentUpload = async (e) => {
    e.preventDefault()
    if (documents.length === 0) return
    
    setIsUploading(true)
    setUploadMessage('')
    
    try {
      const response = await fetch('http://localhost:8000/ingest', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          documents: documents,
          client_id: 'frontend_ui'
        })
      })
      
      const result = await response.json()
      
      if (result.success) {
        setUploadMessage(`Successfully uploaded ${result.documents_added} documents. Collection now has ${result.collection_size} documents.`)
        setDocuments([]) // Clear the form
      } else {
        setUploadMessage(`Upload failed: ${result.error || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Document upload failed:', error)
      setUploadMessage(`Upload error: ${error.message}`)
    } finally {
      setIsUploading(false)
    }
  }

  const addDocument = () => {
    const title = prompt('Enter document title:')
    const content = prompt('Enter document content:')
    const source = prompt('Enter document source (optional):') || 'manual_upload'
    
    console.log('Adding document:', { title, content, source })
    console.log('Current documents count:', documents.length)
    
    if (title && content) {
      const newDocument = {
        id: `doc_${Date.now()}`,
        title: title,
        content: content,
        source: source,
        page: 1,
        category: 'user_upload'
      }
      console.log('New document:', newDocument)
      setDocuments([...documents, newDocument])
      console.log('Documents after add:', [...documents, newDocument])
    } else {
      console.log('Document not added - missing title or content')
    }
  }

  const removeDocument = (index) => {
    setDocuments(documents.filter((_, i) => i !== index))
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Agentic RAG Query Interface</h1>
        <p>Ask questions and get intelligent responses powered by MCP architecture</p>
      </header>
      
      <main className="app-main">
        <form onSubmit={handleSubmit} className="query-form">
          <div className="input-group">
            <label htmlFor="query">Your Question:</label>
            <textarea
              id="query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Enter your question here..."
              rows={4}
              disabled={isLoading}
            />
          </div>
          
          <button 
            type="submit" 
            disabled={!query.trim() || isLoading}
            className="submit-button"
          >
            {isLoading ? 'Processing...' : 'Submit Query'}
          </button>
        </form>

        <div className="response-section">
          <h2>Response</h2>
          <div className="response-area">
            {isLoading ? (
              <div className="loading">Loading response...</div>
            ) : response ? (
              <div className="response-content">{response}</div>
            ) : (
              <div className="placeholder">
                Submit a query to see the response here
              </div>
            )}
          </div>
        </div>

        <div className="document-section">
          <h2>Document Management</h2>
          <div className="document-upload">
            <div className="document-list">
              <div style={{ marginBottom: '10px', fontSize: '12px', color: '#666' }}>
                Debug: {documents.length} documents in state
              </div>
              {documents.map((doc, index) => (
                <div key={index} className="document-item">
                  <div className="document-info">
                    <strong>{doc.title}</strong>
                    <span className="document-source">Source: {doc.source}</span>
                  </div>
                  <button 
                    onClick={() => removeDocument(index)}
                    className="remove-button"
                  >
                    Remove
                  </button>
                </div>
              ))}
              {documents.length === 0 && (
                <div style={{ color: '#999', fontStyle: 'italic' }}>
                  No documents added yet. Click "Add Document" to get started.
                </div>
              )}
            </div>
            
            <div className="document-actions">
              <button onClick={addDocument} className="add-document-button">
                Add Document
              </button>
              
              <button 
                onClick={handleDocumentUpload}
                disabled={documents.length === 0 || isUploading}
                className="upload-button"
                style={{ 
                  backgroundColor: documents.length === 0 ? '#ccc' : '#007bff',
                  cursor: documents.length === 0 ? 'not-allowed' : 'pointer'
                }}
              >
                {isUploading ? 'Uploading...' : `Upload ${documents.length} Documents`}
              </button>
            </div>
            
            {uploadMessage && (
              <div className={`upload-message ${uploadMessage.includes('Successfully') ? 'success' : 'error'}`}>
                {uploadMessage}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}

export default App
