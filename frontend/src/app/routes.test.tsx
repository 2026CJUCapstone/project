import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { routeDefinitions } from "./routes";

describe("app routes", () => {
  it("renders the leaderboard page", async () => {
    const router = createMemoryRouter(routeDefinitions, {
      initialEntries: ["/leaderboard"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "리더보드" })).toBeInTheDocument();
    expect(screen.getByText("월간 랭킹")).toBeInTheDocument();
  });

  it("renders the challenges page", async () => {
    const router = createMemoryRouter(routeDefinitions, {
      initialEntries: ["/challenges"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByText("챌린지 허브")).toBeInTheDocument();
    expect(screen.getByText('B++로 "Hello, World!" 출력하기')).toBeInTheDocument();
  });
});
