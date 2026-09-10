import { createBrowserRouter } from "react-router";
import { Layout } from "./Layout";
import { Landing } from "./pages/Landing";
import { lazyRoute } from "./lazyRoute";

async function loadWithLocalMonaco<Module>(loadPage: () => Promise<Module>) {
  const { configureLocalMonaco } = await import("./services/localMonaco");
  configureLocalMonaco();
  return loadPage();
}

const IDE = lazyRoute(() => loadWithLocalMonaco(() => import("./pages/IDE")), "IDE");
const Leaderboard = lazyRoute(() => import("./pages/Leaderboard"), "Leaderboard");
const Challenges = lazyRoute(() => import("./pages/Challenges"), "Challenges");
const ChallengeDetail = lazyRoute(() => import("./pages/ChallengeDetail"), "ChallengeDetail");
const Community = lazyRoute(() => import("./pages/Community"), "Community");
const CompileQueue = lazyRoute(() => import("./pages/CompileQueue"), "CompileQueue");
const Submissions = lazyRoute(() => import("./pages/Submissions"), "Submissions");
const Admin = lazyRoute(() => import("./pages/Admin"), "Admin");
const PasswordReset = lazyRoute(() => import("./pages/PasswordReset"), "PasswordReset");
const Contests = lazyRoute(() => import("./pages/Contests"), "Contests");
const ContestDetail = lazyRoute(() => import("./pages/ContestDetail"), "ContestDetail");
const ContestEditor = lazyRoute(() => import("./pages/ContestEditor"), "ContestEditor");
const ContestProblemPage = lazyRoute(
  () => loadWithLocalMonaco(() => import("./pages/ContestProblemPage")),
  "ContestProblemPage",
);

const routerBasePath = import.meta.env.BASE_URL.replace(/\/$/, "");

export const routeDefinitions = [
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: Landing },
      { path: "ide", Component: IDE },
      { path: "contests", Component: Contests },
      { path: "contests/new", Component: ContestEditor },
      { path: "contests/:contestId", Component: ContestDetail },
      { path: "contests/:contestId/edit", Component: ContestEditor },
      { path: "contests/:contestId/problems/:contestProblemId", Component: ContestProblemPage },
      { path: "leaderboard", Component: Leaderboard },
      { path: "challenges", Component: Challenges },
      { path: "challenges/:challengeId", Component: ChallengeDetail },
      { path: "queue", Component: CompileQueue },
      { path: "submissions", Component: Submissions },
      { path: "community", Component: Community },
    ],
	  },
	  { path: "/admin", Component: Admin },
	  { path: "/reset-password", Component: PasswordReset },
	];

export const router = createBrowserRouter(routeDefinitions, {
  basename: routerBasePath === "" ? "/" : routerBasePath,
});
