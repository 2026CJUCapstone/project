import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { routeDefinitions } from "./routes";
import { getLeaderboard, getProblem, getProblems } from "./services/problemApi";

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
  getProblem: vi.fn(),
  createProblem: vi.fn(),
  deleteProblem: vi.fn(),
  updateProblem: vi.fn(),
  getSubmissions: vi.fn(() => Promise.resolve({ submissions: [], total: 0, filteredTotal: 0 })),
  getLeaderboard: vi.fn(),
  submitLeaderboardScore: vi.fn(),
}));

describe("app routes", () => {
  beforeEach(() => {
    vi.mocked(getProblems).mockResolvedValue([]);
    vi.mocked(getProblem).mockRejectedValue(new Error("not found"));
    vi.mocked(getLeaderboard).mockResolvedValue([
      {
        rank: 1,
        username: "bpp_master",
        totalScore: 120,
        rating: 36,
        tier: "Iron V",
        solvedCount: 2,
        avatarUrl: null,
      },
    ]);
  });

  it("renders the platform landing page", async () => {
    const router = createMemoryRouter(routeDefinitions, {
      initialEntries: ["/"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByTestId("landing-page")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /브라우저에서 코드를 실행하고/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "코드 실행하기" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /챌린지 둘러보기/ })).toBeInTheDocument();
  });

  it("explains the B++ language with the approved introduction", async () => {
    const router = createMemoryRouter(routeDefinitions, { initialEntries: ["/"] });
    render(<RouterProvider router={router} />);

    const introduction = await screen.findByRole("region", { name: "B++는 어떤 언어인가요?" });
    expect(within(introduction).getByRole("heading", { level: 2 })).toHaveTextContent("B++는 어떤 언어인가요?");
    expect(within(introduction).getByText("B++는 컴파일러의 동작 원리를 배우고 알고리즘 문제를 풀기 위해 만든 프로그래밍 언어입니다.")).toBeInTheDocument();
    expect(within(introduction).getByText("직접 작성한 코드가 어떻게 분석되고 실행 파일로 바뀌는지 단계별로 살펴볼 수 있습니다.")).toBeInTheDocument();
  });

  it("uses the approved plain copy throughout the homepage", async () => {
    const router = createMemoryRouter(routeDefinitions, { initialEntries: ["/"] });
    render(<RouterProvider router={router} />);
    const landing = await screen.findByTestId("landing-page");
    const content = within(landing);

    expect(content.getByRole("heading", { level: 1 })).toHaveTextContent("브라우저에서 코드를 실행하고B++의 컴파일 과정을 살펴보세요.");
    for (const text of [
      "B++ 온라인 컴파일러",
      "별도 설치 없이 코드를 작성하고 실행할 수 있습니다. B++ 코드의 컴파일 과정을 살펴보거나, 알고리즘 문제를 풀고 커뮤니티에서 질문을 주고받을 수 있습니다.",
      "회원가입 없이 코드 실행", "6개 언어 지원", "B++ 컴파일 과정 분석", "주요 기능",
      "코드 실행은 IDE에서, 알고리즘 연습은 챌린지에서 시작하세요. 질문이나 풀이 이야기는 커뮤니티에 남길 수 있습니다.",
      "B++, C, C++, Python, Java, JavaScript를 지원합니다. 언어를 선택하고 코드를 실행하면 결과를 확인할 수 있습니다.",
      "B++ 코드의 AST와 SSA는 그래프로, IR과 어셈블리 코드는 텍스트로 확인할 수 있습니다.",
      "난이도와 주제별로 문제를 찾아 풀어보세요. 제출한 코드의 채점 결과와 이전 제출 기록을 확인할 수 있습니다.",
      "문제를 풀다가 막힌 부분이나 언어 사용법을 질문해 보세요. 자유 게시판에는 서비스 개선 의견도 남길 수 있습니다.",
      "B++ 문법이 낯설다면 기본 예제부터 실행해 보세요. 코드를 조금씩 바꾸고 결과가 어떻게 달라지는지 확인하면 됩니다.",
      "IDE에서 언어를 선택하면 기본 예제 코드가 나타납니다. 예제를 그대로 실행하거나 직접 코드를 작성해 보세요.",
      "B++ 코드를 실행한 뒤 AST·SSA 그래프와 IR·어셈블리 코드를 살펴보세요. 코드가 분석되고 변환되는 과정을 확인할 수 있습니다.",
      "챌린지에서 문제를 골라 코드를 제출해 보세요. 채점 결과와 레이팅을 확인하고, 궁금한 점은 커뮤니티에 질문할 수 있습니다.",
      "IDE에서 언어를 선택하고 시작하면 됩니다.",
    ]) expect(content.getByText(text)).toBeInTheDocument();

    for (const name of ["코드 실행과 문제 풀이", "설치 없이 코드 실행", "B++ 컴파일 과정 살펴보기", "질문과 풀이 나누기", "예제 코드부터 실행해 보세요", "코드 실행하기", "B++ 컴파일 결과 살펴보기", "코드를 실행해 보세요"]) {
      expect(content.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(content.getAllByRole("heading", { name: "알고리즘 문제 풀기" })).toHaveLength(2);
    expect(content.getAllByRole("article")).toHaveLength(4);
    expect(content.getAllByRole("listitem")).toHaveLength(3);
    for (const name of ["코드 실행하기", "챌린지 둘러보기", "커뮤니티 가기", "IDE 열기", "리더보드 보기"]) {
      expect(content.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(landing).not.toHaveTextContent(/READY TO BUILD|LEARNING PLAYGROUND|ONE PLACE, FULL CYCLE|실력을 증명|성장을 확인|동료 학습자|코드 실행에서 끝나지/);
  });

  it("renders the leaderboard page", async () => {
    const router = createMemoryRouter(routeDefinitions, {
      initialEntries: ["/leaderboard"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "리더보드" })).toBeInTheDocument();
    expect(await screen.findByText("전체 랭킹")).toBeInTheDocument();
    expect(await screen.findAllByText("bpp_master")).toHaveLength(2);
    expect(screen.getAllByText("36")).not.toHaveLength(0);
    expect(screen.getAllByText("Iron V")).not.toHaveLength(0);
  });

  it("renders the challenges page", async () => {
    const router = createMemoryRouter(routeDefinitions, {
      initialEntries: ["/challenges"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "문제 목록" })).toBeInTheDocument();
  });

  it("renders the challenge detail page", async () => {
    vi.mocked(getProblem).mockResolvedValue({
      id: "p-1",
      title: "두 수의 합",
      difficulty: "iron5",
      tags: ["io"],
      points: 100,
      description: "## 문제\n\n두 수를 더하세요.",
      testCases: [{ input: "1 2", expectedOutput: "3" }],
	      hiddenTestCases: [],
	      createdAt: new Date().toISOString(),
	      solved: false,
	      attempted: false,
	      lastSubmissionStatus: null,
	      lastSubmissionVerdict: null,
	      lastSubmittedAt: null,
	      bestAwardedPoints: 0,
	    });

    const router = createMemoryRouter(routeDefinitions, {
      initialEntries: ["/challenges/p-1"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "두 수의 합" })).toBeInTheDocument();
    expect(await screen.findByText("입력")).toBeInTheDocument();
    expect(await screen.findByText("출력")).toBeInTheDocument();
  });
});
