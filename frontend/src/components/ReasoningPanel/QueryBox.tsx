import { useState, useRef, useEffect, ReactNode } from 'react';
import { queryAnalysis } from '../../api/client';
import { useAppStore } from '../../store/appStore';
import type { QueryResult } from '../../api/client';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  steps?: QueryResult['steps'];
  warning?: string;
}

const STARTER_QUESTIONS = [
  'List all maneuver events in LEO in the past 30 days',
  'Which Chinese satellites pass over Taiwan most often?',
  'What launches have occurred in the past 60 days?',
];

function renderInline(text: string): ReactNode {
  const parts: ReactNode[] = [];
  let current = text;
  let key = 0;

  while (current.length > 0) {
    const boldMatch = current.match(/^\*\*([^*]+)\*\*/);
    const italicMatch = current.match(/^_([^_]+)_/);
    const codeMatch = current.match(/^`([^`]+)`/);

    if (boldMatch) {
      parts.push(
        <strong key={key++} style={{ color: '#79c0ff', fontWeight: 700 }}>
          {boldMatch[1]}
        </strong>
      );
      current = current.slice(boldMatch[0].length);
    } else if (italicMatch) {
      parts.push(
        <em key={key++} style={{ color: '#a371f7', fontStyle: 'italic' }}>
          {italicMatch[1]}
        </em>
      );
      current = current.slice(italicMatch[0].length);
    } else if (codeMatch) {
      parts.push(
        <code key={key++} style={{ background: '#0d1117', color: '#79c0ff', padding: '1px 4px', borderRadius: 3, fontSize: 10 }}>
          {codeMatch[1]}
        </code>
      );
      current = current.slice(codeMatch[0].length);
    } else {
      const nextMatch = current.match(/[\*_`]/);
      if (nextMatch && nextMatch.index !== undefined) {
        parts.push(current.slice(0, nextMatch.index));
        // Skip the special character that didn't match a complete pattern
        current = current.slice(nextMatch.index + 1);
      } else {
        parts.push(current);
        current = '';
      }
    }
  }

  return <>{parts}</>;
}

function renderMarkdown(text: string): ReactNode {
  const lines = text.split('\n');
  const elements: ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Empty line
    if (!line.trim()) {
      elements.push(<div key={`empty-${i}`} style={{ height: 6 }} />);
      i++;
      continue;
    }

    // Headers
    if (line.startsWith('### ')) {
      elements.push(
        <h4 key={i} style={{ color: '#79c0ff', margin: '10px 0 4px', fontSize: 12, fontWeight: 700 }}>
          {renderInline(line.slice(4))}
        </h4>
      );
      i++;
    } else if (line.startsWith('## ')) {
      elements.push(
        <h3 key={i} style={{ color: '#58a6ff', margin: '12px 0 6px', fontSize: 13, fontWeight: 700 }}>
          {renderInline(line.slice(3))}
        </h3>
      );
      i++;
    }
    // Bullet list
    else if (line.startsWith('- ') || line.startsWith('* ')) {
      const items: string[] = [];
      while (i < lines.length && (lines[i].startsWith('- ') || lines[i].startsWith('* '))) {
        items.push(lines[i].slice(2));
        i++;
      }
      elements.push(
        <div key={`list-${i}`} style={{ margin: '4px 0' }}>
          {items.map((item, idx) => (
            <div key={idx} style={{ display: 'flex', gap: 8, margin: '3px 0', fontSize: 11, color: '#e6edf3' }}>
              <span style={{ color: '#3fb950', flexShrink: 0, fontWeight: 600 }}>•</span>
              <span>{renderInline(item)}</span>
            </div>
          ))}
        </div>
      );
    }
    // Numbered list
    else if (line.match(/^\d+\. /)) {
      const items: { num: string; text: string }[] = [];
      while (i < lines.length && lines[i].match(/^\d+\. /)) {
        const match = lines[i].match(/^(\d+)\. (.*)$/);
        if (match) {
          items.push({ num: match[1], text: match[2] });
        }
        i++;
      }
      elements.push(
        <div key={`numlist-${i}`} style={{ margin: '4px 0' }}>
          {items.map((item, idx) => (
            <div key={idx} style={{ display: 'flex', gap: 8, margin: '3px 0', fontSize: 11, color: '#e6edf3' }}>
              <span style={{ color: '#3fb950', flexShrink: 0, fontWeight: 600, minWidth: 20 }}>{item.num}.</span>
              <span>{renderInline(item.text)}</span>
            </div>
          ))}
        </div>
      );
    }
    // Paragraph
    else {
      elements.push(
        <p key={i} style={{ color: '#e6edf3', fontSize: 11, margin: '4px 0', lineHeight: 1.6 }}>
          {renderInline(line)}
        </p>
      );
      i++;
    }
  }

  return <>{elements}</>;
}

export default function QueryBox() {
  const { selectedSatelliteId } = useAppStore();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [expandedStep, setExpandedStep] = useState<string | null>(null);
  const [showReasoning, setShowReasoning] = useState<number | null>(null);
  const [toolProgress, setToolProgress] = useState<{ tool: string; args: Record<string, any> } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const send = async (question: string) => {
    if (!question.trim() || loading) return;
    const q = question.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: q }]);
    setLoading(true);
    setToolProgress(null);
    try {
      const history = messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({ role: m.role, content: m.content }));

      const result = await queryAnalysis(
        q,
        selectedSatelliteId ?? undefined,
        history,
        (toolName, args) => {
          // Update progress when tool is called
          setToolProgress({ tool: toolName, args });
        }
      );
      setToolProgress(null);
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: result.answer,
        steps: result.steps,
        warning: result.warning,
      }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Error: could not reach analysis API.' }]);
    }
    setLoading(false);
    setToolProgress(null);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0d1117' }}>
      {/* Message area */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }}>
        {messages.length === 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, color: '#484f58', marginBottom: 6, fontWeight: 600 }}>SUGGESTED QUESTIONS</div>
            {STARTER_QUESTIONS.map((q) => (
              <button key={q} onClick={() => send(q)} style={{
                display: 'block', width: '100%', textAlign: 'left',
                background: 'none', border: '1px solid #30363d', borderRadius: 4,
                color: '#58a6ff', fontSize: 11, padding: '6px 8px', marginBottom: 6, cursor: 'pointer',
              }}>
                {q}
              </button>
            ))}
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
            {msg.role === 'user' ? (
              <div style={{ background: '#1f6feb22', border: '1px solid #1f6feb44', borderRadius: 6, padding: '8px 10px', fontSize: 11, color: '#e6edf3' }}>
                {msg.content}
              </div>
            ) : (
              <div>
                <div style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 6, padding: '10px 12px', fontSize: 11, color: '#e6edf3' }}>
                  {renderMarkdown(msg.content)}
                </div>

                {msg.steps && msg.steps.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    <button onClick={() => setShowReasoning(showReasoning === i ? null : i)} style={{
                      background: '#161b22', border: '1px solid #30363d', borderRadius: 4,
                      color: '#58a6ff', fontSize: 10, padding: '4px 8px', cursor: 'pointer', width: '100%', textAlign: 'left',
                      marginBottom: 4,
                    }}>
                      {showReasoning === i ? '▼' : '▶'} {showReasoning === i ? 'Hide' : 'Show'} reasoning ({msg.steps.length})
                    </button>

                    {showReasoning === i && (
                      <div style={{ marginBottom: 6 }}>
                        {msg.steps.map((step, si) => {
                          const key = `${i}-${si}`;
                          const expanded = expandedStep === key;
                          return (
                            <div key={si} style={{ marginBottom: 3 }}>
                              <button onClick={() => setExpandedStep(expanded ? null : key)} style={{
                                background: '#0d1117', border: '1px solid #30363d', borderRadius: 4,
                                color: '#8b949e', fontSize: 10, padding: '3px 8px', cursor: 'pointer', width: '100%', textAlign: 'left',
                              }}>
                                {expanded ? '▼' : '▶'} {step.tool}
                              </button>
                              {expanded && (
                                <div style={{
                                  padding: '6px 8px', background: '#0d1117', borderRadius: '0 0 4px 4px',
                                  fontSize: 9, color: '#8b949e', border: '1px solid #30363d', borderTop: 'none',
                                  maxHeight: 200, overflowY: 'auto',
                                }}>
                                  <div style={{ marginBottom: 4 }}>
                                    <span style={{ color: '#58a6ff' }}>Input:</span>
                                    <pre style={{ margin: '2px 0', fontSize: 9 }}>
                                      {Object.entries(step.args).map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join('\n')}
                                    </pre>
                                  </div>
                                  <div>
                                    <span style={{ color: '#3fb950' }}>Result:</span>
                                    <pre style={{ margin: '2px 0', fontSize: 9 }}>
                                      {JSON.stringify(step.result, null, 2)}
                                    </pre>
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {msg.warning && <div style={{ fontSize: 10, color: '#f0a500', marginTop: 4 }}>⚠ {msg.warning}</div>}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div style={{ color: '#484f58', fontSize: 11, padding: '6px 0' }}>
            {toolProgress ? (
              <div>
                <span style={{ color: '#58a6ff' }}>Calling {toolProgress.tool}</span>
                <span style={{ color: '#8b949e', marginLeft: 6 }}>with {Object.keys(toolProgress.args).length} param{Object.keys(toolProgress.args).length !== 1 ? 's' : ''}</span>
              </div>
            ) : (
              'Analyzing…'
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: '8px 12px', borderTop: '1px solid #21262d', display: 'flex', gap: 6 }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') send(input); }}
          placeholder="Ask about satellites, maneuvers, coverage…"
          disabled={loading}
          style={{
            flex: 1, background: '#161b22', border: '1px solid #30363d', borderRadius: 4,
            color: '#e6edf3', fontSize: 11, padding: '6px 8px', outline: 'none',
          }}
        />
        <button onClick={() => send(input)} disabled={loading || !input.trim()} style={{
          background: '#1f6feb', border: '1px solid #388bfd', borderRadius: 4,
          color: '#fff', fontSize: 11, padding: '6px 12px', cursor: 'pointer',
        }}>
          Send
        </button>
      </div>
    </div>
  );
}
