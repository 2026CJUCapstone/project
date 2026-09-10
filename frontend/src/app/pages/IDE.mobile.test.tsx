import { useEffect } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IDE } from "./IDE";

let editorMounts = 0;

vi.mock("../components/CodeEditor", () => ({
  CodeEditor: () => {
    useEffect(() => {
      editorMounts += 1;
    }, []);
    return <div>editor contents</div>;
  },
}));
vi.mock("../components/OutputConsole", () => ({ OutputConsole: () => <div>console contents</div> }));
vi.mock("../components/CompilerGraphViewer", () => ({ CompilerGraphViewer: () => <div>graph contents</div> }));
vi.mock("../components/ChallengePanel", () => ({ ChallengePanel: () => <div>problem contents</div> }));

const setGraphViewerOpen = vi.fn();
vi.mock("../store/compilerStore", () => {
  const useCompilerStore = Object.assign(
    () => ({
      code: "saved draft",
      setCode: vi.fn(),
      isGraphViewerOpen: false,
    }),
    { getState: () => ({ setGraphViewerOpen }) },
  );
  return { useCompilerStore };
});

describe("IDE mobile panels", () => {
  beforeEach(() => {
    editorMounts = 0;
    setGraphViewerOpen.mockClear();
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });

  it("switches full panels without remounting the editor", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><IDE /></MemoryRouter>);

    expect(screen.getByRole("tab", { name: "코드" })).toHaveAttribute("aria-selected", "true");
    expect(editorMounts).toBe(1);

    await user.click(screen.getByRole("tab", { name: "실행 결과" }));
    expect(screen.getByRole("tab", { name: "실행 결과" })).toHaveAttribute("aria-selected", "true");
    expect(editorMounts).toBe(1);

    await user.click(screen.getByRole("tab", { name: "코드" }));
    expect(screen.getByText("editor contents")).toBeVisible();
    expect(editorMounts).toBe(1);
  });

  it("supports arrow-key tab navigation and opens the graph on demand", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><IDE /></MemoryRouter>);

    const codeTab = screen.getByRole("tab", { name: "코드" });
    codeTab.focus();
    await user.keyboard("{ArrowLeft}");

    expect(screen.getByRole("tab", { name: "그래프" })).toHaveFocus();
    expect(setGraphViewerOpen).toHaveBeenCalledWith(true);
  });
});
