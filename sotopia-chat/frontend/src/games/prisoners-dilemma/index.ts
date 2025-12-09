import type { GameDefinition } from "@/core/types/game-module";
import { ConsentCard } from "@/core/components/consent-card";
import { PrisonersDilemmaLobby } from "@/games/prisoners-dilemma/components/lobby";
import { PrisonersDilemmaGameBoard } from "@/games/prisoners-dilemma/components/game-board";
import { usePrisonersDilemmaSession } from "@/games/prisoners-dilemma/use-session";
import { usePrisonersDilemmaActions } from "@/games/prisoners-dilemma/use-actions";
import type { PrisonersDilemmaSessionState } from "@/games/prisoners-dilemma/types";

export const prisonersDilemmaGame: GameDefinition<PrisonersDilemmaSessionState> = {
    slug: "prisoners-dilemma",
    title: "Prisoner's Dilemma",
    summary:
        "Decide whether to cooperate or defect against an LLM prisoner in a simultaneous, one-shot game.",
    tags: ["game theory", "simultaneous"],
    accentColor: "#facc15",
    components: {
        Consent: ConsentCard,
        Lobby: PrisonersDilemmaLobby,
        GameBoard: PrisonersDilemmaGameBoard,
    },
    hooks: {
        useSession: usePrisonersDilemmaSession,
        useActions: usePrisonersDilemmaActions,
    },
};

export default prisonersDilemmaGame;
