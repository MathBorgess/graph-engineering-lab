---
name: system-profiler
description: Guidelines for safely probing host environment, CPU architecture, OS kernel, and memory limits.
triggers:
  - system
  - host
  - environment
  - os
  - kernel
skips: []
---

# System Profiler Skill

When inspecting host environment:
1. Always identify the platform family, architecture (arm64 vs x86_64), and Python version.
2. In macOS Darwin, distinguish between userland environment and kernel version.
3. Report memory allocations with unit conversions (Bytes, KB, MB, GB).
4. Cross-reference OS capabilities with the active proxy port (8000/9300).
