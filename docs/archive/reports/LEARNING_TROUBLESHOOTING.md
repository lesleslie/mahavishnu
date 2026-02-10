# Learning Feedback System - Troubleshooting Guide

Common issues and solutions when working with the learning feedback system.

## Table of Contents

- [MCP Tools Not Appearing](#mcp-tools-not-appearing)
- [Database Connection Errors](#database-connection-errors)
- [Performance Issues](#performance-issues)
- [Privacy Notice Problems](#privacy-notice-problems)
- [Feedback Not Being Captured](#feedback-not-being-captured)
- [Router Not Learning](#router-not-learning)
- [Embedding Model Issues](#embedding-model-issues)
- [CLI Feedback Commands Not Working](#cli-feedback-commands-not-working)

---

## MCP Tools Not Appearing

### Problem: Feedback tools don't show up in MCP client

**Symptoms:**
- `submit_feedback` tool not available
- `feedback_help` tool not available
- MCP client shows no feedback tools

### Solutions

#### 1. Check Tool Registration

Verify tools are registered in FastMCP server:

```python
# In mahavishnu/mcp/server_core.py
from mahavishnu.mcp.tools.feedback_tools import register_feedback_tools

# Should be called during server initialization
register_feedback_tools(mcp)
```

**Check:**
```bash
# List available tools
mahavishnu mcp list-tools

# Should show:
# - submit_feedback
# - feedback_help
```

#### 2. Verify MCP Server is Running

```bash
# Check MCP server status
mahavishnu mcp status

# Should show:
# ✓ MCP server running on localhost:8675
```

**If not running:**
```bash
# Start MCP server
mahavishnu mcp start
```

#### 3. Restart MCP Client

Some MCP clients cache tool lists. Restart your client:

```bash
# For Claude Code Desktop
# Quit and restart the application

# For CLI clients
# Restart your terminal session
```

#### 4. Check Logs for Registration Errors

```bash
# View MCP server logs
mahavishnu mcp logs

# Look for:
# "Registered 2 feedback tools"
```

**If error:**
```
# Should see tool registration
INFO:root:Registered 2 feedback tools

# If missing, check import:
# from mahavishnu.mcp.tools.feedback_tools import register_feedback_tools
```

---

## Database Connection Errors

### Problem: Cannot connect to learning database

**Symptoms:**
- `RuntimeError: Connection pool not initialized`
- `duckdb.Error: Database file not found`
- `ImportError: sentence-transformers not installed`

### Solutions

#### 1. Install sentence-transformers

The learning database requires sentence-transformers for embeddings:

```bash
# Install via pip
pip install sentence-transformers

# Or install with dev dependencies
pip install -e ".[dev]"

# Verify installation
python -c "from sentence_transformers import SentenceTransformer; print('OK')"
```

#### 2. Initialize Database Properly

```python
from mahavishnu.learning.database import LearningDatabase

# Create database instance
db = LearningDatabase(database_path="data/learning.db")

# Initialize schema and connection pool
await db.initialize()

# Now you can use it
await db.store_execution(record)
```

**Common mistake:**
```python
# Bad: Using database without initialization
db = LearningDatabase("data/learning.db")
await db.store_execution(record)  # RuntimeError: not initialized

# Good: Initialize first
db = LearningDatabase("data/learning.db")
await db.initialize()
await db.store_execution(record)  # Works!
```

#### 3. Check Database Path

```python
from pathlib import Path

# Ensure data directory exists
db_path = Path("data/learning.db")
db_path.parent.mkdir(parents=True, exist_ok=True)

# Create database
db = LearningDatabase(database_path=str(db_path))
await db.initialize()
```

#### 4. Verify Database Permissions

```bash
# Check file permissions
ls -la data/learning.db

# Should be readable and writable
# -rw-r--r--  1 user  staff  ...  learning.db

# Fix permissions if needed
chmod 644 data/learning.db
```

#### 5. Check for Database Locks

```bash
# Another process might have the database open
lsof data/learning.db

# If locked, close other processes using the database
```

---

## Performance Issues

### Problem: Learning system slows down execution

**Symptoms:**
- Tasks take longer to complete
- High memory usage
- Database queries are slow

### Solutions

#### 1. Adjust Connection Pool Size

```python
# Default pool size is 4, increase for concurrency
db = LearningDatabase(
    database_path="data/learning.db",
    pool_size=8,  # Increase from 4 to 8
)
```

#### 2. Use Batch Inserts

Instead of inserting one record at a time:

```python
# Bad: Sequential inserts
for record in records:
    await db.store_execution(record)

# Good: Batch inserts (if you implement this)
await db.store_executions_batch(records)
```

#### 3. Disable Embeddings for Testing

```python
# For testing without semantic search
# You can temporarily disable embedding generation

# Edit the record before storing
record_dict = record.to_dict()
record_dict["embedding"] = None  # Skip embedding

# Insert directly without embedding generation
# (This requires custom implementation)
```

#### 4. Use Materialized Views

Materialized views are pre-computed for common queries:

```python
# Instead of querying raw executions
slow_results = await db.query("""
    SELECT AVG(duration_seconds)
    FROM executions
    WHERE timestamp >= NOW() - INTERVAL '30 days'
    GROUP BY model_tier
""")

# Use materialized view
fast_results = await db.get_tier_performance(days_back=30)
```

#### 5. Optimize Indexes

```sql
-- Check if indexes exist
SELECT * FROM duckdb_indexes()
WHERE table_name = 'executions';

-- Recreate indexes if needed
CREATE INDEX IF NOT EXISTS idx_executions_repo_task
ON executions (repo, task_type, timestamp DESC);
```

#### 6. Clean Old Data

```python
# Archive old data to improve performance
await db.execute("""
    DELETE FROM executions
    WHERE timestamp < NOW() - INTERVAL '365 days'
""")
```

---

## Privacy Notice Problems

### Problem: Privacy notice keeps appearing

**Symptoms:**
- Privacy notice shown every session
- Flag file not being created
- Notice reappears after dismissal

### Solutions

#### 1. Check Privacy Notice Path

```python
from pathlib import Path

# Default path
privacy_path = Path.home() / ".mahavishnu" / "privacy-notice-viewed"

# Verify directory exists
privacy_path.parent.mkdir(parents=True, exist_ok=True)

# Create flag file
privacy_path.touch()
```

#### 2. Set Custom Path

```python
from mahavishnu.learning.feedback.capture import FeedbackCapturer

capturer = FeedbackCapturer(
    enable_prompts=True,
    privacy_notice_path=Path("/tmp/mahavishnu-privacy-notice"),
)
```

#### 3. Manually Dismiss Notice

```bash
# Create the flag file manually
mkdir -p ~/.mahavishnu
touch ~/.mahavishnu/privacy-notice-viewed

# Or disable prompts entirely
export MAHAVISHNU_FEEDBACK_PROMPTS=false
```

---

## Feedback Not Being Captured

### Problem: Feedback submissions are lost

**Symptoms:**
- Feedback submitted but not saved
- History shows no entries
- No learning from feedback

### Solutions

#### 1. Check Feedback Storage

```python
# Verify feedback is being captured
# In mahavishnu/mcp/tools/feedback_tools.py

# Line 174: TODO: Store in learning database
# This should be implemented:

from mahavishnu.learning.database import LearningDatabase

db = LearningDatabase()
await db.initialize()

# Store feedback
# Implementation needed here
```

#### 2. Verify Feedback Validation

```python
# Check validation rules
# - issue_type required for fair/poor ratings
# - comment required when issue_type="other"

# Good: Valid feedback
feedback = FeedbackSubmission(
    task_id=uuid4(),
    satisfaction="fair",
    issue_type="wrong_model",  # Required for fair/poor
    comment="Haiku was too small",
    visibility="private",
)

# Bad: Missing issue_type
feedback = FeedbackSubmission(
    task_id=uuid4(),
    satisfaction="fair",  # Missing issue_type!
    # ValidationError: issue_type is required for fair/poor ratings
)
```

#### 3. Check Logs

```bash
# View feedback submission logs
mahavishnu logs --component feedback

# Look for:
# "Feedback submitted: fb-abc-123"
```

#### 4. Enable Debug Logging

```python
import logging

# Enable debug logging
logging.getLogger("mahavishnu.learning").setLevel(logging.DEBUG)

# Submit feedback
# Check console for detailed logs
```

---

## Router Not Learning

### Problem: SONA router accuracy not improving

**Symptoms:**
- Routing accuracy stays at 75%
- No improvement over time
- Router makes same mistakes

### Solutions

#### 1. Verify Learning is Enabled

```python
from mahavishnu.core.learning_router import SONARouter, SONAConfig

# Ensure SONA is enabled
config = SONAConfig(
    enabled=True,  # Must be True
    learning_rate=0.001,
    update_frequency=100,
)

router = SONARouter(config=config)
```

#### 2. Call `learn_from_outcome()`

The router only learns if you call `learn_from_outcome()`:

```python
# Route task
decision = await router.route_task(task)

# Execute task
result = await execute_task(task)

# LEARN from outcome
await router.learn_from_outcome(
    task_id=str(decision.learning_data["task_id"]),
    outcome={
        "quality": 0.85,
        "execution_time": result.duration,
        "success": result.success,
    },
)
```

**Common mistake:**
```python
# Bad: Never calling learn_from_outcome()
decision = await router.route_task(task)
result = await execute_task(task)
# Router never learns from this!

# Good: Always call learn_from_outcome()
decision = await router.route_task(task)
result = await execute_task(task)
await router.learn_from_outcome(task_id, outcome)
```

#### 3. Check Learning Frequency

The router updates every `update_frequency` tasks:

```python
config = SONAConfig(
    update_frequency=100,  # Update every 100 tasks
)

# After 100 tasks learned, EWC matrix updates
# Before that, learning is accumulated but not applied
```

#### 4. Save Model Periodically

```python
# Save model after learning
await router.save_model("models/sona_router.json")

# Load model on startup
await router.load_model("models/sona_router.json")
```

#### 5. Check Statistics

```python
# View router statistics
stats = router.get_statistics()

print(f"Total routes: {stats['total_routes']}")
print(f"Tasks learned: {stats['tasks_learned']}")
print(f"Accuracy history: {stats['accuracy_history']}")

# If tasks_learned is 0, learning is not happening
```

---

## Embedding Model Issues

### Problem: Embedding generation fails

**Symptoms:**
- `ImportError: sentence-transformers not installed`
- `OSError: Can't load tokenizer for 'all-MiniLM-L6-v2'`
- Slow embedding generation

### Solutions

#### 1. Install sentence-transformers

```bash
# Install sentence-transformers
pip install sentence-transformers

# Verify installation
python -c "import sentence_transformers; print(sentence_transformers.__version__)"
```

#### 2. Download Model Explicitly

```python
from sentence_transformers import SentenceTransformer

# Download model (happens automatically on first use)
model = SentenceTransformer('all-MiniLM-L6-v2')

# Test model
embedding = model.encode("Test sentence")
print(f"Embedding shape: {embedding.shape}")  # Should be (384,)
```

#### 3. Use Different Model

```python
# Use a smaller/faster model
db = LearningDatabase(
    database_path="data/learning.db",
    embedding_model="all-MiniLM-L6-v2",  # 384 dims, fast
    # Or:
    # embedding_model="paraphrase-MiniLM-L3-v2",  # 384 dims, faster
)
```

#### 4. Cache Model in Memory

```python
# Model is loaded once in initialize()
# Subsequent calls reuse the loaded model

db = LearningDatabase("data/learning.db")
await db.initialize()  # Model loaded here

# Fast: Model already loaded
await db.store_execution(record1)
await db.store_execution(record2)
await db.store_execution(record3)
```

---

## CLI Feedback Commands Not Working

### Problem: CLI feedback commands fail

**Symptoms:**
- `mahavishnu feedback submit` fails
- `mahavishnu feedback --history` shows nothing
- Command not found errors

### Solutions

#### 1. Check CLI Registration

```python
# In mahavishnu/cli.py
# Ensure feedback commands are registered

@app.command()
def feedback(
    submit: bool = typer.Option(False, "--submit"),
    history: bool = typer.Option(False, "--history"),
    # ...
):
    """Submit and manage feedback."""
    # Implementation
```

#### 2. Verify Command Availability

```bash
# List all commands
mahavishnu --help

# Should show:
# feedback  Submit and manage feedback
```

#### 3. Check Database Connection

```bash
# CLI needs database connection
# Ensure learning database exists

ls -la data/learning.db

# If missing, create it:
python -c "
import asyncio
from mahavishnu.learning.database import LearningDatabase

async def create():
    db = LearningDatabase('data/learning.db')
    await db.initialize()
    await db.close()

asyncio.run(create())
"
```

#### 4. Run with Debug Output

```bash
# Enable debug logging
MAHAVISHNU_LOG_LEVEL=debug mahavishnu feedback --history

# Check for errors in output
```

---

## Getting Help

If you're still experiencing issues:

### 1. Check Logs

```bash
# View all logs
mahavishnu logs

# View specific component logs
mahavishnu logs --component learning
mahavishnu logs --component feedback
mahavishnu logs --component router
```

### 2. Run Diagnostics

```bash
# Check learning system health
mahavishnu diagnose --learning

# Check database integrity
mahavishnu diagnose --database

# Check MCP tools
mahavishnu diagnose --mcp
```

### 3. Enable Debug Logging

```python
import logging

# Enable debug logging for learning components
logging.getLogger("mahavishnu.learning").setLevel(logging.DEBUG)
logging.getLogger("mahavishnu.learning.execution").setLevel(logging.DEBUG)
logging.getLogger("mahavishnu.learning.feedback").setLevel(logging.DEBUG)
logging.getLogger("mahavishnu.core.learning_router").setLevel(logging.DEBUG)
```

### 4. Report Issues

When reporting issues, include:

1. **Error Message:** Full error traceback
2. **Configuration:** Your SONA config, database path, etc.
3. **Environment:** Python version, OS, mahavishnu version
4. **Steps to Reproduce:** Minimal reproduction case
5. **Logs:** Relevant log output

```bash
# Gather diagnostic info
mahavishnu diagnose --all > diagnostics.txt

# Include this in your issue report
```

### 5. Check Documentation

- **[Quick Start Guide](LEARNING_FEEDBACK_LOOPS_QUICKSTART.md)** - Get started
- **[Integration Guide](LEARNING_INTEGRATION_GUIDE.md)** - Integration help
- **[API Reference](LEARNING_API_REFERENCE.md)** - API documentation

---

## Common Error Messages

### `RuntimeError: LearningDatabase not initialized`

**Cause:** Using database without calling `initialize()`

**Solution:**
```python
db = LearningDatabase("data/learning.db")
await db.initialize()  # Add this line
await db.store_execution(record)
```

### `ImportError: sentence-transformers is required`

**Cause:** sentence-transformers package not installed

**Solution:**
```bash
pip install sentence-transformers
```

### `ValidationError: issue_type is required for fair/poor ratings`

**Cause:** Submitting fair/poor feedback without issue_type

**Solution:**
```python
feedback = FeedbackSubmission(
    satisfaction="fair",
    issue_type="wrong_model",  # Add this
    # ...
)
```

### `Connection pool not initialized`

**Cause:** Using TelemetryCapture without initialization

**Solution:**
```python
telemetry = TelemetryCapture(message_bus=bus)
await telemetry.initialize()  # Add this line
await telemetry.capture_routing_decision(data)
```

---

## Performance Tuning

### For High-Volume Systems

```python
# Increase connection pool
db = LearningDatabase(
    database_path="data/learning.db",
    pool_size=16,  # Increase from 4
)

# Use batch operations (if implemented)
await db.store_executions_batch(records)

# Archive old data
await db.archive_data(days_to_keep=90)
```

### For Low-Resource Systems

```python
# Use smaller embedding model
db = LearningDatabase(
    database_path="data/learning.db",
    embedding_model="paraphrase-MiniLM-L3-v2",  # Smaller
    pool_size=2,  # Reduce pool
)

# Disable semantic search if not needed
# Set embedding=None in records
```

---

## Next Steps

- **[Quick Start Guide](LEARNING_FEEDBACK_LOOPS_QUICKSTART.md)** - Get started with feedback
- **[Integration Guide](LEARNING_INTEGRATION_GUIDE.md)** - Integration help
- **[API Reference](LEARNING_API_REFERENCE.md)** - Complete API documentation
