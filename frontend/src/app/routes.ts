import { createBrowserRouter } from "react-router";
import { Layout } from "./Layout";
import { IDE } from "./pages/IDE";
import { Leaderboard } from "./pages/Leaderboard";
import { Challenges } from "./pages/Challenges";

const routerBasePath = import.meta.env.BASE_URL.replace(/\/$/, "");

export const routeDefinitions = [
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: IDE },
      { path: "leaderboard", Component: Leaderboard },
      { path: "challenges", Component: Challenges },
    ],
  },
];

export const router = createBrowserRouter(routeDefinitions, {
  basename: routerBasePath === "" ? "/" : routerBasePath,
});
