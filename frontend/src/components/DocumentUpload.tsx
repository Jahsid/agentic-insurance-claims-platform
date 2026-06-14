import { Plus, Trash2 } from "lucide-react";

type Document = {
  file_id: string;
  actual_type: string;
};

type Props = {
  documents: Document[];
  setDocuments: React.Dispatch<
    React.SetStateAction<Document[]>
  >;
};

const DOCUMENT_TYPES = [
  "PRESCRIPTION",
  "HOSPITAL_BILL",
  "PHARMACY_BILL",
  "LAB_REPORT",
  "DIAGNOSTIC_REPORT",
  "DISCHARGE_SUMMARY",
  "DENTAL_REPORT",
];

export default function DocumentUpload({
  documents,
  setDocuments,
}: Props) {
  const addDocument = () => {
    setDocuments((prev) => [
      ...prev,
      {
        file_id: crypto.randomUUID(),
        actual_type: "PRESCRIPTION",
      },
    ]);
  };

  const updateDocument = (
    index: number,
    value: string,
  ) => {
    const updated = [...documents];
    updated[index].actual_type = value;
    setDocuments(updated);
  };

  const removeDocument = (index: number) => {
    setDocuments(
      documents.filter((_, i) => i !== index),
    );
  };

  return (
    <div className="rounded-xl border bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold">
          Documents
        </h3>

        <button
          type="button"
          onClick={addDocument}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus size={16} />
          Add Document
        </button>
      </div>

      <div className="space-y-3">
        {documents.map((doc, index) => (
          <div
            key={doc.file_id}
            className="flex items-center gap-3"
          >
            <select
              value={doc.actual_type}
              onChange={(e) =>
                updateDocument(
                  index,
                  e.target.value,
                )
              }
              className="flex-1 rounded-lg border p-2"
            >
              {DOCUMENT_TYPES.map((type) => (
                <option
                  key={type}
                  value={type}
                >
                  {type}
                </option>
              ))}
            </select>

            <button
              type="button"
              onClick={() =>
                removeDocument(index)
              }
              className="rounded-lg border p-2 text-red-600 hover:bg-red-50"
            >
              <Trash2 size={16} />
            </button>
          </div>
        ))}

        {documents.length === 0 && (
          <p className="text-sm text-slate-500">
            No documents added yet.
          </p>
        )}
      </div>
    </div>
  );
}