"""
UCust AI — Unified Skill Registry & Progressive Skill Loader.
============================================================
Provides progressive disclosure of modular agent capabilities:
1. Discovery: Lightweight metadata (~50 tokens per skill) for LLM context.
2. Activation: Full instructions and rules loaded only when task matches skill intent.
3. Execution: Direct invocation of underlying skills engines without context pollution.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SkillManifest:
    """Lightweight metadata descriptor for a registered skill."""
    name: str
    description: str
    target_agents: List[str]
    category: str
    skill_dir: Path
    triggers: List[str] = field(default_factory=list)
    version: str = "1.0.0"

    def get_discovery_snippet(self) -> str:
        """Compact summary used in system prompts during discovery phase."""
        triggers_str = ", ".join(self.triggers) if self.triggers else "auto"
        return f"- **{self.name}** [{self.category}]: {self.description} (triggers: {triggers_str})"

    def load_full_instructions(self) -> str:
        """Load full SKILL.md body during activation phase."""
        skill_file = self.skill_dir / "SKILL.md"
        if skill_file.is_file():
            content = skill_file.read_text(encoding="utf-8")
            # Strip YAML frontmatter if present
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
            return content.strip()
        return f"Skill {self.name}: No detailed SKILL.md file found."


class SkillRegistry:
    """Central registry and progressive loader for all UCust AI agent skills."""

    _instance: Optional["SkillRegistry"] = None

    def __init__(self, skills_root: Optional[Path] = None):
        self.skills_root = skills_root or Path(__file__).parent
        self._skills: Dict[str, SkillManifest] = {}
        self.discover_skills()

    @classmethod
    def get_instance(cls, skills_root: Optional[Path] = None) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = cls(skills_root)
        return cls._instance

    def register_skill(self, manifest: SkillManifest) -> None:
        self._skills[manifest.name] = manifest

    def discover_skills(self) -> Dict[str, SkillManifest]:
        """Scan skills_root for directories containing SKILL.md."""
        self._skills.clear()

        if not self.skills_root.is_dir():
            return self._skills

        for item in self.skills_root.iterdir():
            if item.is_dir() and (item / "SKILL.md").is_file():
                manifest = self._parse_skill_file(item / "SKILL.md", item)
                if manifest:
                    self._skills[manifest.name] = manifest

        return self._skills

    def _parse_skill_file(self, skill_file: Path, skill_dir: Path) -> Optional[SkillManifest]:
        try:
            content = skill_file.read_text(encoding="utf-8")
            name = skill_dir.name
            description = "Specialized agent capability module"
            target_agents = ["all"]
            category = "general"
            triggers = []
            version = "1.0.0"

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    for line in frontmatter.strip().splitlines():
                        if ":" in line:
                            k, _, v = line.partition(":")
                            k, v = k.strip().lower(), v.strip().strip('"').strip("'")
                            if k == "name":
                                name = v
                            elif k == "description":
                                description = v
                            elif k == "agents" or k == "target_agents":
                                target_agents = [a.strip() for a in v.split(",") if a.strip()]
                            elif k == "category":
                                category = v
                            elif k == "triggers":
                                triggers = [t.strip() for t in v.split(",") if t.strip()]
                            elif k == "version":
                                version = v

            return SkillManifest(
                name=name,
                description=description,
                target_agents=target_agents,
                category=category,
                skill_dir=skill_dir,
                triggers=triggers,
                version=version,
            )
        except Exception:
            return None

    def get_skills_for_agent(self, agent_name: str) -> List[SkillManifest]:
        """Return all skills available for a specific agent (e.g. Agent_Copywriter)."""
        res = []
        normalized_name = agent_name.lower().replace(" ", "_")
        for s in self._skills.values():
            targets = [t.lower().replace(" ", "_") for t in s.target_agents]
            if "all" in targets or normalized_name in targets or any(normalized_name.endswith(t) for t in targets):
                res.append(s)
        return res

    def get_prompt_discovery_block(self, agent_name: str) -> str:
        """Generate compact markdown listing available skills for the agent."""
        skills = self.get_skills_for_agent(agent_name)
        if not skills:
            return ""
        lines = [
            f"### Доступные навыки агента `{agent_name}` (Active Skills):"
        ]
        for s in skills:
            lines.append(s.get_discovery_snippet())
        return "\n".join(lines)

    def activate_skill(self, skill_name: str) -> Optional[str]:
        """Activate and return full instructions for a named skill."""
        manifest = self._skills.get(skill_name)
        if manifest:
            return manifest.load_full_instructions()
        return None

    def auto_activate_for_task(self, agent_name: str, task_context: str) -> str:
        """Find matching skills by triggers and return activated instruction blocks."""
        skills = self.get_skills_for_agent(agent_name)
        matched_instructions = []
        task_lower = task_context.lower()

        for s in skills:
            is_matched = False
            for trigger in s.triggers:
                if trigger.lower() in task_lower:
                    is_matched = True
                    break
            if is_matched:
                matched_instructions.append(
                    f"#### [ACTIVATED SKILL: {s.name}]\n{s.load_full_instructions()}"
                )

        if matched_instructions:
            return "\n\n---\n\n".join(matched_instructions)
        return ""


__all__ = ["SkillManifest", "SkillRegistry"]
