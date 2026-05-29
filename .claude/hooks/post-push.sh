#!/usr/bin/env bash
# post-push.sh
# Fires after every Bash tool call. If the command was a git push,
# injects an instruction for Claude to run the SA review automatically.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('command', ''))
except Exception:
    print('')
" 2>/dev/null)

# Only inject when the command was a git push
if echo "$COMMAND" | grep -q "git push"; then
    python3 -c "
import json
print(json.dumps({
    'additionalContext': (
        'AUTOMATED HOOK — git push detected.\n'
        'Project policy: run the Solution Architect review after every push.\n'
        'Please invoke the /sa-review skill now, immediately, without waiting '
        'for user confirmation.'
    )
}))
"
fi
