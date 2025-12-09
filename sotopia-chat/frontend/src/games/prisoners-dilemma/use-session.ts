import useSWR from "swr";
import type { PrisonersDilemmaSessionState } from "./types";
import type { GameSessionHookResult } from "@/core/types/game-module";
import { getPrisonersDilemmaSession } from "./api";

export function usePrisonersDilemmaSession(
    sessionId: string | null,
    _participantId: string | null
): GameSessionHookResult<PrisonersDilemmaSessionState> {
    void _participantId;
    const key = sessionId ? ["prisoners-dilemma-session", sessionId] : null;
    const { data, error, isLoading } = useSWR(
        key,
        () => (sessionId ? getPrisonersDilemmaSession(sessionId) : Promise.reject()),
        {
            refreshInterval: 2000,
            revalidateOnFocus: false,
        }
    );

    return {
        session: data,
        isLoading,
        error,
    };
}
