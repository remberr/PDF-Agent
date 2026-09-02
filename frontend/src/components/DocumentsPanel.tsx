import { useRef, useState, type DragEvent } from "react";
import { FileText, LoaderCircle, UploadCloud } from "lucide-react";

import type { Translation } from "../i18n";
import type { SessionDetail } from "../types";

interface DocumentsPanelProps {
  session: SessionDetail | null;
  uploading: boolean;
  uploadError: string;
  onUpload: (files: File[]) => void;
  t: Translation;
}

export function DocumentsPanel({
  session,
  uploading,
  uploadError,
  onUpload,
  t,
}: DocumentsPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);

  const submitFiles = (files: File[]) => {
    const pdfs = files.filter(
      (file) => file.type === "application/pdf" || file.name.endsWith(".pdf"),
    );
    if (pdfs.length > 0) {
      onUpload(pdfs);
    }
  };

  const handleDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    setDragActive(false);
    submitFiles(Array.from(event.dataTransfer.files));
  };

  const pdfs = session?.loaded_pdfs ?? [];

  return (
    <aside
      className="panel documents-panel"
      aria-label={t.documents.title}
    >
      <div className="panel-heading">
        <div>
          <span className="eyebrow">{t.documents.library}</span>
          <h2>{t.documents.title}</h2>
        </div>
        <span
          className="count-badge"
          aria-label={`${pdfs.length} ${t.documents.countLabel}`}
        >
          {pdfs.length}
        </span>
      </div>

      <button
        className={`upload-zone${dragActive ? " drag-active" : ""}`}
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        disabled={uploading || !session}
      >
        {uploading ? (
          <LoaderCircle className="spin" size={22} aria-hidden="true" />
        ) : (
          <UploadCloud size={22} aria-hidden="true" />
        )}
        <span>{uploading ? t.documents.indexing : t.documents.add}</span>
        <small>{t.documents.drop}</small>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        hidden
        onChange={(event) => {
          submitFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />

      {uploadError && <div className="inline-error">{uploadError}</div>}

      <div className="document-list">
        {pdfs.map((pdf, index) => (
          <div className="document-row" key={`${pdf}-${index}`}>
            <div className="file-icon" aria-hidden="true">
              <FileText size={18} />
            </div>
            <div className="document-meta">
              <strong title={pdf}>{pdf}</strong>
              <span>{t.documents.indexed}</span>
            </div>
            <span className="status-dot success" title={t.documents.ready} />
          </div>
        ))}

        {pdfs.length === 0 && (
          <div className="empty-list">
            <FileText size={24} aria-hidden="true" />
            <span>{t.documents.empty}</span>
          </div>
        )}
      </div>

      <div className="library-footer">
        <span>{t.documents.pagesIndexed}</span>
        <strong>{session?.total_documents ?? 0}</strong>
      </div>
    </aside>
  );
}
