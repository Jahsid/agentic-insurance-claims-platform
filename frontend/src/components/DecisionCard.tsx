// frontend/src/components/DecisionCard.tsx
type Props = {
  decision: any;
};

export default function DecisionCard({ decision }: Props) {
  if (!decision) return null;

  const getColor = () => {
    switch (decision.decision) {
      case "APPROVED":
        return "border-green-500 bg-green-50 text-green-900";
      case "PARTIAL":
        return "border-yellow-500 bg-yellow-50 text-yellow-900";
      case "MANUAL_REVIEW":
        return "border-orange-500 bg-orange-50 text-orange-900";
      case "REJECTED":
        return "border-red-500 bg-red-50 text-red-900";
      default:
        return "border-slate-300 bg-white";
    }
  };

  const { breakdown } = decision;

  return (
    <div className={`rounded-xl border-2 p-6 shadow-sm ${getColor()}`}>
      <div className="mb-4 flex items-center justify-between border-b pb-4 border-current/10">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">{decision.decision}</h2>
          {decision.manual_review_recommended && (
            <p className="text-xs font-medium text-orange-700 mt-1">⚠️ Manual Review Flagged</p>
          )}
        </div>

        <span className="rounded-lg bg-white/80 backdrop-blur-sm px-3 py-1 text-sm font-semibold border shadow-sm text-slate-800">
          Pipeline Confidence: {(decision.confidence_score * 100).toFixed(0)}%
        </span>
      </div>

      {/* Main Totals */}
      <div className="grid gap-4 sm:grid-cols-3 mb-6">
        <div className="rounded-lg bg-white/50 p-3 border">
          <p className="text-xs text-slate-600 font-medium uppercase">Claimed Amount</p>
          <p className="text-2xl font-bold text-slate-900">₹{decision.claimed_amount}</p>
        </div>
        <div className="rounded-lg bg-white/50 p-3 border">
          <p className="text-xs text-slate-600 font-medium uppercase">Approved Amount</p>
          <p className="text-2xl font-bold text-blue-700">₹{decision.approved_amount}</p>
        </div>
        <div className="rounded-lg bg-white/50 p-3 border">
          <p className="text-xs text-slate-600 font-medium uppercase">Currency</p>
          <p className="text-2xl font-bold text-slate-900">{decision.currency || "INR"}</p>
        </div>
      </div>

      {/* Calculation Arithmetic Breakdown */}
      {breakdown && (
        <div className="mb-6 rounded-lg bg-white p-4 border text-slate-800 text-sm space-y-2 shadow-inner">
          <h4 className="font-bold border-b pb-1 text-slate-900">Adjudication Breakdown</h4>
          <div className="flex justify-between"><span>Base Amount:</span> <span className="font-mono">₹{breakdown.base_amount}</span></div>
          {breakdown.is_network_hospital && (
            <div className="flex justify-between text-green-700">
              <span>Network Discount ({breakdown.network_discount_percent}%):</span> 
              <span className="font-mono">-₹{breakdown.discount_amount}</span>
            </div>
          )}
          <div className="flex justify-between text-slate-700">
            <span>Amount After Network Discount:</span> 
            <span className="font-mono">₹{breakdown.amount_after_discount}</span>
          </div>
          <div className="flex justify-between text-red-600">
            <span>Co-pay Deduction ({breakdown.copay_percent}%):</span> 
            <span className="font-mono">-₹{breakdown.copay_amount}</span>
          </div>
          {breakdown.cap_applied && (
            <div className="flex justify-between text-orange-600">
              <span>Policy Cap Applied Ceiling:</span> 
              <span className="font-mono">₹{breakdown.cap_value}</span>
            </div>
          )}
          <div className="flex justify-between border-t pt-2 font-bold text-base text-slate-900">
            <span>Final Settlement Payout:</span> 
            <span className="font-mono">₹{breakdown.approved_amount}</span>
          </div>
        </div>
      )}

      {/* Itemized Line Items Handling (For Partial Claims) */}
      {decision.line_items?.length > 0 && (
        <div className="mt-4 rounded-lg bg-white p-4 border text-slate-800 shadow-sm">
          <h4 className="mb-2 font-bold text-slate-900">Itemized Bill Assessment</h4>
          <div className="divide-y text-xs">
            {decision.line_items.map((item: any, idx: number) => (
              <div key={idx} className="py-2 flex justify-between items-start gap-4">
                <div>
                  <p className="font-semibold text-slate-900">{item.description}</p>
                  {item.reason && <p className="text-slate-500 mt-0.5">{item.reason}</p>}
                </div>
                <div className="text-right">
                  <span className={`inline-block rounded px-1.5 py-0.5 font-bold mb-1 ${item.status === 'APPROVED' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                    {item.status}
                  </span>
                  <p className="font-mono font-medium">Claimed: ₹{item.claimed_amount} → Approved: ₹{item.approved_amount}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Narrative Summary Reasons */}
      {decision.reasons?.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-1 font-bold text-slate-900">Policy Rules Applied</h4>
          <ul className="list-disc pl-5 space-y-1 text-sm">
            {decision.reasons.map((reason: string, index: number) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {decision.notes && (
        <div className="mt-4 rounded-lg bg-slate-900/5 p-3 text-xs italic font-medium">
          Note: {decision.notes}
        </div>
      )}
    </div>
  );
}