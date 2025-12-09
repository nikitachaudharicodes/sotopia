export interface PDPlayer {
    id: string;
    displayName: string;
    role: string;
    team?: string;
    isHost?: boolean;
}

export interface PDPhase {
    phase: string;
    description?: string;
    allowChat?: boolean;
    allowActions?: boolean;
}

export interface PrisonersDilemmaSessionState {
    sessionId: string;
    players: PDPlayer[];
    me?: PDPlayer | null;
    phase: PDPhase;
    availableActions: string[];
    status: string;
    waitingForAction: boolean;
    gameOver: boolean;
    choices: Record<string, string>;
    payoffs: Record<string, number>;
    communicationMode: string;
    currentRound: number;
    totalRounds: number;
    roundLogs: Array<{
        round: number;
        actions: Record<string, string>;
        payoffs: Record<string, number>;
    }>;
    totals: Record<string, number>;
    interpretation?: string | null;
    activePlayerId?: string | null;
    lastUpdated: number;
    hostId?: string;
}
