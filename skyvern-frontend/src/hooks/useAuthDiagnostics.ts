import { useQuery } from "@tanstack/react-query";
import axios from "axios";

import { isRemoteAuthDiagnosticsError } from "@/api/localAuthDiagnostics";

import { getClient } from "@/api/AxiosClient";

export type AuthStatusValue =
  | "missing_api_key"
  | "invalid_format"
  | "invalid"
  | "expired"
  | "not_found"
  | "remote_unavailable"
  | "ok";

export type AuthDiagnosticsResponse = {
  status: AuthStatusValue;
  detail?: string;
  next_step?: string;
};

async function fetchDiagnostics(): Promise<AuthDiagnosticsResponse> {
  const client = await getClient(null);
  try {
    const response = await client.get<AuthDiagnosticsResponse>(
      "/internal/auth/status",
    );
    return response.data;
  } catch (error) {
    if (isRemoteAuthDiagnosticsError(error)) {
      return { status: "remote_unavailable" };
    }
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return { status: "ok" };
    }
    throw error;
  }
}

function useAuthDiagnostics() {
  return useQuery<AuthDiagnosticsResponse, Error>({
    queryKey: ["internal", "auth", "status"],
    queryFn: fetchDiagnostics,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export { useAuthDiagnostics };
