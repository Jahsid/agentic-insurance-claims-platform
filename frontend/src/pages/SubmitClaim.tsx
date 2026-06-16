// Parts of frontend/src/pages/SubmitClaim.tsx
import { useState } from "react";
import api from "../api/client";
import DocumentUpload, { type UploadedDocument } from "../components/DocumentUpload";
import ClaimResult from "./ClaimResult";

export default function SubmitClaim() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  
  const [documents, setDocuments] = useState<UploadedDocument[]>([
    { file_id: crypto.randomUUID(), actual_type: "PRESCRIPTION", fileObject: null },
    { file_id: crypto.randomUUID(), actual_type: "HOSPITAL_BILL", fileObject: null },
  ]);

  const [formData, setFormData] = useState({
    member_id: "EMP001",
    policy_id: "PLUM_GHI_2024",
    claim_category: "CONSULTATION",
    treatment_date: "2024-10-01",
    claimed_amount: 1000,
    hospital_name: "Apollo Hospitals",
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: name === "claimed_amount" ? Number(value) : value,
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Verification: Ensure files are selected for each document entry
    const missingFiles = documents.some((doc) => !doc.fileObject);
    if (missingFiles) {
      alert("Please upload a physical file for all listed documents before submitting.");
      return;
    }

    try {
      setLoading(true);

      // Create browser native multi-part form constructor
      const multipartPayload = new FormData();

      multipartPayload.append("member_id", formData.member_id);
      multipartPayload.append("policy_id", formData.policy_id);
      multipartPayload.append("claim_category", formData.claim_category);
      multipartPayload.append("treatment_date", formData.treatment_date);
      multipartPayload.append("claimed_amount", String(formData.claimed_amount));
      multipartPayload.append("hospital_name", formData.hospital_name);

      documents.forEach((doc, index) => {
        if (doc.fileObject) {
          // Append binary file object stream
          multipartPayload.append("files", doc.fileObject);
          
          // Append meta mappings configuration (as JSON strings or structural matching)
          multipartPayload.append(`document_metadata_${index}`, JSON.stringify({
            file_id: doc.file_id,
            actual_type: doc.actual_type,
          }));
        }
      });

      // Issue dynamic Axios network post over multiform configuration
      const response = await api.post("/claims", multipartPayload, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      setResult(response.data);
    } catch (error: any) {
      console.error(error);
      alert(error?.response?.data?.detail || "Claim submission pipeline error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8">
      <div className="rounded-xl border bg-white p-6 shadow-sm">
        <h2 className="mb-6 text-2xl font-bold">
          Submit Claim
        </h2>

        <form
          onSubmit={handleSubmit}
          className="space-y-5"
        >
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm font-medium">
                Member ID
              </label>

              <input
                type="text"
                name="member_id"
                value={
                  formData.member_id
                }
                onChange={
                  handleChange
                }
                className="w-full rounded-lg border p-3"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">
                Policy ID
              </label>

              <input
                type="text"
                name="policy_id"
                value={
                  formData.policy_id
                }
                onChange={
                  handleChange
                }
                className="w-full rounded-lg border p-3"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">
                Claim Category
              </label>

              <select
                name="claim_category"
                value={
                  formData.claim_category
                }
                onChange={
                  handleChange
                }
                className="w-full rounded-lg border p-3"
              >
                <option value="CONSULTATION">
                  CONSULTATION
                </option>

                <option value="DIAGNOSTIC">
                  DIAGNOSTIC
                </option>

                <option value="PHARMACY">
                  PHARMACY
                </option>

                <option value="DENTAL">
                  DENTAL
                </option>

                <option value="VISION">
                  VISION
                </option>

                <option value="ALTERNATIVE_MEDICINE">
                  ALTERNATIVE_MEDICINE
                </option>
              </select>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">
                Treatment Date
              </label>

              <input
                type="date"
                name="treatment_date"
                value={
                  formData.treatment_date
                }
                onChange={
                  handleChange
                }
                className="w-full rounded-lg border p-3"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">
                Claimed Amount
              </label>

              <input
                type="number"
                name="claimed_amount"
                value={
                  formData.claimed_amount
                }
                onChange={
                  handleChange
                }
                className="w-full rounded-lg border p-3"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">
                Hospital Name
              </label>

              <input
                type="text"
                name="hospital_name"
                placeholder="Apollo Hospitals"
                value={
                  formData.hospital_name
                }
                onChange={
                  handleChange
                }
                className="w-full rounded-lg border p-3"
              />
            </div>
          </div>

          <DocumentUpload
            documents={documents}
            setDocuments={
              setDocuments
            }
          />

          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-blue-600 px-6 py-3 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading
              ? "Processing..."
              : "Submit Claim"}
          </button>
        </form>
      </div>

      {result && (
        <ClaimResult
          result={result}
        />
      )}
    </div>
  );
}