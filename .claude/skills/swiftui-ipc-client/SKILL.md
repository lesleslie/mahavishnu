______________________________________________________________________

## name: swiftui-ipc-client description: Use when building native macOS SwiftUI apps that talk to Python backends over Unix sockets.

# SwiftUI IPC Client

## Overview

Use this skill for native macOS SwiftUI apps that communicate with a Python backend via Unix Domain Socket and JSON-RPC 2.0.

## When to Use

- Building a native macOS app with a Python helper process
- Implementing IPC between SwiftUI and backend services
- Defining type-safe JSON-RPC methods and socket paths

## Core Pattern

- SwiftUI views own presentation.
- App state owns UI state and service calls.
- An IPC client handles socket connection and JSON-RPC transport.
- The Python process exposes the backend methods.

## Notes

- Keep the socket path convention consistent.
- Use Codable request and response types.
- Prefer a small, explicit method surface over ad hoc IPC calls.
