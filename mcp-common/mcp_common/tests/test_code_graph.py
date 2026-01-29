import pytest
from mcp_common.code_graph import CodeGraphAnalyzer
from pathlib import Path


@pytest.mark.asyncio
async def test_analyze_simple_repository(tmp_path):
    """Test analyzing a simple Python repository"""
    # Create test files
    (tmp_path / "test.py").write_text("""
def hello():
    print("Hello, world!")
""")

    analyzer = CodeGraphAnalyzer(tmp_path)
    stats = await analyzer.analyze_repository(str(tmp_path))

    assert stats["files_indexed"] == 1
    assert stats["functions_indexed"] == 1
