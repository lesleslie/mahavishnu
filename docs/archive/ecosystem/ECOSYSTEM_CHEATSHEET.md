# Ecosystem Cheatsheet

**Quick Reference for All 18 Projects**

**Last Updated**: 2026-02-03

______________________________________________________________________

## 🎯 One-Minute Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    ECOSYSTEM ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐    │
│  │ Foundation  │──────│Orchestration│──────│ Management  │    │
│  │  (2 projs)  │      │  (1 proj)   │      │  (1 proj)   │    │
│  └─────────────┘      └─────────────┘      └─────────────┘    │
│         │                    │                    │             │
│         v                    v                    v             │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐    │
│  │  Quality    │      │   Builder   │      │    Apps     │    │
│  │  (2 projs)  │      │  (2 projs)  │      │  (2 projs)  │    │
│  └─────────────┘      └─────────────┘      └─────────────┘    │
│                                                                   │
│  Plus: 3 Visualizers + 3 Tools + 2 Extensions                    │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Total**: 18 projects | **Quality**: 92/100 | **Status**: 🟢 Production Ready

______________________________________________________________________

## 📋 Project Quick Reference

### By Role (Alphabetical)

| Role | Project | Description | Port | Status |
|------|---------|-------------|------|--------|
| **app** | mdinject | Document injection/editor | - | 🟢 |
| **app** | splashstand | Web dashboard | - | 🟢 |
| **asset** | fastbulma | UI component library | - | 🟢 |
| **builder** | fastblocks | Web app framework | - | 🟢 |
| **extension** | jinja2-custom-delimiters | Custom template delimiters | - | 🟢 |
| **extension** | jinja2-inflection | String inflection filters | - | 🟢 |
| **foundation** | mcp-common | Shared utilities | - | 🟢 |
| **inspector** | crackerjack | Quality control | 8676 | 🟢 |
| **manager** | session-buddy | Session management | 8678 | 🟢 |
| **orchestrator** | mahavishnu | Workflow orchestration | 8680 | 🟢 |
| **resolver** | oneiric | Component resolution | 8681 | 🟢 |
| **diviner** | akosha | Analytics engine | 8682 | 🟢 |
| **tool** | mailgun-mcp | Email integration | - | 🟢 |
| **tool** | raindropio-mcp | Bookmark manager | - | 🟢 |
| **tool** | unifi-mcp | Network management | - | 🟢 |
| **visualizer** | chart-antv | Data visualization | 3036 | 🟢 |
| **visualizer** | excalidraw-mcp | Diagram collaboration | 3032 | 🟢 |
| **visualizer** | mermaid-mcp | Chart generation | 3033 | 🟢 |

### By Port (MCP Servers Only)

| Port | Project | Purpose | Tools |
|------|---------|---------|-------|
| 6379 | Redis | Cache | - |
| 3032 | excalidraw-mcp | Diagrams | 10+ |
| 3033 | mermaid-mcp | Charts | 15+ |
| 3036 | chart-antv | Data viz | 12+ |
| 8676 | crackerjack | Quality | 30+ |
| 8678 | session-buddy | Sessions | 40+ |
| 8680 | mahavishnu | Orchestration | 50+ |
| 8681 | oneiric | Config | 20+ |
| 8682 | akosha | Analytics | 15+ |

**Total MCP Tools**: 155+

______________________________________________________________________

## 🚀 Quick Start Commands

### Start Ecosystem

```bash
# Start all MCP servers (from mahavishnu directory)
cd ~/Projects/mahavishnu
make start-all

# Or manually (in order):
redis-server --port 6379                          # Terminal 1
oneiric mcp start                                 # Terminal 2
akosha mcp start                                  # Terminal 3
session-buddy mcp start                           # Terminal 4
crackerjack mcp start                             # Terminal 5
mahavishnu mcp start                              # Terminal 6
```

### Health Checks

```bash
# Check all servers
curl http://localhost:8680/health  # mahavishnu
curl http://localhost:8678/health  # session-buddy
curl http://localhost:8676/health  # crackerjack
curl http://localhost:8681/health  # oneiric
curl http://localhost:8682/health  # akosha
```

### Common Tasks

```bash
# List all repositories
mahavishnu list-repos

# Trigger workflow
mahavishnu sweep --tag python --adapter llamaindex

# Run quality checks
crackerjack run all

# Check sessions
session-buddy list-sessions

# Resolve component
oneiric resolve adapter:llamaindex
```

______________________________________________________________________

## 🔗 Key Dependencies

### Dependency Chain

```
mcp-common (foundation)
    ↓
oneiric (resolver)
    ↓
┌─────────┬─────────┬─────────┐
│         │         │         │
mahavishnu session-  cracker-
         buddy    jack
    ↓         ↓         ↓
  akosha  (all projects)
```

### Import Patterns

```python
# Foundation
from mcp_common import MCPServerSettings

# Resolution
from oneiric import Resolver, resolve_adapter

# Orchestration
from mahavishnu import MahavishnuApp
from mahavishnu.pools import PoolManager

# Management
from session_buddy import SessionManager

# Quality
from crackerjack import QualityChecker
```

______________________________________________________________________

## 📊 Quality Metrics Snapshot

### Overall Scores

| Category | Score | Grade |
|----------|-------|-------|
| **Security** | 92/100 | A |
| **Testing** | 88/100 | B+ |
| **Architecture** | 90/100 | A- |
| **Code Quality** | 92/100 | A |
| **Documentation** | 95/100 | A |
| **Performance** | 89/100 | B+ |
| **Overall** | **92/100** | **A** |

### Top Performers

1. **mahavishnu**: 97/100 (Orchestration)
2. **mcp-common**: 95/100 (Foundation)
3. **oneiric**: 93/100 (Resolver)
4. **crackerjack**: 92/100 (Quality)
5. **session-buddy**: 90/100 (Management)

______________________________________________________________________

## 🎨 Visualization Tools

### MCP Visualizers Available

| Tool | Port | Best For | Example |
|------|------|----------|---------|
| **excalidraw-mcp** | 3032 | Collaborative diagrams | Whiteboard sessions |
| **mermaid-mcp** | 3033 | Flowcharts, sequence diagrams | Architecture docs |
| **chart-antv** | 3036 | Data visualization | Metrics dashboards |

### Generate Diagrams

```python
# Using mermaid-mcp
import mcp__mermaid__generate_mermaid_diagram

diagram = """
flowchart TD
    A[Start] --> B[Process]
    B --> C[End]
"""
mcp__mermaid__generate_mermaid_diagram(mermaid=diagram, output_format="png")
```

______________________________________________________________________

## 🔧 Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| **Port already in use** | `lsof -ti:8680 \| xargs kill -9` |
| **Redis not running** | `redis-server --port 6379` |
| **Import errors** | `pip install -e ".[dev]"` in project dir |
| **MCP connection failed** | Check server is running: `curl localhost:PORT/health` |
| **Config not loading** | Check Oneiric cache: `ls -la .oneiric_cache/` |

### Debug Mode

```bash
# Enable verbose logging
export MAHAVISHNU_LOG_LEVEL=DEBUG
export SESSION_BUDDY_LOG_LEVEL=DEBUG

# Start with verbose output
mahavishnu mcp start --verbose
```

______________________________________________________________________

## 📚 Documentation Links

### Core Documentation

| Document | Purpose | Path |
|----------|---------|------|
| **Ecosystem Architecture** | Complete ecosystem map | `docs/ECOSYSTEM_ARCHITECTURE.md` |
| **Visual Summary** | Quick overview with charts | `docs/ECOSYSTEM_VISUAL_SUMMARY.md` |
| **Protocols & ABCs** | All interface definitions | `ECOSYSTEM_PROTOCOLS_AND_ABCS.md` |
| **Mahavishnu Architecture** | Orchestrator deep dive | `ARCHITECTURE.md` |
| **Mahavishnu Visual Guide** | Mahavishnu diagrams | `docs/VISUAL_GUIDE.md` |

### Project READMEs

```
~/Projects/
├── mahavishnu/README.md              # Orchestration
├── session-buddy/README.md           # Session management
├── crackerjack/README.md             # Quality control
├── oneiric/README.md                 # Component resolution
├── akosha/README.md                  # Analytics
├── fastblocks/README.md              # Web framework
└── ...
```

______________________________________________________________________

## 💡 Pro Tips

### Workflow Optimization

1. **Use pool routing** for parallel workflow execution
2. **Enable memory aggregation** for cross-pool insights
3. **Cache quality scores** to avoid redundant QC runs
4. **Batch operations** when working with multiple repos
5. **Use MCP tools** from Claude Desktop for best experience

### Performance Tips

1. **Keep Redis running** for fast session lookups
2. **Use quality score caching** (5-minute TTL)
3. **Leverage pool concurrency** (up to 20 parallel ops)
4. **Enable observability** for production monitoring
5. **Use checkpointing** for long-running workflows

### Development Tips

1. **Start servers in order** (deps first)
2. **Use `make start-all`** for local development
3. **Check health endpoints** before running workflows
4. **Read architecture docs** before making changes
5. **Follow role patterns** when adding features

______________________________________________________________________

## 🆘 Emergency Commands

### Stop All Servers

```bash
# Graceful shutdown
make stop-all

# Force kill (if needed)
pkill -f "mcp start"
pkill -f "oneiric"
pkill -f "mahavishnu"
```

### Reset Ecosystem

```bash
# Clear caches
rm -rf .oneiric_cache/
rm -rf .pytest_cache/
rm -rf **/__pycache__/

# Restart Redis
redis-cli FLUSHALL

# Start fresh
make start-all
```

### Backup & Recovery

```bash
# Backup sessions
session-buddy backup-all

# Export configuration
oneiric config export > backup.yaml

# Restore
oneiric config import backup.yaml
session-buddy restore-all
```

______________________________________________________________________

## 📞 Support & Resources

### Getting Help

1. **Documentation**: Start with project READMEs
2. **Architecture Docs**: See `docs/` directories
3. **Code Examples**: Check `tests/` and `examples/`
4. **MCP Tools**: Use `help` tool in Claude Desktop

### Contributing

1. Read project `CLAUDE.md` for guidelines
2. Follow role-based architecture
3. Add tests for new features
4. Update documentation
5. Submit PR with description

______________________________________________________________________

**Version**: 1.0
**Last Updated**: 2026-02-03
**Ecosystem Quality**: 92/100 (A - Production Ready)

**Remember**: This cheatsheet is a quick reference. For detailed information, see the full documentation files listed above.
