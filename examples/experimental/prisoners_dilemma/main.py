"""Helpers for running the Prisoner's Dilemma scenario with SocialDeductionGame."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

import logging

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
    """Load the Prisoner's Dilemma scenario JSON."""
    target = path or CONFIG_PATH
    with target.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_config(base: Dict[str, Any], communication_mode: str) -> Dict[str, Any]:
    """Return a config dict with state machine tailored to communication mode."""
    config = deepcopy(base)

    if communication_mode == "communication":
        config["initial_state"] = "Dialogue1"
        config["state_transition"] = {
            "Dialogue1": "Dialogue2",
            "Dialogue2": "Decision",
            "Decision": "Reveal",
            "Reveal": "Dialogue1",
        }
        config["state_properties"] = {
            "Dialogue1": {
                "acting_roles": ["PD_Player"],
                "actions": ["speak"],
                "action_order": "round-robin",
                "visibility": "public",
                "description": "First dialogue turn",
            },
            "Dialogue2": {
                "acting_roles": ["PD_Player"],
                "actions": ["speak"],
                "action_order": "round-robin",
                "visibility": "public",
                "description": "Second dialogue turn",
            },
            "Decision": {
                "acting_roles": ["PD_Player"],
                "actions": ["action"],
                "action_order": "simultaneous",
                "visibility": "private",
                "description": "Choose cooperate or defect",
            },
            "Reveal": {
                "actions": [],
                "visibility": "public",
                "description": "Reveal choices and payoffs",
            },
        }
    else:
        config["initial_state"] = "Decision"
        config["state_transition"] = {
            "Decision": "Reveal",
            "Reveal": "Decision",
        }
        config["state_properties"] = {
            "Decision": {
                "acting_roles": ["PD_Player"],
                "actions": ["action"],
                "action_order": "simultaneous",
                "visibility": "private",
                "description": "Choose cooperate or defect",
            },
            "Reveal": {
                "actions": [],
                "visibility": "public",
                "description": "Reveal choices and payoffs",
            },
        }

    config["state_properties"]["End"] = {
        "actions": [],
        "visibility": "public",
        "description": "Game complete",
    }
    config["state_transition"]["End"] = "End"
    return config


class PrisonersDilemmaActionHandler(ActionHandler):
    """Track simultaneous cooperate/defect choices."""

    VALID_CHOICES = {
        "cooperate": "cooperate",
        "defect": "defect",
        "stay_silent": "cooperate",
        "betray": "defect",
    }

    def handle_action(
        self, env: SocialDeductionGame, agent_name: str, action: AgentAction
    ) -> None:
        if env.current_state != "Decision":
            return

        normalized = self._normalize_choice(action.argument)
        env.internal_state.setdefault("choices", {})[agent_name] = normalized

    def _normalize_choice(self, argument: str) -> str:
        lowered = argument.strip().lower()
        for keyword, mapped in self.VALID_CHOICES.items():
            if keyword in lowered:
                return mapped
        return "cooperate"

    def get_action_instruction(
        self, env: SocialDeductionGame, agent_name: str
    ) -> str:
        if env.current_state == "Decision":
            return (
                "Choose either 'cooperate' or 'defect'. "
                "Respond using the JSON action schema."
            )
        return ""


class PrisonersDilemmaEnv(SocialDeductionGame):
    """Minimal SocialDeductionGame specialization with round tracking."""

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
        super().__init__(action_handler=PrisonersDilemmaActionHandler(), **kwargs)

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
        """Customize transitions to respect round limits."""
        state_transition = self._config.get("state_transition", {})
        if self.current_state == "Reveal":
            if self.current_round >= self.total_rounds:
                next_state = "End"
            else:
                self.current_round += 1
                next_state = (
                    "Dialogue1"
                    if self.communication_mode == "communication"
                    else "Decision"
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
        logger.info(f"{'-'* 50}\nTurn to {self.current_state}\n{'-'* 50}")


def ensure_agent_profile(config: Dict[str, Any]) -> AgentProfile:
    """Create or retrieve an AgentProfile for a PD player."""
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
) -> PrisonersDilemmaEnv:
    """Instantiate the PD environment."""
    return PrisonersDilemmaEnv(
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
    """Build LLM agents with simple prompts."""
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
            agent_name=profile.first_name if not profile.last_name else f"{profile.first_name} {profile.last_name}",
            agent_profile=profile,
            model_name=model_name,
            strict_action_constraint=True,
            custom_template=filled,
        )
        llm_agent.goal = goal
        agents[llm_agent.agent_name] = llm_agent
    return agents
