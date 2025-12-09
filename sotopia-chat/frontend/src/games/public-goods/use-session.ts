import useSWR from "swr";
import type { GameSessionHookResult } from "@/core/types/game-module";
import type { PublicGoodsSessionState } from "./types";
import { getPublicGoodsSession } from "./api";

export function usePublicGoodsSession(
    sessionId: string | null,
    _participantId: string | null
): GameSessionHookResult<PublicGoodsSessionState> {
    void _participantId;
    const key = sessionId ? ["public-goods-session", sessionId] : null;
    const { data, error, isLoading } = useSWR(
        key,
        () => (sessionId ? getPublicGoodsSession(sessionId) : Promise.reject()),
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
