#!/bin/bash
# Toggle between LiteLLM proxy and Claude subscription

MODE=${1:-status}

case $MODE in
  proxy)
    echo "Enabling LiteLLM proxy mode..."
    export ANTHROPIC_BASE_URL="http://localhost:4000"
    echo "✅ Proxy mode enabled - all models available"
    echo "Models: Claude, GPT-5.1-Codex, Mistral, Gemini, Qwen"
    ;;

  subscription)
    echo "Enabling Claude subscription mode..."
    unset ANTHROPIC_BASE_URL
    echo "✅ Subscription mode enabled - Claude models only"
    echo "Using your Claude Pro subscription"
    ;;

  status)
    if [ -z "$ANTHROPIC_BASE_URL" ]; then
      echo "📱 Current mode: Claude Subscription"
    else
      echo "🌐 Current mode: LiteLLM Proxy ($ANTHROPIC_BASE_URL)"
    fi
    ;;

  *)
    echo "Usage: $0 {proxy|subscription|status}"
    exit 1
    ;;
esac
