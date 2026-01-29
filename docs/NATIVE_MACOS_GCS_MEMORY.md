# Native macOS Memory Systems: GCS + Homebrew (No Docker/K8s)

**Requirements**:

- ✅ Google Cloud Storage for backup/sync
- ✅ Oneiric storage adapter (or direct GCS integration)
- ✅ No Docker or Kubernetes
- ✅ Homebrew-installable when possible
- ✅ Native Python packages preferred

______________________________________________________________________

## 🎯 Top Recommendation: pgvector + PostgreSQL + GCS Backup

**Perfect fit for your requirements!**

### Why pgvector?

- ✅ **Homebrew available**: `brew install pgvector`
- ✅ **Native macOS**: PostgreSQL runs natively on macOS
- ✅ **GCS backup**: Well-documented PostgreSQL → GCS backup strategies
- ✅ **No Docker**: Pure Python + PostgreSQL
- ✅ **Production-proven**: Used by Google Cloud SQL
- ✅ **Oneiric-compatible**: Can use Oneiric's storage patterns

______________________________________________________________________

## 📦 Installation: pgvector on macOS

### Step 1: Install PostgreSQL (Homebrew)

```bash
# Install PostgreSQL 16 (or latest)
brew install postgresql@16

# Or install Postgres.app (includes pgvector built-in)
# Download from: https://postgresapp.com/
# Version 17+ includes pgvector pre-installed
```

**Source**: [PostgreSQL pgvector Setup Guide](https://thedbadmin.com/blog/postgresql-pgvector-setup-guide)

### Step 2: Install pgvector Extension

```bash
# Method 1: Via Homebrew (recommended)
brew install pgvector

# Method 2: Via PostgreSQL (if using Postgres.app)
# pgvector is included in Postgres.app v17+
```

### Step 3: Initialize Database

```bash
# Start PostgreSQL service
brew services start postgresql@16

# Connect to PostgreSQL
psql postgres

# Enable pgvector extension
CREATE EXTENSION vector;

# Create your memory database
CREATE DATABASE memory_db;

# Connect to memory database
\c memory_db

# Create memories table
CREATE TABLE memories (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(1536),  -- OpenAI ada-002 dimension
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create index for fast vector search
CREATE INDEX ON memories
USING ivfflat (embedding vector_cosine_ops);

-- Exit
\q
```

**Sources**:

- [macOS pgvector installation guide](https://blog.csdn.net/chenji_big/article/details/152044409)
- [pgvector on StackOverflow](https://stackoverflow.com/questions/75664004/install-pgv-ext-on-mac)

______________________________________________________________________

## ☁️ Google Cloud Storage Setup

### Step 1: Install Google Cloud SDK

```bash
# Install Google Cloud CLI
brew install --cask google-cloud-sdk

# Initialize gcloud
gcloud init

# Authenticate
gcloud auth login

# Set default project
gcloud config set project YOUR_PROJECT_ID
```

### Step 2: Create GCS Bucket

```bash
# Create bucket
gsutil mb gs://your-memory-backup-bucket

# Set versioning (optional, for backup history)
gsutil versioning set on gs://your-memory-backup-bucket
```

______________________________________________________________________

## 🐍 Python Implementation: pgvector + GCS

### Option 1: Direct PostgreSQL + GCS Backup

```python
"""
Memory system using pgvector + PostgreSQL + GCS backup.
No Docker/K8s, native macOS.
"""
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import psycopg
from psycopg2.sql import sql
from google.cloud import storage


class PGVectorMemoryWithGCS:
    """
    Local memory system with pgvector + Google Cloud Storage backup.

    Features:
    - Local PostgreSQL + pgvector for vector search
    - GCS backup using pg_dump
    - Oneiric-compatible configuration
    - Native macOS (no Docker)
    """

    def __init__(
        self,
        db_name: str = "memory_db",
        table_name: str = "memories",
        gcs_bucket: str = "your-memory-backup-bucket",
        gcs_prefix: str = "memory-backups",
    ):
        # PostgreSQL connection
        self.conn = psycopg.connect(
            host="localhost",
            port=5432,
            database=db_name,
            user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD", ""),
        )
        self.table_name = table_name

        # Google Cloud Storage client
        self.storage_client = storage.Client()
        self.gcs_bucket = gcs_bucket
        self.gcs_prefix = gcs_prefix

    def store_memory(
        self,
        content: str,
        embedding: List[float],
        metadata: Dict[str, Any],
    ) -> int:
        """
        Store a memory in PostgreSQL.

        Returns the memory ID.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memories (content, embedding, metadata)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (content, embedding, metadata),
            )
            memory_id = cur.fetchone()[0]
            self.conn.commit()
        return memory_id

    def recall(
        self,
        query_embedding: List[float],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Recall memories using vector similarity.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content, metadata,
                       1 - (embedding <=> %s) AS similarity
                FROM memories
                ORDER BY embedding <=> %s DESC
                LIMIT %s
                """,
                (query_embedding, query_embedding, limit),
            )
            results = cur.fetchall()

        # Convert to list of dicts
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in results]

    def backup_to_gcs(self) -> str:
        """
        Backup entire database to Google Cloud Storage.

        Returns the GCS path.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"memory_backup_{timestamp}.sql.gz"

        # 1. Dump database using pg_dump
        import subprocess

        dump_file = f"/tmp/{backup_file}"
        subprocess.run(
            [
                "pg_dump",
                "-U", os.getenv("PGUSER", "postgres"),
                "-d", self.conn.info.dbname,
                "-f", dump_file,
            ],
            check=True,
        )

        # 2. Compress
        subprocess.run(
            ["gzip", dump_file],
            check=True,
        )
        compressed_file = f"{dump_file}.gz"

        # 3. Upload to GCS
        gcs_path = f"{self.gcs_prefix}/{backup_file}"
        blob = self.storage_client.bucket(self.gcs_bucket).blob(gcs_path)
        blob.upload_from_filename(compressed_file)

        # 4. Clean up
        os.remove(compressed_file)
        os.remove(dump_file)

        print(f"✅ Backed up to GCS: {gcs_path}")
        return gcs_path

    def restore_from_gcs(self, backup_file: str) -> None:
        """
        Restore database from GCS backup.

        Args:
            backup_file: GCS path (e.g., "memory-backups/memory_backup_20250123.sql.gz")
        """
        # 1. Download from GCS
        compressed_file = f"/tmp/{os.path.basename(backup_file)}"
        blob = self.storage_client.bucket(self.gcs_bucket).blob(backup_file)
        blob.download_to_filename(compressed_file)

        # 2. Decompress
        import subprocess

        dump_file = compressed_file.replace(".gz", "")
        subprocess.run(["gunzip", compressed_file], check=True)

        # 3. Restore using psql
        subprocess.run(
            [
                "psql",
                "-U", os.getenv("PGUSER", "postgres"),
                "-d", self.conn.info.dbname,
                "-f", dump_file,
            ],
            check=True,
        )

        # 4. Clean up
        os.remove(dump_file)

        print(f"✅ Restored from GCS: {backup_file}")
```

### Option 2: Using rclone for GCS Sync

```bash
# Install rclone via Homebrew
brew install rclone

# Configure GCS as remote
rclone config create gcs remote
# Follow prompts to set OAuth2 credentials

# Sync database backups to GCS
rclone sync /path/to/postgres/backups gcs:your-bucket/postgres-backups
```

**Sources**:

- [PostgreSQL logical backup to GCS](https://blog.csdn.net/gitblog_01026/article/details/152007541)
- [Postgres to GCS backup script](https://github.com/diogopms/postgres-gcs-backup)
- [Simple Backups: Postgres to GCS](https://simplebackups.com/blog/how-to-backup-postgresql-to-google-cloud-storage-gcs)

______________________________________________________________________

## 🚀 Alternative: Weaviate (Homebrew Available)

### Installation

```bash
# Install Weaviate via Homebrew
brew install weaviate

# Or start with Docker (but you don't want this)
# docker run -p 8080:8080 weaviate/weaviate:latest
```

### GCS Integration

Weaviate supports backup via object storage:

```python
import weaviate

# Connect to local Weaviate
client = weaviate.Client(
    url="http://localhost:8080",
    auth_client_secret=os.getenv("WEAVIATE_API_KEY"),
)

# Backup to GCS
import boto3
s3 = boto3.client('s3')  # GCS is S3-compatible

# Export Weaviate data
# (implementation depends on Weaviate backup API)
```

**Source**: [Weaviate Cloud Storage docs](https://weaviate.io/documentation/cloud-storage)

______________________________________________________________________

## 🔧 Alternative: LanceDB + GCS (Embedded)

### Installation

```bash
# Install LanceDB
pip install lancedb google-cloud-storage

# Or add to pyproject.toml
lancedb>=0.11.0
google-cloud-storage>=2.0.0
```

### GCS Integration

```python
import lancedb
from google.cloud import storage

# Local LanceDB
db = lancedb.connect("./memory_db")

# Backup to GCS
db.backup.to_s3(
    "gs://your-bucket/memory-backup",
    # Uses Google Cloud Storage Python SDK under the hood
)
```

**Benefits**:

- ✅ **Embedded**: No separate database server
- ✅ **Fast**: Local queries on SSD
- ✅ **Simple**: Python-only, no configuration

______________________________________________________________________

## 🤔 What About AgentDB?

**Bad news**: AgentDB is **not available via Homebrew**

AgentDB is distributed as:

- **npm package**: `npm install agentdb`
- **MCP server**: `claude mcp add agentdb npx agentdb@latest`

### Why AgentDB Might Not Fit Your Needs

1. **Not Homebrew-installable**: Requires npm/node
1. **Newer project**: Less mature than pgvector/Weaviate
1. **Agent-focused**: Optimized for AI agents, not general memory
1. **Limited GCS integration**: Less documentation on cloud backup

**Alternative**: If you really want AgentDB features:

```bash
# Install via npm (not Homebrew)
npm install -g agentdb

# Use as library
pip install agentdb-sdk
```

**Sources**:

- [AgentDB Official Site](https://agentdb.ruv.io/)
- [AgentDB npm package](https://www.npmjs.com/package/agentdb)
- [AgentDB PyPI](https://pypi.org/project/agentDB/)

______________________________________________________________________

## 📊 Comparison Table (Native macOS + GCS)

| Solution | Homebrew | No Docker | GCS Support | Maturity |
|----------|----------|-----------|-------------|----------|
| **pgvector + PostgreSQL** | ✅ | ✅ | ✅ pg_dump+gsutil | ⭐⭐⭐⭐⭐ Production |
| **Weaviate** | ✅ | ✅ | ✅ Object storage | ⭐⭐⭐⭐ Mature |
| **LanceDB** | ✅ pip | ✅ | ✅ S3 SDK | ⭐⭐⭐⭐ Newer |
| **AgentDB** | ❌ npm | ✅ | ⚠️ Limited | ⭐⭐ New |

______________________________________________________________________

## 🎯 Recommended Architecture

```
┌─────────────────────────────────────────────────┐
│                   Your Mac (macOS)               │
│                                                 │
│  ┌──────────────────────────────────────────┐   │
│  │  PostgreSQL + pgvector (Homebrew)        │   │
│  │  ├─ memories table                       │   │
│  │  └─ vector similarity search           │   │
│  └──────────────────────────────────────────┘   │
│                      ↓                        │
│  ┌──────────────────────────────────────────┐   │
│  │  Google Cloud Storage                    │   │
│  │  ├─ Automated backups (pg_dump)        │   │
│  │  ├─ rclone sync (continuous)           │   │
│  │  └─ Oneiric storage adapter          │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

______________________________________________________________________

## 📝 Auto-Backup Setup (macOS Launchd)

### Daily Backup Script

```bash
#!/bin/bash
# backup_memory.sh

# Configuration
DB_NAME="memory_db"
GCS_BUCKET="your-memory-backup-bucket"
DATE=$(date +%Y%m%d_%H%M%S)

# Dump database
pg_dump -U postgres -d $DB_NAME | gzip > /tmp/memory_backup_$DATE.sql.gz

# Upload to GCS
gsutil cp /tmp/memory_backup_$DATE.sql.gz \
  gs://$GCS_BUCKET/memory-backups/

# Clean up
rm /tmp/memory_backup_$DATE.sql.gz

echo "✅ Memory backed up to GCS: gs://$GCS_BUCKET/memory-backups/memory_backup_$DATE.sql.gz"
```

### Install as macOS Service

```bash
# Copy script to PATH
sudo cp backup_memory.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/backup_memory.sh

# Create launchd plist
cat > ~/Library/LaunchAgents/com.memory.backup.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>Memory Database Backup</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/local/bin/backup_memory.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <integer>86400</integer>
    <key>WorkingDirectory</key>
    <string>/path/to/project</string>
  </dict>
</plist>
EOF

# Load launchd agent
launchctl load ~/Library/LaunchAgents/com.memory.backup.plist
```

______________________________________________________________________

## 🔗 Oneiric Integration

Oneiric (v0.3.0+) provides storage abstractions. Here's how to use it with GCS:

```yaml
# settings/mahavishnu.yaml
storage:
  type: "gcs"  # Google Cloud Storage
  bucket: "your-memory-bucket"
  prefix: "memories/"
  credentials:
    type: "service-account"
    path: "/path/to/service-account.json"

# Alternative: Direct PostgreSQL
storage:
  type: "postgresql"
  connection:
    host: "localhost"
    port: 5432
    database: "memory_db"
    user: "postgres"
```

______________________________________________________________________

## 💡 Why This is Better Than AgentDB

1. **Homebrew available**: No npm/node dependency
1. **Mature ecosystem**: PostgreSQL has 30+ years of production use
1. **Better GCS tools**: pg_dump + gsutil are battle-tested
1. **PostgreSQL + pgvector** = Used by Google Cloud SQL
1. **No Docker required**: Pure Python + Homebrew
1. **Oneiric-compatible**: Can leverage Oneiric storage patterns

______________________________________________________________________

## 🚀 Quick Start (5 Minutes)

```bash
# 1. Install PostgreSQL + pgvector
brew install postgresql@16 pgvector
brew services start postgresql@16

# 2. Initialize database
psql postgres -c "CREATE DATABASE memory_db;"
psql memory_db -c "CREATE EXTENSION vector;"
psql memory_db -c "CREATE TABLE memories (content TEXT, embedding vector(1536));"

# 3. Install dependencies
pip install psycopg2-binary google-cloud-storage

# 4. Test backup
python backup_memory.py  # Script from above

# 5. Schedule auto-backup
# Follow launchd setup above
```

______________________________________________________________________

## 📚 Complete Source List

### pgvector + GCS

- [PostgreSQL pgvector Setup Guide](https://thedbadmin.com/blog/postgresql-pgvector-setup-guide)
- [Install pgvector on macOS](https://stackoverflow.com/questions/75664004/install-pgv-ext-on-mac)
- [Postgres to GCS backup guide](https://blog.csdn.net/gitblog_01026/article/details/152007541)
- [Postgres GCS backup tool](https://github.com/diogopms/postgres-gcs-backup)

### Weaviate

- [Weaviate Homepage](https://weaviate.io/)
- [Weaviate Cloud Storage](https://weaviate.io/documentation/cloud-storage)

### LanceDB

- [LanceDB Official Site](https://lancedb.com/)
- [Install Vector with Homebrew](https://vector.dev/docs/setup/installation/package-managers/homebrew/)

### GCS Tools

- [Google Cloud SDK](https://cloud.google.com/sdk/docs)
- [rclone for GCS sync](https://rclone.org/)

### AgentDB Information

- [AgentDB Official Site](https://agentdb.ruv.io/)
- [AgentDB npm package](https://www.npmjs.com/package/agentdb)
- [AgentDB integration discussion](https://github.com/ruvnet/claude-flow/issues/829)

______________________________________________________________________

## Summary

**Recommended Stack**: PostgreSQL + pgvector + GCS Backup

**Why**:

- ✅ 100% native macOS (Homebrew + Python)
- ✅ No Docker or Kubernetes required
- ✅ GCS backup with pg_dump + gsutil
- ✅ Production-proven (used by Google Cloud SQL)
- ✅ Oneiric-compatible storage patterns
- ✅ Mature ecosystem (30+ years of PostgreSQL)

**Cost**:

- **Local**: Free (self-hosted)
- **GCS storage**: ~$0.026/GB/month (standard)
  - 100GB = ~$2.60/month
  - 1TB = ~$26/month

**Migration from AutoMem**: Easy! Both use PostgreSQL (FalkorDB in AutoMem, PostgreSQL in pgvector).
