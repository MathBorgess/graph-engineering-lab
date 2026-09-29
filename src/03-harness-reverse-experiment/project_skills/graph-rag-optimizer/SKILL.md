---
name: graph-rag-optimizer
description: Guidelines and calculations for optimizing KnowledgeGraph RAG pipelines and triple indexing.
triggers:
  - graphrag
  - graph rag
  - triple
  - knowledge graph
skips:
  - bash
---

# GraphRAG Optimization Skill

When tasked with designing or sizing GraphRAG components:
1. **Node Record Overhead**:
   - In-memory node representation: 128 bytes minimum per node.
   - Relation triple (Subject-Predicate-Object): 96 bytes per edge.
2. **Formula for Graph Memory**:
   - `Total Bytes = (Nodes * 128) + (Edges * 96)`
   - To get Megabytes: divide total bytes by `(1024 * 1024)`.
3. **Execution Procedure**:
   - Always run arithmetic via the `calculate` tool to avoid approximation.
   - Check if graph density ratio (Edges / Nodes) exceeds 3.0. If so, recommend adjacency list compression.
