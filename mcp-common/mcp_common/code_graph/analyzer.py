"""Shared code graph analyzer - used by Session Buddy and Mahavishnu"""
import ast
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
import asyncio


@dataclass
class CodeNode:
    """Base class for code nodes"""
    id: str
    name: str
    file_id: str
    node_type: str  # "file", "function", "class", "import"


@dataclass
class FunctionNode(CodeNode):
    """Function or method"""
    is_export: bool
    start_line: int
    end_line: int
    calls: list[str]
    lang: str = "python"


@dataclass
class ClassNode(CodeNode):
    """Class definition"""
    methods: list[str]
    inherits_from: list[str]


@dataclass
class ImportNode(CodeNode):
    """Import statement"""
    imported_from: str
    alias: Optional[str] = None


class CodeGraphAnalyzer:
    """Analyze and index codebase structure"""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.nodes: Dict[str, CodeNode] = {}
        self.file_to_nodes: Dict[str, List[str]] = {}

    async def analyze_repository(self, repo_path: str) -> dict:
        """Analyze repository and build code graph."""
        repo_path_obj = Path(repo_path)
        files_indexed = 0
        functions_indexed = 0
        classes_indexed = 0

        # Walk through all Python files in the repository
        for py_file in repo_path_obj.rglob("*.py"):
            if "/__pycache__/" in str(py_file) or str(py_file).endswith("__init__.py"):
                continue

            try:
                await self._analyze_file(py_file)
                files_indexed += 1
            except Exception as e:
                print(f"Error analyzing file {py_file}: {e}")

        # Count different node types
        for node_id, node in self.nodes.items():
            if isinstance(node, FunctionNode):
                functions_indexed += 1
            elif isinstance(node, ClassNode):
                classes_indexed += 1

        return {
            "files_indexed": files_indexed,
            "functions_indexed": functions_indexed,
            "classes_indexed": classes_indexed,
            "total_nodes": len(self.nodes)
        }

    async def _analyze_file(self, file_path: Path):
        """Analyze a single Python file and extract code graph information."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse the file with AST
            tree = ast.parse(content)

            # Create a file node
            file_node_id = f"file:{file_path}"
            file_node = CodeNode(
                id=file_node_id,
                name=file_path.name,
                file_id=str(file_path),
                node_type="file"
            )
            self.nodes[file_node_id] = file_node

            # Process all nodes in the AST
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    await self._process_function_def(node, file_path, content)
                elif isinstance(node, ast.AsyncFunctionDef):
                    await self._process_function_def(node, file_path, content)
                elif isinstance(node, ast.ClassDef):
                    await self._process_class_def(node, file_path, content)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    await self._process_import(node, file_path)

        except SyntaxError:
            # Skip files with syntax errors
            pass
        except Exception:
            # Skip any other problematic files
            pass

    async def _process_function_def(self, func_node: ast.AST, file_path: Path, content: str):
        """Process a function definition and add it to the graph."""
        func_name = func_node.name
        func_id = f"func:{file_path}:{func_name}:{func_node.lineno}"

        # Determine if function is exported (not private)
        is_export = not func_name.startswith('_')

        # Find function calls within the function
        calls = []
        for child_node in ast.walk(func_node):
            if isinstance(child_node, ast.Call):
                if isinstance(child_node.func, ast.Name):
                    calls.append(child_node.func.id)
                elif isinstance(child_node.func, ast.Attribute):
                    calls.append(child_node.func.attr)

        # Create function node
        func_node_obj = FunctionNode(
            id=func_id,
            name=func_name,
            file_id=str(file_path),
            is_export=is_export,
            start_line=func_node.lineno,
            end_line=getattr(func_node, 'end_lineno', func_node.lineno),
            calls=list(set(calls))  # Remove duplicates
        )

        self.nodes[func_id] = func_node_obj

        # Link to file
        if str(file_path) not in self.file_to_nodes:
            self.file_to_nodes[str(file_path)] = []
        self.file_to_nodes[str(file_path)].append(func_id)

    async def _process_class_def(self, class_node: ast.AST, file_path: Path, content: str):
        """Process a class definition and add it to the graph."""
        class_name = class_node.name
        class_id = f"class:{file_path}:{class_name}:{class_node.lineno}"

        # Get methods in the class
        methods = []
        inherits_from = []

        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(item.name)
            elif isinstance(item, ast.Assign):
                # Handle assignments in class
                pass

        # Get inheritance info
        for base in class_node.bases:
            if isinstance(base, ast.Name):
                inherits_from.append(base.id)
            elif isinstance(base, ast.Attribute):
                inherits_from.append(base.attr)

        # Create class node
        class_node_obj = ClassNode(
            id=class_id,
            name=class_name,
            file_id=str(file_path),
            node_type="class",
            methods=methods,
            inherits_from=inherits_from
        )

        self.nodes[class_id] = class_node_obj

        # Link to file
        if str(file_path) not in self.file_to_nodes:
            self.file_to_nodes[str(file_path)] = []
        self.file_to_nodes[str(file_path)].append(class_id)

    async def _process_import(self, import_node: ast.AST, file_path: Path):
        """Process an import statement and add it to the graph."""
        if isinstance(import_node, ast.Import):
            # Regular import: import module
            for alias in import_node.names:
                import_name = alias.name
                import_alias = alias.asname
                import_id = f"import:{file_path}:{import_name}:{import_node.lineno}"

                import_node_obj = ImportNode(
                    id=import_id,
                    name=import_name,
                    file_id=str(file_path),
                    node_type="import",
                    imported_from=import_name,
                    alias=import_alias
                )

                self.nodes[import_id] = import_node_obj

                # Link to file
                if str(file_path) not in self.file_to_nodes:
                    self.file_to_nodes[str(file_path)] = []
                self.file_to_nodes[str(file_path)].append(import_id)

        elif isinstance(import_node, ast.ImportFrom):
            # From import: from module import name
            module = import_node.module or ""
            for alias in import_node.names:
                import_name = alias.name
                import_alias = alias.asname
                import_id = f"import:{file_path}:{module}.{import_name}:{import_node.lineno}"

                import_node_obj = ImportNode(
                    id=import_id,
                    name=import_name,
                    file_id=str(file_path),
                    node_type="import",
                    imported_from=module,
                    alias=import_alias
                )

                self.nodes[import_id] = import_node_obj

                # Link to file
                if str(file_path) not in self.file_to_nodes:
                    self.file_to_nodes[str(file_path)] = []
                self.file_to_nodes[str(file_path)].append(import_id)

    async def get_function_context(self, function_name: str) -> dict:
        """Get comprehensive context for a function."""
        # Find the function node
        func_nodes = [
            node for node_id, node in self.nodes.items()
            if isinstance(node, FunctionNode) and node.name == function_name
        ]

        if not func_nodes:
            return {"error": f"Function '{function_name}' not found"}

        # Return context for the first match
        func_node = func_nodes[0]
        return {
            "function": func_node,
            "file_path": func_node.file_id,
            "calls": func_node.calls,
            "is_export": func_node.is_export
        }

    async def find_related_files(self, file_path: str, relationship_type: str = "import") -> list[dict]:
        """Find files related by imports/calls."""
        related = []

        if file_path in self.file_to_nodes:
            node_ids = self.file_to_nodes[file_path]
            for node_id in node_ids:
                node = self.nodes[node_id]
                if isinstance(node, ImportNode):
                    # Look for files that import from this file
                    for other_file, other_nodes in self.file_to_nodes.items():
                        if other_file != file_path:
                            for other_node_id in other_nodes:
                                other_node = self.nodes[other_node_id]
                                if (isinstance(other_node, ImportNode) and
                                    hasattr(other_node, 'imported_from') and
                                    other_node.imported_from in node.name):
                                    related.append({
                                        "file": other_file,
                                        "relationship": "import",
                                        "node": other_node
                                    })

        return related