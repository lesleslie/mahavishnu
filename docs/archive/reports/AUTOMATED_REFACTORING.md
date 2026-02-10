# Automated Refactoring System

Production-safe automated refactoring for the Mahavishnu ecosystem.

## Overview

The Automated Refactoring System provides safe, AST-based code transformations with comprehensive safety guarantees. It makes refactoring routine rather than scary.

### Key Features

- **10+ Detection Patterns**: Long methods, large classes, high complexity, duplication, missing type hints, magic numbers, dead code, unused imports, long parameter lists, complex conditionals
- **8+ Refactoring Operations**: Extract method/class/variable/constant, inline variable/method, move method/class, rename operations, add type hints, modernize syntax, remove dead code
- **Impact Analysis**: Call graph analysis, data flow analysis, test coverage analysis, risk assessment
- **Safety Guarantees**: AST-based transformations, pre-refactoring testing, automatic rollback, semantic verification, manual review for high-risk changes
- **Orchestration**: Dependency-aware ordering, batch refactorings, incremental refactoring, conflict detection, refactoring history with rollback

## Architecture

```
PatternDetector → ImpactAnalyzer → RefactoringEngine → SafetyGuarantees
                                                           ↓
                                                    RefactoringOrchestrator
                                                           ↓
                                                        (FastAPI)
```

### Components

1. **PatternDetector**: Detects refactoring opportunities using static analysis
2. **ImpactAnalyzer**: Analyzes the impact of proposed refactorings
3. **RefactoringEngine**: Applies AST-based transformations using libcst
4. **SafetyGuarantees**: Ensures safe refactoring with testing and rollback
5. **RefactoringOrchestrator**: Coordinates complex multi-step workflows
6. **RefactoringAPI**: FastAPI endpoints for REST access

## Installation

The automated refactoring system requires `libcst` for AST transformations.

```bash
# Add to pyproject.toml dependencies
pip add libcst

# Or install with dev dependencies
pip install -e ".[dev]"
```

## Quick Start

### Basic Usage

```python
from mahavishnu.integrations.automated_refactoring import (
    RefactoringOrchestrator,
    RefactoringConfig,
    SeverityLevel,
)
from pathlib import Path

# Initialize orchestrator
orchestrator = RefactoringOrchestrator(
    repo_path=Path("/path/to/repo"),
    config=RefactoringConfig(
        max_method_lines=50,
        max_class_lines=300,
        max_complexity=15,
        require_test_coverage=True,
        min_test_coverage=0.8,
        auto_rollback=True,
    ),
)

# Detect opportunities
opportunities = await orchestrator.detector.detect_opportunities(
    severity_filter=SeverityLevel.HIGH,
)

print(f"Found {len(opportunities)} opportunities")

# Analyze impact of first opportunity
impact = await orchestrator.analyzer.analyze_impact(opportunities[0])

print(f"Risk: {impact.risk_level}")
print(f"Coverage: {impact.test_coverage * 100:.0f}%")
print(f"Recommendations: {impact.recommendations}")

# Create and execute plan
plan = await orchestrator.create_plan(opportunities[:5])

if not plan.requires_manual_review:
    history = await orchestrator.execute_plan(plan)
    print(f"Result: {'SUCCESS' if history.overall_success else 'FAILED'}")
```

### End-to-End Refactoring

```python
# Detect and refactor in one step
history = await orchestrator.detect_and_refactor(
    severity_filter=SeverityLevel.MEDIUM,
)

print(f"Refactored {len(history.results)} files")
print(f"Tests passed: {all(r.tests_passed for r in history.results)}")
```

## Detection Patterns

### 1. Long Methods

Detects methods exceeding line threshold.

```python
# Before
def process_data(data):
    # 100+ lines of processing
    result = []
    for item in data:
        # ... many steps ...
    return result

# Detected: RefactoringType.EXTRACT_METHOD
# Severity: HIGH (if > 100 lines)
```

### 2. Large Classes

Detects classes exceeding line threshold.

```python
# Before
class DataProcessor:
    def method1(self): pass
    def method2(self): pass
    # ... 50+ more methods ...

# Detected: RefactoringType.EXTRACT_CLASS
# Suggestion: Split into focused classes
```

### 3. High Complexity

Detects high cyclomatic complexity.

```python
# Before
def complex_function(x, y, z):
    if x > 0:
        if y > 0:
            if z > 0:
                # deeply nested conditions
                return x + y + z
    # ...

# Detected: RefactoringType.EXTRACT_METHOD
# Suggestion: Extract complex conditions
```

### 4. Duplicate Code

Detects repeated code blocks.

```python
# Before (in multiple places)
result = []
for item in data:
    if item > 0:
        result.append(item * 2)

# Detected: RefactoringType.EXTRACT_METHOD
# Suggestion: Extract to shared method
```

### 5. Missing Type Hints

Detects missing type annotations.

```python
# Before
def calculate(x, y):
    return x + y

# Detected: RefactoringType.ADD_TYPE_HINTS
# Suggestion:
# def calculate(x: int, y: int) -> int:
#     return x + y
```

### 6. Magic Numbers

Detects numeric literals.

```python
# Before
def calculate_price(items):
    return items * 1.15  # What is 1.15?

# Detected: RefactoringType.EXTRACT_CONSTANT
# Suggestion:
# TAX_RATE = 1.15
# def calculate_price(items):
#     return items * TAX_RATE
```

### 7. Dead Code

Detects unused functions and classes.

```python
# Before
def unused_function():
    return 42  # Never called

# Detected: RefactoringType.REMOVE_DEAD_CODE
# Suggestion: Remove or mark as @deprecated
```

### 8. Unused Imports

Detects unused imports.

```python
# Before
import os
import sys
import json  # Never used

def main():
    print(os.getcwd())

# Detected: RefactoringType.REMOVE_UNUSED_IMPORTS
# Suggestion: Remove unused imports
```

### 9. Long Parameter Lists

Detects too many parameters.

```python
# Before
def process_data(
    name, age, email, phone, address,
    city, state, zip, country
):
    pass

# Detected: RefactoringType.EXTRACT_CLASS
# Suggestion: Create dataclass for parameters
```

### 10. Complex Conditionals

Detects complex boolean expressions.

```python
# Before
if (x > 0 and y > 0 and z > 0) or (x < 0 and y < 0):
    # complex logic
    pass

# Detected: RefactoringType.EXTRACT_METHOD
# Suggestion: Extract to named predicate
```

## Refactoring Operations

### Extract Method

```python
# Before
def process_order(order):
    # Validate
    if not order.items:
        return False

    # Calculate total
    total = sum(item.price for item in order.items)

    # Apply discount
    if total > 100:
        total *= 0.9

    return total

# After
def process_order(order):
    if not validate_order(order):
        return False

    total = calculate_total(order)
    total = apply_discount(total)

    return total

def validate_order(order):
    return bool(order.items)

def calculate_total(order):
    return sum(item.price for item in order.items)

def apply_discount(total):
    if total > 100:
        total *= 0.9
    return total
```

### Extract Class

```python
# Before
class OrderProcessor:
    def validate(self, order): pass
    def calculate(self, order): pass
    def save(self, order): pass
    def notify(self, order): pass
    def archive(self, order): pass

# After
class OrderProcessor:
    def __init__(self):
        self.validator = OrderValidator()
        self.calculator = OrderCalculator()
        self.repository = OrderRepository()
        self.notifier = OrderNotifier()
        self.archiver = OrderArchiver()

class OrderValidator:
    def validate(self, order): pass

class OrderCalculator:
    def calculate(self, order): pass
```

### Add Type Hints

```python
# Before
def fetch_user(user_id):
    return {"id": user_id, "name": "Alice"}

# After
from typing import TypedDict

class User(TypedDict):
    id: int
    name: str

def fetch_user(user_id: int) -> User:
    return {"id": user_id, "name": "Alice"}
```

## Impact Analysis

### Call Graph Analysis

Identifies all callers of modified code.

```python
impact = await analyzer.analyze_impact(opportunity)

print(f"Call sites: {len(impact.call_sites)}")
for site in impact.call_sites:
    print(f"  {site.file_path}:{site.line_number}")
    print(f"    {site.context}")
```

### Data Flow Analysis

Tracks data flow through the codebase.

```python
print(f"Data flow impacts: {impact.data_flow_impact}")
# ['Data flows through return values', 'Parameters affect computation']
```

### Risk Assessment

Calculates risk score (0.0 to 1.0).

```python
print(f"Risk score: {impact.risk_score:.2f}")
print(f"Risk level: {impact.risk_level}")  # LOW, MEDIUM, HIGH
```

### Test Coverage Analysis

Checks test coverage of affected code.

```python
print(f"Test coverage: {impact.test_coverage * 100:.0f}%")
print(f"Affected tests: {len(impact.affected_tests)}")
```

## Safety Guarantees

### Pre-Refactoring Validation

```python
# Validates before starting
safe = await safety.validate_preconditions(
    opportunity,
    impact,
)

# Checks:
# - Test coverage threshold met
# - Risk level acceptable
# - No breaking changes (or safe to proceed)
```

### Backup Creation

```python
# Creates backups before modifying
backups = await safety.create_backup([
    "/path/to/file1.py",
    "/path/to/file2.py",
])

# Returns: {"file_path": "backup_path"}
```

### Automatic Testing

```python
# Runs tests after refactoring
result = await engine.apply_refactoring(opportunity, impact)

print(f"Tests passed: {result.tests_passed}")
print(f"Tests run: {result.tests_run}")
print(f"Tests failed: {result.tests_failed}")
```

### Rollback on Failure

```python
if not result.tests_passed and config.auto_rollback:
    # Automatically rolls back
    print("Tests failed - rolling back")
    await safety.rollback_changes(backups)
```

### Semantic Verification

```python
# Verifies semantic equivalence
equivalent = await safety.verify_semantics(
    opportunity,
    original_code,
    new_code,
)
```

## Orchestration

### Dependency-Aware Ordering

```python
plan = await orchestrator.create_plan(opportunities)

# Steps are ordered by dependencies
for step in plan.steps:
    print(f"Step {step.order}: {step.opportunity.title}")
    print(f"  Depends on: {step.dependencies}")
```

### Batch Refactoring

```python
# Refactor multiple related changes
plan = await orchestrator.create_plan(opportunities[:10])

history = await orchestrator.execute_plan(plan)

print(f"Executed {len(history.results)} steps")
print(f"Success: {history.overall_success}")
print(f"Rollback: {history.rollback_performed}")
```

### Incremental Refactoring

```python
# Refactor in small, safe steps
for opportunity in opportunities:
    impact = await orchestrator.analyzer.analyze_impact(opportunity)

    if impact.safe_to_refactor:
        result = await orchestrator.engine.apply_refactoring(
            opportunity,
            impact,
        )
        if not result.success:
            break  # Stop on failure
```

## Configuration

### RefactoringConfig

```python
from mahavishnu.integrations.automated_refactoring import RefactoringConfig

config = RefactoringConfig(
    # Detection thresholds
    max_method_lines=50,      # Max lines before method flagged
    max_class_lines=300,      # Max lines before class flagged
    max_complexity=15,        # Max cyclomatic complexity
    max_duplication_lines=10, # Max duplicated lines

    # Safety settings
    require_test_coverage=True,  # Require tests before refactoring
    min_test_coverage=0.8,       # Minimum coverage (0.0-1.0)
    auto_rollback=True,          # Auto-rollback on test failure
    manual_review_risk_threshold="high",  # Manual review threshold

    # Performance
    max_files_parallel=10,   # Max files to analyze in parallel
    timeout_seconds=300,     # Timeout for operations
)
```

## API Reference

### PatternDetector

```python
detector = PatternDetector(repo_path, config)

# Detect all opportunities
opportunities = await detector.detect_opportunities(
    file_patterns=["**/*.py"],
    severity_filter=SeverityLevel.HIGH,
)

# Detect in single file
opportunities = await detector.detect_in_file(file_path)
```

### ImpactAnalyzer

```python
analyzer = ImpactAnalyzer(repo_path, config)

# Analyze impact
impact = await analyzer.analyze_impact(opportunity)

# Properties:
# - affected_files: List[str]
# - call_sites: List[CallSite]
# - risk_score: float (0.0-1.0)
# - risk_level: RiskLevel
# - test_coverage: float (0.0-1.0)
# - safe_to_refactor: bool
# - recommendations: List[str]
```

### RefactoringEngine

```python
engine = RefactoringEngine(repo_path, config)

# Apply refactoring
result = await engine.apply_refactoring(opportunity, impact)

# Properties:
# - success: bool
# - tests_passed: bool
# - changes_made: Dict[str, str]  # file_path -> diff
# - rollback_performed: bool
# - execution_time_seconds: float
```

### RefactoringOrchestrator

```python
orchestrator = RefactoringOrchestrator(repo_path, config)

# Detect and refactor
history = await orchestrator.detect_and_refactor(
    severity_filter=SeverityLevel.MEDIUM,
)

# Get history
history = orchestrator.get_history()

# Rollback operation
success = await orchestrator.rollback_operation(operation_id)
```

## Best Practices

### 1. Start with Low-Risk Changes

```python
# Always filter by severity
opportunities = await detector.detect_opportunities(
    severity_filter=SeverityLevel.LOW,
)
```

### 2. Review Impact Before Refactoring

```python
for opportunity in opportunities:
    impact = await analyzer.analyze_impact(opportunity)

    print(f"Risk: {impact.risk_level}")
    print(f"Coverage: {impact.test_coverage * 100:.0f}%")

    # Only refactor if safe
    if impact.safe_to_refactor:
        # Proceed with refactoring
        pass
```

### 3. Use Incremental Refactoring

```python
# Refactor one file at a time
for opportunity in opportunities:
    result = await orchestrator.execute_plan(
        await orchestrator.create_plan([opportunity])
    )

    if not result.overall_success:
        print("Failed - stopping")
        break
```

### 4. Maintain High Test Coverage

```python
config = RefactoringConfig(
    require_test_coverage=True,
    min_test_coverage=0.8,  # 80% coverage required
)
```

### 5. Enable Auto-Rollback

```python
config = RefactoringConfig(
    auto_rollback=True,  # Always rollback on failure
)
```

## CLI Usage

```bash
# Detect refactoring opportunities
mahavishnu refactor detect --severity high

# Analyze impact of specific refactoring
mahavishnu refactor analyze /path/to/file.py:10-50

# Create refactoring plan
mahavishnu refactor plan --severity medium

# Execute refactoring
mahavishnu refactor execute --plan plan.json

# End-to-end refactoring
mahavishnu refactor run --severity high --auto-apply

# Rollback operation
mahavishnu refactor rollback <operation-id>

# View history
mahavishnu refactor history
```

## FastAPI Integration

```python
from fastapi import FastAPI
from mahavishnu.integrations.automated_refactoring import RefactoringAPI

app = FastAPI()
refactor_api = RefactoringAPI(repo_path="/path/to/repo")

@app.post("/refactor/detect")
async def detect_opportunities(severity: str = "medium"):
    opportunities = await refactor_api.detect_opportunities(
        severity_filter=SeverityLevel(severity),
    )
    return {"opportunities": opportunities}

@app.post("/refactor/plan")
async def create_plan(opportunity_ids: list[str]):
    opportunities = [...]  # Load by ID
    plan = await refactor_api.create_plan(opportunities)
    return {"plan": plan}

@app.post("/refactor/execute")
async def execute_plan(plan: RefactoringPlan):
    history = await refactor_api.execute_plan(plan)
    return {"history": history}
```

## Error Handling

```python
from mahavishnu.integrations.automated_refactoring import (
    RefactoringError,
    PatternDetectionError,
    RefactoringApplicationError,
    SafetyCheckError,
)

try:
    history = await orchestrator.detect_and_refactor()
except RefactoringError as e:
    print(f"Refactoring failed: {e}")
except PatternDetectionError as e:
    print(f"Detection failed: {e}")
except RefactoringApplicationError as e:
    print(f"Application failed: {e}")
except SafetyCheckError as e:
    print(f"Safety check failed: {e}")
```

## Performance

### Large Repositories

```python
# Configure for large repos
config = RefactoringConfig(
    max_files_parallel=20,  # More parallelism
    timeout_seconds=600,    # Longer timeout
)
```

### Caching

The detector caches results for efficiency:

```python
# First call - analyzes all files
opportunities = await detector.detect_opportunities()

# Subsequent calls - uses cache
opportunities = await detector.detect_opportunities()
```

## Limitations

1. **Python Only**: Currently supports Python code only
2. **Test Coverage Required**: Refactoring requires existing tests
3. **Conservative by Default**: Prefers safety over aggressive refactoring
4. **Manual Review**: High-risk changes require manual approval

## Future Enhancements

- Support for other languages (TypeScript, Go, Rust)
- ML-based refactoring suggestions
- Advanced semantic diff visualization
- Git integration with automatic branch creation
- Real-time collaborative refactoring
- IDE plugin integration (VS Code, PyCharm)

## Contributing

When adding new refactoring patterns:

1. Add detection logic to `PatternDetector._detect_*`
2. Create transformer in `RefactoringEngine._create_transformer`
3. Add tests in `tests/unit/test_integrations/test_automated_refactoring.py`
4. Update documentation

## License

MIT License - See LICENSE file for details.
