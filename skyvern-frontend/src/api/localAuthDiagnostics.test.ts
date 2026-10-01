import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";
import { isRemoteAuthDiagnosticsError } from "./localAuthDiagnostics";

function failure(url: string, status: number, detail: string) {
  const config = { url, headers: new AxiosHeaders() };
  return new AxiosError("Failed", undefined, config, undefined, {
    config,
    data: { detail },
    status,
    statusText: "Failed",
    headers: {},
  });
}

describe("remote diagnostics", () => {
  it.each(["/internal/auth/status", "/internal/llms/status"])(
    "recognizes the loopback restriction on %s",
    (endpoint) => {
      expect(
        isRemoteAuthDiagnosticsError(
          failure(endpoint, 403, "Endpoint requires localhost access"),
        ),
      ).toBe(true);
    },
  );
  it.each([
    ["/tasks", 403, "Endpoint requires localhost access"],
    ["/internal/auth/status", 401, "Endpoint requires localhost access"],
    ["/internal/auth/status", 403, "Invalid credentials"],
    ["/internal/auth/status", 500, "Endpoint requires localhost access"],
  ])("preserves real errors at %s (%s)", (url, status, detail) => {
    expect(isRemoteAuthDiagnosticsError(failure(url, status, detail))).toBe(
      false,
    );
  });
  it("does not suppress network errors", () => {
    expect(isRemoteAuthDiagnosticsError(new Error("Network Error"))).toBe(
      false,
    );
  });
});
