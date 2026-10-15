import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { graphqlRequest } from "../api/client";
import {
  ADAPTER_RUN_QUERY,
  APPROVE_MAPPING_MUTATION,
  CANONICAL_ORDER_SCHEMA_QUERY,
  CANONICAL_SCHEMAS_QUERY,
  MAPPABLE_CONNECTIONS_QUERY,
  MAPPING_JOBS_QUERY,
  MAPPING_JOB_QUERY,
  PROBE_ERP_SAMPLES_MUTATION,
  REGISTER_CANONICAL_SCHEMA_MUTATION,
  SUBMIT_MAPPING_FROM_PROBE_MUTATION,
  SUBMIT_MAPPING_MUTATION,
  SUGGEST_SAMPLE_REQUESTS_MUTATION,
  type AdapterRun,
  type CanonicalSchema,
  type MappableConnection,
  type MappingJob,
  type ProbeSample,
  type SampleRequestInput,
  type SuggestedRequest,
} from "../api/queries/mapping";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";

// A mapping job is worker-driven (an LLM call off the request path), so poll until it
// reaches a terminal state, then stop — same refetchInterval convention as orders.
const POLL_MS = 2000;

export interface SampleFile {
  filename: string;
  content: string;
}

function isTerminal(status: string | undefined): boolean {
  return status === "DONE" || status === "FAILED";
}

export function useCanonicalSchemas() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["canonicalSchemas"],
    queryFn: () =>
      graphqlRequest<{ canonicalSchemas: CanonicalSchema[] }>(
        "operator",
        CANONICAL_SCHEMAS_QUERY,
        {},
        idToken,
      ).then((d) => d.canonicalSchemas),
    enabled: isAuthenticated,
  });
}

// No button, no manual upkeep: refetched whenever the page mounts, so a field added to
// the real order model shows up here on the operator's next visit.
export function useCanonicalOrderSchema() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["canonicalOrderSchema"],
    queryFn: () =>
      graphqlRequest<{ canonicalOrderSchema: string }>(
        "operator",
        CANONICAL_ORDER_SCHEMA_QUERY,
        {},
        idToken,
      ).then((d) => d.canonicalOrderSchema),
    enabled: isAuthenticated,
  });
}

export function useRegisterCanonicalSchema() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { name: string; csvText: string }) =>
      graphqlRequest("operator", REGISTER_CANONICAL_SCHEMA_MUTATION, input, idToken),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["canonicalSchemas"] });
      notify("Canonical schema saved.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useMappableConnections() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["mappableConnections"],
    queryFn: () =>
      graphqlRequest<{ mappableConnections: MappableConnection[] }>(
        "operator",
        MAPPABLE_CONNECTIONS_QUERY,
        {},
        idToken,
      ).then((d) => d.mappableConnections),
    enabled: isAuthenticated,
  });
}

export function useSubmitMapping() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: {
      connectionId: string;
      sampleFiles: SampleFile[];
      schemaName?: string | null;
      canonicalFieldsCsv?: string | null;
    }) =>
      graphqlRequest<{ submitMapping: { jobId: string; status: string } }, typeof input>(
        "operator",
        SUBMIT_MAPPING_MUTATION,
        input,
        idToken,
      ).then((d) => d.submitMapping),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mappingJobs"] });
      queryClient.invalidateQueries({ queryKey: ["mappableConnections"] });
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useProbeErpSamples() {
  const { idToken } = useAuth();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { connectionId: string; requests: SampleRequestInput[] }) =>
      graphqlRequest<{ probeErpSamples: ProbeSample[] }, typeof input>(
        "operator",
        PROBE_ERP_SAMPLES_MUTATION,
        input,
        idToken,
      ).then((d) => d.probeErpSamples),
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useSuggestSampleRequests() {
  const { idToken } = useAuth();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: {
      connectionId: string;
      schemaName?: string | null;
      canonicalFieldsCsv?: string | null;
    }) =>
      graphqlRequest<{ suggestSampleRequests: SuggestedRequest[] }, typeof input>(
        "operator",
        SUGGEST_SAMPLE_REQUESTS_MUTATION,
        input,
        idToken,
      ).then((d) => d.suggestSampleRequests),
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useSubmitMappingFromProbe() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: {
      connectionId: string;
      requests: SampleRequestInput[];
      schemaName?: string | null;
      canonicalFieldsCsv?: string | null;
    }) =>
      graphqlRequest<{ submitMappingFromProbe: { jobId: string; status: string } }, typeof input>(
        "operator",
        SUBMIT_MAPPING_FROM_PROBE_MUTATION,
        input,
        idToken,
      ).then((d) => d.submitMappingFromProbe),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mappingJobs"] });
      queryClient.invalidateQueries({ queryKey: ["mappableConnections"] });
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useMappingJobs() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["mappingJobs"],
    queryFn: () =>
      graphqlRequest<{ mappingJobs: MappingJob[] }>("operator", MAPPING_JOBS_QUERY, {}, idToken).then(
        (d) => d.mappingJobs,
      ),
    enabled: isAuthenticated,
    refetchInterval: (query) =>
      query.state.data?.some((job) => !isTerminal(job.status)) ? POLL_MS : false,
  });
}

export function useMappingJob(jobId: string | null) {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["mappingJob", jobId],
    queryFn: () =>
      graphqlRequest<{ mappingJob: MappingJob | null }, { jobId: string }>(
        "operator",
        MAPPING_JOB_QUERY,
        { jobId: jobId as string },
        idToken,
      ).then((d) => d.mappingJob),
    enabled: isAuthenticated && !!jobId,
    // stop polling once the job finishes (DONE/FAILED); keep polling while it's running
    refetchInterval: (query) => (isTerminal(query.state.data?.status) ? false : POLL_MS),
  });
}

export function useApproveMapping() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { jobId: string }) =>
      graphqlRequest<
        { approveMapping: { jobId: string; adapterRunId: string | null } },
        { jobId: string }
      >("operator", APPROVE_MAPPING_MUTATION, input, idToken).then((d) => d.approveMapping),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["adapterRun", variables.jobId] });
      queryClient.invalidateQueries({ queryKey: ["mappingJobs"] });
      notify("Mapping approved — the adapter is being implemented.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useAdapterRun(jobId: string | null, enabled: boolean) {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["adapterRun", jobId],
    queryFn: () =>
      graphqlRequest<{ adapterRun: AdapterRun | null }, { jobId: string }>(
        "operator",
        ADAPTER_RUN_QUERY,
        { jobId: jobId as string },
        idToken,
      ).then((d) => d.adapterRun),
    enabled: isAuthenticated && !!jobId && enabled,
    refetchInterval: (query) => (isTerminal(query.state.data?.status) ? false : POLL_MS),
  });
}
