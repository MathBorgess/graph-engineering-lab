---
name: audit_code
description: "Rigorously audit code changes for security, resource leaks, and regressions."
model_invoked: false
triggers:
  - audit
---

# Code Audit Directives
- Check all file writes to ensure no files outside the worktree are touched.
- Ensure no secret tokens or credentials are logged.
- Verify error handling and exit codes.
