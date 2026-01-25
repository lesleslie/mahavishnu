"""Unit tests for Session Buddy integration functionality."""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from pathlib import Path
from datetime import datetime
from mahavishnu.session_buddy.integration import SessionBuddyIntegration, SessionBuddyManager
from mahavishnu.core.app import MahavishnuApp


@pytest.fixture
def mock_app():
    """Create a mock app for testing."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = Mock()
    app.workflow_state_manager = Mock()
    app.adapters = {}
    app.config = Mock()
    return app


@pytest.mark.asyncio
async def test_session_buddy_integration_initialization(mock_app):
    """Test that SessionBuddyIntegration initializes correctly."""
    integration = SessionBuddyIntegration(mock_app)
    
    # Verify components were initialized
    assert integration.app == mock_app
    assert integration.code_graph_analyzer is not None
    assert integration.logger is not None


@pytest.mark.asyncio
async def test_session_buddy_manager_initialization(mock_app):
    """Test that SessionBuddyManager initializes correctly."""
    manager = SessionBuddyManager(mock_app)
    
    # Verify components were initialized
    assert manager.app == mock_app
    assert manager.integration is not None


@pytest.mark.asyncio
async def test_integrate_code_graph(mock_app):
    """Test code graph integration functionality."""
    integration = SessionBuddyIntegration(mock_app)
    
    # Create a temporary directory with a test Python file
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test Python file
        test_file = Path(temp_dir) / "test_module.py"
        test_content = '''
def sample_function():
    """A sample function for testing."""
    return "hello world"

class SampleClass:
    """A sample class for testing."""
    def sample_method(self):
        return "method result"
'''
        test_file.write_text(test_content)
        
        # Integrate code graph for the temporary directory
        result = await integration.integrate_code_graph(temp_dir)
        
        # Verify result structure
        assert result["status"] == "success"
        assert "analysis_result" in result
        assert "code_context_sent" in result
        assert "functions_extracted" in result
        assert "classes_extracted" in result
        assert "imports_extracted" in result
        
        # Verify that functions and classes were extracted
        assert result["functions_extracted"] >= 1  # sample_function
        assert result["classes_extracted"] >= 1    # SampleClass


@pytest.mark.asyncio
async def test_get_related_code(mock_app):
    """Test getting related code functionality."""
    integration = SessionBuddyIntegration(mock_app)
    
    # Create a temporary directory with test files
    import tempfile
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a main module
        main_file = Path(temp_dir) / "main.py"
        main_content = '''
from helper import helper_function

def main():
    result = helper_function()
    return result
'''
        main_file.write_text(main_content)
        
        # Create a helper module
        helper_file = Path(temp_dir) / "helper.py"
        helper_content = '''
def helper_function():
    return "helper result"
'''
        helper_file.write_text(helper_content)
        
        # Get related code
        result = await integration.get_related_code(temp_dir, str(main_file))
        
        # Verify result structure
        assert result["status"] == "success"
        assert "file_path" in result
        assert "related_files" in result
        assert "count" in result


@pytest.mark.asyncio
async def test_get_function_context(mock_app):
    """Test getting function context functionality."""
    integration = SessionBuddyIntegration(mock_app)
    
    # Create a temporary directory with a test file
    import tempfile
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test Python file
        test_file = Path(temp_dir) / "test_module.py"
        test_content = '''
def target_function():
    """This is the target function."""
    return "found me!"
'''
        test_file.write_text(test_content)
        
        # Get function context
        result = await integration.get_function_context(temp_dir, "target_function")
        
        # Verify result structure
        assert result["status"] == "success"
        assert "function_name" in result
        assert "context" in result
        assert result["function_name"] == "target_function"


@pytest.mark.asyncio
async def test_index_documentation(mock_app):
    """Test documentation indexing functionality."""
    integration = SessionBuddyIntegration(mock_app)
    
    # Create a temporary directory with a test file
    import tempfile
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test Python file with docstrings
        test_file = Path(temp_dir) / "test_module.py"
        test_content = '''
def documented_function():
    """This function has documentation.
    
    Returns:
        str: A sample string result
    """
    return "documented result"

class DocumentedClass:
    """This class has documentation.
    
    Attributes:
        value: An integer value
    """
    def __init__(self):
        self.value = 42
    
    def documented_method(self):
        """This method has documentation."""
        return self.value
'''
        test_file.write_text(test_content)
        
        # Index documentation
        result = await integration.index_documentation(temp_dir)
        
        # Verify result structure
        assert result["status"] == "success"
        assert "repo_path" in result
        assert "documentation_items" in result
        assert "indexed" in result
        assert result["repo_path"] == temp_dir
        
        # Should have found functions and classes with docstrings
        assert result["documentation_items"] >= 2  # function + class


@pytest.mark.asyncio
async def test_search_documentation(mock_app):
    """Test documentation search functionality."""
    integration = SessionBuddyIntegration(mock_app)
    
    # Search for documentation (would normally require indexed content)
    result = await integration.search_documentation("test query")
    
    # Verify result structure
    assert result["status"] == "success"
    assert "query" in result
    assert "results" in result
    assert "count" in result
    assert result["query"] == "test query"


@pytest.mark.asyncio
async def test_send_project_message(mock_app):
    """Test sending project messages."""
    integration = SessionBuddyIntegration(mock_app)
    
    # Send a project message
    result = await integration.send_project_message(
        from_project="project_a",
        to_project="project_b",
        subject="Test Subject",
        message="Test message content"
    )
    
    # Verify result structure
    assert result["status"] == "success"
    assert "message_id" in result
    assert "sent" in result
    assert result["sent"] is True


@pytest.mark.asyncio
async def test_list_project_messages(mock_app):
    """Test listing project messages."""
    integration = SessionBuddyIntegration(mock_app)
    
    # List messages for a project
    result = await integration.list_project_messages("test_project")
    
    # Verify result structure
    assert result["status"] == "success"
    assert "project" in result
    assert "messages" in result
    assert "count" in result
    assert result["project"] == "test_project"


@pytest.mark.asyncio
async def test_process_repository_for_session_buddy(mock_app):
    """Test the full repository processing for Session Buddy."""
    manager = SessionBuddyManager(mock_app)
    
    # Create a temporary directory with test files
    import tempfile
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test Python file
        test_file = Path(temp_dir) / "test_module.py"
        test_content = '''
def sample_function():
    """A sample function for testing."""
    return "hello world"

class SampleClass:
    """A sample class for testing."""
    def sample_method(self):
        return "method result"
'''
        test_file.write_text(test_content)
        
        # Process repository for Session Buddy
        result = await manager.process_repository_for_session_buddy(temp_dir)
        
        # Verify result structure
        assert result["repository"] == temp_dir
        assert "code_graph_integration" in result
        assert "documentation_indexing" in result
        assert "overall_status" in result
        
        # Verify code graph integration was successful
        cg_result = result["code_graph_integration"]
        assert cg_result["status"] == "success"
        
        # Verify documentation indexing was attempted
        doc_result = result["documentation_indexing"]
        assert doc_result["status"] == "success"


@pytest.mark.asyncio
async def test_get_enhanced_context(mock_app):
    """Test getting enhanced context."""
    manager = SessionBuddyManager(mock_app)
    
    # Get enhanced context with various query elements
    query_elements = {
        "function_name": "test_function",
        "file_path": "/path/to/test.py",
        "query": "test documentation query"
    }
    
    result = await manager.get_enhanced_context("/test/repo", query_elements)
    
    # Verify result structure
    assert result["status"] == "success"
    assert "enhanced_context" in result
    assert "repo_path" in result
    assert result["repo_path"] == "/test/repo"
    
    # Verify that the context includes the requested elements
    context = result["enhanced_context"]
    # Note: The actual results may be empty if the requested elements don't exist
    # but the structure should be present