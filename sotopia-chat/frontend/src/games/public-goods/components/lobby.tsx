"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { createPublicGoodsGame } from "@/games/public-goods/api";

interface PublicGoodsLobbyProps {
    onGameCreated: (sessionId: string, participantId: string) => void;
}

export function PublicGoodsLobby({ onGameCreated }: PublicGoodsLobbyProps) {
    const [playerId, setPlayerId] = useState("");
    const [communicationMode, setCommunicationMode] = useState<
        "communication" | "no-communication"
    >("no-communication");
    const [rounds, setRounds] = useState(1);
    const [isCreating, setIsCreating] = useState(false);
    const [error, setError] = useState<string | undefined>();

    const handleCreateGame = async () => {
        if (!playerId.trim()) {
            setError("Please enter a player identifier");
            return;
        }
        try {
            setIsCreating(true);
            setError(undefined);
            const response = await createPublicGoodsGame(
                playerId.trim(),
                communicationMode,
                rounds
            );
            onGameCreated(response.session_id, playerId.trim());
        } catch (err) {
            console.error(err);
            setError(
                err instanceof Error ? err.message : "Failed to create game"
            );
        } finally {
            setIsCreating(false);
        }
    };

    return (
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 rounded-lg border bg-card p-8 shadow-lg">
            <header className="space-y-2">
                <h1 className="text-3xl font-bold">💰 Public Goods Game</h1>
                <p className="text-sm text-muted-foreground">
                    Join two LLM partners to invest in a shared pool. Contribute generously,
                    or free-ride and hope the others pay the cost.
                </p>
            </header>

            <div className="space-y-4 rounded-lg bg-muted/40 p-4">
                <h2 className="font-semibold">Game Setup</h2>
                <ul className="space-y-1 text-sm text-muted-foreground">
                    <li>• 3 players total: You + 2 AI partners</li>
                    <li>• Contribution options: low, medium, high, or free ride</li>
                    <li>
                        • Payoff = (1.5 × total pool / 3) − your personal contribution
                    </li>
                    <li>• Results reveal at the end of each round</li>
                </ul>
            </div>

            <div className="space-y-2">
                <label className="text-sm font-medium">Your Identifier</label>
                <input
                    type="text"
                    value={playerId}
                    onChange={(e) => setPlayerId(e.target.value)}
                    placeholder="e.g., strategist-17"
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    disabled={isCreating}
                />
                <p className="text-xs text-muted-foreground">
                    Used to resume or reference this session.
                </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                    <label className="text-sm font-medium">
                        Communication Mode
                    </label>
                    <select
                        value={communicationMode}
                        onChange={(e) =>
                            setCommunicationMode(
                                e.target.value as "communication" | "no-communication"
                            )
                        }
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                        <option value="no-communication">No communication</option>
                        <option value="communication">Allow dialogue</option>
                    </select>
                    <p className="text-xs text-muted-foreground">
                        Dialogue mode grants up to two short messages per agent before
                        each contribution phase.
                    </p>
                </div>
                <div className="space-y-2">
                    <label className="text-sm font-medium">Number of Rounds</label>
                    <input
                        type="number"
                        min={1}
                        value={rounds}
                        onChange={(e) => setRounds(Math.max(1, Number(e.target.value)))}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        disabled={isCreating}
                    />
                    <p className="text-xs text-muted-foreground">
                        Play a one-shot experiment or repeat for N rounds.
                    </p>
                </div>
            </div>

            {error && (
                <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {error}
                </div>
            )}

            <Button
                size="lg"
                onClick={handleCreateGame}
                disabled={isCreating || !playerId.trim()}
                className="w-full"
            >
                {isCreating ? "Creating..." : "Start Public Goods Game"}
            </Button>

            <div className="space-y-2 rounded-lg border-l-4 border-emerald-500 bg-emerald-50 p-4 dark:bg-emerald-950">
                <h3 className="text-sm font-semibold text-emerald-900 dark:text-emerald-100">
                    📈 Contribution Payoffs
                </h3>
                <p className="text-xs text-emerald-800 dark:text-emerald-200">
                    Shared return = 1.5 × (total contributions) ÷ 3. Your reward is this
                    shared return minus your own contribution. Cooperation lifts everyone;
                    free riding pays if others stay generous.
                </p>
            </div>
        </div>
    );
}
