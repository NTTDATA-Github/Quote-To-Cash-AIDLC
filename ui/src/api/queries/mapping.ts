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

export interface AdapterRun {
  status: string; // PENDING | PROCESSING | DONE | FAILED
  branch: string | null;
  prUrl: string | null;
  error: string | null;
}

export const CANONICAL_SCHEMAS_QUERY = /* GraphQL */ `
  query CanonicalSchemas {
    canonicalSchemas { name fieldCount }
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

export const REGISTER_CANONICAL_SCHEMA_MUTATION = /* GraphQL */ `
  mutation RegisterCanonicalSchema($name: String!, $csvText: String!) {
    registerCanonicalSchema(name: $name, csvText: $csvText) { name fieldCount }
  }
`;

export const SUBMIT_MAPPING_MUTATION = /* GraphQL */ `
  mutation SubmitMapping(
    $erpName: String!
    $sampleFiles: [SampleFileInput!]!
    $schemaName: String
    $canonicalFieldsCsv: String
  ) {
    submitMapping(
      erpName: $erpName
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
