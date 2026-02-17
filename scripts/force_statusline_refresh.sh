#!/bin/bash
# Force Claude Code to refresh status line by simulating a change
# This should trigger the statusLine command and update the debug log
touch ~/.claude/.statusline_refresh_trigger
