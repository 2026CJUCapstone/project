import { createBrowserRouter } from "react-router";
import { Layout } from "./Layout";
import { IDE } from "./pages/IDE";
import { Leaderboard } from "./pages/Leaderboard";
import { Challenges } from "./pages/Challenges";
import { ChallengeDetail } from "./pages/ChallengeDetail";
import { Community } from "./pages/Community";
import { Admin } from "./pages/Admin";

const routerBasePath = import.meta.env.BASE_URL.replace(/\/$/, "");

export const routeDefinitions = [
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: IDE },
      { path: "leaderboard", Component: Leaderboard },
      { path: "challenges", Component: Challenges },
      { path: "challenges/:challengeId", Component: ChallengeDetail },
      { path: "community", Component: Community },
    ],
  },
  { path: "/admin", Component: Admin },
];

export const router = createBrowserRouter(routeDefinitions, {
  basename: routerBasePath === "" ? "/" : routerBasePath,
});
