# Session Buddy + Mahavishnu: Feature Overlap Analysis

**Date:** 2025-01-24
**Purpose:** Determine which AI Maestro features should be shared vs. separate

---

## Executive Summary

**Short Answer:** YES, implement features for Session Buddy, but follow a **shared library pattern** to avoid duplication.

**Key Insight:** Session Buddy and Mahavishnu have **different but complementary purposes**. Some features should be shared, others should be separate.

---

## Architecture Comparison

```
┌─────────────────────────────────────────────────────────────────┐
│                        Your Ecosystem                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐         ┌──────────────────┐             │
│  │  Session Buddy   │         │   Mahavishnu     │             │
│  │  (MCP Server)    │         │  (MCP Server)    │             │
│  ├──────────────────┤         ├──────────────────┤             │
│  │ Purpose          │         │ Purpose          │             │
│  │ - Session memory │         │ - Workflow       │             │
│  │ - Context        │         │   orchestration  │             │
│  │ - Search         │         │ - Multi-repo     │             │
│  │ - Quality        │         │   coordination   │             │
│  │                  │         │ - RAG pipelines  │             │
│  ├──────────────────┤         ├──────────────────┤             │
│  │ Scope            │         │ Scope            │             │
│  │ - Single Claude  │         │ - Multiple       │             │
│  │   Code instance  │         │   repositories   │             │
│  │ - Multi-project  │         │ - Multiple       │             │
│  │   (git worktrees)│         │   adapters       │             │
│  └────────┬─────────┘         └────────┬─────────┘             │
│           │                            │                        │
│           └────────────┬───────────────┘                        │
│                        ▼                                        │
│           ┌──────────────────────────┐                         │
│           │   Shared Libraries       │                         │
│           ├──────────────────────────┤                         │
│           │ ✅ Code Graph Analyzer   │                         │
│           │ ✅ Message Types         │                         │
│           │ ✅ Portable Config       │                         │
│           └──────────────────────────┘                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Feature-by-Feature Analysis

### 1. Code Graph Indexing ⭐⭐⭐⭐⭐

**OVERLAP: 90% - IMPLEMENT AS SHARED LIBRARY**

| Aspect | Session Buddy | Mahavishnu | Recommendation |
|--------|---------------|------------|----------------|
| **Purpose** | Better context compaction + search | Better RAG chunking + retrieval | **Same core need** |
| **Implementation** | AST parsing → DuckDB | AST parsing → Vector store | **Shared parser** |
| **Data Model** | Functions, classes, calls, imports | Functions, classes, calls, imports | **Identical** |
| **Storage** | DuckDB graph tables | Could use DuckDB or vector store | **Session Buddy's DB** |

#### Why Share?

```python
# WITHOUT sharing (duplication):
session_buddy/code_graph.py  ← 500 lines of AST parsing
mahavishnu/code_graph.py    ← 500 lines of AST parsing (SAME CODE!)

# WITH sharing:
mcp-common/code_graph.py    ← 500 lines (implemented ONCE)
  ↓
session_buddy/code_graph.py  ← 50 lines (uses mcp-common)
mahavishnu/code_graph.py    ← 50 lines (uses mcp-common)
```

#### Recommended Architecture

```python
# mcp-common/code_graph/analyzer.py

"""
SHARED LIBRARY - Code Graph Analyzer

Used by:
- Session Buddy: For context compaction and search
- Mahavishnu: For RAG chunking and retrieval
"""

import ast
from pathlib import Path
from typing import Literal
from dataclasses import dataclass

@dataclass
class CodeNode:
    """Base class for code nodes"""
    id: str
    name: str
    file_id: str
    node_type: Literal["file", "function", "class", "import"]

@dataclass
class FunctionNode(CodeNode):
    """Function or method"""
    is_export: bool
    start_line: int
    end_line: int
    calls: list[str]
    lang: str = "python"

class CodeGraphAnalyzer:
    """Analyze and index codebase structure"""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.nodes: dict[str, CodeNode] = {}

    async def analyze_repository(self, repo_path: str) -> dict[str, object]:
        """Analyze repository and build code graph"""
        # Implementation here - used by BOTH systems
        pass

    async def get_function_context(self, function_name: str) -> dict[str, object]:
        """Get comprehensive context for a function"""
        # Implementation here - used by BOTH systems
        pass

    # ... rest of implementation

# ============ USAGE IN SESSION BUDDY ============

# session_buddy/code_graph.py

from mcp_common.code_graph import CodeGraphAnalyzer, FunctionNode

class SessionBuddyCodeAnalyzer:
    """Session Buddy-specific code graph features"""

    def __init__(self, project_path: Path):
        # Use shared analyzer
        self.analyzer = CodeGraphAnalyzer(project_path)

    async def compact_context_with_graph(self, file_path: str) -> list[str]:
        """Use code graph for smarter context compaction"""
        # Session Buddy-specific logic
        # - Find related files
        # - Keep called functions together
        # - Prioritize exported functions
        pass

# ============ USAGE IN MAHAVISHNU ============

# mahavishnu/code_graph.py

from mcp_common.code_graph import CodeGraphAnalyzer, FunctionNode

class MahavishnuCodeAnalyzer:
    """Mahavishnu-specific code graph features"""

    def __init__(self, project_path: Path):
        # Use shared analyzer
        self.analyzer = CodeGraphAnalyzer(project_path)

    async def enhance_rag_with_graph(self, documents: list[Document]) -> list[Document]:
        """Use code graph for better RAG chunking"""
        # Mahavishnu-specific logic
        # - Chunk along function boundaries
        # - Add caller/callee context to documents
        # - Enhance embeddings with structure
        pass
```

#### Benefits

1. **Single Implementation** - Write AST parser once, use everywhere
2. **Consistency** - Same code understanding across both systems
3. **Maintenance** - Bug fixes benefit both projects
4. **Storage** - Session Buddy's DuckDB can serve both
5. **Features** - Mahavishnu gets immediate code graph support

#### Implementation Strategy

```
Phase 1: Create shared library in mcp-common
  - mcp-common/code_graph/analyzer.py
  - AST parsing for Python (extend to JS/TS later)
  - Data models (CodeNode, FunctionNode, ClassNode)
  - Basic graph operations

Phase 2: Session Buddy integration
  - Use shared analyzer for context compaction
  - Store graph in existing DuckDB
  - Add MCP tools for graph queries

Phase 3: Mahavishnu integration
  - Use shared analyzer for RAG enhancement
  - Query graph from Session Buddy's DuckDB
  - Integrate with LlamaIndex adapter
```

---

### 2. Messaging System ⭐⭐⭐⭐⭐

**OVERLAP: 30% - SEPARATE IMPLEMENTATIONS, SHARED TYPES**

| Aspect | Session Buddy | Mahavishnu | Recommendation |
|--------|---------------|------------|----------------|
| **Purpose** | Multi-project coordination | Inter-repository + adapter messaging | **Different purposes** |
| **Granularity** | Projects (git worktrees) | Repositories + Adapters | **Different units** |
| **Data Model** | Similar (priority, type, status) | Similar (priority, type, status) | **Share types** |
| **Storage** | Session Buddy's DuckDB | Mahavishnu's DB | **Separate storage** |
| **Use Cases** | "Project A ready" | "API endpoint ready, adapter: prefect" | **Different contexts** |

#### Why Separate?

```python
# Session Buddy: Multi-project coordination
await send_project_message(
    from_project="session-buddy",
    to_project="crackerjack",
    subject="Quality metrics available",
    message="Session quality score: 87/100"
)

# Mahavishnu: Inter-repository + adapter coordination
await send_repository_message(
    from_repository="backend-api",
    to_repository="frontend-dashboard",
    subject="User stats API ready",
    message="GET /api/stats implemented",
    from_adapter="prefect",  # ← Mahavishnu-specific
    workflow_id="wf-123"     # ← Mahavishnu-specific
)
```

#### Recommended Architecture

```python
# mcp-common/messaging/types.py

"""
SHARED TYPES - Message data models

Both systems use the same message structure for consistency.
"""

from typing import Literal
from pydantic import BaseModel

class Priority(str, Literal["low", "normal", "high", "urgent"]):
    """Message priority levels - SHARED"""
    pass

class MessageType(str, Literal["request", "response", "notification", "update"]):
    """Message types - SHARED"""
    pass

# ============ SESSION BUDDY IMPLEMENTATION ============

# session_buddy/messaging/project_messenger.py

from mcp_common.messaging import Priority, MessageType

class ProjectMessage(BaseModel):
    """Session Buddy: Project-to-project message"""
    id: str
    from_project: str      # ← Project identifier
    to_project: str        # ← Project identifier
    timestamp: str
    subject: str
    priority: Priority     # ← Shared type
    content_type: MessageType  # ← Shared type
    content_message: str
    # Session Buddy-specific fields
    session_id: str | None = None

class ProjectMessenger:
    """Handle project-to-project messaging"""

    async def send_message(
        self,
        from_project: str,
        to_project: str,
        subject: str,
        message: str,
        priority: Priority = Priority.NORMAL  # ← Shared type
    ) -> ProjectMessage:
        """Send message between projects"""
        # Session Buddy implementation
        # Stores in Session Buddy's DuckDB
        pass

# =ittance MAHAVISHNU IMPLEMENTATION ============

# mahavishnu/messaging/repository_messenger.py

from mcp_common.messaging import Priority, MessageType

class RepositoryMessage(BaseModel):
    """Mahavishnu: Repository-to-repository message"""
    id: str
    from_repository: str     # ← Repository identifier
    from_adapter: str | None  # ← Mahavishnu-specific
    to_repository: str       # ← Repository identifier
    timestamp: str
    subject: str
    priority: Priority       # ← Shared type
    content_type: MessageType  # ← Shared type
    content_message: str
    # Mahavishnu-specific fields
    workflow_id: str | None = None

class RepositoryMessenger:
    """Handle repository-to-repository messaging"""

    async def send_message(
        self,
        from_repository: str,
        to_repository: str,
        subject: str,
        message: str,
        priority: Priority = Priority.NORMAL,  # ← Shared type
        from_adapter: str | None = None,       # ← Mahavishnu-specific
        workflow_id: str | None = None         # ← Mahavishnu-specific
    ) -> RepositoryMessage:
        """Send message between repositories"""
        # Mahavishnu implementation
        # Stores in Mahavishnu's database
        pass
```

#### Benefits

1. **Type Safety** - Shared enums prevent mismatched priorities
2. **Consistency** - Same message structure across ecosystem
3. **Flexibility** - Each system has domain-specific fields
4. **Independent Storage** - No database conflicts

#### Implementation Strategy

```
Phase 1: Create shared types in mcp-common
  - mcp-common/messaging/types.py
  - Priority, MessageType enums
  - Base message structures

Phase 2: Session Buddy messaging
  - ProjectMessenger with project-specific logic
  - Store in Session Buddy's DuckDB
  - MCP tools for project coordination

Phase 3: Mahavishnu messaging
  - RepositoryMessenger with repo-specific logic
  - Store in Mahavishnu's database
  - MCP tools for repository coordination
```

---

### 3. Portable Configuration ⭐⭐⭐⭐

**OVERLAP: 40% - SEPARATE IMPLEMENTATIONS, SHARED PATTERN**

| Aspect | Session Buddy | Mahavishnu | Recommendation |
|--------|---------------|------------|----------------|
| **Purpose** | Export session configs | Export workflow configs | **Different purposes** |
| **Format** | .zip with JSON | .zip with JSON | **Same pattern** |
| **Contents** | Sessions, reflections, quality | Workflows, repos, adapter configs | **Different data** |
| **Merge Strategy** | Preview, merge, replace | Preview, merge, replace | **Same logic** |

#### Why Separate?

```python
# Session Buddy: Export session configuration
await export_session_config(
    session_id="session-buddy-main",
    include_reflections=True,        # ← Session Buddy-specific
    include_quality_history=True,    # ← Session Buddy-specific
    include_multi_project_config=True
)

# Mahavishnu: Export workflow configuration
await export_workflow_config(
    workflow_id="backend-api-pipeline",
    include_repos_config=True,       # ← Mahavishnu-specific
    include_adapter_configs=True,    # ← Mahavishnu-specific
    include_quality_history=True
)
```

#### Recommended Architecture

```python
# mcp-common/portable/config.py

"""
SHARED PATTERN - Portable configuration export/import

Both systems use the same zip-based pattern.
"""

import zipfile
import json
from pathlib import Path
from typing import Literal
from abc import ABC, abstractmethod

class MergeStrategy(str, Literal["preview", "merge", "replace"]):
    """Configuration merge strategy - SHARED"""
    pass

class PortableConfig(ABC):
    """Base class for portable configuration - SHARED PATTERN"""

    @abstractmethod
    async def export(
        self,
        id: str,
        include_options: dict[str, bool]
    ) -> dict[str, object]:
        """Export configuration to zip file"""
        pass

    @abstractmethod
    async def import_config(
        self,
        zip_path: str,
        strategy: MergeStrategy
    ) -> dict[str, object]:
        """Import configuration from zip file"""
        pass

# ============ SESSION BUDDY IMPLEMENTATION ============

# session_buddy/portable/session_config.py

from mcp_common.portable import PortableConfig, MergeStrategy

class SessionConfig(PortableConfig):
    """Session Buddy: Portable session configuration"""

    async def export(
        self,
        session_id: str,
        include_options: dict[str, bool]
    ) -> dict[str, object]:
        """Export session configuration"""
        # Session Buddy-specific implementation
        # - Export reflections
        # - Export quality history
        # - Export multi-project config
        pass

    async def import_config(
        self,
        zip_path: str,
        strategy: MergeStrategy
    ) -> dict[str, object]:
        """Import session configuration"""
        # Session Buddy-specific implementation
        pass

# ============ MAHAVISHNU IMPLEMENTATION ============

# mahavishnu/portable/workflow_config.py

from mcp_common.portable import PortableConfig, MergeStrategy

class WorkflowConfig(PortableConfig):
    """Mahavishnu: Portable workflow configuration"""

    async def export(
        self,
        workflow_id: str,
        include_options: dict[str, bool]
    ) -> dict[str, object]:
        """Export workflow configuration"""
        # Mahavishnu-specific implementation
        # - Export workflow definition
        # - Export repos.yaml
        # - Export adapter configs
        pass

    async def import_config(
        self,
        zip_path: str,
        strategy: MergeStrategy
    ) -> dict[str, object]:
        """Import workflow configuration"""
        # Mahavishnu-specific implementation
        pass
```

#### Benefits

1. **Consistent Pattern** - Same export/import UX across ecosystem
2. **Shared Strategy** - Preview/merge/replace logic shared
3. **Domain-Specific** - Each system exports its own data
4. **No Conflicts** - Different file formats, same pattern

---

### 4. Conversation Memory Browser ⭐⭐⭐⭐

**OVERLAP: 0% - SESSION BUDDY ONLY**

This feature is **specific to Session Buddy's purpose** - session memory and search. Mahavishnu doesn't need this.

**Implementation:** Session Buddy only

---

### 5. Auto-Generated Documentation ⭐⭐⭐

**OVERLAP: 50% - SESSION BUDDY FIRST, MAHAVISHNU LATER**

| Aspect | Session Buddy | Mahavishnu | Recommendation |
|--------|---------------|------------|----------------|
| **Purpose** | Search documentation for context | Generate docs from code | **Different priorities** |
| **Data Source** | Code Graph | Code Graph | **Share data source** |
| **Primary Use** | Semantic search | Auto-generation | **Session Buddy first** |

#### Recommended Approach

```
Phase 1: Session Buddy implements
  - Extract docstrings during code graph indexing
  - Store in DuckDB with embeddings
  - Add search_documentation() MCP tool
  - Used for context retrieval

Phase 2: Mahavishnu leverages
  - Query Session Buddy's documentation index
  - Use in RAG pipelines for API documentation
  - Generate docs from indexed code
```

**Implementation:** Session Buddy first, Mahavishnu queries Session Buddy

---

## Decision Matrix

| Feature | Overlap | Strategy | Effort | Priority |
|---------|---------|----------|--------|----------|
| **Code Graph** | 90% | **Shared library in mcp-common** | Medium | HIGH |
| **Messaging** | 30% | **Shared types, separate implementations** | Low-Medium | HIGH |
| **Portable Config** | 40% | **Shared pattern, separate implementations** | Low | MEDIUM |
| **Conversation Browser** | 0% | **Session Buddy only** | Low | MEDIUM |
| **Auto Documentation** | 50% | **Session Buddy first, Mahavishnu queries** | Low | MEDIUM |

---

## Recommended Implementation Order

### For mcp-common (Shared Infrastructure)

```
1. Code Graph Analyzer
   - AST parsing for Python
   - Data models (CodeNode, FunctionNode, ClassNode)
   - Graph operations
   - Effort: 3-4 days

2. Messaging Types
   - Priority, MessageType enums
   - Base message structures
   - Effort: 1 day

3. Portable Config Pattern
   - MergeStrategy enum
   - PortableConfig base class
   - Effort: 1 day
```

### For Session Buddy

```
1. Code Graph Integration
   - Use mcp-common analyzer
   - Store graph in DuckDB
   - Add MCP tools
   - Effort: 2-3 days

2. Project Messaging
   - ProjectMessenger implementation
   - Store in DuckDB
   - MCP tools
   - Effort: 2-3 days

3. Documentation Indexing
   - Extract docstrings during graph indexing
   - Semantic search
   - Effort: 1-2 days

4. Portable Session Config
   - Export/import sessions
   - Effort: 1-2 days
```

### For Mahavishnu

```
1. Code Graph Integration
   - Use mcp-common analyzer
   - Query from Session Buddy's DuckDB (or own storage)
   - Integrate with LlamaIndex adapter
   - Effort: 3-4 days

2. Repository Messaging
   - RepositoryMessenger implementation
   - Store in Mahavishnu's DB
   - MCP tools
   - Effort: 2-3 days

3. Portable Workflow Config
   - Export/import workflows
   - Effort: 1-2 days
```

---

## Summary & Recommendations

### ✅ YES, Implement for Session Buddy

**Reasons:**
1. **High Value** - All features enhance Session Buddy's core purpose
2. **Low Duplication Risk** - Shared library pattern prevents overlap
3. **Mahavishnu Benefits** - Gets features for free via mcp-common
4. **Ecosystem Growth** - Both systems become more powerful together

### 🎯 Key Principle: **Shared Infrastructure, Separate Implementations**

```
mcp-common/              ← Shared infrastructure
├── code_graph/          ← Implemented ONCE
├── messaging/types.py   ← Shared types only
└── portable/pattern.py  ← Shared pattern only

session_buddy/           ← Session Buddy implementations
├── code_graph.py        ← Uses mcp-common
├── messaging/           ← Project-specific
└── portable/            ← Session-specific

mahavishnu/              ← Mahavishnu implementations
├── code_graph.py        ← Uses mcp-common
├── messaging/           ← Repository-specific
└── portable/            ← Workflow-specific
```

### 📋 Implementation Checklist

**Phase 1: Foundation (mcp-common)**
- [ ] Create `mcp-common/code_graph/analyzer.py`
- [ ] Create `mcp-common/messaging/types.py`
- [ ] Create `mcp-common/portable/config.py`

**Phase 2: Session Buddy Features**
- [ ] Integrate code graph analyzer
- [ ] Implement project messaging system
- [ ] Add documentation indexing
- [ ] Implement portable session config

**Phase 3: Mahavishnu Features**
- [ ] Integrate code graph for RAG enhancement
- [ ] Implement repository messaging system
- [ ] Implement portable workflow config

**Phase 4: Integration**
- [ ] Mahavishnu queries Session Buddy's code graph
- [ ] Mahavishnu queries Session Buddy's documentation
- [ ] Cross-system messaging (if needed)

---

## Final Recommendation

**YES - Implement AI Maestro features for Session Buddy first, using mcp-common for shared infrastructure.**

**Rationale:**
1. Session Buddy is the **memory layer** for the ecosystem
2. Mahavishnu can **leverage Session Buddy's indexed data**
3. Shared library in mcp-common **prevents duplication**
4. Both systems become **more powerful together**
5. **Efficient development** - build once, use everywhere

**Next Steps:**
1. Start with **Code Graph** in mcp-common (highest overlap)
2. Implement in Session Buddy for immediate value
3. Integrate in Mahavishnu for RAG enhancement
4. Add messaging and portable config incrementally

Want me to start implementing the shared Code Graph library in mcp-common?
