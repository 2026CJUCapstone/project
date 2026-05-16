import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { routeDefinitions } from "./routes";
import { getLeaderboard, getProblems } from "./services/problemApi";

vi.mock("./services/problemApi", () => ({
  DIFFICULTY_LEVELS: [
    'iron5', 'iron4', 'iron3', 'iron2', 'iron1',
    'bronze5', 'bronze4', 'bronze3', 'bronze2', 'bronze1',
    'silver5', 'silver4', 'silver3', 'silver2', 'silver1',
    'gold5', 'gold4', 'gold3', 'gold2', 'gold1',
    'platinum5', 'platinum4', 'platinum3', 'platinum2', 'platinum1',
    'diamond5', 'diamond4', 'diamond3', 'diamond2', 'diamond1',
  ],
  getProblems: vi.fn(),
  createProblem: vi.fn(),
  deleteProblem: vi.fn(),
  updateProblem: vi.fn(),
  getLeaderboard: vi.fn(),
  submitLeaderboardScore: vi.fn(),
}));

describe("app routes", () => {
  beforeEach(() => {
    vi.mocked(getProblems).mockResolvedValue([]);
    vi.mocked(getLeaderboard).mockResolvedValue([
      {
        rank: 1,
        username: "bpp_master",
        totalScore: 120,
        avatarUrl: null,
      },
    ]);
  });

  it("renders the leaderboard page", async () => {
    const router = createMemoryRouter(routeDefinitions, {
      initialEntries: ["/leaderboard"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "리더보드" })).toBeInTheDocument();
    expect(await screen.findByText("전체 랭킹")).toBeInTheDocument();
    expect(await screen.findAllByText("bpp_master")).toHaveLength(2);
    expect(screen.getByText("120 XP")).toBeInTheDocument();
  });

  it("renders the challenges page", async () => {
    const router = createMemoryRouter(routeDefinitions, {
      initialEntries: ["/challenges"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "문제 목록" })).toBeInTheDocument();
  });

  it("renders the challenge detail page", async () => {
    vi.mocked(getProblems).mockResolvedValue([
      {
        id: "p-1",
        title: "두 수의 합",
        difficulty: "iron5",
        tags: ["io"],
        description: "## 문제\n\n두 수를 더하세요.",
        testCases: [{ input: "1 2", expectedOutput: "3" }],
        hiddenTestCases: [],
        createdAt: new Date().toISOString(),
      },
    ]);

    const router = createMemoryRouter(routeDefinitions, {
      initialEntries: ["/challenges/p-1"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "두 수의 합" })).toBeInTheDocument();
    expect(await screen.findByText("입력")).toBeInTheDocument();
    expect(await screen.findByText("출력")).toBeInTheDocument();
  });
});
