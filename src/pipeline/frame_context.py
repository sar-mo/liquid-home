#!/usr/bin/env python

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any
import json


@dataclass
class AutomationAction:
    """A single action the home system can perform.

    These are predefined and shown in the frontend as a dropdown.
    """
    id: str
    label: str
    description: str | None = None


@dataclass
class ConditionActionRule:
    """A user-defined mapping from a free-form condition to an action.

    The condition is natural language text entered by the user.
    The action_id must match an AutomationAction.id.
    """
    id: str
    condition_text: str
    action_id: str


@dataclass
class AutomationConfig:
    """Bundle of actions and condition→action rules."""
    actions: List[AutomationAction]
    rules: List[ConditionActionRule]

    def actions_by_id(self) -> Dict[str, AutomationAction]:
        return {a.id: a for a in self.actions}

    def rules_by_id(self) -> Dict[str, ConditionActionRule]:
        return {r.id: r for r in self.rules}


def load_automation_config(path: Path) -> AutomationConfig:
    """Load actions + rules from a JSON file.

    Expected structure:

    {
      "actions": [
        {"id": "turn_on_bedside_lamp",
         "label": "Turn on bedside lamp",
         "description": "Turn on the lamp near the bed"}
      ],
      "rules": [
        {"id": "rule-1",
         "condition_text": "A person is lying in bed and the room is dark",
         "action_id": "turn_on_bedside_lamp"}
      ]
    }
    """
    if not path.exists():
        raise FileNotFoundError(f"Automation config not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    raw_actions = raw.get("actions", [])
    raw_rules = raw.get("rules", [])

    if not isinstance(raw_actions, list) or not isinstance(raw_rules, list):
        raise ValueError("Invalid automation config: 'actions' and 'rules' must be lists")

    actions: List[AutomationAction] = []
    for item in raw_actions:
        try:
            actions.append(
                AutomationAction(
                    id=str(item["id"]),
                    label=str(item.get("label", item["id"])),
                    description=item.get("description"),
                )
            )
        except KeyError as e:
            raise ValueError(f"Invalid action entry in automation config: missing {e}") from e

    actions_by_id = {a.id: a for a in actions}

    rules: List[ConditionActionRule] = []
    for item in raw_rules:
        try:
            action_id = str(item["action_id"])
            if action_id not in actions_by_id:
                raise ValueError(f"Rule references unknown action_id '{action_id}'")
            rules.append(
                ConditionActionRule(
                    id=str(item["id"]),
                    condition_text=str(item["condition_text"]),
                    action_id=action_id,
                )
            )
        except KeyError as e:
            raise ValueError(f"Invalid rule entry in automation config: missing {e}") from e

    return AutomationConfig(actions=actions, rules=rules)


def automation_config_to_json_blob(config: AutomationConfig) -> str:
    """Return a compact JSON string describing actions + rules.

    This is meant to be embedded in VLM prompts so it should be stable and simple.
    """
    payload: Dict[str, Any] = {
        "actions": [
            {
                "id": a.id,
                "label": a.label,
                "description": a.description,
            }
            for a in config.actions
        ],
        "rules": [
            {
                "id": r.id,
                "condition_text": r.condition_text,
                "action_id": r.action_id,
            }
            for r in config.rules
        ],
    }
    return json.dumps(payload, ensure_ascii=False)
