export type Beacon = {
  src: string;
  dst: string;
  kind: string;
  payload: Record<string, unknown>;
  received_at: string;
};

export type Patient = {
  patient_id: string;
  name: string;
  primary_language?: string;
  insurance_id?: string;
};

export type DocMeta = {
  doc_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  description?: string | null;
  uploaded_at?: string | null;
};

export type Outreach = {
  outreach_id: string;
  patient_id?: string;
  patient_name?: string;
  language_request?: string;
  language_detected?: string;
  language_match?: boolean;
  specialty?: string;
  clinic_name?: string;
  clinic_address?: string;
  clinic_phone?: string;
  candidates_count?: number;
  outcome?: string;
  started_at?: string;
  ended_at?: string;
  booking_when?: string;
  ai_summary?: string;
};

export type OutreachStats = {
  total: number;
  booked: number;
  no_answer: number;
  language_mismatch: number;
  failed: number;
  in_progress: number;
};

export type ConnStatus = "connecting" | "live" | "disconnected";
export type Tab = "outreach" | "live";
