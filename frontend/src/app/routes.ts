import { createBrowserRouter } from "react-router";
import { Layout } from "./Layout";
import { IDE } from "./pages/IDE";
import { Leaderboard } from "./pages/Leaderboard";
import { Challenges } from "./pages/Challenges";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: IDE },
      { path: "leaderboard", Component: Leaderboard },
      { path: "challenges", Component: Challenges },
    ],
  },
]);
