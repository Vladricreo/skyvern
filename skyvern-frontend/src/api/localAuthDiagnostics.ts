import axios from "axios";

// Diagnostics intentionally require loopback access, even with a valid key.
export function isRemoteAuthDiagnosticsError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  const path = error.config?.url?.split("?")[0]?.replace(/\/$/, "");
  return (
    ["/internal/auth/status", "/internal/llms/status"].some((endpoint) =>
      path?.endsWith(endpoint),
    ) &&
    error.response?.status === 403 &&
    error.response.data?.detail === "Endpoint requires localhost access"
  );
}
