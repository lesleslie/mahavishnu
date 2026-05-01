## /run

**Smart Crackerjack Execution with Intelligent Fallback**

Executes Crackerjack AI auto-fix with enhanced session management and automatic fallback strategy.

## Usage

```
/run [--debug]
```

### Arguments

- `--debug`: Run in foreground with debug output visible (for troubleshooting)

## Description

This command provides intelligent execution of Crackerjack's AI-powered auto-fix workflow with automatic fallback:

1. **Primary**: Attempts enhanced session-buddy crackerjack execution with analytics and learning
1. **Fallback**: Falls back to direct crackerjack:run if session-buddy is unavailable or fails
1. **Comprehensive**: Always runs with `--ai-fix --run-tests` for complete quality enforcement

## Execution Strategy

### Phase 1: Enhanced Session Management (Primary)

```
/session-buddy:crackerjack-run --ai-fix --run-tests
```

- **Benefits**: Enhanced analytics, learning system integration, progress tracking
- **Features**: Session continuity, failure pattern learning, optimization insights

### Phase 2: Direct Execution (Fallback)

```
/crackerjack:run --ai-fix --run-tests
```

- **Benefits**: Direct MCP server execution, reliable core functionality
- **Features**: Standard AI auto-fix workflow, comprehensive quality checks

### Phase 3: Bash Fallback (Emergency)

```bash
python -m crackerjack --ai-fix --run-tests
```

- **Benefits**: Always available, bypasses MCP issues
- **Features**: Core crackerjack functionality, direct command execution

## What It Does

**Iterative AI-Powered Auto-Fixing Process:**

1. ⚡ **Fast Hooks**: formatting, basic checks, retry logic
1. 🧪 **Test Suite**: comprehensive test execution and failure collection
1. 🔍 **Quality Checks**: type checking, security, complexity analysis
1. 🤖 **AI Fixing**: intelligent batch resolution of all detected issues
1. 🔄 **Iteration**: repeat until perfect quality or max iterations reached

## Benefits

- **Intelligent Fallback**: Automatically tries best available execution method
- **Zero Configuration**: No need to remember different command variations
- **Enhanced Analytics**: Uses session-buddy when available for learning and insights
- **Reliability**: Always falls back to working execution method
- **Comprehensive**: Always includes tests and AI auto-fixing

## Implementation

When executed, this command tries execution methods in order:

```python
# 1. Try enhanced session-buddy execution (via crackerjack MCP)
try:
    result = mcp__crackerjack__execute_crackerjack(args)
    if result.success:
        return result
except Exception:
    pass

# 2. Fallback to crackerjack quality run
try:
    result = mcp__crackerjack__run_crackerjack_stage(args)
    if result.success:
        return result
except Exception:
    pass

# 3. Emergency bash fallback
result = bash_execute(f"python -m crackerjack {args}")
return result
```

This ensures reliable execution regardless of MCP server status or availability.
