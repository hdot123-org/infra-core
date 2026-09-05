#!/usr/bin/env python3
"""write_comment.py — Linear GraphQL comment writer.

Usage: write_comment.py <issue_uuid> <api_key> <body_file>
"""
import json
import sys
import urllib.request

def main():
    if len(sys.argv) < 4:
        print("Usage: write_comment.py <issue_uuid> <api_key> <body_file>", file=sys.stderr)
        sys.exit(1)

    issue_uuid = sys.argv[1]
    api_key = sys.argv[2]
    body_file = sys.argv[3]

    with open(body_file) as f:
        body = f.read()

    payload = json.dumps({
        "query": "mutation($issueId: String!, $body: String!) { commentCreate(input: { issueId: $issueId, body: $body }) { success comment { id } } }",
        "variables": {"issueId": issue_uuid, "body": body}
    })

    req = urllib.request.Request(
        "https://api.linear.app/graphql",
        data=payload.encode(),
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = resp.read().decode()
            print(f"Linear API response: {result}")
    except Exception as e:
        print(f"Failed to write comment: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
