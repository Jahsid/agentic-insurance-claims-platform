import DecisionCard from "../components/DecisionCard";
import TraceViewer from "../components/TraceViewer";

type Props = {
  result: any;
};

export default function ClaimResult({
  result,
}: Props) {
  if (!result) return null;

  return (
    <div className="space-y-6">
      <DecisionCard
        decision={result.decision}
      />

      <TraceViewer
        trace={result.trace}
      />
    </div>
  );
}