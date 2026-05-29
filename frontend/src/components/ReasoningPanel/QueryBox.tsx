import { useState } from 'react';
import { submitQuery } from '../../api/client';
import { useAppStore } from '../../store/appStore';

interface QAEntry {
  question: string;
  answer: string;
}

export default function QueryBox() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<QAEntry[]>([]);
  const { setActiveReasoning } = useAppStore();

  async function handleSubmit() {
    const q = input.trim();
    if (!q || loading) return;
    setInput('');
    setLoading(true);
    try {
      const { answer, subgraphNodeIds } = await submitQuery(q);
      setHistory((h) => [...h, { question: q, answer }]);
      setActiveReasoning(null, subgraphNodeIds);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <h3 style={{ color: '#e6edf3', margin: '0 0 4px', fontSize: 14 }}>Query Knowledge Graph</h3>

      {/* History */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 320, overflowY: 'auto' }}>
        {history.map((entry, i) => (
          <div key={i}>
            <div style={{
              background: '#21262d', borderRadius: '8px 8px 8px 0',
              padding: '8px 12px', marginBottom: 4,
            }}>
              <span style={{ color: '#58a6ff', fontSize: 12 }}>You: </span>
              <span style={{ color: '#e6edf3', fontSize: 12 }}>{entry.question}</span>
            </div>
            <div style={{
              background: '#0d1117', borderRadius: '0 8px 8px 8px',
              padding: '8px 12px', border: '1px solid #21262d',
            }}>
              <span style={{ color: '#3fb950', fontSize: 12 }}>TASA: </span>
              <span style={{ color: '#e6edf3', fontSize: 12, lineHeight: 1.6 }}>{entry.answer}</span>
            </div>
          </div>
        ))}
        {loading && (
          <div style={{
            background: '#0d1117', borderRadius: 8, padding: '8px 12px',
            border: '1px solid #21262d', color: '#58a6ff', fontSize: 12,
          }}>
            Reasoning…
          </div>
        )}
      </div>

      {/* Input */}
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="Ask about a satellite or event…"
          style={{
            flex: 1, background: '#0d1117', border: '1px solid #30363d',
            borderRadius: 6, padding: '8px 12px', color: '#e6edf3',
            fontSize: 13, outline: 'none',
          }}
          onFocus={(e) => (e.target.style.borderColor = '#58a6ff')}
          onBlur={(e) => (e.target.style.borderColor = '#30363d')}
        />
        <button
          onClick={handleSubmit}
          disabled={!input.trim() || loading}
          style={{
            background: '#238636', border: 'none', borderRadius: 6,
            color: '#fff', padding: '8px 14px', cursor: 'pointer',
            fontSize: 13, opacity: (!input.trim() || loading) ? 0.5 : 1,
          }}
        >
          Ask
        </button>
      </div>

      <div style={{ color: '#484f58', fontSize: 11 }}>
        Example: "What threats are associated with NOAA-20?"
      </div>
    </div>
  );
}
