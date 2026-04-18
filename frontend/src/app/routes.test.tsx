import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { routeDefinitions } from "./routes";
import { getLeaderboard, getProblems } from "./services/problemApi";

vi.mock("./services/problemApi", () => ({
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

    expect(await screen.findByText("챌린지 허브")).toBeInTheDocument();
  });
});
