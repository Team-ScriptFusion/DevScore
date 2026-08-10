import { useEffect, useRef, useState } from 'react';
import DashboardLayout from '../components/DashboardLayout.jsx';
import { resumeApi } from '../lib/api.js';

function formatSize(bytes) {
  if (!bytes) return '';
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Upload Resume screen (FR 19-27). Accepts a PDF, stores it, and reports the
 * current upload state. Re-uploading replaces the existing file.
 */
export default function UploadResume() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        setStatus(await resumeApi.status());
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function handleFileChosen(e) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;

    setError('');
    if (file.type !== 'application/pdf') {
      return setError('Only PDF resumes are accepted.');
    }
    if (file.size > 5 * 1024 * 1024) {
      return setError('Resume must be 5MB or smaller.');
    }

    setUploading(true);
    try {
      const result = await resumeApi.upload(file);
      setStatus(result);
    } catch (err) {
      setError(err.message || 'Upload failed. Please try again.');
    } finally {
      setUploading(false);
    }
  }

  return (
    <DashboardLayout>
      <h1 className="page-title">Upload Resume</h1>
      <p className="page-subtitle">
        Upload a PDF resume so we can extract the skills you claim and match
        them against your GitHub evidence.
      </p>

      {error && (
        <div className="alert alert--error" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      <div className="card" style={{ maxWidth: 480 }}>
        {loading ? (
          <p>Checking resume status…</p>
        ) : status?.uploaded ? (
          <>
            <p>
              <strong>Uploaded</strong> {status.filename}
            </p>
            <p className="muted">
              {formatSize(status.sizeBytes)}
              {status.uploadedAt
                ? ` · ${new Date(status.uploadedAt).toLocaleDateString()}`
                : ''}
            </p>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => inputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? 'Uploading…' : 'Replace resume'}
            </button>
          </>
        ) : (
          <>
            <p className="muted">PDF only, up to 5MB.</p>
            <button
              type="button"
              className="btn-primary"
              onClick={() => inputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? 'Uploading…' : 'Upload Resume'}
            </button>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          onChange={handleFileChosen}
          hidden
        />
      </div>
    </DashboardLayout>
  );
}
