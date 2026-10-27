import { useEffect, useState } from 'react';
import './style.css';

const DEFAULT_URL = 'https://divvybikes.com/pricing';
const money = (value) => typeof value === 'number' && Number.isFinite(value) ? '$' + value.toFixed(2) : '—';

export default function App() {
  const [upload, setUpload] = useState(null);
  const [pricingUrl, setPricingUrl] = useState(DEFAULT_URL);
  const [scenario, setScenario] = useState('Run both acceptance cases');
  const [prompt, setPrompt] = useState('');
  const [loadingUpload, setLoadingUpload] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [apiReady, setApiReady] = useState(null);

  async function checkApi() {
    try {
      const response = await fetch('/api/health');
      const data = await response.json();
      setApiReady(Boolean(data.modelConfigured));
    } catch {
      setApiReady(false);
    }
  }

  useEffect(() => { void checkApi(); }, []);

  async function onFile(file) {
    if (!file) return;
    setError('');
    setResult(null);
    setUpload(null);
    setLoadingUpload(true);
    const form = new FormData();
    form.append('csv', file);
    try {
      const response = await fetch('/api/upload', { method: 'POST', body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Upload failed.');
      setUpload(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.');
    } finally {
      setLoadingUpload(false);
    }
  }

  async function runAgent() {
    if (!upload) {
      setError('Upload a trip CSV first.');
      return;
    }
    setError('');
    setRunning(true);
    setResult(null);
    try {
      const response = await fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ datasetId: upload.id, pricingUrl, scenario, prompt })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'The analysis could not be completed.');
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The analysis could not be completed.');
    } finally {
      setRunning(false);
      void checkApi();
    }
  }

  const reports = result?.reports || (result?.report ? [result.report] : []);
  return <main className="shell">
    <header className="topbar" aria-hidden="true"></header>
    <section className="hero"><h1 className="hero-prompt">Upload your trip data to get started!</h1></section>

    <section className="workbench">
      <div className="inputs-card">
        <div className="card-heading"><span className="step-number">01</span><div><h2>Set up your analysis</h2><p>Choose a trip file and the official fare page.</p></div></div>
        <label className="field-label" htmlFor="trip-file">TRIP DATA · CSV</label>
        <label className={'upload-box ' + (upload ? 'has-file' : '')} htmlFor="trip-file">
          <input id="trip-file" type="file" accept=".csv,text/csv" onChange={e => void onFile(e.target.files?.[0])}/>
          <span className="upload-icon">{upload ? '✓' : '↑'}</span>
          <span className="upload-copy">
            <strong>{loadingUpload ? 'Reading your file…' : upload?.filename ?? 'Choose a CSV file'}</strong>
            <small>{upload ? upload.rowCount.toLocaleString() + ' trip rows · ' + upload.headers.slice(0, 4).join(', ') + (upload.headers.length > 4 ? ', …' : '') : 'Click to browse · max 80 MB'}</small>
          </span>
          {upload && <span className="file-check">READY</span>}
        </label>
        <label className="field-label" htmlFor="pricing-url">OFFICIAL PRICING PAGE</label>
        <div className="url-input"><span className="link-icon">↗</span><input id="pricing-url" value={pricingUrl} onChange={e => setPricingUrl(e.target.value)} placeholder="https://…"/></div>
        <div className="field-row">
          <div className="field grow">
            <label className="field-label" htmlFor="scenario">SCENARIO</label>
            <select id="scenario" value={scenario} onChange={e => setScenario(e.target.value)}>
              <option>Run both acceptance cases</option>
              <option>Frequent / longer rides</option>
              <option>Occasional / short rides</option>
            </select>
          </div>
          <div className="field grow">
            <label className="field-label" htmlFor="notes">EXTRA CONTEXT <span className="optional">OPTIONAL</span></label>
            <input id="notes" value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="e.g. classic bikes only"/>
          </div>
        </div>
        {apiReady === false && <div className="setup-note"><span>i</span><div><strong>Ollama rationale unavailable</strong><p>Cost calculations still run from the uploaded trips and captured pricing. Start the configured Ollama model to have it phrase the concise rationale.</p></div></div>}
        <button className="run-button" onClick={() => void runAgent()} disabled={running || loadingUpload || !upload}>
          <span>{running ? 'AGENT AT WORK' : 'RUN ANALYSIS'}</span><span className="button-arrow">{running ? <span className="spinner"/> : '↗'}</span>
        </button>
      </div>

      <div className="right-column">
        <section className="panel timeline-panel">
          <div className="panel-head"><div><span className="step-number">02</span><h2>Agent timeline</h2></div><span className="panel-meta">{result ? result.timeline.length + ' TOOL CALLS' : running ? 'WORKING…' : 'AWAITING RUN'}</span></div>
          {!result && !running && <div className="empty-state"><div className="empty-symbol">◎</div><p>Tool calls and observations<br/>will appear here.</p></div>}
          {running && <div className="loading-state"><span className="spinner dark"/><span>Checking the trip data and published pricing…</span></div>}
          {result?.timeline.map((step, i) => <article className="tool-step" key={step.step + '-' + i}>
            <div className="tool-rail"><span className="tool-dot">{String(step.step).padStart(2, '0')}</span>{i < result.timeline.length - 1 && <span className="rail-line"/>}</div>
            <div className="tool-body">
              <div className="tool-title"><strong>{step.tool}</strong><span className={step.observation.success ? '' : 'tool-error'}>{step.observation.success ? 'SUCCESS' : 'ERROR'}</span></div>
              <code className="tool-input">{JSON.stringify(step.input)}</code>
              {step.observation.error ? <p className="tool-error">{step.observation.error}</p> : <pre>{JSON.stringify(step.observation.data, null, 2)}</pre>}
            </div>
          </article>)}
        </section>
        {result && <section className="panel evidence-panel">
          <div className="panel-head"><div><span className="step-number">03</span><h2>Saved evidence</h2></div><span className="panel-meta">SNAPSHOT</span></div>
          {result.snapshots?.length ? result.snapshots.map((s, i) => <div className="snapshot" key={i}>
            <a href={s.sourceUrl} target="_blank" rel="noreferrer">{s.sourceUrl} ↗</a>
            <span>Captured {s.accessedAt} (UTC)</span>
            <code>SHA-256 · {s.sha256}</code>
            <small>Saved to snapshots/{s.filename}</small>
          </div>) : <p className="muted">No pricing snapshot was saved during this run.</p>}
          <p className="evidence-count">Trip rows: {Number(result.rowCount || 0).toLocaleString()} · Valid durations: {Number(result.validTripCount || 0).toLocaleString()}</p>
        </section>}
      </div>
    </section>

    {error && <div className="error-banner" role="alert"><span>!</span>{error}</div>}
    {reports.length > 0 && <section className="results">
      {reports.map((report, reportIndex) => <section className="scenario-result" key={report.scenario}>
        <div className="results-title">
          <div><div className="eyebrow"><span className="eyebrow-line"/> THE COMPARISON · CASE {reportIndex + 1}</div><h2>{report.decision ? 'Your cost picture' : 'Analysis incomplete'}</h2></div>
          <span className="scenario-chip">{report.scenario}</span>
        </div>
        {report.decision && <div className="decision-banner"><div><span className="decision-label">RECOMMENDATION</span><strong>{report.decision}</strong></div><div className="decision-icon">↗</div></div>}
        <div className="cost-grid">
          <div className="cost-card pay"><span>PAY PER USE · 4 WEEKS</span><strong>{money(report.costBreakdown?.payPerUse)}</strong><small>Includes modeled unlock and minute charges</small></div>
          <div className="cost-card member"><span>MEMBERSHIP · MONTH EQUIVALENT</span><strong>{money(report.costBreakdown?.membership)}</strong><small>{money(report.costBreakdown?.membershipFee)} fee plus residual charges</small></div>
          <div className="cost-card"><span>RESIDUAL CHARGES</span><strong>{money(report.costBreakdown?.residualCharges)}</strong><small>Modeled member overages</small></div>
          <div className="cost-card"><span>BREAK-EVEN POINT</span><strong>{report.costBreakdown?.breakEvenRides ?? '—'} rides</strong><small>{report.costBreakdown?.breakEvenMinutes ?? '—'} ride minutes</small></div>
        </div>
        <div className="results-grid">
          <section className="result-card rationale"><h3>Why this plan</h3><p>{report.rationale || 'No rationale returned.'}</p><div className="stop-reason"><span>STOP REASON</span>{report.stopReason || 'Analysis complete'}</div></section>
          <section className="result-card weekly"><h3>Weekly usage</h3>{report.weeklyTable?.length ? <table><thead><tr><th>WEEK</th><th>RIDES</th><th>AVG. MIN</th><th>PAY PER USE</th><th>MEMBERSHIP</th></tr></thead><tbody>{report.weeklyTable.map((w, i) => <tr key={i}><td>{w.week}</td><td>{w.rideCount}</td><td>{Number(w.averageDuration).toFixed(1)}</td><td>{money(w.spend)}</td><td>{money(w.membershipSpend)}</td></tr>)}</tbody></table> : <p className="muted">Weekly breakdown not available.</p>}</section>
        </div>
        <section className="result-card citations"><h3>Pricing citations</h3>{report.citations?.map((c, i) => <div className="citation" key={i}><a href={c.sourceUrl} target="_blank" rel="noreferrer">{c.sourceUrl}</a><span>Captured {c.accessedAt} (UTC) · SHA-256 {c.sha256}</span><blockquote>{c.text}</blockquote></div>)}</section>
        <section className="assumptions"><h3>Assumptions &amp; caveats</h3><ul>{(report.assumptions || []).map((x, i) => <li key={i}>{x}</li>)}</ul><p className="step-count">AGENT STOPPED AFTER {result.timeline.length} TOOL STEPS · TOTAL TIME {Number(result.elapsedSeconds || 0).toFixed(1)} SECONDS</p></section>
      </section>)}
    </section>}
  </main>;
}
