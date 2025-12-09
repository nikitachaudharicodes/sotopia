"""Helpers for running the Public Goods Game scenario."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

from sotopia.agents.llm_agent import Agents, LLMAgent
from sotopia.database.persistent_profile import (
    AgentProfile,
    EnvironmentProfile,
    RelationshipType,
)
from sotopia.envs.social_game import (
    ActionHandler,
    SOCIAL_GAME_PROMPT_TEMPLATE,
    SocialDeductionGame,
)
from sotopia.messages import AgentAction, Observation, SimpleMessage

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
logger = logging.getLogger(__name__)


def load_config(path: Path | None = None) -> Dict[str, Any]:
    """Load the Public Goods Game scenario JSON."""
    target = path or CONFIG_PATH
    with target.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_config(base: Dict[str, Any], communication_mode: str) -> Dict[str, Any]:
    """Return a config dict tailored to the desired communication mode."""
    config = deepcopy(base)

    if communication_mode == "communication":
        config["initial_state"] = "Dialogue1"
        config["state_transition"] = {
            "Dialogue1": "Dialogue2",
            "Dialogue2": "Contribution",
            "Contribution": "Reveal",
            "Reveal": "Dialogue1",
        }
        config["state_properties"] = {
            "Dialogue1": {
                "acting_roles": ["PG_Player"],
                "actions": ["speak"],
                "action_order": "round-robin",
                "visibility": "public",
                "description": "First dialogue turn before contributing.",
            },
            "Dialogue2": {
                "acting_roles": ["PG_Player"],
                "actions": ["speak"],
                "action_order": "round-robin",
                "visibility": "public",
                "description": "Second dialogue turn before contributing.",
            },
            "Contribution": {
                "acting_roles": ["PG_Player"],
                "actions": ["action"],
                "action_order": "simultaneous",
                "visibility": "private",
                "description": "Select a contribution level.",
            },
            "Reveal": {
                "actions": [],
                "visibility": "public",
                "description": "Reveal contributions and payoffs.",
            },
        }
    else:
        config["initial_state"] = "Contribution"
        config["state_transition"] = {
            "Contribution": "Reveal",
            "Reveal": "Contribution",
        }
        config["state_properties"] = {
            "Contribution": {
                "acting_roles": ["PG_Player"],
                "actions": ["action"],
                "action_order": "simultaneous",
                "visibility": "private",
                "description": "Select a contribution level.",
            },
            "Reveal": {
                "actions": [],
                "visibility": "public",
                "description": "Reveal contributions and payoffs.",
            },
        }

    config["state_properties"]["End"] = {
        "actions": [],
        "visibility": "public",
        "description": "Game complete.",
    }
    config["state_transition"]["End"] = "End"
    return config


class PublicGoodsActionHandler(ActionHandler):
    """Capture discrete contribution selections."""

    VALID_CHOICES = {
        "contribute_low": "contribute_low",
        "low": "contribute_low",
        "contribute_medium": "contribute_medium",
        "medium": "contribute_medium",
        "contribute_high": "contribute_high",
        "high": "contribute_high",
        "free_ride": "free_ride",
        "free ride": "free_ride",
        "free-ride": "free_ride",
    }

    def handle_action(
        self,
        env: SocialDeductionGame,
        agent_name: str,
        action: AgentAction,
    ) -> None:
        if env.current_state != "Contribution":
            return
        normalized = self._normalize_choice(action.argument)
        env.internal_state.setdefault("choices", {})[agent_name] = normalized

    def _normalize_choice(self, argument: str) -> str:
        lowered = argument.strip().lower()
        for keyword, mapped in self.VALID_CHOICES.items():
            if keyword in lowered:
                return mapped
        return "contribute_low"

    def get_action_instruction(
        self,
        env: SocialDeductionGame,
        agent_name: str,
    ) -> str:
        if env.current_state == "Contribution":
            return (
                "Choose exactly one of: contribute_low, contribute_medium, "
                "contribute_high, or free_ride. Respond as JSON using the "
                "provided action schema."
            )
        if env.current_state.startswith("Dialogue"):
            return (
                "Share your reasoning briefly before contributing. Keep it concise."
            )
        return ""


class PublicGoodsEnv(SocialDeductionGame):
    """SocialDeductionGame specialization with round/communication support."""

    def __init__(
        self,
        *,
        total_rounds: int,
        communication_mode: str,
        **kwargs: Any,
    ) -> None:
        self.total_rounds = max(1, total_rounds)
        self.communication_mode = communication_mode
        self.current_round = 1
        super().__init__(action_handler=PublicGoodsActionHandler(), **kwargs)

    def reset(
        self,
        seed: int | None = None,
        options: dict[str, str] | None = None,
        agents: Agents | None = None,
        omniscient: bool = False,
        lite: bool = False,
        include_background_observations: bool = True,
    ) -> Dict[str, Observation]:
        self.current_round = 1
        return super().reset(
            seed=seed,
            options=options,
            agents=agents,
            omniscient=omniscient,
            lite=lite,
            include_background_observations=include_background_observations,
        )

    def _perform_transition_state(self) -> None:
        state_transition = self._config.get("state_transition", {})
        if self.current_state == "Reveal":
            if self.current_round >= self.total_rounds:
                next_state = "End"
            else:
                self.current_round += 1
                next_state = (
                    "Dialogue1"
                    if self.communication_mode == "communication"
                    else "Contribution"
                )
        elif self.current_state == "End":
            next_state = "End"
        else:
            next_state = state_transition.get(self.current_state)

        if not next_state:
            return

        self.current_state = next_state
        if hasattr(self, "_state_turn_count"):
            self._state_turn_count[self.current_state] = 0
        if hasattr(self, "_round_robin_idx"):
            self._round_robin_idx = 0
        self.recv_message(
            "Environment",
            SimpleMessage(message=f"[Game] Entering state: {self.current_state}"),
        )
        logger.info("%s\nTurn to %s\n%s", "-" * 50, self.current_state, "-" * 50)


def ensure_agent_profile(config: Dict[str, Any]) -> AgentProfile:
    """Create or retrieve an AgentProfile for a PGG player."""
    full_name = config.get("name", "")
    first_name, _, last_name = full_name.partition(" ")

    try:
        existing = AgentProfile.find(
            (AgentProfile.first_name == first_name)
            & (AgentProfile.last_name == last_name)
        ).all()
        if existing:
            return AgentProfile.get(existing[0].pk)
    except Exception:
        pass

    profile = AgentProfile(
        first_name=first_name,
        last_name=last_name,
        secret="",
    )
    profile.save()
    return profile


def create_environment(
    env_profile: EnvironmentProfile,
    model_name: str,
    config: Dict[str, Any],
    *,
    total_rounds: int,
    communication_mode: str,
) -> PublicGoodsEnv:
    return PublicGoodsEnv(
        env_profile=env_profile,
        config=config,
        model_name=model_name,
        action_order="simultaneous",
        hide_unknown=True,
        evaluators=[],
        terminal_evaluators=[],
        total_rounds=total_rounds,
        communication_mode=communication_mode,
    )


def create_llm_agents(
    agent_profiles: List[AgentProfile],
    env_profile: EnvironmentProfile,
    model_name: str,
) -> Agents:
    agents: Agents = Agents()
    for idx, profile in enumerate(agent_profiles):
        goal = env_profile.agent_goals[idx]
        filled = (
            SOCIAL_GAME_PROMPT_TEMPLATE.replace("{agent}", profile.first_name)
            .replace("{description}", env_profile.scenario)
            .replace("{goal}", goal)
            .replace("{secret}", "")
        )
        llm_agent = LLMAgent(
            agent_name=profile.first_name
            if not profile.last_name
            else f"{profile.first_name} {profile.last_name}",
            agent_profile=profile,
            model_name=model_name,
            strict_action_constraint=True,
            custom_template=filled,
        )
        llm_agent.goal = goal
        agents[llm_agent.agent_name] = llm_agent
    return agents
