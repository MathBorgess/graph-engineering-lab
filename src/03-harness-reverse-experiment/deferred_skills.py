"""
Deferred Skills & Tool Registry for DeepAgents
==============================================
Replicates the on-demand skill discovery and progressive disclosure mechanisms
reverse-engineered from Claude Code and OpenAI Codex.

Key Design Principles:
1. Compact Catalog Exposure:
   - Exposes only lightweight descriptors (name, description, triggers) to the Planner.
   - Protects the agent's initial prompt context budget.
2. Context Deferred Loading:
   - Full instructions inside `SKILL.md` are only loaded into working memory when
     actively invoked by the Directive or explicit user keyword.
3. Progressive Disclosure:
   - Secondary reference docs (e.g. `references/`) are kept deferred until the skill
     specifically routes to them.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class SkillDescriptor:
    """Represents a lightweight skill descriptor for initial context."""

    def __init__(
        self,
        name: str,
        description: str,
        triggers: List[str],
        skips: Optional[List[str]] = None,
        path: Optional[Path] = None,
    ):
        self.name = name
        self.description = description
        self.triggers = triggers
        self.skips = skips or []
        self.path = path

    def matches_goal(self, user_goal: str) -> bool:
        """Determines if the skill triggers based on user goal."""
        goal_lower = user_goal.lower()

        # Check skips first
        for skip in self.skips:
            if skip.lower() in goal_lower:
                return False

        # Explicit name match or trigger keyword match
        if self.name.lower() in goal_lower:
            return True

        for trig in self.triggers:
            if trig.lower() in goal_lower:
                return True

        return False


class DeferredSkillsRegistry:
    """Manages skill catalog registration, trigger evaluation, and on-demand loading."""

    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or (Path(__file__).parent / "project_skills")
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._skills: Dict[str, SkillDescriptor] = {}
        self.refresh_catalog()

    def refresh_catalog(self):
        """Scans the skills directory for SKILL.md packages."""
        self._skills.clear()
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            content = skill_md.read_text(encoding="utf-8")
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                try:
                    meta = yaml.safe_load(match.group(1)) or {}
                    name = meta.get("name", skill_dir.name)
                    desc = meta.get("description", "")
                    triggers = meta.get("triggers", [name])
                    skips = meta.get("skips", [])
                    self._skills[name] = SkillDescriptor(
                        name=name,
                        description=desc,
                        triggers=triggers if isinstance(triggers, list) else [triggers],
                        skips=skips if isinstance(skips, list) else [skips],
                        path=skill_md,
                    )
                except Exception:
                    pass

    def get_compact_catalog(self) -> List[Dict[str, Any]]:
        """Returns the lightweight catalog for the Planner's initial prompt."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "triggers": s.triggers,
            }
            for s in self._skills.values()
        ]

    def evaluate_triggers(self, user_goal: str) -> List[str]:
        """Identifies skills that should be activated for a given goal."""
        return [name for name, s in self._skills.items() if s.matches_goal(user_goal)]

    def load_skill_content(self, skill_name: str) -> Optional[str]:
        """Deferred loading: loads the full instruction markdown only when requested."""
        desc = self._skills.get(skill_name)
        if not desc or not desc.path or not desc.path.exists():
            return None
        return desc.path.read_text(encoding="utf-8")
