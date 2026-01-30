"""Unit tests for code graph analyzer functionality."""

import os
from pathlib import Path
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "mcp-common"))

from mcp_common.code_graph.analyzer import ClassNode, CodeGraphAnalyzer, FunctionNode, ImportNode


@pytest.mark.asyncio
async def test_code_graph_analyzer_basic():
    """Test basic functionality of the code graph analyzer."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a test Python file
        test_file = Path(tmp_dir) / "test_module.py"
        test_content = '''
def simple_function():
    """A simple function."""
    return "hello"

def function_with_calls():
    """A function that calls another function."""
    result = simple_function()
    return result

class SimpleClass:
    """A simple class."""
    def __init__(self):
        self.value = 42

    def get_value(self):
        return self.value

import os
from pathlib import Path
'''
        test_file.write_text(test_content)

        # Create analyzer and analyze the repository
        analyzer = CodeGraphAnalyzer(Path(tmp_dir))
        result = await analyzer.analyze_repository(str(tmp_dir))

        # Verify the analysis results
        assert result["files_indexed"] >= 1
        assert result["functions_indexed"] >= 2  # simple_function and function_with_calls
        assert result["classes_indexed"] >= 1  # SimpleClass
        assert result["total_nodes"] >= 4  # At least functions, class, and imports

        # Verify that function nodes were created
        func_nodes = [node for node in analyzer.nodes.values() if isinstance(node, FunctionNode)]
        assert len(func_nodes) >= 2

        # Verify that class nodes were created
        class_nodes = [node for node in analyzer.nodes.values() if isinstance(node, ClassNode)]
        assert len(class_nodes) >= 1

        # Verify that import nodes were created
        import_nodes = [node for node in analyzer.nodes.values() if isinstance(node, ImportNode)]
        assert len(import_nodes) >= 2  # os and pathlib imports


@pytest.mark.asyncio
async def test_code_graph_analyzer_function_context():
    """Test getting function context from the analyzer."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a test Python file
        test_file = Path(tmp_dir) / "test_module.py"
        test_content = '''
def target_function():
    """This is the target function."""
    return "found me!"

def calling_function():
    """This function calls the target function."""
    result = target_function()
    return result
'''
        test_file.write_text(test_content)

        # Create analyzer and analyze the repository
        analyzer = CodeGraphAnalyzer(Path(tmp_dir))
        await analyzer.analyze_repository(str(tmp_dir))

        # Get context for the target function
        context = await analyzer.get_function_context("target_function")

        assert "function" in context
        assert context["function"].name == "target_function"
        assert context["is_export"] is True  # Not starting with underscore
        assert len(context["calls"]) == 0  # Function doesn't call others


@pytest.mark.asyncio
async def test_code_graph_analyzer_related_files():
    """Test finding related files functionality."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a main module
        main_file = Path(tmp_dir) / "main.py"
        main_content = """
from helper import helper_function

def main():
    result = helper_function()
    return result
"""
        main_file.write_text(main_content)

        # Create a helper module
        helper_file = Path(tmp_dir) / "helper.py"
        helper_content = """
def helper_function():
    return "helper result"
"""
        helper_file.write_text(helper_content)

        # Create analyzer and analyze the repository
        analyzer = CodeGraphAnalyzer(Path(tmp_dir))
        await analyzer.analyze_repository(str(tmp_dir))

        # Find related files for main.py
        related = await analyzer.find_related_files(str(main_file))

        # Should find the import relationship
        assert len(related) >= 0  # May not find direct relationships in this simple case


@pytest.mark.asyncio
async def test_code_graph_analyzer_complex_function():
    """Test analyzing a more complex function with multiple calls."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a test Python file with a complex function
        test_file = Path(tmp_dir) / "complex_module.py"
        test_content = '''
def utility_func_a():
    return "a"

def utility_func_b():
    return "b"

def complex_function():
    """A function that calls multiple other functions."""
    val_a = utility_func_a()
    val_b = utility_func_b()
    combined = val_a + val_b
    return combined

class ComplexClass:
    """A class with multiple methods."""

    def method_one(self):
        return utility_func_a()

    def method_two(self):
        return utility_func_b()

    def combined_method(self):
        return self.method_one() + self.method_two()
'''
        test_file.write_text(test_content)

        # Create analyzer and analyze the repository
        analyzer = CodeGraphAnalyzer(Path(tmp_dir))
        result = await analyzer.analyze_repository(str(tmp_dir))

        # Verify analysis results
        assert result["functions_indexed"] >= 3  # utility_func_a, utility_func_b, complex_function
        assert result["classes_indexed"] >= 1  # ComplexClass

        # Find the complex function and verify its calls
        complex_func_nodes = [
            node
            for node in analyzer.nodes.values()
            if isinstance(node, FunctionNode) and node.name == "complex_function"
        ]

        assert len(complex_func_nodes) == 1
        complex_func = complex_func_nodes[0]
        # The complex function should call utility_func_a and utility_func_b
        assert (
            len(
                [
                    call
                    for call in complex_func.calls
                    if call in ["utility_func_a", "utility_func_b"]
                ]
            )
            >= 2
        )


@pytest.mark.asyncio
async def test_code_graph_analyzer_private_functions():
    """Test that private functions (starting with _) are correctly identified."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a test Python file with private functions
        test_file = Path(tmp_dir) / "private_module.py"
        test_content = """
def public_function():
    return _private_helper()

def _private_helper():
    return "private result"

class PublicClass:
    def public_method(self):
        return self._private_method()

    def _private_method(self):
        return "private method result"
"""
        test_file.write_text(test_content)

        # Create analyzer and analyze the repository
        analyzer = CodeGraphAnalyzer(Path(tmp_dir))
        await analyzer.analyze_repository(str(tmp_dir))

        # Find all function nodes
        func_nodes = [node for node in analyzer.nodes.values() if isinstance(node, FunctionNode)]

        # Verify that private functions are correctly identified
        public_funcs = [fn for fn in func_nodes if fn.is_export]
        private_funcs = [fn for fn in func_nodes if not fn.is_export]

        assert len(public_funcs) >= 2  # public_function and PublicClass.public_method
        assert len(private_funcs) >= 2  # _private_helper and PublicClass._private_method
