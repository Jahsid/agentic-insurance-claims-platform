import DecisionCard from "../components/DecisionCard";
import TraceViewer from "../components/TraceViewer";

import PipelineSummary from "../components/PipelineSummary";
import FraudSignals from "../components/FraudSignals";
import BlockedClaimCard from "../components/BlockedClaimCard";

type Props = {
  result: any;
};

export default function ClaimResult({
  result,
}: Props) {
  if (!result) return null;

  return (
    <div className="space-y-6">

      <PipelineSummary
        result={result}
      />

      {result.blocked ? (
        <BlockedClaimCard
          code={result.block_code}
          message={result.block_message}
        />
      ) : (
        <>
          <DecisionCard
            decision={result.decision}
          />

          <FraudSignals
            signals={
              result.fraud_signals
            }
          />
        </>
      )}

      <TraceViewer
        trace={result.trace}
      />
    </div>
  );
}