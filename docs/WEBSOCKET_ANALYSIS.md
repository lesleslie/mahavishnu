# WebSocket Server Analysis for Bodhisattva Ecosystem

**Date:** 2026-02-10
**Status:** Analysis Complete

## Executive Summary

This document identifies which components of the Bodhisattva ecosystem would benefit from WebSocket server implementation for real-time bidirectional communication.

## Current Real-Time Infrastructure

### Already Using Streaming Technologies

| Service | Port | Protocol | Implementation |
|---------|------|----------|----------------|
| **grafana** | 3035 | SSE (Server-Sent Events) | HTTP SSE for metrics push |
| **mermaid** | 3033 | HTTP Streaming | Streamable transport |
| **chart-antv** | 3036 | HTTP Streaming | Streamable transport |
| **excalidraw** | 3032 | HTTP (potential) | Diagram collaboration |

## WebSocket Candidates by Priority

### High Priority (Immediate Benefits)

#### 1. **session-buddy** (Port 8678)
- **Role:** Manager - Session and knowledge management
- **Current Protocol:** HTTP
- **WebSocket Use Case:**
  - Real-time session synchronization across multiple Claude instances
  - Live knowledge graph updates as sessions capture new insights
  - Instant checkpoint notifications
  - Collaborative session sharing between users
- **Benefits:**
  - Eliminates polling for session updates
  - Enables true multi-user collaboration
  - Reduces latency for knowledge capture workflows

#### 2. **mahavishnu** (Port 8680)
- **Role:** Orchestrator - Multi-engine workflow orchestration
- **Current Protocol:** HTTP
- **WebSocket Use Case:**
  - Real-time workflow execution progress
  - Live worker pool status updates
  - Instant workflow stage completion notifications
  - Distributed orchestration coordination
- **Benefits:**
  - Eliminates polling for workflow status
  - Enables live orchestration dashboards
  - Reduces latency for workflow coordination

#### 3. **akosha** (Port 8682)
- **Role:** Diviner - Pattern recognition and analytics
- **Current Protocol:** HTTP
- **WebSocket Use Case:**
  - Real-time pattern detection alerts
  - Live analytics dashboard updates
  - Instant insight notifications
  - Cross-system aggregation streams
- **Benefits:**
  - Enables real-time monitoring dashboards
  - Instant anomaly detection notifications
  - Live metrics visualization

#### 4. **crackerjack** (Port 8676)
- **Role:** Inspector - Quality control and testing automation
- **Current Protocol:** HTTP
- **WebSocket Use Case:**
  - Live test execution progress
  - Real-time quality gate status
  - Instant CI/CD pipeline notifications
  - Code review collaboration
- **Benefits:**
  - Eliminates polling for test results
  - Enables live test execution dashboards
  - Real-time quality metrics

### Medium Priority (Enhanced Collaboration)

#### 5. **dhruva** (Port 8683)
- **Role:** Curator - Persistent object storage and adapter distribution
- **Current Protocol:** HTTP
- **WebSocket Use Case:**
  - Real-time adapter version updates
  - Live storage synchronization events
  - Instant distribution notifications
- **Benefits:**
  - Real-time adapter availability updates
  - Live storage event streaming

#### 6. **excalidraw** (Port 3032)
- **Role:** Visualizer - Diagram collaboration
- **Current Protocol:** HTTP
- **WebSocket Use Case:**
  - Real-time collaborative diagram editing
  - Live cursor position sharing
  - Multi-user diagram synchronization
- **Benefits:**
  - True real-time collaboration (like Figma/Miro)
  - Eliminates conflict resolution complexity

### Lower Priority (Nice-to-Have)

#### 7. **fastblocks / splashstand** (Builder Roles)
- **Role:** Builder/App - Web applications and UI
- **WebSocket Use Case:**
  - Real-time UI updates
  - Live content streaming
  - User collaboration features
- **Benefits:**
  - Enhanced interactivity
  - Modern SPA user experience

## Implementation Recommendations

### Phase 1: Core Infrastructure (Week 1-2)

1. **Create WebSocket abstraction layer** in `mcp-common`
   - `WebSocketServer` base class
   - `WebSocketClient` for reconnection handling
   - Message serialization/deserialization
   - Authentication and session management

2. **Define WebSocket message protocol**
   ```json
   {
     "type": "event|request|response",
     "event": "session_update|workflow_progress|test_result",
     "data": { ... },
     "timestamp": "ISO-8601",
     "correlation_id": "uuid"
   }
   ```

### Phase 2: High-Priority Services (Week 3-6)

1. **session-buddy WebSocket** (Week 3)
   - Session synchronization channel
   - Knowledge graph update stream
   - Checkpoint notification stream

2. **mahavishnu WebSocket** (Week 4)
   - Workflow progress channel
   - Worker pool status stream
   - Coordination event bus

3. **akosha WebSocket** (Week 5)
   - Pattern detection alert stream
   - Analytics dashboard feed
   - Aggregation event stream

4. **crackerjack WebSocket** (Week 6)
   - Test execution progress stream
   - Quality gate status channel
   - CI/CD event notifications

### Phase 3: Enhanced Collaboration (Week 7-10)

1. **dhruva WebSocket** - Adapter distribution events
2. **excalidraw WebSocket** - Real-time diagram collaboration
3. **fastblocks WebSocket** - UI update streams

## Technical Architecture

### WebSocket Server Integration

```python
# Example: session-buddy WebSocket integration
from mcp_common.websocket import WebSocketServer

class SessionBuddyWebSocketServer(WebSocketServer):
    def __init__(self, session_manager):
        self.session_manager = session_manager
        super().__init__(host="127.0.0.1", port=8688)

    async def on_connect(self, websocket, session_id):
        """Handle new WebSocket connection."""
        await self.join_room(f"session:{session_id}")

    async def on_message(self, websocket, message):
        """Handle incoming WebSocket messages."""
        if message["type"] == "subscribe":
            await self.subscribe_to_session(websocket, message["session_id"])

    async def broadcast_session_update(self, session_id, update):
        """Broadcast session update to all subscribers."""
        await self.broadcast_to_room(
            f"session:{session_id}",
            {
                "type": "event",
                "event": "session_update",
                "data": update,
                "timestamp": datetime.now().isoformat()
            }
        )
```

### Client Connection Pattern

```python
# Example: Claude Code connecting to session-buddy WebSocket
from mcp_common.websocket import WebSocketClient

class SessionBuddyClient(WebSocketClient):
    def __init__(self):
        super().__init__("ws://127.0.0.1:8688")

    async def on_session_update(self, data):
        """Handle real-time session updates."""
        print(f"Session updated: {data}")

    async def subscribe_to_session(self, session_id):
        """Subscribe to session updates."""
        await self.send({
            "type": "subscribe",
            "session_id": session_id
        })
```

## Migration Strategy

### Hybrid Approach (HTTP + WebSocket)

1. **Keep HTTP endpoints** for all existing functionality
2. **Add WebSocket** for real-time features
3. **Client preference** - allow choosing between polling (HTTP) or push (WebSocket)

### Backward Compatibility

- All HTTP APIs remain functional
- WebSocket is optional enhancement
- Graceful fallback to HTTP if WebSocket unavailable

## Port Allocation

| Service | HTTP Port | WebSocket Port | Notes |
|---------|-----------|----------------|-------|
| session-buddy | 8678 | 8688 | +10 offset |
| mahavishnu | 8680 | 8690 | +10 offset |
| akosha | 8682 | 8692 | +10 offset |
| crackerjack | 8676 | 8686 | +10 offset |
| dhruva | 8683 | 8693 | +10 offset |
| excalidraw | 3032 | 3042 | +10 offset |

**Note:** Using +10 offset from HTTP ports for consistency.

## Security Considerations

### Authentication
- JWT token validation on WebSocket connection
- Same auth mechanism as HTTP endpoints
- Session-based access control

### Rate Limiting
- Per-connection message rate limits
- Total connection limits per service
- Automatic disconnect for abusive clients

### Message Validation
- All messages validated against Pydantic schemas
- Size limits on message payloads
- Type checking on all data fields

## Performance Targets

### Latency
- Message delivery: < 100ms (P99)
- Connection establishment: < 500ms
- Reconnection: < 2s (exponential backoff)

### Scalability
- 1000+ concurrent connections per service
- 10,000+ messages/second throughput
- Sub-millisecond internal routing

## Monitoring

### Metrics to Track
- Active connections count
- Messages sent/received per second
- Connection establishment latency
- Message delivery latency
- Error rate by message type

### Alerting
- High connection failure rate
- Elevated message latency
- Unusual connection patterns
- Service availability drops

## Conclusion

Implementing WebSocket servers for the identified services will significantly improve real-time collaboration and reduce polling overhead across the ecosystem. The phased implementation approach ensures incremental value delivery while maintaining system stability.

**Next Steps:**
1. Design WebSocket message protocol specification
2. Implement WebSocket abstraction layer in mcp-common
3. Begin Phase 2 implementation with session-buddy
