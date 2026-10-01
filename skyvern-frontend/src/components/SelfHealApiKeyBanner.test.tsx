// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { diagnosticsState } = vi.hoisted(() => ({
  diagnosticsState: {
    data: {
      status: "missing_api_key" as "missing_api_key" | "remote_unavailable",
    },
    error: null,
    isLoading: false,
    refetch: vi.fn(),
  },
}));

vi.mock("@/hooks/useAuthDiagnostics", () => ({
  useAuthDiagnostics: () => diagnosticsState,
}));

import { useAuthIssueStore } from "@/store/AuthIssueStore";

import { SelfHealApiKeyBanner } from "./SelfHealApiKeyBanner";

afterEach(() => {
  cleanup();
  diagnosticsState.data.status = "missing_api_key";
  useAuthIssueStore.getState().clearAuthIssue();
  vi.clearAllMocks();
});

describe("SelfHealApiKeyBanner", () => {
  it("directs the operator to the CLI without offering browser repair", () => {
    render(<SelfHealApiKeyBanner />);

    screen.getByText("skyvern doctor --fix");
    expect(
      screen.queryByRole("button", { name: "Regenerate API key" }),
    ).toBeNull();
  });
});

it("does not present unavailable remote diagnostics as invalid credentials", () => {
  diagnosticsState.data.status = "remote_unavailable";
  render(<SelfHealApiKeyBanner />);
  screen.getByText("Local diagnostics unavailable remotely");
  expect(screen.queryByText("skyvern doctor --fix")).toBeNull();
});

it("prioritizes an actual API rejection over remote diagnostics", () => {
  diagnosticsState.data.status = "remote_unavailable";
  useAuthIssueStore
    .getState()
    .reportAuthIssue({ statusCode: 401, path: "/tasks" });
  render(<SelfHealApiKeyBanner />);
  screen.getByText("Skyvern API requests are unauthorized");
});
