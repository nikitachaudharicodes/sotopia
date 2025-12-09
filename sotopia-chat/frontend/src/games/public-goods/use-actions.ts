import { useCallback, useState } from "react";
import type {
    GameActionsControls,
    GameActionsState,
} from "@/core/types/game-module";
import {
    submitPublicGoodsAction,
    type PublicGoodsAction,
} from "./api";

export function usePublicGoodsActions(
    sessionId: string | null,
    participantId: string | null
): [GameActionsState, GameActionsControls] {
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [lastError, setLastError] = useState<string | undefined>(undefined);

    const submitAction = useCallback(
        async (actionType: string, argument: string) => {
            if (!sessionId || !participantId) {
                setLastError("Missing session or participant id");
                return;
            }
            const payload: PublicGoodsAction = {
                action_type: actionType,
                argument,
            };
            try {
                setIsSubmitting(true);
                setLastError(undefined);
                await submitPublicGoodsAction(sessionId, participantId, payload);
            } catch (err) {
                console.error(err);
                setLastError(
                    err instanceof Error ? err.message : "Failed to submit action"
                );
            } finally {
                setIsSubmitting(false);
            }
        },
        [sessionId, participantId]
    );

    const clearError = useCallback(() => setLastError(undefined), []);

    return [
        { isSubmitting, lastError },
        {
            submitAction,
            clearError,
        },
    ];
}
