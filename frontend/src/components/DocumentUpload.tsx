import React, { useRef } from "react";
import { Plus, Trash2, Upload } from "lucide-react";

export type UploadedDocument = {
  file_id: string;
  actual_type: string;
  fileObject: File | null;
};

type Props = {
  documents: UploadedDocument[];
  setDocuments: React.Dispatch<React.SetStateAction<UploadedDocument[]>>;
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

export default function DocumentUpload({ documents, setDocuments }: Props) {
  const fileInputRefs = useRef<{ [key: string]: HTMLInputElement | null }>({});

  const addDocumentSlot = () => {
    setDocuments((prev) => [
      ...prev,
      {
        file_id: crypto.randomUUID(),
        actual_type: "PRESCRIPTION",
        fileObject: null,
      },
    ]);
  };

  const handleFileChange = (index: number, e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const updated = [...documents];
      updated[index].fileObject = e.target.files[0];
      setDocuments(updated);
    }
  };

  const updateDocumentType = (index: number, value: string) => {
    const updated = [...documents];
    updated[index].actual_type = value;
    setDocuments(updated);
  };

  const removeDocument = (index: number) => {
    setDocuments(documents.filter((_, i) => i !== index));
  };

  return (
    <div className="rounded-xl border bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-slate-900">Claim Documents</h3>
          <p className="text-xs text-slate-500">Upload your physical medical bills and prescriptions</p>
        </div>

        <button
          type="button"
          onClick={addDocumentSlot}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 transition"
        >
          <Plus size={16} />
          Add Document
        </button>
      </div>

      <div className="space-y-3">
        {documents.map((doc, index) => (
          <div key={doc.file_id} className="flex flex-col sm:flex-row gap-3 p-3 rounded-lg border bg-slate-50/50 items-center">
            
            {/* File Selector Block */}
            <div className="flex-1 w-full">
              <input
                type="file"
                accept=".pdf,image/png,image/jpeg"
                ref={(el) => { fileInputRefs.current[doc.file_id] = el; }}
                onChange={(e) => handleFileChange(index, e)}
                className="hidden"
              />
              
              <button
                type="button"
                onClick={() => fileInputRefs.current[doc.file_id]?.click()}
                className="w-full flex items-center justify-center gap-2 border-2 border-dashed border-slate-300 rounded-lg p-3 bg-white text-slate-600 hover:border-blue-500 hover:text-blue-600 transition text-sm font-medium"
              >
                <Upload size={16} />
                {doc.fileObject ? (
                  <span className="text-slate-900 truncate font-normal">
                    {doc.fileObject.name} ({(doc.fileObject.size / 1024).toFixed(1)} KB)
                  </span>
                ) : (
                  <span>Choose PDF or Image</span>
                )}
              </button>
            </div>

            {/* Document Meta and Delete Row */}
            <div className="flex gap-2 w-full sm:w-auto justify-end">
              <select
                value={doc.actual_type}
                onChange={(e) => updateDocumentType(index, e.target.value)}
                className="rounded-lg border bg-white p-2 text-sm font-medium h-11 min-w-[160px]"
              >
                {DOCUMENT_TYPES.map((type) => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>

              <button
                type="button"
                onClick={() => removeDocument(index)}
                className="rounded-lg border border-red-200 bg-white p-2 text-red-600 hover:bg-red-50 transition h-11 w-11 flex items-center justify-center"
              >
                <Trash2 size={16} />
              </button>
            </div>

          </div>
        ))}

        {documents.length === 0 && (
          <p className="text-sm text-slate-500 text-center py-6 border border-dashed rounded-lg">
            No documents attached yet. Click "Add Document" to begin upload.
          </p>
        )}
      </div>
    </div>
  );
}