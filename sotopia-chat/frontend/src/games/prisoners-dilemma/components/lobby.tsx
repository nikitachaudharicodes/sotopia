"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { createPrisonersDilemmaGame } from "@/games/prisoners-dilemma/api";

interface PrisonersDilemmaLobbyProps {
    onGameCreated: (sessionId: string, participantId: string) => void;
}

export function PrisonersDilemmaLobby({
    onGameCreated,
}: PrisonersDilemmaLobbyProps) {
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
            const response = await createPrisonersDilemmaGame(
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
        <div className="mx-auto flex w-full max-w-xl flex-col gap-6 rounded-lg border bg-card p-8 shadow-lg">
            <header className="space-y-2">
                <h1 className="text-3xl font-bold">🤝 Prisoner&rsquo;s Dilemma</h1>
                <p className="text-sm text-muted-foreground">
                    Face off against an LLM prisoner. Cooperate or defect once—your choice
                    determines both of your outcomes.
                </p>
            </header>

            <div className="space-y-4 rounded-lg bg-muted p-4">
                <h2 className="font-semibold">Game Setup</h2>
                <ul className="space-y-2 text-sm text-muted-foreground">
                    <li>• 2 players total: You + 1 AI agent</li>
                    <li>• Actions: cooperate or defect (simultaneous)</li>
                    <li>• Payoffs follow the classic dilemma matrix</li>
                    <li>• Results reveal immediately after both choices</li>
                </ul>
            </div>

            <div className="space-y-2">
                <label className="text-sm font-medium">
                    Your Player Identifier
                </label>
                <input
                    type="text"
                    value={playerId}
                    onChange={(e) => setPlayerId(e.target.value)}
                    placeholder="e.g., prisoner-42"
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    disabled={isCreating}
                />
                <p className="text-xs text-muted-foreground">
                    Used to resume or track this session.
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
                        Allow up to two dialogue turns per agent before each decision.
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
                        Play a one-shot dilemma or repeat for multiple rounds.
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
                {isCreating ? "Creating..." : "Start New Game"}
            </Button>

            <div className="space-y-2 rounded-lg border-l-4 border-blue-500 bg-blue-50 p-4 dark:bg-blue-950">
                <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-100">
                    📋 Payoff Matrix
                </h3>
                <div className="space-y-1 text-xs text-blue-800 dark:text-blue-200">
                    <p>
                        • Both cooperate → (2, 2)
                    </p>
                    <p>
                        • You defect, other cooperates → (3, 0)
                    </p>
                    <p>
                        • You cooperate, other defects → (0, 3)
                    </p>
                    <p>
                        • Both defect → (1, 1)
                    </p>
                </div>
            </div>
        </div>
    );
}
