# CLI Design Analysis: Dynamic Parser + IPython Shells

**Date**: 2026-02-06
**Component**: Multi-Component Admin CLI Shell Architecture
**Status**: Design Review

---

## Executive Summary

This analysis evaluates the proposed dynamic `--help --help` parsing strategy for admin CLI shells across multiple components (Oneiric, Session-Buddy, Crackerjack, Akosha MCP). The design aims to provide unified shell experiences without requiring prefixes or manual command registration.

**Key Finding**: Dynamic `--help --help` parsing is **fundamentally flawed** for production use. This document outlines the risks and provides recommended alternatives.

---

## Current Design Overview

### Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    IPython Shell                             │
│                  (Interactive Environment)                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Dynamic Command Parser                          │
│         (Parses --help --help output recursively)            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Input Preprocessor                              │
│      (Routes CLI commands vs Python expressions)             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Component CLI (Typer/Click)                     │
└─────────────────────────────────────────────────────────────┘
```

### Example Workflow

```python
# User enters in shell (no prefix required)
In [1]: list-repos --tag python

# Parser detects CLI command
# Routes to: mahavishnu list-repos --tag python
# Returns result to shell
```

---

## Critical Analysis: Dynamic --help Parsing

### Problem Statement

The proposed design uses `subprocess.run(["cli", "--help", "--help"])` (or similar) to dynamically generate a command tree by parsing help output.

### Why This Approach Is Not Production-Ready

#### 1. **Fragility - Help Text Is Not Machine-Readable**

**Issue**: Help output formats vary significantly between CLIs and versions.

```bash
# Typer help output
Usage: mahavishnu list-repos [OPTIONS]

# Click help output
Usage: mahavishnu list-repos [OPTIONS] Typer

# argparse help output
usage: mahavishnu list-repos [-h] [--tag TAG]

# Custom CLIs
LIST-REPOS: List repositories (custom format)
```

**Impact**: Parser must handle multiple formats, leading to:

- Brittle regex patterns that break on CLI changes
- Version-specific compatibility issues
- Edge cases with exotic help formatters

#### 2. **Recursive Discovery Complexity**

**Issue**: Discovering all subcommands requires recursive help parsing.

```python
# Pseudocode for recursive discovery
def discover_commands(cli_path, depth=0):
    # Parse top-level help
    help_output = subprocess.run([cli_path, "--help", "--help"], capture_output=True)

    # Extract subcommands (fragile parsing)
    subcommands = parse_subcommands(help_output)  # ⚠️ Brittle

    for cmd in subcommands:
        # Recurse into subcommands
        discover_commands(f"{cli_path} {cmd}", depth+1)
```

**Problems**:

- **Performance**: O(n) subprocess calls where n = total commands
- **Race conditions**: CLI state changes during discovery
- **Infinite loops**: Cyclic command references
- **Dynamic commands**: Commands generated at runtime (plugins, aliases)

#### 3. **No Type Information**

**Issue**: Help text doesn't provide parameter types, validation rules, or constraints.

```bash
# Help output
--tag TEXT     Filter repositories by tag

# Parser sees: "tag" is optional, takes TEXT
# Parser doesn't know:
#   - Valid tag values (enum?)
#   - Validation rules (regex?)
#   - Mutual exclusions (--tag vs --role?)
#   - Required combinations
```

**Impact**:

- No tab completion for valid values
- No input validation before execution
- Poor error messages ("invalid value" vs "expected one of: python, go, rust")

#### 4. **Shell Integration Complexity**

**Issue**: IPython's input preprocessing must distinguish CLI from Python.

```python
# Ambiguous inputs
list-repos --tag python        # CLI command
repos = []                     # Python variable assignment
list = get_repos()             # Python function (conflicts with CLI)
repos.filter(tag="python")     # Python method call (looks like CLI flags)
```

**Problems**:

- **False positives**: Python code interpreted as CLI
- **False negatives**: CLI commands interpreted as Python syntax errors
- **Context awareness**: Can't distinguish without AST parsing

#### 5. **Startup Performance**

**Issue**: Every shell startup requires CLI discovery.

```python
# Shell startup sequence
def start_shell():
    # 1. Parse all CLI commands (slow)
    command_tree = discover_all_commands(cli_binary)  # 1-5 seconds

    # 2. Build command router
    router = build_router(command_tree)

    # 3. Start IPython
    shell.start()
```

**Impact**:

- **Shell latency**: 1-5 second startup delay
- **Stale cache**: CLI updates require cache invalidation
- **Background sync**: Can't parse help while shell is running

#### 6. **Error Handling and Debugging**

**Issue**: Failures in dynamic parsing are opaque and hard to debug.

```python
# Parser failure scenarios
# 1. Help text format changed
ParserError: Unexpected help format at line 3

# 2. Subcommand not found
SubprocessError: 'mahavishnu' returned exit code 2

# 3. Infinite recursion
RecursionError: Maximum recursion depth exceeded in command discovery

# 4. Cache corruption
ValueError: Invalid command tree in cache
```

**Problems**:

- No clear error messages for users
- Difficult to debug (is it the parser? the CLI? the cache?)
- Can't recover gracefully (partial command tree)

#### 7. **Security Concerns**

**Issue**: Dynamic command execution based on parsed help text.

```python
# Attacker-controlled input
user_input = "list-repos; rm -rf /"  # Command injection?

# Parser routes to:
subprocess.run(f"mahavishnu {user_input}", shell=True)  # ⚠️ DANGEROUS
```

**Risks**:

- **Command injection**: If parser uses `shell=True`
- **Path traversal**: If CLI binary path is user-controlled
- **Privilege escalation**: If shell runs with elevated permissions

---

## CLI Design Best Practices

### 1. **Explicit > Implicit**

**Principle**: Commands should be explicitly registered, not dynamically discovered.

```python
# ✅ GOOD: Explicit registration
shell.register_command("list-repos", list_repos_handler)
shell.register_command("sweep", sweep_handler)

# ❌ BAD: Dynamic discovery
commands = parse_help_output(cli_binary)  # Fragile
```

**Benefits**:

- Clear intent and auditability
- Type safety and validation
- Better error messages
- Easier testing and debugging

### 2. **Native Integration > Shell Wrappers**

**Principle**: Extend the CLI framework natively, not via shell preprocessing.

```python
# ✅ GOOD: Native Typer extension
app = typer.Typer()

@app.command()
def shell():
    """Start interactive shell with pre-configured environment."""
    # Start IPython with known namespace
    start_ipython(namespace={"app": app, "commands": get_commands()})

# ❌ BAD: Shell wrapper with routing
shell.add_cli_router(cli_binary)  # Requires dynamic parsing
```

**Benefits**:

- No subprocess overhead
- Direct Python integration (no serialization)
- Native exception handling
- Better performance

### 3. **Declarative Configuration**

**Principle**: Use structured config for command discovery, not help parsing.

```python
# ✅ GOOD: Declarative command registry
COMMAND_REGISTRY = {
    "list-repos": {
        "handler": list_repos_handler,
        "args": [
            {"name": "--tag", "type": str, "required": False},
            {"name": "--role", "type": str, "required": False},
        ],
        "help": "List repositories in repos.yaml",
    },
    "sweep": {
        "handler": sweep_handler,
        "args": [
            {"name": "--tag", "type": str, "required": True},
            {"name": "--adapter", "type": str, "default": "langgraph"},
        ],
        "help": "Perform an AI sweep across repositories",
    },
}

# ❌ BAD: Dynamic help parsing
registry = parse_cli_help(cli_binary)  # Fragile, slow
```

**Benefits**:

- Version-controllable
- Type-safe
- Self-documenting
- Testable without subprocess calls

### 4. **Hybrid Python/CLI Experience**

**Principle**: Provide both CLI commands AND Python functions, not routing.

```python
# ✅ GOOD: Dual interface
# CLI command
@app.command()
def list_repos(tag: Optional[str] = None, role: Optional[str] = None):
    """List repositories in repos.yaml."""
    repos = app.get_repos(tag=tag, role=role)
    typer.echo(format_repos(repos))

# Python function (same implementation)
def list_repos_py(tag: Optional[str] = None, role: Optional[str] = None) -> List[Repo]:
    """List repositories (Python API)."""
    return app.get_repos(tag=tag, role=role)

# Shell provides both
In [1]: list_repos(tag="python")  # Python function (returns data)
In [2]: %list-repos --tag python  # CLI command (prints output)
```

**Benefits**:

- Clear separation (CLI for output, Python for data)
- No routing ambiguity
- Better composability (Python functions can be chained)
- Familiar to both CLI and Python users

### 5. **Tab Completion via Metadata**

**Principle**: Use structured metadata for completions, not help parsing.

```python
# ✅ GOOD: Explicit completions
@app.command()
@app.argument("tag", shell_complete=complete_tags)
def list_repos(tag: Optional[str] = None):
    """List repositories."""
    pass

def complete_tags():
    """Return valid tags for completion."""
    return ["python", "go", "rust", "javascript"]

# ❌ BAD: Help parsing for completions
tags = parse_help_output(cli_binary)  # Incomplete, fragile
```

**Benefits**:

- Dynamic values (e.g., from config or runtime state)
- Context-aware completions (e.g., filter based on previous args)
- Better user experience (faster, more accurate)

---

## Recommended Architecture

### Option 1: Native IPython Extension (Recommended)

Extend IPython with magic commands and convenience functions. No dynamic parsing required.

```python
# mahavishnu/shell/core.py
from IPython.terminal.embed import InteractiveShellEmbed
from IPython.core.magic import register_line_magic

class MahavishnuShell:
    def __init__(self, app: MahavishnuApp):
        self.app = app
        self.shell = InteractiveShellEmbed()

    def start(self):
        # Register magic commands
        self.shell.register_magic_function(self._magic_list_repos, 'line', 'list_repos')

        # Add convenience functions to namespace
        self.shell.user_ns['list_repos'] = self._list_repos_py
        self.shell.user_ns['sweep'] = self._sweep_py

        # Start shell
        self.shell()

    @register_line_magic
    def _magic_list_repos(self, line):
        """Magic command: %list_repos [--tag TAG] [--role ROLE]"""
        args = parse_magic_args(line)  # Simple argparse
        repos = self.app.get_repos(**args)
        print(format_repos(repos))

    def _list_repos_py(self, tag: str = None, role: str = None) -> List[Repo]:
        """Python function: Returns data."""
        return self.app.get_repos(tag=tag, role=role)

    def _sweep_py(self, tag: str, adapter: str = "langgraph"):
        """Python function: Executes workflow."""
        return asyncio.run(self.app.execute_workflow(tag, adapter))
```

**Usage**:

```python
Mahavishnu> %list_repos --tag python     # Magic command (prints)
Mahavishnu> repos = list_repos(tag="python")  # Python function (returns data)
Mahavishnu> result = sweep("python")     # Python function (async wrapper)
```

**Pros**:

- ✅ No dynamic parsing
- ✅ Fast startup (< 100ms)
- ✅ Type-safe
- ✅ Native IPython integration
- ✅ Tab completion works out-of-the-box
- ✅ Clear separation (magic vs Python)

**Cons**:

- ❌ Requires manual registration (boilerplate)
- ❌ Must update shell when CLI changes

---

### Option 2: Typer Shell Command

Add a `shell` command to the CLI that starts IPython with pre-configured namespace.

```python
# mahavishnu/cli.py
@app.command()
def shell():
    """Start interactive admin shell."""
    import asyncio
    from IPython import start_ipython

    # Initialize app
    app = MahavishnuApp()

    # Build namespace
    namespace = {
        "app": app,
        "asyncio": asyncio,
        # Convenience functions (sync wrappers for async)
        "list_repos": lambda **kw: app.get_repos(**kw),
        "sweep": lambda tag, adapter="langgraph": asyncio.run(
            app.execute_workflow(tag, adapter)
        ),
        "ps": lambda: asyncio.run(print_workflows(app)),
        "top": lambda: asyncio.run(print_active_workflows(app)),
        # ... more functions
    }

    # Start IPython
    start_ipython(argv=[], user_ns=namespace, display_banner=False)
```

**Usage**:

```bash
$ mahavishnu shell
Mahavishnu Shell> repos = list_repos(tag="python")
Mahavishnu Shell> sweep("python", adapter="llamaindex")
```

**Pros**:

- ✅ Simple implementation
- ✅ No subprocess calls
- ✅ Fast startup
- ✅ Full Python access

**Cons**:

- ❌ No CLI commands in shell (only Python functions)
- ❌ Must prefix with `mahavishnu shell`

---

### Option 3: Click/Typer Shell Integration

Use Click's shell integration extensions.

```python
# Using click-shell extension
from click_shell import shell

@app.group()
def cli():
    """Mahavishnu CLI."""
    pass

@cli.command()
@shell(prompt='mahavishnu> ')
def list_repos(tag: Optional[str] = None, role: Optional[str] = None):
    """List repositories."""
    repos = app.get_repos(tag=tag, role=role)
    typer.echo(format_repos(repos))
```

**Pros**:

- ✅ Native CLI framework integration
- ✅ Tab completion included
- ✅ No dynamic parsing

**Cons**:

- ❌ Limited to Click (not Typer)
- ❌ Less flexible than IPython
- ❌ Not suitable for complex workflows

---

## Tab Completion Strategies

### 1. **Static Completion Files**

Generate completion files from CLI metadata.

```bash
# Generate bash completion
$ mahavishnu --completion > /etc/bash_completion.d/mahavishnu

# Generate zsh completion
$ mahavishnu --completion-zsh > /usr/local/share/zsh/site-functions/_mahavishnu
```

**Pros**:

- ✅ Native shell integration
- ✅ Fast (no subprocess calls)
- ✅ Works outside IPython

**Cons**:

- ❌ Must regenerate on CLI changes
- ❌ Limited to what's in help text

### 2. **IPython Tab Completion**

Use IPython's completion hooks.

```python
from IPython.core.completer import IPCompleter

def mahavishnu_completer(shell, event):
    """Custom completer for Mahavishnu commands."""
    line = event.line
    if line.startswith("list_repos"):
        return ["--tag", "--role"]
    elif line.startswith("sweep"):
        return ["--tag", "--adapter"]
    return []

# Register completer
ip = get_ipython()
ipCompleter = ip.Completer
ipCompleter.matchers.insert(0, mahavishnu_completer)
```

**Pros**:

- ✅ Dynamic (can query runtime state)
- ✅ Context-aware (can filter based on previous args)
- ✅ Works in shell

**Cons**:

- ❌ Requires custom completer logic
- ❌ Must update when CLI changes

### 3. **Typer/Click Auto-Completion**

Let the CLI framework generate completions.

```python
# Typer auto-generates completions
app = typer.Typer()

@app.command()
def list_repos(
    tag: Optional[str] = typer.Option(None, "--tag", "-t"),
    role: Optional[str] = typer.Option(None, "--role", "-r"),
):
    """List repositories."""
    pass

# Generate completion script
if __name__ == "__main__":
    typer_completion()
```

**Pros**:

- ✅ Automatic (no manual work)
- ✅ Type-aware
- ✅ Consistent with CLI

**Cons**:

- ❌ Limited to shell completion (not IPython)
- ❌ Can't customize easily

---

## Common Pitfalls to Avoid

### 1. **Over-Engineering**

❌ **Don't**: Build a generic dynamic parser for all CLIs.

```python
# ❌ Over-engineered
class UniversalCLIParser:
    def parse_any_cli(self, cli_binary):
        # Parse help, detect format, build tree...
        # Too complex, fragile
```

✅ **Do**: Build simple, specific registration.

```python
# ✅ Simple and specific
shell.register_command("list-repos", list_repos_handler)
shell.register_command("sweep", sweep_handler)
```

### 2. **Shell Preprocessing**

❌ **Don't**: Intercept all input and route to CLI.

```python
# ❌ Brittle routing
def preprocess_input(user_input):
    if looks_like_cli_command(user_input):  # Ambiguous
        return execute_cli(user_input)
    else:
        return eval(user_input)  # Dangerous
```

✅ **Do**: Use explicit prefixes or magic commands.

```python
# ✅ Clear intent
%sweep --tag python           # Magic command (explicit prefix)
sweep(tag="python")           # Python function (clear syntax)
```

### 3. **Subprocess Overhead**

❌ **Don't**: Spawn subprocesses for every command.

```python
# ❌ Slow (subprocess overhead)
def execute_cli_command(args):
    result = subprocess.run(["mahavishnu"] + args)
    return result.stdout
```

✅ **Do**: Import and call Python functions directly.

```python
# ✅ Fast (direct Python call)
from mahavishnu.cli import list_repos

def execute_shell_command(args):
    return list_repos(**args)  # Direct function call
```

### 4. **Ignoring Error Context**

❌ **Don't**: Lose error context in shell routing.

```python
# ❌ Poor error messages
try:
    execute_cli(user_input)
except Exception:
    print("Command failed")  # No context
```

✅ **Do**: Preserve and enrich error messages.

```python
# ✅ Rich error messages
try:
    execute_cli(user_input)
except ValidationError as e:
    print(f"Validation error: {e}")
    print(f"Expected: --tag TAG (valid: {valid_tags})")
except Exception as e:
    logger.exception("Command execution failed")
    print(f"Error: {e}")
```

### 5. **Startup Latency**

❌ **Don't**: Parse entire CLI tree on shell startup.

```python
# ❌ Slow startup (1-5 seconds)
def start_shell():
    command_tree = discover_all_commands(cli_binary)  # Expensive
    shell.start(command_tree)
```

✅ **Do**: Lazy-load or pre-generate command registry.

```python
# ✅ Fast startup (< 100ms)
def start_shell():
    # Load pre-generated registry (fast)
    command_tree = load_command_registry()  # From file or import
    shell.start(command_tree)

# Or lazy-load
def handle_command(cmd_name):
    if cmd_name not in registry:
        registry[cmd_name] = load_command_handler(cmd_name)  # On-demand
    registry[cmd_name]()
```

---

## Production Readiness Assessment

### Dynamic --help Parsing: ❌ NOT PRODUCTION-READY

| Criterion | Score | Notes |
|-----------|-------|-------|
| **Robustness** | 2/10 | Fragile parsing, breaks on CLI changes |
| **Performance** | 3/10 | Slow startup, subprocess overhead |
| **Maintainability** | 2/10 | Hard to debug, complex error handling |
| **Security** | 4/10 | Risk of command injection if not careful |
| **UX** | 5/10 | No prefix is nice, but errors are confusing |
| **Type Safety** | 1/10 | No type information from help text |
| **Tab Completion** | 3/10 | Can't complete valid values without types |
| **Testability** | 2/10 | Requires mocking subprocess calls |

**Overall: 2.8/10 - NOT RECOMMENDED**

### Native IPython Extension: ✅ PRODUCTION-READY

| Criterion | Score | Notes |
|-----------|-------|-------|
| **Robustness** | 9/10 | Explicit registration, type-safe |
| **Performance** | 10/10 | Direct function calls, < 100ms startup |
| **Maintainability** | 9/10 | Clear code paths, easy debugging |
| **Security** | 10/10 | No subprocess, direct Python calls |
| **UX** | 8/10 | Magic commands are explicit |
| **Type Safety** | 10/10 | Full type hints, validation |
| **Tab Completion** | 8/10 | IPython completion works well |
| **Testability** | 10/10 | Unit test each handler |

**Overall: 9.2/10 - HIGHLY RECOMMENDED**

---

## Recommendations

### For Mahavishnu (Current Implementation)

**Current State**: Using `AdminShell` from Oneiric with IPython integration.

**Recommendation**: ✅ **Keep Current Approach**

The current `MahavishnuShell` implementation is already production-ready:

- Uses IPython with explicit namespace registration
- Provides convenience functions (`ps()`, `top()`, `errors()`)
- Supports magic commands (`%repos`, `%workflow`)
- No dynamic parsing required

**Improvements**:

1. **Add more convenience functions** for common workflows
2. **Improve tab completion** for custom functions
3. **Add shell startup cache** for expensive operations (e.g., loading repos)
4. **Document shell commands** in help text

### For Multi-Component Rollout

**Recommendation**: ✅ **Standardize on AdminShell Pattern**

Use the same `AdminShell` base class across all components:

```python
# oneiric/shell/core.py (base class)
class AdminShell:
    def __init__(self, app, config=None):
        self.app = app
        self.config = config or ShellConfig()
        self._build_namespace()

    def start(self):
        # Start IPython with namespace
        pass

# mahavishnu/shell/adapter.py (extends base)
class MahavishnuShell(AdminShell):
    def _add_mahavishnu_namespace(self):
        # Add Mahavishnu-specific functions
        pass

# session-buddy/shell/adapter.py (extends base)
class SessionBuddyShell(AdminShell):
    def _add_session_buddy_namespace(self):
        # Add Session-Buddy-specific functions
        pass

# crackerjack/shell/adapter.py (extends base)
class CrackerjackShell(AdminShell):
    def _add_crackerjack_namespace(self):
        # Add Crackerjack-specific functions
        pass
```

**Benefits**:

- Consistent UX across components
- Shared infrastructure (base class, formatters, magics)
- Easy to maintain and extend
- No dynamic parsing required

### For Akosha MCP Server

**Recommendation**: ✅ **Use Shell Command Pattern**

Add a `shell` command to the MCP server CLI:

```python
# akosya/cli.py
@app.command()
def shell():
    """Start interactive admin shell for pattern detection."""
    import asyncio
    from akosya.app import AkosyaApp
    from akosya.shell import AkosyaShell

    app = AkosyaApp()
    shell = AkosyaShell(app)
    shell.start()
```

---

## Implementation Roadmap

### Phase 1: Standardize AdminShell (1 week)

1. **Refactor Oneiric AdminShell** (if needed)
   - Add configuration options
   - Improve error handling
   - Add helper methods

2. **Create Shell Adapters** for each component
   - Mahavishnu: Already exists ✅
   - Session-Buddy: Create `SessionBuddyShell`
   - Crackerjack: Create `CrackerjackShell`
   - Akosya: Create `AkosyaShell`

3. **Add Shell Commands** to each CLI
   ```bash
   $ mahavishnu shell      # Already exists ✅
   $ oneiric shell         # Add
   $ session-buddy shell   # Add
   $ crackerjack shell     # Add
   $ akosya shell          # Add
   ```

### Phase 2: Improve Shell UX (1 week)

1. **Add convenience functions** for common workflows
2. **Improve tab completion** (custom completers)
3. **Add shell documentation** (help text, examples)
4. **Add shell startup cache** (for expensive operations)

### Phase 3: Advanced Features (Optional, 2 weeks)

1. **Shell plugins** (load custom commands from plugins)
2. **Shell history** (persistent command history)
3. **Shell macros** (record and replay command sequences)
4. **Shell themes** (customizable colors and formatting)

---

## Conclusion

### TL;DR

**Dynamic `--help --help` parsing is NOT production-ready** for admin CLI shells. It is fragile, slow, hard to maintain, and provides poor UX.

**Recommended approach**: Use IPython with explicit command registration (current MahavishnuShell pattern). This is:
- ✅ Fast (< 100ms startup)
- ✅ Robust (no fragile parsing)
- ✅ Type-safe (full Python types)
- ✅ Maintainable (clear code paths)
- ✅ Secure (no subprocess calls)

### Next Steps

1. **Keep current MahavishnuShell** implementation ✅
2. **Standardize on AdminShell** pattern across components
3. **Add shell commands** to Session-Buddy, Crackerjack, Akosya
4. **Improve tab completion** and documentation
5. **Avoid dynamic `--help` parsing** entirely

### Resources

- **IPython Documentation**: https://ipython.readthedocs.io/
- **Typer Documentation**: https://typer.tiangolo.com/
- **Click Shell Extensions**: https://click-docs.readthedocs.io/
- **Mahavishnu Shell**: `/Users/les/Projects/mahavishnu/mahavishnu/shell/`
- **Oneiric Shell**: `/Users/les/Projects/oneiric/oneiric/shell/`

---

**Document Status**: Ready for Review
**Author**: Claude (CLI Development Specialist)
**Last Updated**: 2026-02-06
