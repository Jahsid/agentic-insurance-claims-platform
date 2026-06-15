type Props = {
  code: string;
  message: string;
};

export default function BlockedClaimCard({
  code,
  message,
}: Props) {
  return (
    <div className="rounded-xl border-2 border-red-500 bg-red-50 p-6">
      <h2 className="mb-3 text-2xl font-bold text-red-700">
        Claim Blocked
      </h2>

      <div className="mb-3">
        <span className="rounded bg-red-100 px-3 py-1 text-sm font-medium">
          {code}
        </span>
      </div>

      <p className="text-red-800">
        {message}
      </p>
    </div>
  );
}