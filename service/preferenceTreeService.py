"""
service/preferenceTreeService.py
Stateless in-memory preference tree for one request-response cycle.
"""

import json
import logging
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Any

from configCredidential import get_settings
from service import llmService

logger = logging.getLogger(__name__)
settings = get_settings()



@dataclass(frozen=True)
class QAPair:
    level1: str
    level2: str
    question: str
    answer: str


@dataclass
class TreeNode:
    level1: str | None = None
    level2: str | None = None
    node_type: str = "root"
    children: dict[str, "TreeNode"] = field(default_factory=dict)
    qa_list: list[dict[str, str]] = field(default_factory=list)

    def serialize(self) -> dict[str, Any]:
        return {
            "level1": self.level1,
            "level2": self.level2,
            "node_type": self.node_type,
            "children": {
                key: child.serialize() for key, child in self.children.items()
            },
            "qa_list": self.qa_list,
        }


class PreferenceTree:
    def __init__(self):
        self.llm = llmService.LLMService()
        self.root = TreeNode(node_type="root")
        self.leaf_map: dict[tuple[str, str], TreeNode] = {}

    async def update_tree(self, qa_set: list[QAPair]) -> None:
        for qa in qa_set:
            await self.add_qa(
                level1=qa.level1,
                level2=qa.level2,
                question=qa.question,
                answer=qa.answer,
            )

    async def add_qa(
        self, level1: str, level2: str, question: str, answer: str
    ) -> None:
        level1_node = self.root.children.setdefault(
            level1,
            TreeNode(level1=level1, node_type="level1"),
        )
        level2_node = level1_node.children.setdefault(
            level2,
            TreeNode(level1=level1, level2=level2, node_type="level2"),
        )
        leaf = level2_node.children.setdefault(
            "leaf",
            TreeNode(level1=level1, level2=level2, node_type="leaf"),
        )
        self.leaf_map[(level1, level2)] = leaf
        leaf.qa_list = await self._node_merge(
            old_list=leaf.qa_list,
            new_pair={"question": question, "answer": answer},
        )

    def serialize(self) -> dict[str, Any]:
        return self.root.serialize()

    def build_additional_information(self) -> str:
        """
        Build additional information string by traversing the preference tree.
        Collects all QA pairs from leaf nodes, skips "Lewati" answers.
        """
        lines: list[str] = []

        def traverse_node(node: TreeNode) -> None:
            """Recursively traverse tree to collect QA pairs from leaf nodes."""
            if node.node_type == "leaf" and node.qa_list:
                for qa in node.qa_list:
                    answer = qa.get("answer", "")
                    if answer == "Lewati":
                        continue
                    question = qa.get("question", "")
                    lines.append(f"- {question}: {answer}")

            for child in node.children.values():
                traverse_node(child)

        traverse_node(self.root)

        if not lines:
            return "Tidak ada informasi tambahan selain klarifikasi yang dilewati."

        return "\n".join(lines)

    async def _node_merge(
        self,
        old_list: list[dict[str, str]],
        new_pair: dict[str, str],
    ) -> list[dict[str, str]]:
        if self.llm is None or not old_list:
            return self._deterministic_merge(old_list, new_pair)

        try:
            from template.promptTemplate import build_node_merge_prompt

            prompt = build_node_merge_prompt(old_list=old_list, new_pair=new_pair)
            response = await self.llm._call_llm(
                model=settings.LLM_MODEL_DISAMBIGUATION,
                prompt=prompt,
                temperature=0.0,
                max_output_tokens=500,
            )
            merged = json.loads(response.strip())
            if not isinstance(merged, list):
                raise ValueError("NodeMerge response must be a list")

            normalized: list[dict[str, str]] = []
            for item in merged:
                if not isinstance(item, dict):
                    raise ValueError("NodeMerge item must be an object")
                question = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()
                if question and answer:
                    normalized.append({"question": question, "answer": answer})
            if not normalized:
                raise ValueError("NodeMerge response was empty after normalization")
            return normalized
        except (JSONDecodeError, ValueError, AttributeError, TypeError) as exc:
            logger.warning(
                "[PreferenceTree] NodeMerge failed, using deterministic merge: %s", exc
            )
            return self._deterministic_merge(old_list, new_pair)

    @staticmethod
    def _deterministic_merge(
        old_list: list[dict[str, str]],
        new_pair: dict[str, str],
    ) -> list[dict[str, str]]:
        new_question = new_pair["question"].strip().lower()
        filtered = [
            item
            for item in old_list
            if item.get("question", "").strip().lower() != new_question
        ]
        return [*filtered, new_pair]
