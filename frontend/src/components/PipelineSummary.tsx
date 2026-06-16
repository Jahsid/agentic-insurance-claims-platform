// frontend/src/components/PipelineSummary.tsx
type Props = {
  result: any;
};

export default function PipelineSummary({ result }: Props) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4">
      <div className="rounded-lg border bg-white p-4 shadow-sm">
        <p className="text-sm text-slate-500 font-medium">Confidence Score</p>
        <p className={`text-2xl font-bold mt-1 ${result.confidence_score < 0.5 ? 'text-red-600' : 'text-slate-900'}`}>
          {(result.confidence_score * 100).toFixed(0)}%
        </p>
      </div>

      <div className="rounded-lg border bg-white p-4 shadow-sm">
        <p className="text-sm text-slate-500 font-medium">Fraud Score</p>
        <p className={`text-2xl font-bold mt-1 ${result.fraud_score > 0 ? 'text-orange-600' : 'text-slate-900'}`}>
          {result.fraud_score ?? 0}
        </p>
      </div>

      <div className="rounded-lg border bg-white p-4 shadow-sm">
        <p className="text-sm text-slate-500 font-medium">Blocked Route</p>
        <p className={`text-2xl font-bold mt-1 ${result.blocked ? 'text-red-600' : 'text-green-600'}`}>
          {result.blocked ? "Blocked" : "Clear"}
        </p>
      </div>

      <div className="rounded-lg border bg-white p-4 shadow-sm relative overflow-hidden">
        <p className="text-sm text-slate-500 font-medium">Degraded Pipeline</p>
        <p className={`text-2xl font-bold mt-1 ${result.degraded ? 'text-amber-600' : 'text-slate-900'}`}>
          {result.degraded ? "Fallback Active" : "Optimal"}
        </p>
        {result.degraded && (
          <div className="absolute top-0 right-0 w-2 h-full bg-amber-500" />
        )}
      </div>
    </div>
  );
}