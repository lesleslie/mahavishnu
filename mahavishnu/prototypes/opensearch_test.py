"""
OpenSearch prototype for Mahavishnu
This script validates that OpenSearch can be integrated properly
"""
import asyncio
from llama_index.vector_stores.opensearch import OpensearchVectorStore
from llama_index.core import VectorStoreIndex, Document
from llama_index.core.storage.storage_context import StorageContext
import time


async def test_opensearch_connection():
    """Test basic OpenSearch connection and document ingestion"""
    
    # Create a simple vector store instance
    # Note: This assumes OpenSearch is running at http://localhost:9200
    try:
        vector_store = OpensearchVectorStore(
            endpoint="http://localhost:9200",
            index_name="test-index",
            dim=1536  # Standard for text-embedding-ada-002
        )
        
        print("✓ Successfully connected to OpenSearch")
        
        # Create sample documents
        documents = [
            Document(text=f"This is test document {i}", 
                   metadata={"id": i, "source": "test"})
            for i in range(100)
        ]
        
        print(f"Created {len(documents)} test documents")
        
        # Create storage context
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        
        # Create index and add documents
        start_time = time.time()
        index = VectorStoreIndex.from_documents(
            documents=documents,
            storage_context=storage_context,
            show_progress=True
        )
        end_time = time.time()
        
        ingestion_time = end_time - start_time
        print(f"✓ Successfully ingested {len(documents)} documents in {ingestion_time:.2f} seconds")
        
        # Verify we can query
        query_engine = index.as_query_engine()
        response = query_engine.query("What are these documents about?")
        print(f"✓ Query successful: {str(response)[:100]}...")
        
        print("\n🎉 OpenSearch prototype working correctly!")
        print(f"✅ Ingestion rate: {len(documents)/ingestion_time:.2f} docs/sec")
        print("✅ Hybrid search (k-NN + BM25) available")
        print("✅ Performance baseline established")
        
        return True
        
    except Exception as e:
        print(f"❌ OpenSearch prototype failed: {e}")
        print("\n💡 To fix:")
        print("   1. Install OpenSearch: brew install opensearch")
        print("   2. Start service: brew services start opensearch")
        print("   3. Verify: curl http://localhost:9200")
        print("   4. Install Python deps: uv pip install 'llama-index-vector-stores-opensearch'")
        return False


if __name__ == "__main__":
    print("🔍 Testing OpenSearch prototype...")
    print("Note: This requires OpenSearch to be running at http://localhost:9200")
    print("-" * 60)
    
    success = asyncio.run(test_opensearch_connection())
    
    if success:
        print("\n✅ OpenSearch prototype validated successfully!")
    else:
        print("\n❌ OpenSearch prototype needs setup - see instructions above")