type Props = {
  signals: string[];
};

export default function FraudSignals({
  signals,
}: Props) {
  if (!signals?.length) return null;

  return (
    <div className="rounded-xl border border-orange-400 bg-orange-50 p-5">
      <h3 className="mb-3 text-lg font-semibold text-orange-800">
        Fraud Signals
      </h3>

      <ul className="list-disc pl-5">
        {signals.map(
          (signal, index) => (
            <li key={index}>
              {signal}
            </li>
          ),
        )}
      </ul>
    </div>
  );
}