import type { components } from './schema';

type S = components['schemas'];
export type ApiError = S['Error'];
export type ErrorCode = S['Error']['code'];
export type EvidenceState = S['EvidenceState'];
export type Evidence = S['Evidence'];
export type LonLat = S['LonLat'];
export type Health = S['Health'];
export type Coverage = S['Coverage'];
export type DataSource = S['DataSource'];
export type WeatherCurrent = S['WeatherCurrent'];
export type WeatherForecast = S['WeatherForecast'];
export type HazardKind = S['HazardKind'];
export type HazardFeature = S['HazardFeature'];
export type HazardCollection = S['HazardCollection'];
export type SegmentFeature = S['SegmentFeature'];
export type SegmentCollection = S['SegmentCollection'];
export type RiskLevel = S['RiskEstimate']['level'];
export type RouteProfile = S['RouteProfile'];
export type RouteCompareRequest = S['RouteCompareRequest'];
export type RouteCompareResponse = S['RouteCompareResponse'];
export type Route = S['Route'];
export type ReportCategory = S['ReportCategory'];
export type ReportCreate = S['ReportCreate'];
export type ReportReceipt = S['ReportReceipt'];
export type ReportAdminView = S['ReportAdminView'];
export type ModerationStatus = S['ModerationStatus'];
export type ModelStatus = S['ModelStatus'];
export type PilotRequest = S['PilotRequest'];

export const EVIDENCE_STATES: readonly EvidenceState[] = [
  'confirmed',
  'unverified_report',
  'model_estimate',
  'unknown',
  'simulated',
] as const;
