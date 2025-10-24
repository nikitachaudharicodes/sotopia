"""Social game environment that reads its rulebook and action space from JSON."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, cast

from collections import Counter

from sotopia.game_utils.memory_tracker import GameMemory


from pydantic import BaseModel, Field, RootModel, ValidationError

from sotopia.envs.parallel import ParallelSotopiaEnv, render_text_for_agent
from sotopia.agents.llm_agent import Agents
from sotopia.database import EnvironmentProfile
from sotopia.messages import AgentAction, Observation, SimpleMessage



class RoleActionConfig(BaseModel):
    """Declared abilities and messaging semantics for a specific role."""

    name: str
    team: str
    description: str = ""
    goal_prompt: str = ""
    default_actions: list[str] = Field(default_factory=lambda: ["speak", "action"])
    phase_actions: dict[str, list[str]] = Field(default_factory=dict)
    initial_state: dict[str, Any] = Field(default_factory=dict)
    allow_team_private_speech: bool = False
    allow_role_private_speech: bool = False


class RoleActionLibrary(RootModel[dict[str, RoleActionConfig]]):
    """Pydantic wrapper for mapping roles to role metadata."""

    def team_for_role(self, role: str) -> str:
        return self.root[role].team


class PhaseResolution(BaseModel):
    operation: str = Field(
        default="noop",
        description="Name of the builtin resolution handler to invoke at phase end.",
    )
    state_key: str | None = None
    visibility: str = Field(
        default="public",
        description="Default visibility for resolution feedback.",
    )


class PhaseDefinition(BaseModel):
    name: str
    kind: str = Field(
        default="discussion",
        description="Macro describing how the phase behaves (discussion, team_target, vote, single_target, announcement).",
    )
    group: str | None = Field(
        default=None,
        description="Optional label used to cluster phases into higher-level cycles (e.g., 'night', 'day').",
    )
    turn_mode: str = Field(
        default="round-robin",
        description="round-robin => sequential actors, simultaneous => everyone at once, single => one actor only.",
    )
    acting_roles: list[str] | None = None
    acting_teams: list[str] | None = None
    max_cycles: int = Field(
        default=1,
        description="Number of complete round-robin passes required before the phase advances.",
    )
    max_turns: int | None = Field(
        default=None,
        description="Optional cap on total turns inside the phase (overrides max_cycles when smaller).",
    )
    speech_visibility: str = Field(
        default="public",
        description="Where speech is visible ('public', 'team', 'private', 'hidden').",
    )
    action_visibility: str = Field(
        default="public",
        description="Where action outcomes are visible ('public', 'team', 'private', 'hidden').",
    )
    instructions: list[str] = Field(
        default_factory=list,
        description="General prompts injected into agent observations for this phase.",
    )
    role_instructions: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Optional role-specific prompts keyed by role name.",
    )
    resolution: PhaseResolution | None = None
    entry_messages: list[str] = Field(default_factory=list)
    exit_messages: list[str] = Field(default_factory=list)
    description: str = ""


class EndConditionDefinition(BaseModel):
    operation: str
    team: str | None = None
    other_team: str | None = None
    winner: str | None = None
    message: str | None = None


class RulebookConfig(BaseModel):
    initial_phase: str
    phases: list[PhaseDefinition]
    phase_transitions: dict[str, str]
    end_conditions: list[EndConditionDefinition] = Field(default_factory=list)
    max_cycles: int | None = Field(
        default=None,
        description="Optional safety bound on day/night cycles to prevent infinite games.",
    )


@dataclass
class AgentState:
    name: str
    role: str
    team: str
    alive: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseEvents:
    public: list[str] = field(default_factory=list)
    team: dict[str, list[str]] = field(default_factory=dict)
    private: dict[str, list[str]] = field(default_factory=dict)
    system: list[str] = field(default_factory=list)

    def extend(self, other: "PhaseEvents") -> None:
        self.public.extend(other.public)
        for team, messages in other.team.items():
            self.team.setdefault(team, []).extend(messages)
        for agent, messages in other.private.items():
            self.private.setdefault(agent, []).extend(messages)
        self.system.extend(other.system)

    @classmethod
    def phase_entry(cls, phase_name: str, messages: list[str]) -> "PhaseEvents":
        events = cls()
        for msg in messages:
            events.public.append(f"[God] Phase '{phase_name}' begins: {msg}")
        if not messages:
            events.public.append(f"[God] Phase '{phase_name}' begins.")
        return events


class GameRulebook:
    """Runtime state machine that enforces the JSON described social game."""

    def __init__(self, rules: RulebookConfig, roles: RoleActionLibrary) -> None:
        self.rules = rules
        self.roles = roles
        self.phase_lookup = {phase.name: phase for phase in rules.phases}
        self.agent_states: dict[str, AgentState] = {}
        self.agent_name_lookup: dict[str, str] = {}
        self.current_phase: str = rules.initial_phase
        self.phase_cycle_progress: int = 0
        self.turns_in_phase: int = 0
        self.current_actor_index: int = 0
        self.state_flags: dict[str, Any] = {}
        self.group_cycle: dict[str, int] = {}
        self.group_stage: dict[str, int] = {}
        self.current_phase_meta: dict[str, Any] = {}
        self.pending_events: PhaseEvents = PhaseEvents()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------
    def assign_agents(
        self,
        agents: Sequence[str],
        role_assignments: dict[str, str],
    ) -> None:
        self.agent_states = {}
        self.agent_name_lookup = {}
        for name in agents:
            role = role_assignments[name]
            role_cfg = self.roles.root.get(role)
            if role_cfg is None:
                raise ValueError(f"Unknown role '{role}' for agent '{name}'")
            attrs = dict(role_cfg.initial_state)
            state = AgentState(
                name=name,
                role=role,
                team=role_cfg.team,
                alive=True,
                attributes=attrs,
            )
            self.agent_states[name] = state
            self.agent_name_lookup[name.lower()] = name
            self.agent_name_lookup[name.split()[0].lower()] = name

        self.current_phase = self.rules.initial_phase
        self.phase_cycle_progress = 0
        self.turns_in_phase = 0
        self.current_actor_index = 0
        self.state_flags = {
            "day_execution": None,
            "night_target": None,
            "witch_saved": None,
            "witch_poisoned": None,
            "seer_result": "",
        }
        self.group_cycle.clear()
        self.group_stage.clear()
        self.current_phase_meta = {}
        self._register_phase_entry(self.current_phase)
        entry_phase = self.phase_lookup[self.current_phase]
        self.pending_events = PhaseEvents.phase_entry(
            self.current_phase, entry_phase.entry_messages
        )

    # ------------------------------------------------------------------
    # Accessors used by the environment
    # ------------------------------------------------------------------
    def alive_agents(self) -> list[str]:
        return [name for name, state in self.agent_states.items() if state.alive]

    def active_agents_for_phase(self) -> list[str]:
        phase = self.phase_lookup[self.current_phase]
        eligible = self._eligible_candidates(phase)
        if not eligible:
            return []
        if phase.turn_mode == "round-robin":
            idx = self.current_actor_index
            if idx >= len(eligible):
                idx = len(eligible) - 1
            if idx < 0:
                idx = 0
            return [eligible[idx]]
        return eligible

    # def available_actions(self, agent_name: str) -> list[str]:
    #     agent_state = self.agent_states[agent_name]
    #     if not agent_state.alive:
    #         return ["none"]
    #     role_cfg = self.roles.root[agent_state.role]
    #     actions = role_cfg.phase_actions.get(
    #         self.current_phase, role_cfg.default_actions
    #     )
    #     if "none" not in actions:
    #         actions = list(actions) + ["none"]
    #     return actions
    
    def available_actions(self, agent_name: str) -> list[str]:
        agent_state = self.agent_states[agent_name]
        if not agent_state.alive:
            return ["none"]
        
        # Get custom actions from role config
        role_cfg = self.roles.root[agent_state.role]
        custom_actions = role_cfg.phase_actions.get(
            self.current_phase, role_cfg.default_actions
        )
        
        # MAP ALL CUSTOM ACTIONS TO "action" for SOTOPIA compatibility
        # But keep them in observation text so agents know what to do
        return ["speak", "action", "none"]  # Only return SOTOPIA-valid actions

    def collect_pending_events(self) -> PhaseEvents:
        events = self.pending_events
        self.pending_events = PhaseEvents()
        return events

    # ------------------------------------------------------------------
    # Core update logic
    # ------------------------------------------------------------------
    def process_actions(
        self, actions: dict[str, AgentAction]
    ) -> tuple[PhaseEvents, bool, Optional[dict[str, str]]]:
        phase = self.phase_lookup[self.current_phase]
        acting_agents = self.active_agents_for_phase()
        events = PhaseEvents()

        if phase.kind == "announcement":
            events.extend(self._resolve_phase(phase, {}))
            winner = self._check_end_conditions()
            self._schedule_phase_exit(phase)
            return events, True, winner

        if not acting_agents:
            events.extend(self._resolve_phase(phase, {}))
            winner = self._check_end_conditions()
            self._schedule_phase_exit(phase)
            return events, True, winner

        relevant = {
            name: actions.get(name, AgentAction(action_type="none", argument=""))
            for name in acting_agents
        }

        if phase.turn_mode == "round-robin":
            actor = acting_agents[0]
            events.extend(self._record_speech(actor, relevant[actor], phase))
            events.extend(self._process_custom_actions(actor, relevant[actor], phase))  # ADD THIS

            events.extend(self._resolve_phase(phase, {actor: relevant[actor]}))
            self._advance_round_robin(phase)
            advance = self._should_advance(phase)
        else:
            for actor, action in relevant.items():
                events.extend(self._record_speech(actor, action, phase))
                events.extend(self._process_custom_actions(actor, relevant[actor], phase))  # ADD THIS

            events.extend(self._resolve_phase(phase, relevant))
            advance = True

        winner = self._check_end_conditions()
        if winner:
            self._schedule_phase_exit(phase)
            return events, True, winner

        if advance:
            self._schedule_phase_exit(phase)
        return events, advance, winner
    
    def start_next_phase(self) -> PhaseEvents:
        next_phase = self.rules.phase_transitions.get(self.current_phase)
        if next_phase is None:
            # No transition means this is the final phase - return empty events
            return PhaseEvents()
        
        # Only execute this if next_phase exists
        self.current_phase = next_phase
        self.phase_cycle_progress = 0
        self.turns_in_phase = 0
        self.current_actor_index = 0
        self._register_phase_entry(next_phase)
        phase_def = self.phase_lookup[next_phase]
        entry = PhaseEvents.phase_entry(next_phase, phase_def.entry_messages)
        return entry
    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _phase_group(self, phase: PhaseDefinition) -> str:
        if phase.group:
            return phase.group
        return phase.name

    def _register_phase_entry(self, phase_name: str) -> None:
        phase = self.phase_lookup[phase_name]
        group = self._phase_group(phase)
        previous_group = (
            self.current_phase_meta.get("group") if self.current_phase_meta else None
        )
        cycle = self.group_cycle.get(group, 0)
        stage = self.group_stage.get(group, 0)
        if previous_group != group:
            cycle += 1
            stage = 1
        else:
            stage += 1
        self.group_cycle[group] = cycle
        self.group_stage[group] = stage
        self.current_phase_meta = {
            "phase": phase_name,
            "group": group,
            "group_cycle": cycle,
            "group_stage": stage,
            "display_name": phase.name.replace("_", " ").title(),
        }

    def current_phase_metadata(self) -> dict[str, Any]:
        return dict(self.current_phase_meta) if self.current_phase_meta else {}

    def _eligible_candidates(self, phase: PhaseDefinition) -> list[str]:
        names = [name for name, state in self.agent_states.items() if state.alive]
        if phase.acting_roles:
            names = [
                name
                for name in names
                if self.agent_states[name].role in phase.acting_roles
            ]
        if phase.acting_teams:
            names = [
                name
                for name in names
                if self.agent_states[name].team in phase.acting_teams
            ]
        return names

    def _record_speech(
        self, actor: str, action: AgentAction, phase: PhaseDefinition
    ) -> PhaseEvents:
        events = PhaseEvents()
        if action.action_type not in {"speak", "non-verbal communication"}:
            return events
        utterance = action.argument.strip()
        if not utterance:
            return events
        line = f'{actor} said: "{utterance}"'
        if phase.speech_visibility == "team":
            team = self.agent_states[actor].team
            events.team.setdefault(team, []).append(line)
        elif phase.speech_visibility == "private":
            events.private.setdefault(actor, []).append(line)
        elif phase.speech_visibility == "hidden":
            pass
        else:
            events.public.append(line)
        return events
    
    def _process_custom_actions(
        self, 
        actor: str, 
        action: AgentAction, 
        phase: PhaseDefinition
    ) -> PhaseEvents:
        """Interpret custom narrative actions."""
        events = PhaseEvents()
        phase_name = self.current_phase
        
        if action.action_type == "accuse":
            target = self._extract_target([action])
            if target:
                events.public.append(f"[God] {actor} accuses {target}!")
                # Track in state_flags for judgment phase
                accusation_log = self.state_flags.setdefault("accusations", [])
                accusation_log.append(
                    {
                        "accuser": actor,
                        "accused": target,
                        "phase": phase_name,
                    }
                )
                accusations_against_target = sum(
                    1 for entry in accusation_log if entry.get("accused") == target
                )
                events.public.append(
                    f"[God] Court docket now records {accusations_against_target} accusation"
                    f"{'s' if accusations_against_target != 1 else ''} naming {target}."
                )
                self._record_case_fact(
                    fact_type="accusation",
                    source=actor,
                    target=target,
                    details={"text": action.argument.strip(), "phase": phase_name},
                )
        
        elif action.action_type == "interrogate":
            target = self._extract_target([action])
            if target:
                events.public.append(f"[God] {actor} interrogates {target} intensely.")
                interrogation_log = self.state_flags.setdefault("interrogations", [])
                interrogation_log.append(
                    {
                        "interrogator": actor,
                        "target": target,
                        "phase": phase_name,
                    }
                )
                self._record_case_fact(
                    fact_type="interrogation",
                    source=actor,
                    target=target,
                    details={"text": action.argument.strip(), "phase": phase_name},
                )
        
        elif action.action_type == "intimidate":
            target = self._extract_target([action])
            if target:
                events.public.append(f"[God] {actor} intimidates {target} menacingly.")
                self._record_case_fact(
                    fact_type="intimidation",
                    source=actor,
                    target=target,
                    details={"text": action.argument.strip(), "phase": phase_name},
                )
        
        elif action.action_type == "present_evidence" or (
            "present" in action.argument.lower() and "card" in action.argument.lower()
        ):
            target = self._extract_target([action])
            events.public.append(f"[God] {actor} presents marked cards as evidence!")
            self.state_flags["evidence_presented"] = True
            self._record_case_fact(
                fact_type="evidence",
                source=actor,
                target=target,
                details={
                    "artifact": "marked_cards",
                    "text": action.argument.strip(),
                    "phase": phase_name,
                },
            )
            if target:
                suspect_evidence = self.state_flags.setdefault("evidence_against", {})
                evidence_list = suspect_evidence.setdefault(target, [])
                if "marked_cards" not in evidence_list:
                    evidence_list.append("marked_cards")
                catalogue = ", ".join(evidence_list)
                events.public.append(
                    f"[God] Case file updated: evidence against {target} now includes {catalogue}."
                )
        
        return events
    
    def _record_case_fact(
        self,
        *,
        fact_type: str,
        source: str,
        target: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Persist structured incident data for later phase resolutions."""
        case_log = self.state_flags.setdefault("case_log", [])
        payload = {
            "type": fact_type,
            "source": source,
            "target": target,
            "details": details or {},
        }
        case_log.append(payload)

    def _find_evidence_presenter(
        self,
        *,
        artifact: str | None = None,
        target: str | None = None,
    ) -> str | None:
        """Find the most recent actor who submitted matching evidence."""
        case_log = self.state_flags.get("case_log", [])
        for entry in reversed(case_log):
            if entry.get("type") != "evidence":
                continue
            details = entry.get("details") or {}
            if artifact and details.get("artifact") != artifact:
                continue
            if target and entry.get("target") != target:
                continue
            return entry.get("source")
        return None

    def _ability_uses(self, state: AgentState, ability: str) -> int:
        abilities = state.attributes.get("abilities", {})
        if not isinstance(abilities, dict):
            return 0
        config = abilities.get(ability)
        if not isinstance(config, dict):
            return 0
        uses = config.get("uses", 0)
        try:
            return max(int(uses), 0)
        except (TypeError, ValueError):
            return 0

    def _consume_ability_use(self, state: AgentState, ability: str) -> bool:
        abilities = state.attributes.get("abilities", {})
        if not isinstance(abilities, dict):
            return False
        config = abilities.get(ability)
        if not isinstance(config, dict):
            return False
        uses = self._ability_uses(state, ability)
        if uses <= 0:
            return False
        config["uses"] = uses - 1
        abilities[ability] = config
        state.attributes["abilities"] = abilities
        return True

    def _combat_attack_rating(self, state: AgentState) -> int:
        rating = 1
        items = state.attributes.get("items", [])
        if isinstance(items, list):
            if any(
                weapon in items
                for weapon in ("revolver", "rifle", "shotgun", "derringer")
            ):
                rating += 3
            elif any("knife" in item for item in items):
                rating += 1

        rating += min(self._ability_uses(state, "sharpshooting"), 1) * 2
        rating += min(self._ability_uses(state, "success"), 1)
        return rating

    def _combat_defense_rating(self, state: AgentState) -> int:
        rating = 1
        items = state.attributes.get("items", [])
        if isinstance(items, list):
            if any(
                armor in items
                for armor in ("bulletproof_vest", "steel_plate", "first_aid_kit")
            ):
                rating += 1
        rating += min(self._ability_uses(state, "flesh_wound"), 1) * 2
        rating += min(self._ability_uses(state, "success"), 1)
        return rating

    def _resolve_phase(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
    ) -> PhaseEvents:
        if phase.resolution is None:
            return PhaseEvents()
        handler = getattr(self, f"_resolve_{phase.resolution.operation}", None)
        if handler is None:
            raise ValueError(
                f"Unsupported resolution operation '{phase.resolution.operation}'"
            )
        return cast(PhaseEvents, handler(phase, actions, phase.resolution))

    def _resolve_noop(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        return PhaseEvents()

    def _resolve_store_target(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        events = PhaseEvents()
        target = self._extract_target(actions.values())
        if target:
            self.state_flags[resolution.state_key or "night_target"] = target
            teams = phase.acting_teams or [self.agent_states[a].team for a in actions]
            for team in teams:
                events.team.setdefault(team, []).append(
                    f"[God] Target locked: {target}."
                )
        return events

    def _resolve_seer_inspect(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        events = PhaseEvents()
        if not actions:
            return events
        actor, action = next(iter(actions.items()))
        target = self._extract_target([action])
        if not target:
            events.private.setdefault(actor, []).append(
                "[God] Vision failed: unable to interpret your target."
            )
            return events
        team = self.agent_states[target].team
        message = f"[God] Vision reveals {target} serves team {team}."
        events.private.setdefault(actor, []).append(message)
        self.state_flags["seer_result"] = message
        return events

    def _resolve_witch_phase(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        events = PhaseEvents()
        if not actions:
            return events
        actor, action = next(iter(actions.items()))
        state = self.agent_states[actor]
        text = action.argument.lower()
        if "save" in text and state.attributes.get("save_available", True):
            target = self._extract_target([action]) or self.state_flags.get(
                "night_target"
            )
            if target:
                self.state_flags["witch_saved"] = target
                state.attributes["save_available"] = False
                events.private.setdefault(actor, []).append(
                    f"[God] You secretly saved {target} tonight."
                )
        if "poison" in text and state.attributes.get("poison_available", True):
            target = self._extract_target([action])
            if target:
                self.state_flags["witch_poisoned"] = target
                state.attributes["poison_available"] = False
                events.private.setdefault(actor, []).append(
                    f"[God] You poisoned {target}."
                )
        if not text.strip() or "pass" in text:
            events.private.setdefault(actor, []).append(
                "[God] You chose to remain idle."
            )
        return events

    def _resolve_resolve_night(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        events = PhaseEvents()
        saved = self.state_flags.get("witch_saved")
        target = self.state_flags.get("night_target")
        poison = self.state_flags.get("witch_poisoned")
        casualties: list[str] = []
        if target and target != saved:
            casualties.append(target)
        if poison and poison not in casualties:
            casualties.append(poison)
        if not casualties:
            events.public.append("[God] Dawn breaks peacefully. No one died.")
        for victim in casualties:
            if victim in self.agent_states and self.agent_states[victim].alive:
                self.agent_states[victim].alive = False
                events.public.append(f"[God] {victim} was found dead at dawn.")
        self.state_flags["night_target"] = None
        self.state_flags["witch_saved"] = None
        self.state_flags["witch_poisoned"] = None
        self.state_flags["seer_result"] = ""
        return events

    def _resolve_vote(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        events = PhaseEvents()
        tally: dict[str, int] = {}
        for action in actions.values():
            target = self._extract_target([action])
            if target:
                tally[target] = tally.get(target, 0) + 1
            elif "none" in action.argument.lower():
                tally.setdefault("none", 0)
                tally["none"] += 1
        if not tally:
            events.public.append("[God] No valid votes were cast.")
            self.state_flags["day_execution"] = None
            return events
        winner, votes = max(tally.items(), key=lambda kv: kv[1])
        if winner == "none":
            events.public.append("[God] The town decided to stay their hand.")
            self.state_flags["day_execution"] = None
            return events
        if list(tally.values()).count(votes) > 1:
            events.public.append("[God] The vote is tied. No execution today.")
            self.state_flags["day_execution"] = None
            return events
        self.state_flags["day_execution"] = winner
        events.public.append(
            f"[God] Majority condemns {winner}. Execution will happen at twilight."
        )
        return events

    def _resolve_post_vote_cleanup(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        events = PhaseEvents()
        target = self.state_flags.get("day_execution")
        if target and target in self.agent_states and self.agent_states[target].alive:
            self.agent_states[target].alive = False
            team = self.agent_states[target].team
            events.public.append(
                f"[God] {target} was executed. They belonged to team {team}."
            )
        self.state_flags["day_execution"] = None
        return events
    
    # Add these methods to the GameRulebook class in social_game.py

    def _resolve_announce_event(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        """Announce key story events (like Zeke's death)."""
        events = PhaseEvents()
        # This is handled by entry_messages in phase definition
        # Just return empty events - the phase entry messages do the work
        return events

    def _resolve_judgment_phase(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        """Handle judgment phase - FORCE a decision if needed."""
        events = PhaseEvents()
        evidence_against = self.state_flags.get("evidence_against", {})
        doc_evidence = set(evidence_against.get("Doc Faraday", []))
        lucy_evidence = set(evidence_against.get("Lucy Calhoun", []))

        accusation_entries = self.state_flags.get("accusations", [])
        accusation_counts: Counter[str] = Counter()
        seen_pairs: set[tuple[str, str]] = set()
        for entry in accusation_entries:
            accuser = entry.get("accuser")
            accused = entry.get("accused")
            if not accuser or not accused:
                continue
            pair = (accuser, accused)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            accusation_counts[accused] += 1

        def finalize(owner: str, message: str, reason: str) -> PhaseEvents:
            self.state_flags["fat_bull_owner"] = owner
            self.state_flags["judgment_reason"] = reason
            events.public.append(message)
            return events
        
        # Check if Judge or Dan made a clear ruling
        judge_actors = ["John Paulson", "Dan Fairweather"]
        
        for actor in judge_actors:
            if actor not in actions or actor not in self.agent_states:
                continue
            if not self.agent_states[actor].alive:
                continue
                
            action = actions[actor]
            text = action.argument.lower()
            
            # Check for explicit judgment
            if ("lucy" in text or "calhoun" in text) and "rules" in text:
                return finalize(
                    owner="Lucy Calhoun",
                    message=(
                        f"[God] {actor} rules that Fat Bull Range belongs to Lucy Calhoun."
                    ),
                    reason="judge_explicit_lucy",
                )
            elif ("doc" in text or "faraday" in text) and "rules" in text:
                return finalize(
                    owner="Doc Faraday",
                    message=(
                        f"[God] {actor} rules that Doc Faraday won Fat Bull Range fairly."
                    ),
                    reason="judge_explicit_doc",
                )
        
        if doc_evidence:
            presenter = self._find_evidence_presenter(
                artifact="marked_cards", target="Doc Faraday"
            )
            witness = presenter or "a witness"
            return finalize(
                owner="Lucy Calhoun",
                message=(
                    f"[God] Judge Paulson accepts the marked cards shown by {witness}. "
                    "Doc Faraday's victory is voided and Fat Bull Range returns to Lucy Calhoun."
                ),
                reason="cheating_proven",
            )

        if lucy_evidence:
            presenter = self._find_evidence_presenter(target="Lucy Calhoun")
            witness = presenter or "a witness"
            evidence_list = ", ".join(sorted(lucy_evidence))
            return finalize(
                owner="Doc Faraday",
                message=(
                    f"[God] Judge Paulson cites {witness}'s evidence against Lucy Calhoun "
                    f"({evidence_list}). Doc Faraday retains ownership of Fat Bull Range."
                ),
                reason="lucy_implicated",
            )

        # FORCE JUDGMENT if we're at the end of judgment phase
        near_end = False
        if phase.max_turns is not None and self.turns_in_phase >= max(phase.max_turns - 1, 0):
            near_end = True
        elif phase.max_cycles is not None and phase.max_cycles > 0:
            if self.phase_cycle_progress >= phase.max_cycles - 1:
                near_end = True
        
        if near_end:
            if accusation_counts:
                top_target, top_count = accusation_counts.most_common(1)[0]
                # Check for tie at top
                if list(accusation_counts.values()).count(top_count) == 1:
                    accuser_count_text = (
                        f"{top_count} separate accusation{'s' if top_count != 1 else ''}"
                    )
                    if top_target == "Doc Faraday":
                        return finalize(
                            owner="Lucy Calhoun",
                            message=(
                                f"[God] Judge Paulson notes {accuser_count_text} naming Doc Faraday. "
                                "The court awards Fat Bull Range to Lucy Calhoun."
                            ),
                            reason="accusation_majority_doc",
                        )
                    elif top_target == "Lucy Calhoun":
                        return finalize(
                            owner="Doc Faraday",
                            message=(
                                f"[God] Judge Paulson cites {accuser_count_text} against Lucy Calhoun. "
                                "Doc Faraday keeps Fat Bull Range."
                            ),
                            reason="accusation_majority_lucy",
                        )
            if self.state_flags.get("evidence_presented"):
                return finalize(
                    owner="Lucy Calhoun",
                    message=(
                        "[God] Judge Paulson rules: 'The evidence of cheating stands. "
                        "Fat Bull Range belongs to Lucy Calhoun.'"
                    ),
                    reason="generic_evidence",
                )
            # Default ruling when no decisive proof
            return finalize(
                owner="Doc Faraday",
                message=(
                    "[God] Judge Paulson rules: 'Without concrete proof, "
                    "the original game result stands. Fat Bull Range belongs to Doc Faraday.'"
                ),
                reason="no_evidence_default",
            )
        
        # Default: no clear judgment yet
        events.public.append("[God] The court awaits the Judge's decision...")
        return events

    def _resolve_duel_resolution(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        """Handle duels and shootouts at High Noon."""
        events = PhaseEvents()
        
        for actor, action in actions.items():
            if action.action_type in {"shoot", "duel"}:
                target = self._extract_target([action])
                if target and target in self.agent_states:
                    actor_state = self.agent_states[actor]
                    target_state = self.agent_states[target]

                    attack_rating = self._combat_attack_rating(actor_state)
                    defense_rating = self._combat_defense_rating(target_state)
                    hit = False
                    ability_used: str | None = None

                    if attack_rating > defense_rating:
                        hit = True
                    elif attack_rating == defense_rating:
                        if self._consume_ability_use(actor_state, "sharpshooting"):
                            hit = True
                            ability_used = "sharpshooting"
                        elif self._consume_ability_use(actor_state, "success"):
                            hit = True
                            ability_used = "success"
                    else:
                        if self._consume_ability_use(actor_state, "success"):
                            hit = True
                            ability_used = "success"

                    if hit:
                        if self._consume_ability_use(target_state, "flesh_wound"):
                            events.public.append(
                                f"[God] {target} survives the shot thanks to a practiced flesh wound trick!"
                            )
                            continue
                        if self._consume_ability_use(target_state, "success"):
                            events.public.append(
                                f"[God] {target} narrowly dodges the attack at the last second!"
                            )
                            continue

                        if target_state.alive:
                            target_state.alive = False
                            if ability_used == "sharpshooting":
                                events.public.append(
                                    f"[God] {actor} executes {target} with deadly sharpshooting precision!"
                                )
                            elif ability_used == "success":
                                events.public.append(
                                    f"[God] {actor}'s quick instincts turn the tide—{target} is shot dead!"
                                )
                            else:
                                events.public.append(f"[God] {actor} shoots {target} dead!")
                    else:
                        events.public.append(f"[God] {actor} misses {target}!")
            
            elif action.action_type == "strangle":
                target = self._extract_target([action])
                if target and target in self.agent_states:
                    # Strangle requires being behind target (garotte)
                    if "garotte" in self.agent_states[actor].attributes.get("items", []):
                        if self.agent_states[target].alive:
                            self.agent_states[target].alive = False
                            events.public.append(f"[God] {actor} strangles {target} with a garotte!")
                            
            elif action.action_type == "poison":
                target = self._extract_target([action])
                if target and target in self.agent_states:
                    # Mark as poisoned
                    self.agent_states[target].attributes["poisoned"] = True
                    events.private.setdefault(target, []).append(
                        "[God] You feel a sudden illness... you've been poisoned!"
                    )
        
        return events

    def _resolve_resolve_game(
        self,
        phase: PhaseDefinition,
        actions: dict[str, AgentAction],
        resolution: PhaseResolution,
    ) -> PhaseEvents:
        """Announce the story's closure and survivors."""
        events = PhaseEvents()
        
        survivors = [name for name, state in self.agent_states.items() if state.alive]
        dead = [name for name, state in self.agent_states.items() if not state.alive]
        
        if survivors:
            events.public.append(f"[God] Survivors of Cactus Gulch: {', '.join(survivors)}")
        else:
            events.public.append("[God] No one survived the bloodshed in Cactus Gulch.")
        
        if dead:
            events.public.append(f"[God] The fallen: {', '.join(dead)}")
        
        # Determine railroad outcome based on Fat Bull Range ownership
        owner = self.state_flags.get("fat_bull_owner", "undecided")
        if owner == "Lucy Calhoun":
            events.public.append(
                "[God] Lucy Calhoun inherits Fat Bull Range. "
                "The burial grounds are protected from the railroad."
            )
        elif owner == "Doc Faraday":
            events.public.append(
                "[God] Doc Faraday owns Fat Bull Range. "
                "The highest bidder will likely desecrate the burial grounds."
            )
        else:
            events.public.append("[God] The ownership of Fat Bull Range remains disputed.")
        
        return events

    def _extract_target(self, actions: Iterable[AgentAction]) -> str | None:
        for action in actions:
            corpus = f"{action.action_type} {action.argument}".lower()
            for name in self.agent_states:
                if name.lower() in corpus:
                    return name
            for name in self.agent_states:
                first = name.split()[0].lower()
                if first in corpus:
                    return name
        return None

    def _advance_round_robin(self, phase: PhaseDefinition) -> None:
        base = self._eligible_candidates(phase)
        self.turns_in_phase += 1
        if not base:
            self.current_actor_index = 0
            return
        self.current_actor_index += 1
        if self.current_actor_index >= len(base):
            self.phase_cycle_progress += 1
            self.current_actor_index = 0

    def _should_advance(self, phase: PhaseDefinition) -> bool:
        if phase.turn_mode != "round-robin":
            return True
        base = self._eligible_candidates(phase)
        if not base:
            return True
        if phase.max_turns is not None and self.turns_in_phase >= phase.max_turns:
            return True
        if self.phase_cycle_progress >= phase.max_cycles:
            return True
        return False

    def _schedule_phase_exit(self, phase: PhaseDefinition) -> None:
        exit_events = PhaseEvents()
        for msg in phase.exit_messages:
            exit_events.public.append(f"[God] {msg}")
        self.pending_events.extend(exit_events)

    def _check_end_conditions(self) -> Optional[dict[str, str]]:
        for cond in self.rules.end_conditions:
            if cond.operation == "team_eliminated" and cond.team:
                alive = sum(
                    1
                    for state in self.agent_states.values()
                    if state.alive and state.team == cond.team
                )
                if alive == 0:
                    message = (
                        cond.message or f"[God] Team {cond.team} has been eliminated."
                    )
                    return {
                        "winner": cond.winner or cond.other_team or cond.team,
                        "message": message,
                    }
            if cond.operation == "parity" and cond.team and cond.other_team:
                team_count = sum(
                    1
                    for state in self.agent_states.values()
                    if state.alive and state.team == cond.team
                )
                other_count = sum(
                    1
                    for state in self.agent_states.values()
                    if state.alive and state.team == cond.other_team
                )
                if team_count >= other_count:
                    message = cond.message or (
                        f"[God] Parity reached: {cond.team} now matches or exceeds {cond.other_team}."
                    )
                    return {
                        "winner": cond.winner or cond.team,
                        "message": message,
                    }
        return None
    


class SocialGameEnv(ParallelSotopiaEnv):
    """Environment subclass that enforces multi-phase social game mechanics."""

    def __init__(
        self,
        env_profile: EnvironmentProfile,
        *,
        rulebook_path: str,
        actions_path: str,
        role_assignments: dict[str, str],
        enable_memory_tracking: bool = False,      # ← NEW TOGGLE
        enable_repetition_check: bool = False,     # ← NEW TOGGLE
        **kwargs: Any,
    ) -> None:
        super().__init__(env_profile=env_profile, **kwargs)
        self._rulebook_path = Path(rulebook_path)
        self._actions_path = Path(actions_path)
        self._role_assignments = role_assignments
        self.game_rulebook: GameRulebook | None = None
        self._last_events: PhaseEvents = PhaseEvents()
        self._winner_payload: dict[str, str] | None = None
        self.phase_log: list[dict[str, Any]] = []
        
        # Optional features (toggle per game)
        self._enable_memory = enable_memory_tracking
        self._enable_repetition = enable_repetition_check
        
        # Conditionally initialize memory features
        if self._enable_memory:
            from sotopia.game_utils.memory_tracker import GameMemory


            self.game_memory = GameMemory()
        else:
            self.game_memory = None
            
        if self._enable_repetition:
            self.recent_utterances: dict[str, list[str]] = {}
        else:
            self.recent_utterances = None

    # ------------------------------------------------------------------
    # Config loading helpers
    # ------------------------------------------------------------------
    def _load_configs(self) -> tuple[RulebookConfig, RoleActionLibrary]:
        try:
            rules = RulebookConfig.model_validate_json(self._rulebook_path.read_text())
        except ValidationError as exc:
            raise ValueError(f"Invalid rulebook config: {exc}") from exc
        actions_raw = json.loads(self._actions_path.read_text())
        try:
            roles = RoleActionLibrary.model_validate(actions_raw["roles"])
        except (KeyError, ValidationError) as exc:
            raise ValueError(f"Invalid action-space config: {exc}") from exc
        return rules, roles

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------
    def reset(
        self,
        seed: int | None = None,
        options: dict[str, str] | None = None,
        agents: Agents | None = None,
        omniscient: bool = False,
        lite: bool = False,
    ) -> dict[str, Observation]:
        base_obs = super().reset(
            seed=seed,
            options=options,
            agents=agents,
            omniscient=omniscient,
            lite=lite,
        )
        rules, role_actions = self._load_configs()
        self.game_rulebook = GameRulebook(rules, role_actions)
        self.game_rulebook.assign_agents(self.agents, self._role_assignments)
        self.phase_log = []
        self._apply_action_mask()
        self._last_events = self.game_rulebook.collect_pending_events()
        self._winner_payload = None
        self._record_phase_history(
            phase_name=self.game_rulebook.current_phase,
            actions={},
            events=self._last_events,
        )
        return self._augment_observations(base_obs, append_to_existing=True)

    def _phase_prompt_lines(
        self,
        *,
        agent_name: str,
        phase: PhaseDefinition,
        acting: bool,
        available: list[str],
    ) -> list[str]:
        assert self.game_rulebook is not None
        meta = self.game_rulebook.current_phase_metadata()
        group = meta.get("group")
        cycle = meta.get("group_cycle")
        stage = meta.get("group_stage")
        title = phase.name.replace("_", " ").title()
        if group:
            group_label = group.replace("_", " ").title()
            if cycle and stage:
                label = f"{group_label} {cycle}.{stage} – {title}"
            elif cycle:
                label = f"{group_label} {cycle} – {title}"
            else:
                label = f"{group_label}: {title}"
        else:
            label = title
        lines = [f"[God] Phase: {label}"]
        if acting:
            lines.append("[God] It is your turn to act in this phase.")
        else:
            lines.append("[God] You are observing while others act.")
        lines.append(f"[God] Available actions right now: {', '.join(available)}")
        lines.extend(f"[God] {text}" for text in phase.instructions)
        role = self.game_rulebook.agent_states[agent_name].role
        for text in phase.role_instructions.get(role, []):
            lines.append(f"[God] {text}")
        return lines

    def _record_phase_history(
        self,
        *,
        phase_name: str,
        actions: dict[str, AgentAction],
        events: PhaseEvents,
    ) -> None:
        if self.game_rulebook is None:
            return
        if not (events.public or events.team or events.private):
            if any(a.action_type != "none" for a in actions.values()):
                pass
            else:
                return
        action_summary = {
            agent: {"action_type": action.action_type, "argument": action.argument}
            for agent, action in actions.items()
            if action.action_type != "none"
        }
        phase_def = (
            self.game_rulebook.phase_lookup.get(phase_name)
            if self.game_rulebook
            else None
        )
        snapshot = {
            "phase": phase_name,
            "turn": self.turn_number,
            "public": list(events.public),
            "team": {team: list(msgs) for team, msgs in events.team.items()},
            "private": {agent: list(msgs) for agent, msgs in events.private.items()},
            "actions": action_summary,
            "meta": self.game_rulebook.current_phase_metadata()
            if self.game_rulebook
            else {},
            "instructions": phase_def.instructions if phase_def else [],
            "role_instructions": phase_def.role_instructions if phase_def else {},
        }
        self.phase_log.append(snapshot)

    def _augment_observations(
        self,
        baseline: dict[str, Observation],
        *,
        append_to_existing: bool,
    ) -> dict[str, Observation]:
        assert self.game_rulebook is not None
        acting = set(self.game_rulebook.active_agents_for_phase())
        events = self._last_events
        phase_name = self.game_rulebook.current_phase
        phase_def = self.game_rulebook.phase_lookup[phase_name]
        new_obs: dict[str, Observation] = {}
        #memory_summary = self.game_memory.get_context_summary() #never use this. commenting for now.
        for idx, agent_name in enumerate(self.agents):
            current = baseline[agent_name]
            available = (
                self.game_rulebook.available_actions(agent_name)
                if agent_name in acting
                else ["none"]
            )
            phase_lines = self._phase_prompt_lines(
                agent_name=agent_name,
                phase=phase_def,
                acting=agent_name in acting,
                available=["speak", "action", "none"] ,
            )

            role_cfg = self.game_rulebook.roles.root[self.game_rulebook.agent_states[agent_name].role]
            custom_actions = role_cfg.phase_actions.get(
                self.game_rulebook.current_phase, 
                role_cfg.default_actions
            )

            if custom_actions:
                phase_lines.append(
                    f"[God] You can use these narrative actions via the 'action' type: "
                    f"{', '.join(custom_actions)}"
                )
            messages: list[str] = []
            messages.extend(events.public)
            team = self.game_rulebook.agent_states[agent_name].team
            messages.extend(events.team.get(team, []))
            messages.extend(events.private.get(agent_name, []))
            if not messages:
                messages.append("[God] Await instructions from the host.")

            segments: list[str] = []
            if append_to_existing:
                prefix = current.last_turn.strip()
                if prefix:
                    segments.append(prefix)

            # Optional: Add memory context
            if self._enable_memory and self.game_memory is not None:
                memory_summary = self.game_memory.get_context_summary()
                if memory_summary:  # Only add if there's actual content
                    segments.append(memory_summary)

            segments.extend(phase_lines)

            segments.extend(messages)
            combined = "\n".join(segment for segment in segments if segment)
            new_obs[agent_name] = Observation(
                last_turn=render_text_for_agent(combined, agent_id=idx),
                turn_number=current.turn_number,
                available_actions=available,
            )
        return new_obs

    def _create_blank_observations(self) -> dict[str, Observation]:
        assert self.game_rulebook is not None
        acting = set(self.game_rulebook.active_agents_for_phase())
        blank: dict[str, Observation] = {}
        for agent_name in self.agents:
            available = (
                self.game_rulebook.available_actions(agent_name)
                if agent_name in acting
                else ["none"]
            )
            blank[agent_name] = Observation(
                last_turn="",
                turn_number=self.turn_number,
                available_actions=available,
            )
        return blank

    def _apply_action_mask(self) -> None:
        assert self.game_rulebook is not None
        acting = set(self.game_rulebook.active_agents_for_phase())
        self.action_mask = [
            agent in acting and self.game_rulebook.agent_states[agent].alive
            for agent in self.agents

        ]
    def _check_repetition(self, agent: str, text: str) -> bool:
        """Check if agent is repeating themselves using generic similarity."""
        if self.recent_utterances is None:
            return False
            
        if agent not in self.recent_utterances:
            self.recent_utterances[agent] = []
        
        # Simple similarity: check if text is very similar to recent utterances
        # (You could use more sophisticated NLP here)
        for recent in self.recent_utterances[agent]:
            # Count matching words (simple approach)
            text_words = set(text.lower().split())
            recent_words = set(recent.lower().split())
            
            # If >70% word overlap, consider it repetitive
            if text_words and recent_words:
                overlap = len(text_words & recent_words) / max(len(text_words), len(recent_words))
                if overlap > 0.7:
                    return True
        
        # Store this utterance (keep last 3)
        self.recent_utterances[agent].append(text)
        if len(self.recent_utterances[agent]) > 3:
            self.recent_utterances[agent].pop(0)
        
        return False
    
    async def astep(
        self, actions: dict[str, AgentAction] | dict[str, dict[str, int | str]]
    ) -> tuple[
        dict[str, Observation],
        dict[str, float],
        dict[str, bool],
        dict[str, bool],
        dict[str, dict[Any, Any]],
    ]:
        assert self.game_rulebook is not None
        if self.turn_number >= 100:
            print(f"\n⏹️ Reached turn limit of 100. Ending game.")
            winner = {"message": "Max turns reached. No decisive winner."}

        self._apply_action_mask()

        self.turn_number += 1
        print(f"\n=== TURN {self.turn_number} — Current Phase: {self.game_rulebook.current_phase} ===")

        # 🔢 Print number of agent actions submitted
        print(f"🔢 Actions this turn: {len(actions)} action(s) from {[a for a in actions.keys()]}")

        # ⚡⚡⚡ ADD THIS SECTION ⚡⚡⚡
        # Filter actions based on active agents for round-robin phases
        acting_agents = set(self.game_rulebook.active_agents_for_phase())
        
        filtered_actions = {
            agent: action 
            for agent, action in actions.items() 
            if agent in acting_agents
        }
        
        print(f"🎯 Acting agents this turn: {acting_agents}")
        print(f"🔢 Actions this turn: {len(filtered_actions)} action(s) from {list(filtered_actions.keys())}")
        # ⚡⚡⚡ END NEW SECTION ⚡⚡⚡

        prepared = self._coerce_actions(filtered_actions)
        self.recv_message(
            "Environment", SimpleMessage(message=f"Turn #{self.turn_number}")
        )
        for agent, action in prepared.items():
            self.recv_message(agent, action)
            
            # Optional: Track memory (Way Out West specific patterns)
            if self._enable_memory and self.game_memory is not None:
                text = action.argument.lower()
                
                # Generic: Track evidence mentions
                if "evidence" in text or "proof" in text:
                    self.game_memory.add_evidence(f"{agent} mentioned evidence")
                
                # Track accusations (generic pattern)
                if action.action_type == "accuse":
                    target = self.game_rulebook._extract_target([action])
                    if target:
                        self.game_memory.add_accusation(agent, target)
                        
        phase_name = self.game_rulebook.current_phase
        events, advance, _ = self.game_rulebook.process_actions(prepared)

         # Check for end condition (turn limit, epilogue, or team elimination)
        winner = self._check_winner_conditions()

        # events, advance, winner = self.game_rulebook.process_actions(prepared)

        # Optional: Check for repetition
        if self._enable_repetition and self.recent_utterances is not None:
            for agent, action in prepared.items():
                if action.action_type == "speak":
                    if self._check_repetition(agent, action.argument):
                        events.public.append(
                            f"[God] {agent} seems to be repeating themselves. "
                            f"Perhaps they should try a different action?"
                        )

        exit_events = self.game_rulebook.collect_pending_events()
        events.extend(exit_events)
        self._record_phase_history(
            phase_name=phase_name,
            actions=prepared,
            events=events,
        )
        self._last_events = events
        if advance:
            next_events = self.game_rulebook.start_next_phase()
            self._record_phase_history(
                phase_name=self.game_rulebook.current_phase,
                actions={},
                events=next_events,
            )
            self._last_events.extend(next_events)
        self._apply_action_mask()
        baseline = self._create_blank_observations()
        observations = self._augment_observations(baseline, append_to_existing=False)
        rewards = {agent_name: 0.0 for agent_name in self.agents}
        terminated = {agent_name: bool(winner) for agent_name in self.agents}
        truncations = {agent_name: False for agent_name in self.agents}
        info = {
            agent_name: {
                "comments": winner["message"] if winner else "",
                "complete_rating": 0,
            }
            for agent_name in self.agents
        }
        if winner:
            self._winner_payload = winner
        if winner:
            print(f"\n🏁 Game Over! Winner decided in turn {self.turn_number}. Message: {winner['message']}")
        else:
            print(f"✅ End of Turn {self.turn_number}. No winner yet.")

        return observations, rewards, terminated, truncations, info

    def _coerce_actions(
        self, actions: dict[str, AgentAction] | dict[str, dict[str, int | str]]
    ) -> dict[str, AgentAction]:
        prepared: dict[str, AgentAction] = {}
        for agent, raw in actions.items():
            if isinstance(raw, AgentAction):
                prepared[agent] = raw
            else:
                idx = int(raw.get("action_type", 0))
                action_type = self.available_action_types[idx]
                prepared[agent] = AgentAction(
                    action_type=action_type,
                    argument=str(raw.get("argument", "")),
                )
        return prepared

    def step(
        self, actions: dict[str, AgentAction] | dict[str, dict[str, int | str]]
    ) -> tuple[
        dict[str, Observation],
        dict[str, float],
        dict[str, bool],
        dict[str, bool],
        dict[str, dict[Any, Any]],
    ]:
        return asyncio.run(self.astep(actions))
    

    #def _check_winner_conditions(self):
    def _check_winner_conditions(self) -> Optional[dict[str, str]]:
        if self.game_rulebook is None:
            return None
        current_phase = self.game_rulebook.current_phase
        turn_count = self.turn_number

        # 1. Turn limit condition
        if turn_count >= 100:
            return {
                "winner": None,
                "message": "[God] The sun sets on Cactus Gulch with no clear winner. History will forget the truth."
            }

        # 2. Phase completion (epilogue)
        if current_phase == "epilogue":
            # Determine winner based on game state
            owner = self.game_rulebook.state_flags.get("fat_bull_owner", "undecided")
            
            if owner == "Lucy Calhoun":
                return {
                    "winner": "locals",
                    "message": "[God] Lucy Calhoun won Fat Bull Range. The burial grounds are protected from the railroad."
                }
            elif owner == "Doc Faraday":
                return {
                    "winner": "out_of_towners",
                    "message": "[God] Doc Faraday controls Fat Bull Range. The burial grounds may be desecrated."
                }
            else:
                return {
                    "winner": None,
                    "message": "[God] The tale of Cactus Gulch is told. Ownership remains disputed."
                }
        
        # 3. Team elimination - use game_rulebook.rules, not self.rules
        for condition in self.game_rulebook.rules.end_conditions:
            if condition.operation == "team_eliminated" and condition.team:
                if self._team_is_eliminated(condition.team):
                    return {
                        "winner": condition.winner,
                        "message": condition.message
                    }

        return None  # No end condition triggered

    def _team_is_eliminated(self, team: str) -> bool:
        """Check if all members of a team are dead."""
        if self.game_rulebook is None:
            return False
        
        for agent_name, state in self.game_rulebook.agent_states.items():
            if state.team == team and state.alive:
                return False  # At least one team member is alive
        
        return True  # All team members are dead
