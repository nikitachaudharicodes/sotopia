"""Launcher for the Wild West social game scenario (Way Out West)."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, cast
from dataclasses import dataclass
from pretty_display import WayOutWestDisplay


# Redis availability check
import redis
try:
    r = redis.Redis(host="localhost", port=6379)
    r.ping()
    print(" Connected to Redis at redis://localhost:6379")
    REDIS_AVAILABLE = True
except redis.ConnectionError:
    print(" Redis not available — running in in-memory mode.")
    REDIS_AVAILABLE = False

@dataclass
class AgentProfileStub:
    first_name: str
    last_name: str
    age: int
    occupation: str = ""
    gender: str = ""
    gender_pronoun: str = "they/them"
    public_info: str = ""
    personality_and_values: str = ""
    decision_making_style: str = ""
    secret: str = ""

@dataclass
class EnvironmentProfileStub:
    scenario: str
    agent_goals: List[str]
    relationship: str
    game_metadata: Dict[str, Any]
    tag: str

from sotopia.database.persistent_profile import RelationshipType
from sotopia.agents import LLMAgent
from sotopia.envs import SocialGameEnv
from sotopia.envs.evaluators import (
    EpisodeLLMEvaluator,
    EvaluationForAgents,
    RuleBasedTerminatedEvaluator,
)
from sotopia.server import arun_one_episode
from sotopia.database import SotopiaDimensions

# -------------------------------
# Paths
# -------------------------------
BASE_DIR = Path(__file__).resolve().parent
ROLE_ACTIONS_PATH = BASE_DIR / "role_actions.json"
RULEBOOK_PATH = BASE_DIR / "game_rules.json"
ROSTER_PATH = BASE_DIR / "roster.json"

# -------------------------------
# Helpers
# -------------------------------
def load_json(path: Path) -> Dict[str, Any]:
    return cast(Dict[str, Any], json.loads(path.read_text()))

def ensure_agent(player: Dict[str, Any]) -> AgentProfileStub:
    """Create in-memory agent profile (no Redis persistence)."""
    return AgentProfileStub(
        first_name=player["first_name"],
        last_name=player["last_name"],
        age=player.get("age", 30),
        occupation=player.get("public_role", ""),
        gender="",
        gender_pronoun=player.get("pronouns", "they/them"),
        public_info=player.get("public_role", ""),
        personality_and_values="",
        decision_making_style="",
        secret=player.get("secret", ""),
    )

def build_agent_goal(player: Dict[str, Any], role_prompt: str) -> str:
    # action_hints = {
    #     "Blaise Sadler": "YOU HAVE THE MARKED CARDS. Use 'present_evidence' to show them!",
    #     "Doc Faraday": "Use 'negotiate' to make deals for $22,000. Use 'pickpocket' to steal evidence.",
    #     "Judge Paulson": "Use 'request_evidence' to demand proof. You must make a judgment!",
    #     "Elijah Entwhistle": "Use 'reveal_identity' to show you're Jake Calhoun!",
    #     "Clem Parham": "Use 'intimidate' to pressure the Judge with blackmail.",
    #     "Dan Fairweather": "Use 'arrest' to detain suspects. Use 'interrogate' to question them.",
    #     "Lucy Calhoun": "Use 'accuse' to point fingers. Use 'interrogate' to demand answers."
    # }

    action_hints = {
        "Blaise Sadler": "YOU HAVE THE MARKED CARDS. Use 'present_evidence' to show them!",
        "Doc Faraday": "Use 'negotiate' to make deals for $22,000. Use 'pickpocket' to steal evidence.",
        "Judge Paulson": "Use 'request_evidence' to demand proof. You must make a judgment!",
        "Elijah Entwhistle": "In HIGH NOON phase, USE 'shoot' to kill Clem Parham for murdering Zeke!",  # ⚡ ADD
        "Clem Parham": "Use 'intimidate' to pressure the Judge with blackmail.",
        "Dan Fairweather": "Use 'arrest' to detain suspects. Use 'interrogate' to question them.",
        "Lucy Calhoun": "In HIGH NOON phase, USE 'shoot' to kill Clem or Doc! Avenge your father!"  # ⚡ ADD
    }
    
    hint = action_hints.get(player['first_name'] + ' ' + player['last_name'], "")
    
    return (
        f"You are {player['first_name']} {player['last_name']}, {player['public_role']}.\n\n"
        f"🎯 PRIMARY GOAL: {player['goal']}\n\n"
        f"⚡ IMMEDIATE ACTION REQUIRED:\n{hint}\n\n"
        f"🚫 FORBIDDEN:\n"
        f"- Do NOT just make speeches about unity/truth/justice\n"
        f"- Do NOT say you'll 'examine evidence later'\n"
        f"- Do NOT repeat what others said\n"
        f"- Do NOT use 'speak' action when other actions are available\n\n"
        f"✅ REQUIRED:\n"
        f"- Use your special actions/abilities from your character sheet\n"
        f"- Take CONCRETE actions that change the game state\n"
        f"- Make specific accusations with names\n"
        f"- Present actual evidence if you have it\n"
        f"- Respond to what others JUST said\n\n"
        f"📋 Role Details: {role_prompt}\n\n"
        f"🎮 Current turn format: {{\"action_type\": \"[your_action]\", \"argument\": \"[specific target/details]\"}}\n"
        f"Example: {{\"action_type\": \"accuse\", \"argument\": \"I accuse Clem Parham of murdering Zeke!\"}}\n"

    )

def prepare_scenario() -> tuple[EnvironmentProfileStub, List[AgentProfileStub], Dict[str, str]]:
    """Load game configuration and create agent profiles."""
    role_actions = load_json(ROLE_ACTIONS_PATH)
    roster = load_json(ROSTER_PATH)
    
    agents: List[AgentProfileStub] = []
    agent_goals: List[str] = []
    role_assignments: Dict[str, str] = {}
    
    for player in roster["players"]:
        profile = ensure_agent(player)
        agents.append(profile)
        
        full_name = f"{player['first_name']} {player['last_name']}"
        role = player["role"]
        
        role_data = role_actions.get("roles", role_actions)
        role_config = role_data.get(role, {})
        role_prompt = role_config.get("goal_prompt", "Play your role.")
        
        agent_goals.append(build_agent_goal(player, role_prompt))
        role_assignments[full_name] = role
    
    env_profile = EnvironmentProfileStub(
        scenario=roster["scenario"],
        agent_goals=agent_goals,
        relationship=RelationshipType.acquaintance,
        game_metadata={
            "mode": "social_game",
            "rulebook_path": str(RULEBOOK_PATH),
            "actions_path": str(ROLE_ACTIONS_PATH),
            "role_assignments": role_assignments,
        },
        tag="way_out_west",
    )
    
    return env_profile, agents, role_assignments

def build_environment(
    env_profile: EnvironmentProfileStub,
    role_assignments: Dict[str, str],
    model_name: str,
    enable_memory_tracking: bool = False,      
    enable_repetition_check: bool = False,     
) -> SocialGameEnv:
    """Create the SocialGameEnv instance."""
    return SocialGameEnv(
        env_profile=env_profile,
        rulebook_path=str(RULEBOOK_PATH),
        actions_path=str(ROLE_ACTIONS_PATH),
        role_assignments=role_assignments,
        model_name=model_name,
        action_order="round-robin",
        enable_memory_tracking=enable_memory_tracking,  # PASS THROUGH
        enable_repetition_check=enable_repetition_check, # PASS THROUGH
        # enable_memory_tracking=True,
        # enable_repetition_check=True,
        evaluators=[
            RuleBasedTerminatedEvaluator(
                max_turn_number=100,  
                max_stale_turn=5
            )
        ],
        terminal_evaluators=[
            EpisodeLLMEvaluator(
                model_name,
                EvaluationForAgents[SotopiaDimensions],
            )
        ],
    )

def create_agents(
    agent_profiles: List[AgentProfileStub],
    env_profile: EnvironmentProfileStub,
    model_names: List[str],
) -> List[LLMAgent]:
    """Create LLMAgent instances for each character."""
    agents: List[LLMAgent] = []
    for profile, model_name, goal in zip(
        agent_profiles,
        model_names,
        env_profile.agent_goals,
        strict=True,
    ):
        agent = LLMAgent(agent_profile=profile, model_name=model_name)
        agent.goal = goal
        agents.append(agent)
    return agents

def print_roster(role_assignments: Dict[str, str]) -> None:
    """Display the cast of characters."""
    print("\n🎭 Cast of Characters:")
    print("=" * 60)
    
    # Group by team
    from collections import defaultdict
    teams = defaultdict(list)
    
    role_data = load_json(ROLE_ACTIONS_PATH)["roles"]
    for name, role in role_assignments.items():
        team = role_data[role]["team"]
        teams[team].append((name, role))
    
    for team_name, members in sorted(teams.items()):
        print(f"\n{team_name.upper()}:")
        for name, role in members:
            print(f"  • {name}")
    
    print("=" * 60)

async def main() -> None:
    """Main entry point."""
    # Load scenario
    env_profile, agent_profiles, role_assignments = prepare_scenario()
    
    # Model configuration
    env_model = "gpt-4o-mini"
    agent_model_list = ["gpt-4o-mini"] * len(agent_profiles)
    
    # Build environment and agents
    env = build_environment(env_profile, role_assignments, env_model, enable_memory_tracking= True, enable_repetition_check = True)
    agents = create_agents(agent_profiles, env_profile, agent_model_list)

    display = WayOutWestDisplay()
    display.show_header()
    display.show_teams()
    
    
    # # Display game information
    # print("\n" + "=" * 60)
    # print("🤠 WAY OUT WEST - Murder Mystery in Cactus Gulch 🤠")
    # print("=" * 60)
    # print("\n📜 Scenario:")
    # print(env_profile.scenario)
    # print_roster(role_assignments)
    # print("\n🎲 Game begins...\n")
    # print("=" * 60)


    # dead_characters = set()

    # # Custom episode loop
    # turn = 0
    # async for messages in env.run_episode_async(agents):
    #     turn += 1
    #     display.turn = turn

    #     # Display each agent’s action
    #     for agent_name, action in messages.items():
    #         team = env.game_rulebook.agent_states[agent_name].team
    #         display.show_action(
    #             agent_name,
    #             action.action_type,
    #             action.argument,
    #             team
    #         )

    #     # Phase transition
    #     if env.game_rulebook.current_phase != display.phase:
    #         display.show_phase_transition(
    #             env.game_rulebook.current_phase,
    #             "Phase transition!"
    #         )

    #     # Check for deaths
    #     for name, state in env.game_rulebook.agent_states.items():
    #         if not state.alive and name not in dead_characters:
    #             display.show_death(name)
    #             dead_characters.add(name)

    # # Show winner at the end
    # if hasattr(env, "_winner_payload") and env._winner_payload:
    #     display.show_winner(
    #         env._winner_payload["winner"],
    #         env._winner_payload["message"]
    #     )
    
    # Run episode
    await arun_one_episode(
        env=env,
        agent_list=agents,
        omniscient=False,
        script_like=False,
        json_in_script=False,
        tag=None,
        push_to_db=False,
    )
    
    # Display results
    print("\n" + "=" * 60)
    print("🏁 GAME OVER")
    print("=" * 60)
    
    if hasattr(env, '_winner_payload') and env._winner_payload:
        print(f"\n🏆 Winner: {env._winner_payload['winner']}")
        print(f"📝 {env._winner_payload['message']}")
    
    # Display phase log summary
    if hasattr(env, 'phase_log') and env.phase_log:
        print("\n📊 Phase Summary:")
        for entry in env.phase_log:
            phase = entry.get('phase', 'unknown')
            turn = entry.get('turn', 0)
            actions_count = len(entry.get('actions', {}))
            print(f"  Turn {turn} - {phase}: {actions_count} actions")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(main())