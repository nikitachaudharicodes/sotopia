import type { PrisonersDilemmaSessionState, PDPlayer, PDPhase } from "./types";

const API_BASE =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type ApiRecord = Record<string, unknown>;

export interface CreateGameResponse {
    session_id: string;
    status: string;
    message: string;
}

export interface PrisonersDilemmaAction {
    action_type: string;
    argument: string;
}

function resolveProp<T = unknown>(
    raw: ApiRecord | undefined,
    ...keys: string[]
): T | undefined {
    if (!raw) {
        return undefined;
    }
    for (const key of keys) {
        const value = raw[key];
        if (value !== undefined) {
            return value as T;
        }
    }
    return undefined;
}

function mapPlayer(raw: ApiRecord): PDPlayer {
    const id = resolveProp<string>(raw, "id") ?? "";
    return {
        id,
        displayName:
            resolveProp<string>(raw, "displayName", "display_name") ?? id,
        role: resolveProp<string>(raw, "role") ?? "PD_Player",
        team: resolveProp<string>(raw, "team"),
        isHost: Boolean(resolveProp(raw, "isHost", "is_host") ?? false),
    };
}

function mapPhase(raw: ApiRecord | undefined): PDPhase {
    return {
        phase: resolveProp<string>(raw, "phase") ?? "waiting",
        description: resolveProp<string>(raw, "description"),
        allowChat: Boolean(resolveProp(raw, "allowChat", "allow_chat") ?? false),
        allowActions: Boolean(
            resolveProp(raw, "allowActions", "allow_actions") ?? false
        ),
    };
}

export async function createPrisonersDilemmaGame(
    hostId: string,
    communicationMode: "communication" | "no-communication",
    rounds: number
): Promise<CreateGameResponse> {
    const response = await fetch(`${API_BASE}/games/prisoners-dilemma/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            host_id: hostId,
            communication_mode: communicationMode,
            rounds,
        }),
    });
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Failed to create Prisoner's Dilemma");
    }
    return response.json();
}

export async function getPrisonersDilemmaSession(
    sessionId: string
): Promise<PrisonersDilemmaSessionState> {
    const response = await fetch(
        `${API_BASE}/games/prisoners-dilemma/sessions/${sessionId}`
    );
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Failed to fetch session");
    }
    const raw = (await response.json()) as ApiRecord;
    const roundLogsRaw = (raw.round_logs as ApiRecord[]) ?? [];
    const roundLogs = roundLogsRaw.map((entry) => ({
        round: resolveProp<number>(entry, "round") ?? 1,
        actions: (entry.actions as Record<string, string>) ?? {},
        payoffs: (entry.payoffs as Record<string, number>) ?? {},
    }));

    return {
        sessionId:
            resolveProp<string>(raw, "sessionId", "session_id") ?? sessionId,
        players: Array.isArray(raw.players)
            ? (raw.players as ApiRecord[]).map(mapPlayer)
            : [],
        me: raw.me ? mapPlayer(raw.me as ApiRecord) : undefined,
        phase: mapPhase(raw.phase as ApiRecord),
        availableActions:
            (resolveProp<string[]>(raw, "availableActions", "available_actions") ??
                []) as string[],
        status: resolveProp<string>(raw, "status") ?? "initializing",
        waitingForAction: Boolean(
            resolveProp(raw, "waitingForAction", "waiting_for_action")
        ),
        gameOver: Boolean(resolveProp(raw, "gameOver", "game_over")),
        choices: (raw.choices as Record<string, string>) ?? {},
        payoffs: (raw.payoffs as Record<string, number>) ?? {},
        communicationMode:
            resolveProp<string>(raw, "communicationMode", "communication_mode") ??
            "no-communication",
        currentRound: resolveProp<number>(raw, "currentRound", "current_round") ?? 1,
        totalRounds: resolveProp<number>(raw, "totalRounds", "total_rounds") ?? 1,
        roundLogs,
        totals: (raw.totals as Record<string, number>) ?? {},
        interpretation: resolveProp<string>(raw, "interpretation") ?? undefined,
        activePlayerId:
            resolveProp<string>(raw, "activePlayerId", "active_player_id") ?? undefined,
        lastUpdated:
            resolveProp<number>(raw, "lastUpdated", "last_updated") ??
            Date.now(),
        hostId: resolveProp<string>(raw, "hostId", "host_id"),
    };
}

export async function submitPrisonersDilemmaAction(
    sessionId: string,
    participantId: string,
    action: PrisonersDilemmaAction
): Promise<void> {
    const response = await fetch(
        `${API_BASE}/games/prisoners-dilemma/sessions/${sessionId}/actions?participant_id=${encodeURIComponent(
            participantId
        )}`,
        {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(action),
        }
    );
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Failed to submit action");
    }
}

export async function leavePrisonersDilemmaGame(
    sessionId: string,
    participantId: string
): Promise<void> {
    await fetch(
        `${API_BASE}/games/prisoners-dilemma/sessions/${sessionId}?participant_id=${encodeURIComponent(
            participantId
        )}`,
        { method: "DELETE" }
    );
}
