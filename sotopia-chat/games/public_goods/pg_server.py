"""Dedicated async server loop for the Public Goods Game."""

from __future__ import annotations

import asyncio
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

import typer

REPO_ROOT = Path(__file__).resolve().parents[3]
if REPO_ROOT.as_posix() not in sys.path:
    sys.path.insert(0, REPO_ROOT.as_posix())

from examples.experimental.public_goods.main import (
    build_config,
    create_environment,
    create_llm_agents,
    ensure_agent_profile,
    load_config,
)
from sotopia.agents import Agents
from sotopia.database.persistent_profile import (
    AgentProfile,
    EnvironmentProfile,
    RelationshipType,
)
from sotopia.envs.social_game import SocialDeductionGame
from sotopia.messages import AgentAction, Observation

from .pg_state import PGStateStore

CONFIG_PATH = (
    REPO_ROOT
    / "examples"
    / "experimental"
    / "public_goods"
    / "config.json"
)

CONTRIBUTION_CHOICES = [
    "contribute_low",
    "contribute_medium",
    "contribute_high",
    "free_ride",
]
CONTRIBUTION_VALUES = {
    "contribute_low": 1,
    "contribute_medium": 2,
    "contribute_high": 3,
    "free_ride": 0,
}
MULTIPLIER = 1.5

app = typer.Typer()


class RedisHumanAgent:
    """Agent that waits for frontend-submitted contributions."""

    def __init__(
        self,
        session_id: str,
        participant_id: str,
        agent_name: str,
        state_store: PGStateStore,
        agent_profile: AgentProfile,
    ) -> None:
        self.session_id = session_id
        self.participant_id = participant_id
        self.agent_name = agent_name
        self.goal = ""
        self.model_name = "human"
        self._state_store = state_store
        self.profile = agent_profile
        self.agent_profile = agent_profile

    async def aact(self, obs: Observation) -> AgentAction:
        while True:
            payload = await self._state_store.pop_action(
                self.session_id,
                self.participant_id,
            )
            if payload:
                return AgentAction(
                    action_type=payload.get("action_type", "action"),
                    argument=payload.get("argument", ""),
                )
            await asyncio.sleep(0.5)

    def reset(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return


def _build_env_and_agents(
    session_id: str,
    human_id: str,
    state_store: PGStateStore,
    *,
    env_model_name: str = "gpt-4o-mini",
    agent_model_name: str = "gpt-4o-mini",
    communication_mode: str,
    total_rounds: int,
) -> tuple[SocialDeductionGame, Agents, Dict[str, str], str]:
    base_config = load_config(CONFIG_PATH)
    config = build_config(base_config, communication_mode)

    agent_profiles: list[AgentProfile] = []
    role_assignments: Dict[str, str] = {}
    profile_map: Dict[str, AgentProfile] = {}
    for entry in config.get("agents", []):
        profile = ensure_agent_profile(entry)
        agent_profiles.append(profile)
        profile_map[entry["name"]] = profile
        role_assignments[entry["name"]] = entry.get("role", "PG_Player")

    env_profile = EnvironmentProfile(
        scenario=config.get("description", ""),
        relationship=RelationshipType.stranger,
        agent_goals=[
            config.get("role_goals", {}).get(entry.get("role", ""), "")
            for entry in config.get("agents", [])
        ],
        tag="public_goods",
    )
    env_profile.save()

    env = create_environment(
        env_profile=env_profile,
        model_name=env_model_name,
        config=config,
        total_rounds=total_rounds,
        communication_mode=communication_mode,
    )

    agents = create_llm_agents(agent_profiles, env_profile, agent_model_name)

    agent_names = list(agents.keys())
    human_name = random.choice(agent_names)
    human_profile = profile_map[human_name]
    human_agent = RedisHumanAgent(
        session_id=session_id,
        participant_id=human_id,
        agent_name=human_name,
        state_store=state_store,
        agent_profile=human_profile,
    )
    agents[human_name] = human_agent
    return env, agents, role_assignments, human_name


def _agent_names(env: SocialDeductionGame) -> List[str]:
    agents = getattr(env, "agents", [])
    if isinstance(agents, dict):
        return list(agents.keys())
    if isinstance(agents, Iterable):
        return list(agents)
    return []


def _active_player(env: SocialDeductionGame) -> str | None:
    mask = getattr(env, "action_mask", None)
    if not mask:
        return None
    names = _agent_names(env)
    for idx, flag in enumerate(mask):
        if flag and idx < len(names):
            return names[idx]
    return None


def _compute_payoffs(
    choices: Dict[str, str],
) -> tuple[Dict[str, float], Dict[str, int], float]:
    if not choices:
        return {}, {}, 0.0
    contributions = {
        player: CONTRIBUTION_VALUES.get(choice, 0) for player, choice in choices.items()
    }
    total_pool = sum(contributions.values())
    player_count = max(1, len(contributions))
    shared_return = MULTIPLIER * total_pool / player_count
    payoffs = {
        player: round(shared_return - contrib, 2)
        for player, contrib in contributions.items()
    }
    return payoffs, contributions, total_pool


def _interpret_rounds(round_logs: List[Dict[str, Any]]) -> str:
    if not round_logs:
        return "No rounds were played."

    avg_totals = [log.get("total_pool", 0) for log in round_logs]
    if avg_totals and min(avg_totals) == 0:
        return "Free-riding tendency detected."
    if avg_totals and all(total >= 6 for total in avg_totals):
        return "Cooperative strategy with high contributions."

    free_rides = sum(
        1
        for log in round_logs
        for action in (log.get("actions") or {}).values()
        if action == "free_ride"
    )
    if free_rides > len(round_logs):
        return "Mixed play with repeated free-riding."
    return "Mixed contributions."


async def publish_game_state(
    session_id: str,
    env: SocialDeductionGame,
    state_store: PGStateStore,
    *,
    host_id: str,
    human_name: str,
    communication_mode: str,
    current_round: int,
    total_rounds: int,
    round_logs: List[Dict[str, Any]],
    totals: Dict[str, float],
    interpretation: str | None,
    status: str = "active",
    available_actions: list[str] | None = None,
    waiting_for_action: bool = False,
    choices: Dict[str, str] | None = None,
    numeric_contributions: Dict[str, int] | None = None,
    payoffs: Dict[str, float] | None = None,
    total_pool: float | None = None,
    game_over: bool = False,
    active_player_id: str | None = None,
) -> None:
    state_props = env._config.get("state_properties", {}).get(env.current_state, {})
    actions_for_state = state_props.get("actions", [])

    players_payload = []
    for name in _agent_names(env):
        players_payload.append(
            {
                "id": name,
                "display_name": name,
                "role": env.agent_to_role.get(name, "PG_Player"),
                "team": env.role_to_team.get(env.agent_to_role.get(name, ""), "Players"),
                "is_alive": True,
                "is_host": name == human_name,
            }
        )

    phase_payload = {
        "phase": env.current_state,
        "description": state_props.get("description", env.current_state),
        "allow_chat": actions_for_state == ["speak"],
        "allow_actions": "action" in actions_for_state,
    }

    payload = {
        "session_id": session_id,
        "players": players_payload,
        "me": next((p for p in players_payload if p["id"] == human_name), None),
        "phase": phase_payload,
        "available_actions": available_actions or actions_for_state or [],
        "status": status,
        "last_updated": time.time(),
        "host_id": host_id,
        "waiting_for_action": waiting_for_action,
        "game_over": game_over,
        "choices": choices or {},
        "numeric_contributions": numeric_contributions or {},
        "payoffs": payoffs or {},
        "total_pool": total_pool,
        "communication_mode": communication_mode,
        "current_round": current_round,
        "total_rounds": total_rounds,
        "round_logs": round_logs,
        "totals": totals,
        "interpretation": interpretation,
        "active_player_id": active_player_id,
    }

    await state_store.write_state(session_id, payload, ttl=600)


async def async_run_pg_game(
    session_id: str,
    human_id: str,
    *,
    state_store: PGStateStore,
    communication_mode: str,
    total_rounds: int,
    env_model_name: str = "gpt-4o-mini",
    agent_model_name: str = "gpt-4o-mini",
) -> None:
    env, agents, _, human_name = _build_env_and_agents(
        session_id,
        human_id,
        state_store,
        env_model_name=env_model_name,
        agent_model_name=agent_model_name,
        communication_mode=communication_mode,
        total_rounds=total_rounds,
    )

    observations = env.reset(agents=agents, omniscient=False)
    round_logs: List[Dict[str, Any]] = []
    totals: Dict[str, float] = {name: 0.0 for name in _agent_names(env)}
    interpretation: str | None = None

    def state_actions() -> list[str]:
        props = env._config.get("state_properties", {}).get(env.current_state, {})
        actions = props.get("actions", [])
        if "action" in actions and env.current_state.startswith("Contribution"):
            return CONTRIBUTION_CHOICES
        return actions or []

    def human_waiting() -> bool:
        choices = env.internal_state.get("choices", {})
        actions = state_actions()
        if actions == ["speak"]:
            return _active_player(env) == human_name
        if "action" in actions:
            return human_name not in choices
        return False

    async def push_state(
        *,
        choices: Dict[str, str],
        numeric: Dict[str, int],
        payoffs: Dict[str, float],
        pool: float,
        game_over: bool,
        status: str,
    ) -> None:
        await publish_game_state(
            session_id,
            env,
            state_store,
            host_id=human_id,
            human_name=human_name,
            communication_mode=communication_mode,
            current_round=env.current_round,
            total_rounds=total_rounds,
            round_logs=round_logs,
            totals=totals,
            interpretation=interpretation,
            available_actions=state_actions(),
            waiting_for_action=human_waiting(),
            choices=choices,
            numeric_contributions=numeric,
            payoffs=payoffs,
            total_pool=pool,
            game_over=game_over,
            status=status,
            active_player_id=_active_player(env),
        )

    await push_state(
        choices={},
        numeric={},
        payoffs={},
        pool=0.0,
        game_over=False,
        status="active",
    )

    game_over = False
    while not game_over:
        action_tasks = [
            agent.aact(observations[name]) for name, agent in agents.items()
        ]
        actions_list = await asyncio.gather(*action_tasks)
        actions = {name: act for name, act in zip(agents.keys(), actions_list)}

        observations, _, _, _, _ = await env.astep(actions)

        choices = env.internal_state.get("choices", {})
        round_complete = len(choices) == len(env.agents)
        payoffs: Dict[str, float] = {}
        numeric: Dict[str, int] = {}
        pool = 0.0
        if round_complete:
            payoffs, numeric, pool = _compute_payoffs(choices)
            round_logs.append(
                {
                    "round": env.current_round,
                    "actions": choices.copy(),
                    "numeric_contributions": numeric.copy(),
                    "total_pool": pool,
                    "payoffs": payoffs.copy(),
                }
            )
            for player, value in payoffs.items():
                totals[player] = round(totals.get(player, 0.0) + value, 2)
            env.internal_state["choices"] = {}

        game_over = env.current_state == "End" or len(round_logs) >= total_rounds
        if game_over and interpretation is None:
            interpretation = _interpret_rounds(round_logs)

        if round_complete and not game_over:
            env._perform_transition_state()
            env._update_action_mask()

        display_choices = choices if round_complete else {}
        display_numeric = numeric if round_complete else {}
        display_pool = pool if round_complete else 0.0
        await push_state(
            choices=display_choices,
            numeric=display_numeric,
            payoffs=payoffs,
            pool=display_pool,
            game_over=game_over,
            status="completed" if game_over else "active",
        )

        if round_complete and not game_over:
            await push_state(
                choices={},
                numeric={},
                payoffs={},
                pool=0.0,
                game_over=False,
                status="active",
            )


@app.command()
def run_public_goods(
    session_id: str = typer.Option(..., help="Session identifier"),
    human_id: str = typer.Option(..., help="Human participant id"),
    communication_mode: str = typer.Option("no-communication"),
    rounds: int = typer.Option(1),
) -> None:
    redis_url = os.environ.get("REDIS_OM_URL", "redis://localhost:6379")
    store = PGStateStore(redis_url)
    asyncio.run(
        async_run_pg_game(
            session_id,
            human_id,
            state_store=store,
            communication_mode=communication_mode,
            total_rounds=rounds,
        )
    )
