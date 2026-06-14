type Props = {
  decision: any;
};

export default function DecisionCard({
  decision,
}: Props) {
  if (!decision) return null;

  const getColor = () => {
    switch (decision.decision) {
      case "APPROVED":
        return "border-green-500 bg-green-50";

      case "PARTIAL":
        return "border-yellow-500 bg-yellow-50";

      case "REJECTED":
        return "border-red-500 bg-red-50";

      default:
        return "border-slate-300 bg-white";
    }
  };

  return (
    <div
      className={`rounded-xl border-2 p-6 ${getColor()}`}
    >
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-2xl font-bold">
          {decision.decision}
        </h2>

        <span className="rounded-lg bg-white px-3 py-1 text-sm font-medium">
          Confidence:{" "}
          {(decision.confidence_score * 100).toFixed(
            0,
          )}
          %
        </span>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="text-sm text-slate-600">
            Claimed Amount
          </p>

          <p className="text-xl font-semibold">
            ₹{decision.claimed_amount}
          </p>
        </div>

        <div>
          <p className="text-sm text-slate-600">
            Approved Amount
          </p>

          <p className="text-xl font-semibold">
            ₹{decision.approved_amount}
          </p>
        </div>
      </div>

      {decision.reasons?.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-2 font-semibold">
            Reasons
          </h4>

          <ul className="list-disc pl-5">
            {decision.reasons.map(
              (
                reason: string,
                index: number,
              ) => (
                <li key={index}>{reason}</li>
              ),
            )}
          </ul>
        </div>
      )}

      {decision.notes && (
        <div className="mt-4 rounded-lg bg-white p-3 text-sm">
          {decision.notes}
        </div>
      )}
    </div>
  );
}