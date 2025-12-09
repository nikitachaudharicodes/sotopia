import type { GameDefinition } from "@/core/types/game-module";
import { ConsentCard } from "@/core/components/consent-card";
import { PublicGoodsLobby } from "@/games/public-goods/components/lobby";
import { PublicGoodsGameBoard } from "@/games/public-goods/components/game-board";
import { usePublicGoodsSession } from "@/games/public-goods/use-session";
import { usePublicGoodsActions } from "@/games/public-goods/use-actions";
import type { PublicGoodsSessionState } from "@/games/public-goods/types";

export const publicGoodsGame: GameDefinition<PublicGoodsSessionState> = {
    slug: "public-goods",
    title: "Public Goods Game",
    summary:
        "Coordinate (or free-ride) as three players contribute to a shared pot. Payoffs follow classical public goods dynamics.",
    tags: ["game theory", "multi-agent"],
    accentColor: "#34d399",
    components: {
        Consent: ConsentCard,
        Lobby: PublicGoodsLobby,
        GameBoard: PublicGoodsGameBoard,
    },
    hooks: {
        useSession: usePublicGoodsSession,
        useActions: usePublicGoodsActions,
    },
};

export default publicGoodsGame;
