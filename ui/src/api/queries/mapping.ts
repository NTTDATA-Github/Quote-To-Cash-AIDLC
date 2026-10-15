// ERP field-mapping proposer (operator "ERP mapping" tab). Folded in from the former
// standalone erp-mapping-service + Streamlit UI: register/pick a canonical field list,
// upload an ERP's sample export(s), get a draft mapping an operator reviews, then approve
// it to hand off to the adapter-codegen service. Operator schema only (ERP identity).

export interface CanonicalSchema {
  name: string;
  fieldCount: number;
}

export interface MappingEntry {
  erpField: string;
  canonicalField: string;
  sampleData: string;
  // 0-100; the prompt calibrates it strict — treat below ~95 as something to check by hand.
  confidence: number;
}

export interface MappingJob {
  jobId: string;
  erpName: string;
  status: string; // PENDING | PROCESSING | DONE | FAILED
  mapping: MappingEntry[]; // empty until DONE (or if nothing matched)
  error: string | null;
  adapterRunId: string | null;
  createdAt: string;
  schemaName: string | null;
  sampleFiles: string[];
}

export interface MappableConnection {
  connectionId: string;
  erpType: string;
  instanceLabel: string;
}

export interface AdapterRun {
  status: string; // PENDING | PROCESSING | DONE | FAILED
  branch: string | null;
  prUrl: string | null;
  error: string | null;
}

// --- ERP onboarding probe (fetch samples live instead of a manual file upload) ---
export type AuthType = "NONE" | "API_KEY_HEADER" | "BASIC" | "BEARER_TOKEN";

export interface AuthConfigInput {
  authType: AuthType;
  params: Record<string, string>;
  secret: string | null;
}

export interface SampleRequestInput {
  label: string;
  method: string;
  path: string;
  queryParams: Record<string, string>;
}

export interface ProbeSample {
  label: string;
  text: string | null;
  error: string | null;
}

export interface SuggestedRequest {
  label: string;
  method: string;
  path: string;
}

export const CANONICAL_SCHEMAS_QUERY = /* GraphQL */ `
  query CanonicalSchemas {
    canonicalSchemas { name fieldCount }
  }
`;

// Derived live from the real adapter contract (ErpPartnerOrder et al.) — a new field
// shows up here on the next fetch, no CSV to maintain.
export const CANONICAL_ORDER_SCHEMA_QUERY = /* GraphQL */ `
  query CanonicalOrderSchema {
    canonicalOrderSchema
  }
`;

export const MAPPING_JOBS_QUERY = /* GraphQL */ `
  query MappingJobs {
    mappingJobs {
      jobId
      erpName
      status
      createdAt
      schemaName
      sampleFiles
      mapping { erpField canonicalField sampleData confidence }
      error
      adapterRunId
    }
  }
`;

export const MAPPING_JOB_QUERY = /* GraphQL */ `
  query MappingJob($jobId: String!) {
    mappingJob(jobId: $jobId) {
      jobId
      erpName
      status
      createdAt
      schemaName
      sampleFiles
      mapping { erpField canonicalField sampleData confidence }
      error
      adapterRunId
    }
  }
`;

export const ADAPTER_RUN_QUERY = /* GraphQL */ `
  query AdapterRun($jobId: String!) {
    adapterRun(jobId: $jobId) { status branch prUrl error }
  }
`;

// ADR-0021/0022: connections whose erp_type has no adapter yet and no mapping job
// already in flight or approved for it — the only ones the Mapping page may pick.
export const MAPPABLE_CONNECTIONS_QUERY = /* GraphQL */ `
  query MappableConnections {
    mappableConnections { connectionId erpType instanceLabel }
  }
`;

export const REGISTER_CANONICAL_SCHEMA_MUTATION = /* GraphQL */ `
  mutation RegisterCanonicalSchema($name: String!, $csvText: String!) {
    registerCanonicalSchema(name: $name, csvText: $csvText) { name fieldCount }
  }
`;

export const SUBMIT_MAPPING_MUTATION = /* GraphQL */ `
  mutation SubmitMapping(
    $connectionId: String!
    $sampleFiles: [SampleFileInput!]!
    $schemaName: String
    $canonicalFieldsCsv: String
  ) {
    submitMapping(
      connectionId: $connectionId
      sampleFiles: $sampleFiles
      schemaName: $schemaName
      canonicalFieldsCsv: $canonicalFieldsCsv
    ) {
      jobId
      status
    }
  }
`;

export const APPROVE_MAPPING_MUTATION = /* GraphQL */ `
  mutation ApproveMapping($jobId: String!) {
    approveMapping(jobId: $jobId) { jobId adapterRunId }
  }
`;

export const PROBE_ERP_SAMPLES_MUTATION = /* GraphQL */ `
  mutation ProbeErpSamples($connectionId: String!, $requests: [SampleRequestInput!]!) {
    probeErpSamples(connectionId: $connectionId, requests: $requests) { label text error }
  }
`;

export const SUGGEST_SAMPLE_REQUESTS_MUTATION = /* GraphQL */ `
  mutation SuggestSampleRequests(
    $connectionId: String!
    $schemaName: String
    $canonicalFieldsCsv: String
  ) {
    suggestSampleRequests(
      connectionId: $connectionId
      schemaName: $schemaName
      canonicalFieldsCsv: $canonicalFieldsCsv
    ) {
      label
      method
      path
    }
  }
`;

export const SUBMIT_MAPPING_FROM_PROBE_MUTATION = /* GraphQL */ `
  mutation SubmitMappingFromProbe(
    $connectionId: String!
    $requests: [SampleRequestInput!]!
    $schemaName: String
    $canonicalFieldsCsv: String
  ) {
    submitMappingFromProbe(
      connectionId: $connectionId
      requests: $requests
      schemaName: $schemaName
      canonicalFieldsCsv: $canonicalFieldsCsv
    ) {
      jobId
      status
    }
  }
`;
