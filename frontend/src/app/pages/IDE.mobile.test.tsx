import { useEffect } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IDE } from "./IDE";
import { useCompilerStore } from "../store/compilerStore";

let editorMounts = 0;

vi.mock("../components/CodeEditor", () => ({
  CodeEditor: () => {
    useEffect(() => {
      editorMounts += 1;
    }, []);
    return <div>editor contents</div>;
  },
}));
vi.mock("../components/RunOutputPanel", () => ({ RunOutputPanel: () => <div>console contents</div> }));
vi.mock("../components/CompilerGraphViewer", () => ({ CompilerGraphViewer: () => <div>graph contents<button onClick={() => useCompilerStore.getState().setGraphViewerOpen(false)}>close graph</button></div> }));
vi.mock("../components/ChallengePanel", () => ({ ChallengePanel: () => <div>problem contents</div> }));

vi.mock("react-resizable-panels", () => ({
  Panel: ({ children }: any) => <div>{children}</div>,
  PanelGroup: ({ children }: any) => <div>{children}</div>,
  PanelResizeHandle: () => null,
}));

describe("IDE mobile panels", () => {
  beforeEach(() => {
    editorMounts = 0;
    useCompilerStore.setState({ language: "bpp", isGraphViewerOpen: false });
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
    expect(useCompilerStore.getState().isGraphViewerOpen).toBe(true);
  });

  it("starts on code, returns to code on close, and reopens without remounting the editor", async () => {
    useCompilerStore.setState({ isGraphViewerOpen: true });
    const user = userEvent.setup();
    render(<MemoryRouter><IDE /></MemoryRouter>);
    expect(screen.getByRole("tab", { name: "코드" })).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: "그래프" }));
    await user.click(screen.getByRole("button", { name: "close graph" }));
    expect(screen.getByText("editor contents")).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "그래프" }));
    expect(screen.getByText("graph contents")).toBeVisible();
    expect(editorMounts).toBe(1);
  });

  it("removes the mobile graph tab and exits it when switching away from B++", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><IDE /></MemoryRouter>);
    await user.click(screen.getByRole("tab", { name: "그래프" }));
    act(() => useCompilerStore.getState().selectLanguage("python"));
    expect(screen.queryByRole("tab", { name: "그래프" })).toBeNull();
    expect(screen.queryByText("graph contents")).toBeNull();
    expect(screen.getByText("editor contents")).toBeVisible();
  });

  it.each(["c", "cpp", "python", "java", "javascript"] as const)("hides desktop graphs for %s including restored languages", language => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    useCompilerStore.setState({ isGraphViewerOpen: true });
    render(<MemoryRouter><IDE /></MemoryRouter>);
    expect(screen.getByText("graph contents")).toBeVisible();
    act(() => useCompilerStore.getState().setLanguage(language));
    expect(screen.queryByText("graph contents")).toBeNull();
    act(() => useCompilerStore.getState().setLanguage("bpp"));
    expect(screen.getByText("graph contents")).toBeVisible();
  });
});
