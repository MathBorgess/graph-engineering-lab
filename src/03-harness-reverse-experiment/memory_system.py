"""
Project-Level Persistent Memory Engine for DeepAgents
=====================================================
Replicates the memory generation, loading, and progressive disclosure architecture
reverse-engineered from Claude Code (Auto-Memory) and OpenAI Codex (Consolidated Memories).

Key Design Principles:
1. Master Index (MEMORY.md):
   - Fast, token-efficient index containing 1-line pointers: `- [slug](slug.md) — description`
   - Loaded into conversation context on turn planning (budget-constrained).
2. Specialized Memory Files (<slug>.md):
   - Structured with YAML frontmatter: name, description, metadata.type
   - Body contains: Fact/Rule, **Why:**, **How to apply:**, and [[linked-memories]]
3. Four Canonical Memory Types:
   - `user`: Role, preferences, background, experience level.
   - `feedback`: Corrections ("don't do X") and validated approaches ("yes, keep doing Y").
   - `project`: Architecture constraints, deadlines, business context.
   - `reference`: Pointers to external tools, docs, and databases.
4. Memory Creation & Consolidation:
   - Extracts durable lessons from execution traces and user feedback.
   - Writes new memory files and keeps MEMORY.md index synchronized.
"""

import datetime
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class MemoryItem:
    """Represents a discrete memory entry."""

    def __init__(
        self,
        slug: str,
        name: str,
        description: str,
        memory_type: str,
        content: str,
        why: Optional[str] = None,
        how_to_apply: Optional[str] = None,
        links: Optional[List[str]] = None,
        created_at: Optional[str] = None,
    ):
        self.slug = slug
        self.name = name
        self.description = description
        self.memory_type = memory_type  # user | feedback | project | reference
        self.content = content
        self.why = why or ""
        self.how_to_apply = how_to_apply or ""
        self.links = links or []
        self.created_at = created_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def to_markdown(self) -> str:
        """Serializes memory item to markdown with frontmatter."""
        frontmatter = {
            "name": self.name,
            "description": self.description,
            "metadata": {
                "type": self.memory_type,
                "created_at": self.created_at,
                "links": self.links,
            },
        }
        yaml_str = yaml.dump(frontmatter, sort_keys=False).strip()
        body = f"{self.content}\n\n**Why:** {self.why}\n\n**How to apply:** {self.how_to_apply}"
        if self.links:
            links_str = " ".join(f"[[{link}]]" for link in self.links)
            body += f"\n\n**Related:** {links_str}"
        return f"---\n{yaml_str}\n---\n\n{body}\n"

    @classmethod
    def from_markdown(cls, slug: str, raw_text: str) -> "MemoryItem":
        """Parses markdown with frontmatter into a MemoryItem."""
        match = re.match(r"^---\n(.*?)\n---\n\n?(.*)$", raw_text, re.DOTALL)
        if not match:
            return cls(
                slug=slug,
                name=slug,
                description="",
                memory_type="project",
                content=raw_text.strip(),
            )
        frontmatter_str, body = match.groups()
        try:
            meta = yaml.safe_load(frontmatter_str) or {}
        except Exception:
            meta = {}

        name = meta.get("name", slug)
        desc = meta.get("description", "")
        mem_type = meta.get("metadata", {}).get("type", "project")
        links = meta.get("metadata", {}).get("links", [])
        created_at = meta.get("metadata", {}).get("created_at")

        # Parse why and how to apply from body
        why_match = re.search(r"\*\*Why:\*\*\s*(.*?)(?=\n\n|\Z)", body, re.DOTALL)
        how_match = re.search(r"\*\*How to apply:\*\*\s*(.*?)(?=\n\n|\Z)", body, re.DOTALL)

        why = why_match.group(1).strip() if why_match else ""
        how = how_match.group(1).strip() if how_match else ""

        # Clean base content
        clean_content = re.sub(r"\*\*Why:\*\*.*", "", body, flags=re.DOTALL).strip()

        return cls(
            slug=slug,
            name=name,
            description=desc,
            memory_type=mem_type,
            content=clean_content,
            why=why,
            how_to_apply=how,
            links=links,
            created_at=created_at,
        )


class ProjectMemoryEngine:
    """Manages the lifecycle of project-level persistent memory."""

    def __init__(self, memory_dir: Optional[Path] = None):
        self.memory_dir = memory_dir or (Path(__file__).parent / "project_memory")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.memory_dir / "MEMORY.md"
        self._ensure_index()

    def _ensure_index(self):
        """Ensures MEMORY.md index file exists."""
        if not self.index_file.exists():
            self.index_file.write_text(
                "# Project Memory Index\n"
                "Auto-generated index of persistent memories for this project.\n\n",
                encoding="utf-8",
            )

    def list_index(self, max_entries: int = 100) -> List[Dict[str, str]]:
        """Reads the master MEMORY.md index and returns compact entry descriptors."""
        entries = []
        if not self.index_file.exists():
            return entries

        lines = self.index_file.read_text(encoding="utf-8").splitlines()
        for line in lines[:max_entries]:
            # Pattern: - [Slug](slug.md) — Description [type]
            match = re.match(r"^-\s+\[(.*?)\]\((.*?)\.md\)\s*[—\-:]\s*(.*?)(?:\s*\[(.*?)\])?$", line.strip())
            if match:
                title, slug, desc, mtype = match.groups()
                entries.append({
                    "title": title,
                    "slug": slug,
                    "description": desc.strip(),
                    "type": (mtype or "project").strip(),
                })
        return entries

    def get_memory(self, slug: str) -> Optional[MemoryItem]:
        """Loads a specific memory item by slug (progressive disclosure)."""
        file_path = self.memory_dir / f"{slug}.md"
        if not file_path.exists():
            return None
        text = file_path.read_text(encoding="utf-8")
        return MemoryItem.from_markdown(slug, text)

    def save_memory(self, item: MemoryItem) -> str:
        """Persists a memory item and updates the master MEMORY.md index."""
        file_path = self.memory_dir / f"{item.slug}.md"
        file_path.write_text(item.to_markdown(), encoding="utf-8")
        self._update_index_entry(item)
        return str(file_path)

    def _update_index_entry(self, item: MemoryItem):
        """Adds or updates the 1-line hook in MEMORY.md."""
        existing_lines = []
        if self.index_file.exists():
            existing_lines = self.index_file.read_text(encoding="utf-8").splitlines()

        hook_line = f"- [{item.name}]({item.slug}.md) — {item.description} [{item.memory_type}]"
        updated = False
        new_lines = []

        for line in existing_lines:
            if f"({item.slug}.md)" in line:
                new_lines.append(hook_line)
                updated = True
            else:
                new_lines.append(line)

        if not updated:
            new_lines.append(hook_line)

        self.index_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def query_relevant_memories(self, query: str, top_k: int = 3) -> List[MemoryItem]:
        """Scans the index descriptors and loads only the top-k relevant full memory items."""
        index_entries = self.list_index()
        query_words = set(re.findall(r"\w+", query.lower()))

        scored_entries = []
        for entry in index_entries:
            text_to_match = f"{entry['title']} {entry['description']} {entry['type']}".lower()
            entry_words = set(re.findall(r"\w+", text_to_match))
            overlap = len(query_words.intersection(entry_words))
            scored_entries.append((overlap, entry["slug"]))

        scored_entries.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, slug in scored_entries[:top_k]:
            item = self.get_memory(slug)
            if item:
                results.append(item)
        return results
