import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ config: vi.fn() }));

vi.mock("@monaco-editor/react", () => ({ loader: { config: mocks.config } }));

import { configureLocalMonaco } from "./localMonaco";

describe("configureLocalMonaco", () => {
  beforeEach(() => mocks.config.mockClear());

  it("configures one local full distribution without injecting a second Monaco instance", () => {
    configureLocalMonaco();
    configureLocalMonaco();

    expect(mocks.config).toHaveBeenCalledTimes(1);
    expect(mocks.config).toHaveBeenCalledWith({ paths: { vs: expect.stringMatching(/^\/assets\/monaco-[a-f0-9]+\/vs$/) } });

  });
});
