"""Sistema de Deferred Skills com catálogo compacto (<= 110 chars) e carregamento sob demanda."""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import yaml
from langchain_core.tools import tool


class SkillDescriptor:
    """Descritor leve de uma skill para exibição no catálogo inicial."""

    def __init__(
        self,
        name: str,
        description: str,
        triggers: List[str],
        skips: Optional[List[str]] = None,
        path: Optional[Path] = None,
        model_invoked: bool = True,
    ):
        self.name = name
        self.description = description
        self.triggers = triggers
        self.skips = skips or []
        self.path = path
        self.model_invoked = model_invoked

    def get_compact_description(self, max_length: int = 110) -> str:
        """Retorna a descrição truncada em até max_length caracteres."""
        desc = " ".join(self.description.strip().split())
        if len(desc) <= max_length:
            return desc
        return desc[: max_length - 3].rstrip() + "..."


class DeferredSkillsRegistry:
    """Gerencia a descoberta de pacotes de skills e a carga progressiva de SKILL.md."""

    def __init__(self, catalog_dir: Optional[Path] = None):
        self.catalog_dir = catalog_dir or (Path(__file__).parent / "catalog")
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        self._skills: Dict[str, SkillDescriptor] = {}
        self.refresh()

    def refresh(self) -> None:
        """Escanêa catalog_dir por subpastas contendo SKILL.md com frontmatter YAML."""
        self._skills.clear()
        if not self.catalog_dir.exists():
            return

        for skill_dir in self.catalog_dir.iterdir():
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
                    model_invoked = meta.get("model_invoked", True)
                    self._skills[name] = SkillDescriptor(
                        name=name,
                        description=desc,
                        triggers=triggers if isinstance(triggers, list) else [triggers],
                        skips=skips if isinstance(skips, list) else [skips],
                        path=skill_md,
                        model_invoked=model_invoked,
                    )
                except Exception:
                    pass

    def get_compact_catalog_prompt(self, max_desc_len: int = 110) -> str:
        """Gera o bloco markdown de catálogo compacto contendo apenas skills onde model_invoked == True."""
        active_skills = [s for s in self._skills.values() if s.model_invoked]
        if not active_skills:
            return "No autonomous deferred skills registered."

        lines = [
            "## Available Deferred Skills",
            "You can dynamically load full instructions for any skill using the `load_skill(name)` tool:",
        ]
        for s in active_skills:
            compact_desc = s.get_compact_description(max_desc_len)
            lines.append(f"- `{s.name}`: {compact_desc}")
        return "\n".join(lines)

    def preprocess_slash_command(self, user_message: str) -> tuple[str, bool]:
        """Intercepta comandos como /SKILL_NAME e injeta as instruções da skill diretamente no prompt.
        
        Retorna (mensagem_processada, foi_interceptada).
        """
        stripped = user_message.strip()
        if not stripped.startswith("/"):
            return user_message, False

        parts = stripped.split(maxsplit=1)
        command = parts[0][1:]  # remove a barra '/'
        extra_text = parts[1] if len(parts) > 1 else ""

        if command in self._skills:
            skill_content = self.load_skill(command)
            injected_prompt = (
                f"### [Human Directive: Activated Skill /{command}]\n\n"
                f"{skill_content}\n\n"
                f"### User Instruction:\n{extra_text or 'Execute according to the activated skill guidelines.'}"
            )
            return injected_prompt, True

        return user_message, False

    def load_skill(self, skill_name: str) -> str:
        """Lê e retorna as instruções limpas do SKILL.md sob demanda (Progressive Disclosure)."""
        descriptor = self._skills.get(skill_name)
        if not descriptor or not descriptor.path or not descriptor.path.exists():
            available = ", ".join(f"`{k}`" for k in self._skills.keys())
            return f"Error: Skill '{skill_name}' not found. Available skills: {available or 'None'}."

        raw = descriptor.path.read_text(encoding="utf-8")
        # Remove o frontmatter YAML para entregar apenas as diretrizes operacionais limpas
        body = re.sub(r"^---\n.*?\n---\n*", "", raw, flags=re.DOTALL).strip()

        # Checa se há pasta de referências complementares (nível 2 de progressive disclosure)
        ref_dir = descriptor.path.parent / "references"
        ref_note = ""
        if ref_dir.exists() and ref_dir.is_dir():
            refs = [f.name for f in ref_dir.iterdir() if f.is_file()]
            if refs:
                ref_note = f"\n\n*Secondary references available in `{ref_dir.name}/`: {', '.join(refs)}. Read them only if needed.*"

        return f"# Loaded Skill: {descriptor.name}\n\n{body}{ref_note}"

    def build_tool(self):
        """Retorna uma Tool do LangChain vinculada a este registro."""
        registry = self

        @tool
        def load_skill(skill_name: str) -> str:
            """Load detailed instructions, schema rules, and workflows for a specific domain skill.
            
            Args:
                skill_name: The exact name of the skill from the Available Deferred Skills catalog.
            """
            return registry.load_skill(skill_name)

        return load_skill
