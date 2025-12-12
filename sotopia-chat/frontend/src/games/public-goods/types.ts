export interface PGPlayer {
    id: string;
    displayName: string;
    role: string;
    team?: string;
    isHost?: boolean;
}

export interface PGPhase {
    phase: string;
    description?: string;
    allowChat?: boolean;
    allowActions?: boolean;
}

export interface PublicGoodsRoundLog {
    round: number;
    actions: Record<string, string>;
    numericContributions: Record<string, number>;
    totalPool: number;
    payoffs: Record<string, number>;
}

export interface PublicGoodsSessionState {
    sessionId: string;
    players: PGPlayer[];
    me?: PGPlayer | null;
    phase: PGPhase;
    availableActions: string[];
    status: string;
    waitingForAction: boolean;
    gameOver: boolean;
    choices: Record<string, string>;
    numericContributions: Record<string, number>;
    payoffs: Record<string, number>;
    totalPool: number;
    communicationMode: string;
    currentRound: number;
    totalRounds: number;
    roundLogs: PublicGoodsRoundLog[];
    totals: Record<string, number>;
    interpretation?: string | null;
    activePlayerId?: string | null;
    lastUpdated: number;
    hostId?: string;
}
