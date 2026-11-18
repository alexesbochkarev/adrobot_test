export type Item = { id: number; name: string };
export type Offer = {
  offer_id: number;
  name: string;
  share: number;
  pinned: boolean;
  removed: boolean;
  is_new: boolean;
};
export type Stream = {
  id: number;
  keitaro_id: number;
  name: string;
  position: number;
  schema_kind: string;
  revision: number;
  remote_present: boolean;
  is_dirty: boolean;
  offers: Offer[];
};
export type Campaign = {
  campaign_id: number;
  keitaro_id: number;
  editor_revision: number;
  sync_locked: boolean;
  publication_id: string | null;
  streams: Stream[];
};
export type Publication = {
  id: string;
  status: string;
  phase: string;
  error_code: string | null;
  result: Stream | null;
};
export type Created = {
  operation_id: string;
  campaign_id: number;
  keitaro_id: number;
  name: string;
  tracking_url: string;
  stream_ids: number[];
};
export type Creation = {
  id: string;
  status: string;
  phase: string;
  remote_campaign_id: number | null;
  error_code: string | null;
  result: Created | null;
};
export type CreateBody = {
  name: string;
  country_code: string;
  offer_id: number;
  domain_id?: number;
  group_id?: number;
  traffic_source_id?: number;
};
