"use client";

import { useState } from "react";
import type { GameBoardProps } from "@/core/types/game-module";
import type { PrisonersDilemmaSessionState } from "@/games/prisoners-dilemma/types";
import { Button } from "@/components/ui/button";

export function PrisonersDilemmaGameBoard({
    session,
    sessionId,
    participantId,
    isLoading,
    error,
    actionsState,
    actionsControls,
}: GameBoardProps<PrisonersDilemmaSessionState>) {
    const [message, setMessage] = useState("");

    const isChatPhase = Boolean(session?.phase.allowChat);
    const isDecisionPhase = Boolean(session?.phase.allowActions);
    const isHumanTurnToChat =
        isChatPhase && session?.activePlayerId === participantId;
    const canAct =
        !!session &&
        !session.gameOver &&
        isDecisionPhase &&
        session.availableActions.some(
            (action) => action === "cooperate" || action === "defect"
        );

    const canChat =
        !!session && !session.gameOver && isChatPhase && isHumanTurnToChat;

    const handleChoice = async (choice: string) => {
        await actionsControls.submitAction("action", choice);
    };

    const handleSendMessage = async () => {
        if (!message.trim()) {
            return;
        }
        await actionsControls.submitAction("speak", message.trim());
        setMessage("");
    };

    return (
        <div className="grid gap-6 md:grid-cols-[2fr_1fr]">
            <div className="space-y-6">
                <section className="rounded-xl border bg-card p-6 shadow-sm">
                    <header className="flex items-center justify-between">
                        <div>
                            <p className="text-xs uppercase text-muted-foreground">
                                Session
                            </p>
                            <h2 className="text-xl font-semibold">
                                Prisoner&apos;s Dilemma
                            </h2>
                        </div>
                        <div className="text-right">
                            <p className="text-xs text-muted-foreground">
                                Session ID
                            </p>
                            <p className="font-mono text-sm">
                                {sessionId.slice(0, 8)}...
                            </p>
                        </div>
                    </header>
                    <div className="mt-4 flex flex-wrap gap-3 text-sm text-muted-foreground">
                        <span className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200">
                            Phase: {session?.phase.phase ?? "loading"}
                        </span>
                        <span className="rounded-full bg-blue-100 px-3 py-1 text-blue-700 dark:bg-blue-900/30 dark:text-blue-200">
                            Status: {session?.status ?? "loading"}
                        </span>
                        <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-700 dark:bg-slate-900/30 dark:text-slate-200">
                            Round {session?.currentRound ?? 1}/
                            {session?.totalRounds ?? 1}
                        </span>
                        <span className="rounded-full bg-purple-100 px-3 py-1 text-purple-700 dark:bg-purple-900/30 dark:text-purple-200">
                            Mode: {session?.communicationMode ?? "unknown"}
                        </span>
                    </div>
                    {session?.phase.description && (
                        <p className="mt-4 text-sm text-muted-foreground">
                            {session.phase.description}
                        </p>
                    )}
                </section>

                <section className="rounded-xl border bg-card p-6 shadow-sm">
                    <h3 className="text-lg font-semibold">Players</h3>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                        {session?.players.map((player) => (
                            <div
                                key={player.id}
                                className={`rounded-lg border px-4 py-3 ${
                                    player.isHost
                                        ? "border-primary/60 bg-primary/5"
                                        : ""
                                }`}
                            >
                                <p className="font-semibold">{player.displayName}</p>
                                <p className="text-xs text-muted-foreground">
                                    {player.role}
                                </p>
                            </div>
                        ))}
                    </div>
                </section>

                <section className="rounded-xl border bg-card p-6 shadow-sm">
                    <div className="flex items-center justify-between">
                        <h3 className="text-lg font-semibold">
                            {isChatPhase ? "Dialogue" : "Your Choice"}
                        </h3>
                        {session?.gameOver && (
                            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-100">
                                Game Complete
                            </span>
                        )}
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">
                        {isChatPhase
                            ? "Exchange up to two short messages per agent before choosing."
                            : "Choose once. The AI prisoner chooses simultaneously."}
                    </p>

                    {isChatPhase ? (
                        <div className="mt-4 space-y-3">
                            <textarea
                                value={message}
                                onChange={(e) => setMessage(e.target.value)}
                                placeholder={
                                    isHumanTurnToChat
                                        ? "Share a message..."
                                        : "Waiting for the other prisoner..."
                                }
                                disabled={!canChat || actionsState.isSubmitting}
                                className="min-h-[96px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            />
                            <div className="flex items-center justify-between text-xs text-muted-foreground">
                                <span>
                                    {isHumanTurnToChat
                                        ? "Your turn to speak."
                                        : "Awaiting the other prisoner."}
                                </span>
                                <Button
                                    size="sm"
                                    disabled={
                                        !canChat ||
                                        !message.trim() ||
                                        actionsState.isSubmitting
                                    }
                                    onClick={handleSendMessage}
                                >
                                    {actionsState.isSubmitting ? "Sending..." : "Send"}
                                </Button>
                            </div>
                        </div>
                    ) : (
                        <div className="mt-4 flex flex-wrap gap-4">
                            <Button
                                variant="default"
                                size="lg"
                                disabled={!canAct || actionsState.isSubmitting}
                                onClick={() => handleChoice("cooperate")}
                            >
                                {actionsState.isSubmitting ? "Submitting..." : "Cooperate"}
                            </Button>
                            <Button
                                variant="outline"
                                size="lg"
                                disabled={!canAct || actionsState.isSubmitting}
                                onClick={() => handleChoice("defect")}
                            >
                                Defect
                            </Button>
                        </div>
                    )}

                    {actionsState.lastError && (
                        <div className="mt-4 rounded-md bg-destructive/10 px-4 py-2 text-sm text-destructive">
                            {actionsState.lastError}
                        </div>
                    )}
                </section>

                <section className="rounded-xl border bg-card p-6 shadow-sm">
                    <h3 className="text-lg font-semibold">Current Round</h3>
                    {session?.roundLogs?.length ? (
                        <div className="mt-4 space-y-4">
                            <div className="rounded-lg border bg-muted/40 p-4">
                                <p className="text-sm font-semibold">
                                    Latest Results
                                </p>
                                {(() => {
                                    const latest =
                                        session.roundLogs[session.roundLogs.length - 1];
                                    return (
                                        <>
                                            <div className="mt-2 text-sm text-muted-foreground">
                                                <p className="font-semibold">
                                                    Actions
                                                </p>
                                                <ul className="mt-1 space-y-1">
                                                    {Object.entries(latest.actions).map(
                                                        ([player, choice]) => (
                                                            <li key={player}>
                                                                {player}:{" "}
                                                                <span className="font-semibold capitalize">
                                                                    {choice}
                                                                </span>
                                                            </li>
                                                        )
                                                    )}
                                                </ul>
                                            </div>
                                            <div className="mt-3 text-sm text-muted-foreground">
                                                <p className="font-semibold">
                                                    Payoffs
                                                </p>
                                                <ul className="mt-1 space-y-1">
                                                    {Object.entries(latest.payoffs).map(
                                                        ([player, payoff]) => (
                                                            <li key={player}>
                                                                {player}:{" "}
                                                                <span className="font-semibold">
                                                                    {payoff}
                                                                </span>
                                                            </li>
                                                        )
                                                    )}
                                                </ul>
                                            </div>
                                        </>
                                    );
                                })()}
                            </div>
                        </div>
                    ) : session?.gameOver ? (
                        <div className="mt-2 text-sm text-muted-foreground">
                            Final results shown above.
                        </div>
                    ) : (
                        <p className="mt-2 text-sm text-muted-foreground">
                            Results appear once both prisoners submit their choices.
                        </p>
                    )}
                </section>

                <section className="rounded-xl border bg-card p-6 shadow-sm">
                    <h3 className="text-lg font-semibold">Outcome</h3>
                    {session?.gameOver ? (
                        <div className="mt-4 space-y-4">
                            <div className="rounded-lg border bg-muted/40 p-4">
                                <p className="text-sm font-semibold">Choices</p>
                                <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                                    {Object.entries(session.choices).map(
                                        ([player, choice]) => (
                                            <li key={player}>
                                                {player}:{" "}
                                                <span className="font-semibold capitalize">
                                                    {choice}
                                                </span>
                                            </li>
                                        )
                                    )}
                                </ul>
                            </div>
                            <div className="rounded-lg border bg-muted/40 p-4">
                                <p className="text-sm font-semibold">Payoffs</p>
                                <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                                    {Object.entries(session.payoffs).map(
                                        ([player, payoff]) => (
                                            <li key={player}>
                                                {player}:{" "}
                                                <span className="font-semibold">
                                                    {payoff}
                                                </span>
                                            </li>
                                        )
                                    )}
                                </ul>
                            </div>
                        </div>
                    ) : (
                        <p className="mt-2 text-sm text-muted-foreground">
                            Results appear once both prisoners submit their choices.
                        </p>
                    )}
                </section>

                <section className="rounded-xl border bg-card p-6 shadow-sm">
                    <h3 className="text-lg font-semibold">Scoreboard</h3>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                        {session?.totals &&
                            Object.entries(session.totals).map(([player, total]) => (
                                <div
                                    key={player}
                                    className="rounded-lg border bg-muted/40 px-4 py-3"
                                >
                                    <p className="text-sm font-semibold">{player}</p>
                                    <p className="text-2xl font-bold">{total}</p>
                                </div>
                            ))}
                    </div>
                    {session?.interpretation && (
                        <p className="mt-4 text-sm italic text-muted-foreground">
                            Interpretation: {session.interpretation}
                        </p>
                    )}
                </section>

                {session?.roundLogs?.length ? (
                    <section className="rounded-xl border bg-card p-6 shadow-sm">
                        <h3 className="text-lg font-semibold">Round Summary</h3>
                        <div className="mt-4 space-y-3 text-sm text-muted-foreground">
                            {session.roundLogs.map((log) => (
                                <div
                                    key={`round-${log.round}`}
                                    className="rounded-lg border px-4 py-3"
                                >
                                    <p className="font-semibold">
                                        Round {log.round}
                                    </p>
                                    <p>
                                        Actions:{" "}
                                        {Object.entries(log.actions)
                                            .map(([player, choice]) => `${player}=${choice}`)
                                            .join(", ")}
                                    </p>
                                    <p>
                                        Payoffs:{" "}
                                        {Object.entries(log.payoffs)
                                            .map(([player, payoff]) => `${player}=${payoff}`)
                                            .join(", ")}
                                    </p>
                                </div>
                            ))}
                        </div>
                    </section>
                ) : null}
            </div>

            <aside className="space-y-4">
                <div className="rounded-xl border bg-card p-5 shadow-sm">
                    <h4 className="text-sm font-semibold uppercase text-muted-foreground">
                        Participant
                    </h4>
                    <p className="mt-2 text-lg font-semibold">
                        {participantId || "Unknown"}
                    </p>
                </div>
                {error && (
                    <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-destructive">
                        Failed to load session:{" "}
                        {error instanceof Error ? error.message : "Unknown error"}
                    </div>
                )}
                {isLoading && (
                    <div className="rounded-xl border bg-muted/40 p-4 text-sm text-muted-foreground">
                        Syncing latest state…
                    </div>
                )}
            </aside>
        </div>
    );
}
