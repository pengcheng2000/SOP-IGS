import type { BoostConfig, SourceDocument, SourceFileSummary, SourceItem } from "../boost/types";

export type CabinetPlanConfig = BoostConfig;
export type CabinetPlanProject = {
  id: string;
  product_type: "cabinet-test-plan";
  business_type: "cabinet";
  document_kind: "plan";
  name: string;
  description: string;
  revision: number;
  fields: Record<string, string>;
  resolved_fields: Record<string, string>;
  field_sources: Record<string, { kind: "excel" | "supplement" | "missing"; cell: string; source_file_id: string | null }>;
  source_file: SourceFileSummary | null;
  status: string;
  updated_at: string;
};
export type CabinetPlanDocument = SourceDocument & {
  extra: { fields: Record<string, { value: string; source: string }>; references: string[]; environment?: SourceItem; instruments?: SourceItem; closing: SourceItem[] };
};
