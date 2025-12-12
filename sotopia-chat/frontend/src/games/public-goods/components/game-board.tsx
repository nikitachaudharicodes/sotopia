"use client";

import { useMemo, useState } from "react";
import type { GameBoardProps } from "@/core/types/game-module";
import type { PublicGoodsSessionState } from "@/games/public-goods/types";
import { Button } from "@/components/ui/button";

const CONTRIBUTION_LABELS: Record<string, { label: string; helper: string }> = {
    contribute_low: { label: "Contribute Low (+1)", helper: "Small investment" },
    contribute_medium: { label: "Contribute Medium (+2)", helper: "Balanced play" },
    contribute_high: { label: "Contribute High (+3)", helper: "Max generosity" },
    free_ride: { label: "Free Ride (+0)", helper: "Let others pay the cost" },
};

export function PublicGoodsGameBoard({
    session,
    sessionId,
    participantId,
    isLoading,
    error,
    actionsState,
    actionsControls,
}: GameBoardProps<PublicGoodsSessionState>) {
    const [message, setMessage] = useState("");

    const isChatPhase = Boolean(session?.phase.allowChat);
    const isContributionPhase =
        Boolean(session?.phase.allowActions) && !isChatPhase;
    const isHumanTurnToChat =
        isChatPhase && session?.activePlayerId === participantId;
    const canChat =
        !!session && !session.gameOver && isChatPhase && isHumanTurnToChat;

    const contributionOptions = useMemo(() => {
        if (!session || !isContributionPhase) {
            return [];
        }
        return session.availableActions.filter(
            (action) => CONTRIBUTION_LABELS[action]
        );
    }, [session, isContributionPhase]);

    const canContribute =
        !!session &&
        !session.gameOver &&
        isContributionPhase &&
        contributionOptions.length > 0;

    const latestRound = session?.roundLogs?.length
        ? session.roundLogs[session.roundLogs.length - 1]
        : undefined;

    const handleContribution = async (choice: string) => {
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
                                Public Goods Game
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
                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                        {session?.players.map((player) => (
                            <div
                                key={player.id}
                                className={`rounded-lg border px-4 py-3 ${
                                    player.isHost ? "border-primary/60 bg-primary/5" : ""
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
                            {isChatPhase ? "Dialogue" : "Contribution"}
                        </h3>
                        {session?.gameOver && (
                            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-100">
                                Game Complete
                            </span>
                        )}
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">
                        {isChatPhase
                            ? "Coordinate quickly—each agent gets up to two brief turns."
                            : "Choose a discrete contribution. All players commit simultaneously."}
                    </p>

                    {isChatPhase ? (
                        <div className="mt-4 space-y-3">
                            <textarea
                                value={message}
                                onChange={(e) => setMessage(e.target.value)}
                                placeholder={
                                    isHumanTurnToChat
                                        ? "Share your plan..."
                                        : "Waiting for other players..."
                                }
                                disabled={!canChat || actionsState.isSubmitting}
                                className="min-h-[96px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            />
                            <div className="flex items-center justify-between text-xs text-muted-foreground">
                                <span>
                                    {isHumanTurnToChat
                                        ? "Your turn to speak."
                                        : "Awaiting the next speaker."}
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
                        <div className="mt-4 grid gap-3 md:grid-cols-2">
                            {contributionOptions.map((choice) => (
                                <Button
                                    key={choice}
                                    variant={
                                        choice === "free_ride" ? "outline" : "default"
                                    }
                                    disabled={!canContribute || actionsState.isSubmitting}
                                    onClick={() => handleContribution(choice)}
                                    className="flex h-auto flex-col items-start gap-1 text-left"
                                >
                                    <span className="text-base font-semibold">
                                        {CONTRIBUTION_LABELS[choice].label}
                                    </span>
                                    <span className="text-xs text-muted-foreground">
                                        {CONTRIBUTION_LABELS[choice].helper}
                                    </span>
                                </Button>
                            ))}
                        </div>
                    )}

                    {actionsState.lastError && (
                        <div className="mt-4 rounded-md bg-destructive/10 px-4 py-2 text-sm text-destructive">
                            {actionsState.lastError}
                        </div>
                    )}
                </section>

                <section className="rounded-xl border bg-card p-6 shadow-sm">
                    <h3 className="text-lg font-semibold">Latest Results</h3>
                    {latestRound ? (
                        <div className="mt-4 space-y-4 text-sm text-muted-foreground">
                            <div className="rounded-lg border bg-muted/40 p-4">
                                <p className="font-semibold">Round {latestRound.round}</p>
                                <p className="mt-2">
                                    Contributions:{" "}
                                    {Object.entries(latestRound.actions)
                                        .map(
                                            ([player, action]) =>
                                                `${player}=${action.replace("_", " ")}`
                                        )
                                        .join(", ")}
                                </p>
                                <p className="mt-1">
                                    Numeric:{" "}
                                    {Object.entries(latestRound.numericContributions)
                                        .map(
                                            ([player, value]) => `${player}=${value}`
                                        )
                                        .join(", ")}
                                </p>
                                <p className="mt-1">
                                    Total Pool: {latestRound.totalPool.toFixed(2)}
                                </p>
                                <p className="mt-1">
                                    Payoffs:{" "}
                                    {Object.entries(latestRound.payoffs)
                                        .map(
                                            ([player, payoff]) =>
                                                `${player}=${payoff.toFixed(2)}`
                                        )
                                        .join(", ")}
                                </p>
                            </div>
                        </div>
                    ) : (
                        <p className="mt-2 text-sm text-muted-foreground">
                            Results appear after all players submit their contributions.
                        </p>
                    )}
                </section>

                <section className="rounded-xl border bg-card p-6 shadow-sm">
                    <h3 className="text-lg font-semibold">Scoreboard</h3>
                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                        {session?.totals &&
                            Object.entries(session.totals).map(([player, total]) => (
                                <div
                                    key={player}
                                    className="rounded-lg border bg-muted/40 px-4 py-3"
                                >
                                    <p className="text-sm font-semibold">{player}</p>
                                    <p className="text-2xl font-bold">
                                        {total.toFixed(2)}
                                    </p>
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
                                        Contributions:{" "}
                                        {Object.entries(log.actions)
                                            .map(([player, action]) => `${player}=${action}`)
                                            .join(", ")}
                                    </p>
                                    <p>
                                        Numeric:{" "}
                                        {Object.entries(log.numericContributions)
                                            .map(([player, value]) => `${player}=${value}`)
                                            .join(", ")}
                                    </p>
                                    <p>Total Pool: {log.totalPool.toFixed(2)}</p>
                                    <p>
                                        Payoffs:{" "}
                                        {Object.entries(log.payoffs)
                                            .map(
                                                ([player, payoff]) =>
                                                    `${player}=${payoff.toFixed(2)}`
                                            )
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
                {typeof session?.totalPool === "number" && session.totalPool > 0 && (
                    <div className="rounded-xl border bg-emerald-50 p-4 text-sm text-emerald-900 dark:bg-emerald-900/20 dark:text-emerald-100">
                        <p className="font-semibold">Current Pool</p>
                        <p className="text-2xl font-bold">
                            {session.totalPool.toFixed(2)}
                        </p>
                        <p className="text-xs">
                            Shared equally after subtracting your contribution.
                        </p>
                    </div>
                )}
                {!!error && (
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
