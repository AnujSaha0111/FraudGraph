export const BAND_CLASS: Record<string, string> = {
  LOW: "band-low",
  MEDIUM: "band-medium",
  HIGH: "band-high",
  CRITICAL: "band-critical",
};

export function BandBadge({ band }: { band: string | null | undefined }) {
  if (!band) return <span className="badge band-none">no score</span>;
  return (
    <span className={`badge ${BAND_CLASS[band] ?? "band-none"}`} data-testid="band-badge">
      {band}
    </span>
  );
}
