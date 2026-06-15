type Props = {
  result: any;
};

export default function PipelineSummary({
  result,
}: Props) {
  return (
    <div className="grid gap-4 md:grid-cols-4">
      <div className="rounded-lg border bg-white p-4">
        <p className="text-sm text-slate-500">
          Confidence
        </p>
        <p className="text-2xl font-bold">
          {(result.confidence_score * 100).toFixed(0)}%
        </p>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <p className="text-sm text-slate-500">
          Fraud Score
        </p>
        <p className="text-2xl font-bold">
          {result.fraud_score ?? 0}
        </p>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <p className="text-sm text-slate-500">
          Blocked
        </p>
        <p className="text-2xl font-bold">
          {result.blocked ? "Yes" : "No"}
        </p>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <p className="text-sm text-slate-500">
          Degraded
        </p>
        <p className="text-2xl font-bold">
          {result.degraded ? "Yes" : "No"}
        </p>
      </div>
    </div>
  );
}