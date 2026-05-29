import { useRef, useState } from 'react';
import { submitReport } from '../../api/client';
import { useAppStore } from '../../store/appStore';

const SEVERITY_COLORS = {
  Low: '#3fb950',
  Medium: '#e3b341',
  High: '#f78166',
  Critical: '#ff4444',
};

export default function ReportViewer() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const { activeReasoning, setActiveReasoning } = useAppStore();

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setLoading(true);
    try {
      const { assessment, subgraphNodeIds } = await submitReport(file);
      setActiveReasoning(assessment, subgraphNodeIds);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ padding: 16 }}>
      <h3 style={{ color: '#e6edf3', margin: '0 0 12px', fontSize: 14 }}>JCO Report Analysis</h3>

      <div
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: '2px dashed #30363d', borderRadius: 8, padding: 20,
          textAlign: 'center', cursor: 'pointer', marginBottom: 16,
          background: '#0d1117', transition: 'border-color 0.2s',
        }}
        onMouseEnter={(e) => (e.currentTarget.style.borderColor = '#58a6ff')}
        onMouseLeave={(e) => (e.currentTarget.style.borderColor = '#30363d')}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.txt"
          style={{ display: 'none' }}
          onChange={handleFile}
        />
        <div style={{ color: '#58a6ff', fontSize: 24, marginBottom: 8 }}>📄</div>
        <div style={{ color: '#8b949e', fontSize: 13 }}>
          {fileName ?? 'Drop JCO report here or click to upload'}
        </div>
        <div style={{ color: '#484f58', fontSize: 11, marginTop: 4 }}>PDF or TXT</div>
      </div>

      {loading && (
        <div style={{
          textAlign: 'center', color: '#58a6ff', padding: 20,
          background: '#0d1117', borderRadius: 8,
        }}>
          Analyzing report with GPT-4o…
        </div>
      )}

      {!loading && activeReasoning && (
        <div style={{ background: '#0d1117', borderRadius: 8, overflow: 'hidden' }}>
          {/* Severity badge */}
          <div style={{
            padding: '10px 16px',
            background: SEVERITY_COLORS[activeReasoning.severity] + '22',
            borderBottom: `2px solid ${SEVERITY_COLORS[activeReasoning.severity]}`,
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <span style={{
              background: SEVERITY_COLORS[activeReasoning.severity],
              color: '#0d1117', fontWeight: 700, fontSize: 12,
              padding: '2px 10px', borderRadius: 20,
            }}>
              {activeReasoning.severity.toUpperCase()}
            </span>
            <span style={{ color: '#8b949e', fontSize: 11 }}>{activeReasoning.timestamp}</span>
          </div>

          {/* Narrative */}
          <div style={{ padding: 16, borderBottom: '1px solid #21262d' }}>
            <div style={{ color: '#8b949e', fontSize: 11, marginBottom: 6 }}>THREAT ASSESSMENT</div>
            <p style={{ color: '#e6edf3', fontSize: 13, margin: 0, lineHeight: 1.7 }}>
              {activeReasoning.narrative}
            </p>
          </div>

          {/* Actions */}
          <div style={{ padding: 16 }}>
            <div style={{ color: '#8b949e', fontSize: 11, marginBottom: 8 }}>RECOMMENDED ACTIONS</div>
            <ul style={{ margin: 0, padding: '0 0 0 16px' }}>
              {activeReasoning.recommendedActions.map((a, i) => (
                <li key={i} style={{ color: '#e6edf3', fontSize: 12, marginBottom: 6, lineHeight: 1.5 }}>
                  {a}
                </li>
              ))}
            </ul>
          </div>

          <div style={{ padding: '8px 16px', borderTop: '1px solid #21262d' }}>
            <span style={{ color: '#484f58', fontSize: 11 }}>
              KG subgraph highlighted in orange ↑
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
