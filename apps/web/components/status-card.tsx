type StatusCardProps = {
  label: string;
  value: string;
  change?: string | null;
};

export function StatusCard({ label, value, change }: StatusCardProps) {
  return (
    <article className="panel">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {change ? <div className="metric-change">{change}</div> : null}
    </article>
  );
}
