"""
SchemaManager: loads schema.yaml and provides hierarchy traversal + LLM prompt context.
"""
import pathlib
from typing import Any

import yaml


class SchemaManager:
    def __init__(self):
        self._raw: dict = {}
        self._entity_types: dict[str, Any] = {}  # flat: type_name → {attributes, parent}
        self._relationship_types: dict[str, Any] = {}
        self._loaded = False

    def load(self, path: str | pathlib.Path) -> None:
        with open(path, "r", encoding="utf-8") as f:
            self._raw = yaml.safe_load(f)
        self._entity_types = {}
        self._relationship_types = self._raw.get("relationship_types", {})
        self._flatten_types(self._raw.get("entity_types", {}), parent=None)
        self._loaded = True
        print(f"[schema] loaded {len(self._entity_types)} types, {len(self._relationship_types)} relationship types")

    def _flatten_types(self, node: dict, parent: str | None) -> None:
        for type_name, body in node.items():
            body = body or {}
            attrs = body.get("attributes", {}) or {}
            self._entity_types[type_name] = {
                "attributes": attrs,
                "parent": parent,
            }
            children = body.get("children", {}) or {}
            if children:
                self._flatten_types(children, parent=type_name)

    def is_valid_type(self, type_name: str) -> bool:
        return type_name in self._entity_types

    def get_all_types(self) -> list[str]:
        return list(self._entity_types.keys())

    def get_relationship_types(self) -> dict[str, Any]:
        return self._relationship_types

    def get_ancestors(self, type_name: str) -> list[str]:
        """Returns ancestor types from immediate parent up to root, not including type_name itself."""
        ancestors = []
        current = self._entity_types.get(type_name, {}).get("parent")
        while current:
            ancestors.append(current)
            current = self._entity_types.get(current, {}).get("parent")
        return ancestors

    def get_resolved_attributes(self, type_name: str) -> dict[str, Any]:
        """Merges attributes from all ancestors (root first) + own attributes."""
        chain = list(reversed(self.get_ancestors(type_name))) + [type_name]
        merged = {}
        for t in chain:
            merged.update(self._entity_types.get(t, {}).get("attributes", {}))
        return merged

    def get_tree(self) -> list[dict]:
        """Returns the type hierarchy as a nested tree, rooted at Entity's children."""
        def _build(type_name: str) -> dict:
            children = [
                _build(t) for t, info in self._entity_types.items()
                if info.get("parent") == type_name
            ]
            return {"type": type_name, "children": children}

        return [_build(t) for t, info in self._entity_types.items() if info.get("parent") == "Entity"]

    def as_prompt_context(self) -> str:
        """Formats schema for injection into GPT-4o system prompt."""
        lines = ["=== ENTITY TYPES (with all inherited attributes) ==="]
        for type_name, info in self._entity_types.items():
            parent = info.get("parent")
            resolved = self.get_resolved_attributes(type_name)
            lines.append(f"\n{type_name}" + (f" (extends {parent})" if parent else ""))
            if resolved:
                for attr, meta in resolved.items():
                    req = "required" if meta.get("required") else "optional"
                    desc = meta.get("description", "")
                    ex = f", e.g. {meta['example']}" if meta.get("example") else ""
                    lines.append(f"  - {attr} [{meta.get('type','string')}, {req}]: {desc}{ex}")
            else:
                lines.append("  (no attributes beyond inherited)")

        lines.append("\n=== RELATIONSHIP TYPES ===")
        for rel, meta in self._relationship_types.items():
            domain = ", ".join(meta.get("domain", []))
            rng = ", ".join(meta.get("range", []))
            desc = f"  # {meta['description']}" if meta.get("description") else ""
            lines.append(f"  {rel}: ({domain}) → ({rng}){desc}")

        return "\n".join(lines)


# Singleton
schema_manager = SchemaManager()
