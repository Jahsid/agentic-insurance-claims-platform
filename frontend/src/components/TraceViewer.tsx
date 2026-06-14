import { ChevronDown } from "lucide-react";

type Props = {
  trace: any[];
};

export default function TraceViewer({
  trace,
}: Props) {
  if (!trace?.length) return null;

  const statusColor = (
    status: string,
  ) => {
    switch (status) {
      case "PASS":
        return "text-green-600";

      case "WARNING":
        return "text-yellow-600";

      case "FAIL":
        return "text-red-600";

      case "BLOCKED":
        return "text-red-700";

      default:
        return "text-slate-600";
    }
  };

  return (
    <div className="rounded-xl border bg-white p-5">
      <h3 className="mb-4 text-lg font-semibold">
        Decision Trace
      </h3>

      <div className="space-y-3">
        {trace.map(
          (entry: any, index: number) => (
            <details
              key={index}
              className="rounded-lg border"
            >
              <summary className="flex cursor-pointer items-center justify-between p-4">
                <div>
                  <span className="font-medium">
                    {entry.stage}
                  </span>

                  <span
                    className={`ml-3 font-semibold ${statusColor(
                      entry.status,
                    )}`}
                  >
                    {entry.status}
                  </span>
                </div>

                <ChevronDown size={16} />
              </summary>

              <div className="border-t bg-slate-50 p-4">
                <p className="mb-2">
                  <strong>
                    Component:
                  </strong>{" "}
                  {entry.component}
                </p>

                <p className="mb-3">
                  {entry.message}
                </p>

                {entry.details && (
                  <pre className="overflow-auto rounded bg-white p-3 text-xs">
                    {JSON.stringify(
                      entry.details,
                      null,
                      2,
                    )}
                  </pre>
                )}
              </div>
            </details>
          ),
        )}
      </div>
    </div>
  );
}