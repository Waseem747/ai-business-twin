import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  Braces,
  Check,
  CheckCircle2,
  ChevronDown,
  ClipboardCheck,
  Code2,
  Download,
  FileCode2,
  FileSpreadsheet,
  FlaskConical,
  GitBranch,
  Layers,
  Play,
  Plus,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import { canApprove, canEditLogic, useAuth } from "../lib/auth";
import { dateTime, money, number, relativeTime, statusTone, titleCase } from "../lib/format";
import { useApi, useInterval } from "../lib/useApi";
import { useToast } from "../components/Toast";
import {
  Badge,
  Button,
  Card,
  CopyButton,
  DefinitionList,
  EmptyState,
  ErrorState,
  JsonBlock,
  LoadingBlock,
  Modal,
  PageHeader,
  Panel,
  StatusBadge,
  Tabs,
} from "../components/ui";
import type { BusinessRule, ExcelConversion } from "../lib/types";

const RULE_TEMPLATE = `def calculate(inputs):
    """Describe the business rule and its guard rails."""
    revenue = inputs.get("revenue")
    cost = inputs.get("cost_of_goods_sold")

    if revenue is None or cost is None:
        return {"result": None}

    if revenue <= 0:
        return {"result": None}

    return {"result": round((revenue - cost) / revenue * 100, 2)}
`;

export function LogicStudioPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState("rules");

  return (
    <div className="page page-wide">
      <PageHeader
        eyebrow="Developer Studio · Deterministic business logic"
        title="Business Logic Studio"
        description="Author, test, version and approve the calculations that define how this business operates — including Excel workbook conversion."
        meta={
          <div className="header-meta-row">
            <Badge tone="success" dot>Sandboxed execution</Badge>
            <Badge tone="info" dot>Versioned & approved</Badge>
            <span className="meta-divider" />
            <span className="meta-text">The LLM never performs business arithmetic</span>
          </div>
        }
      />
      <Tabs
        tabs={[
          { key: "rules", label: "Business rules" },
          { key: "excel", label: "Excel logic conversion" },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "rules" ? <RulesStudio canEdit={canEditLogic(user)} canApprove={canApprove(user)} /> : <ExcelStudio canApprove={canApprove(user)} />}
    </div>
  );
}

function RulesStudio({ canEdit, canApprove }: { canEdit: boolean; canApprove: boolean }) {
  const toast = useToast();
  const rules = useApi(api.rules, []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BusinessRule | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [consoleInput, setConsoleInput] = useState("{}");
  const [consoleOutput, setConsoleOutput] = useState<any>(null);
  const [consoleError, setConsoleError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [newRule, setNewRule] = useState({ key: "custom_rule", name: "Custom business rule", description: "", category: "custom", code: RULE_TEMPLATE, tests: "[]" });
  const [creating, setCreating] = useState(false);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draft, setDraft] = useState({ code: "", tests: "[]", changelog: "" });
  const [savingDraft, setSavingDraft] = useState(false);
  const [activating, setActivating] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedId && rules.data?.length) setSelectedId(rules.data[0].id);
  }, [rules.data, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    api
      .rule(selectedId)
      .then((result) => {
        if (!active) return;
        setDetail(result);
        const sample: Record<string, any> = {};
        Object.keys(result.input_schema || {}).forEach((key) => {
          const test = result.tests?.[0]?.inputs?.[key];
          sample[key] = test ?? 0;
        });
        if (!Object.keys(sample).length) {
          const tests = result.tests?.[0]?.inputs;
          if (tests) Object.assign(sample, tests);
        }
        setConsoleInput(JSON.stringify(sample, null, 2));
      })
      .catch((exc) => toast.push(exc?.message || "Unable to load rule", "danger"))
      .finally(() => active && setDetailLoading(false));
    return () => {
      active = false;
    };
  }, [selectedId, rules.data]);

  const grouped = useMemo(() => {
    const groups: Record<string, BusinessRule[]> = {};
    (rules.data || []).forEach((rule) => {
      const source = rule.source;
      groups[source] = groups[source] || [];
      groups[source].push(rule);
    });
    return groups;
  }, [rules.data]);

  async function runConsole() {
    if (!detail) return;
    setTesting(true);
    setConsoleError(null);
    setConsoleOutput(null);
    try {
      const parsed = JSON.parse(consoleInput);
      const result = await api.testRule(detail.id, { inputs: parsed });
      setConsoleOutput(result);
      if (!result.ok) setConsoleError(result.error || "Execution failed");
    } catch (exc: any) {
      setConsoleError(exc?.message || "Invalid JSON input");
    } finally {
      setTesting(false);
    }
  }

  async function createRule() {
    setCreating(true);
    try {
      const tests = JSON.parse(newRule.tests || "[]");
      const response = await api.createRule({
        key: newRule.key,
        name: newRule.name,
        description: newRule.description,
        category: newRule.category,
        code: newRule.code,
        input_schema: { revenue: "number", cost_of_goods_sold: "number" },
        output_schema: { result: "number" },
        tests,
      });
      toast.push("Draft created. Approval is required before activation.", "success");
      setCreateOpen(false);
      rules.refresh();
      setSelectedId(response.rule.id);
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to create rule", "danger");
    } finally {
      setCreating(false);
    }
  }

  async function saveDraft() {
    if (!detail) return;
    setSavingDraft(true);
    try {
      const tests = JSON.parse(draft.tests || "[]");
      await api.createDraft(detail.id, { code: draft.code, tests, changelog: draft.changelog });
      toast.push("Draft saved. Run tests and activate the version when ready.", "success");
      setDraftOpen(false);
      setSelectedId(detail.id);
      rules.refresh();
      setDetail(await api.rule(detail.id));
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to save draft", "danger");
    } finally {
      setSavingDraft(false);
    }
  }

  async function activate(versionId: string) {
    if (!detail) return;
    setActivating(versionId);
    try {
      await api.activateRule(detail.id, versionId);
      toast.push("Rule version activated after passing tests.", "success");
      setDetail(await api.rule(detail.id));
      rules.refresh();
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to activate rule", "danger");
    } finally {
      setActivating(null);
    }
  }

  return (
    <div className="split-layout logic-layout">
      <aside className="logic-list-column">
        <Card className="logic-list-card">
          <div className="logic-list-head">
            <div><span className="eyebrow">Registry</span><h2>Calculation catalogue</h2></div>
            {canEdit && <Button size="sm" variant="primary" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>New rule</Button>}
          </div>
          <div className="rule-counts">
            <span><strong>{rules.data?.length || 0}</strong> rules</span>
            <span><strong>{rules.data?.filter((rule) => rule.status === "ACTIVE").length || 0}</strong> active</span>
            <span><strong>{rules.data?.filter((rule) => rule.source === "EXCEL").length || 0}</strong> Excel</span>
          </div>
          {rules.loading && !rules.data ? <LoadingBlock lines={8} /> : rules.error ? <ErrorState message={rules.error} onRetry={rules.refresh} /> : (
            <div className="rule-list">
              {Object.entries(grouped).map(([source, list]) => (
                <div key={source} className="rule-group">
                  <div className="rule-group-label">{source}</div>
                  {list.map((rule) => (
                    <button
                      key={rule.id}
                      className={`rule-list-item ${selectedId === rule.id ? "rule-list-item-active" : ""}`}
                      onClick={() => setSelectedId(rule.id)}
                    >
                      <div className="rule-list-top">
                        <StatusBadge status={rule.status} size="sm" />
                        <span className="rule-version">v{rule.version}</span>
                      </div>
                      <strong>{rule.name}</strong>
                      <span>{rule.category} · {rule.execution_frequency.toLowerCase()}</span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          )}
        </Card>
      </aside>

      <section className="logic-detail-column">
        {!detail ? (
          <Card className="detail-placeholder"><EmptyState title="Select a business rule" description="Inspect code, tests, versions and execution evidence." icon={<Code2 size={24} />} /></Card>
        ) : detailLoading && !detail ? <Card><LoadingBlock lines={10} /></Card> : (
          <div className="stack-lg">
            <Card className="rule-detail-head">
              <div>
                <div className="eyebrow">{detail.source} · {detail.category}</div>
                <h2>{detail.name}</h2>
                <p>{detail.description}</p>
              </div>
              <div className="rule-detail-actions">
                <StatusBadge status={detail.status} />
                <Badge tone="muted">v{detail.version}</Badge>
                {canEdit && (
                  <Button size="sm" icon={<GitBranch size={14} />} onClick={() => {
                    setDraft({ code: detail.code || "", tests: JSON.stringify(detail.tests || [], null, 2), changelog: "" });
                    setDraftOpen(true);
                  }}>New draft</Button>
                )}
              </div>
            </Card>

            <div className="rule-meta-grid">
              <Card className="mini-stat"><div className="mini-stat-icon"><Layers size={18} /></div><div><span>Execution frequency</span><strong>{titleCase(detail.execution_frequency)}</strong></div></Card>
              <Card className="mini-stat"><div className="mini-stat-icon"><ShieldCheck size={18} /></div><div><span>Approved by</span><strong>{detail.approved_by || "Pending"}</strong></div></Card>
              <Card className="mini-stat"><div className="mini-stat-icon"><Braces size={18} /></div><div><span>Inputs / outputs</span><strong>{Object.keys(detail.input_schema || {}).length} / {Object.keys(detail.output_schema || {}).length}</strong></div></Card>
              <Card className="mini-stat"><div className="mini-stat-icon"><Play size={18} /></div><div><span>Executions</span><strong>{detail.executions?.length || 0}</strong></div></Card>
            </div>

            <Panel
              title="Implementation"
              subtitle="Executed in a separate process with an AST allow-list, no imports and a wall-clock timeout"
              actions={<CopyButton value={detail.code || ""} label="Copy code" />}
              flush
            >
              <CodeViewer code={detail.code || ""} />
              <div className="schema-row">
                <div>
                  <span className="schema-label">Input schema</span>
                  <div className="chip-wrap">{Object.entries(detail.input_schema || {}).map(([key, type]) => <span key={key} className="chip">{key}: {String(type)}</span>)}</div>
                </div>
                <div>
                  <span className="schema-label">Output schema</span>
                  <div className="chip-wrap">{Object.entries(detail.output_schema || {}).map(([key, type]) => <span key={key} className="chip chip-teal">{key}: {String(type)}</span>)}</div>
                </div>
              </div>
            </Panel>

            <div className="grid-2">
              <Panel title="Rule console" subtitle="Test arbitrary inputs without activating the rule">
                <label className="field">
                  <span>Input JSON</span>
                  <textarea className="code-input" rows={9} value={consoleInput} onChange={(event) => setConsoleInput(event.target.value)} />
                </label>
                <div className="console-actions">
                  <Button variant="primary" size="sm" icon={<Play size={14} />} loading={testing} onClick={runConsole}>Execute in sandbox</Button>
                  <span className="console-hint">No writes to production state</span>
                </div>
                {consoleError && <div className="error-banner compact">{consoleError}</div>}
                {consoleOutput && (
                  <div className="console-result">
                    <div className="console-result-head"><span>Output</span><Badge tone={consoleOutput.ok ? "success" : "danger"}>{consoleOutput.ok ? "SUCCESS" : "FAILED"}</Badge><span className="mono">{number(consoleOutput.duration_ms, 0)} ms</span></div>
                    <JsonBlock value={consoleOutput.outputs || { error: consoleOutput.error }} maxHeight={220} />
                  </div>
                )}
              </Panel>

              <Panel title="Test suite" subtitle="Tests must pass before activation">
                <div className="test-list">
                  {(detail.tests || []).map((test: any, index: number) => {
                    const execution = detail.executions?.find((item) => item.inputs && JSON.stringify(item.inputs) === JSON.stringify(test.inputs));
                    const passed = execution?.status === "SUCCEEDED";
                    return (
                      <div key={index} className="test-row">
                        <div className="test-head">
                          {passed ? <CheckCircle2 size={15} className="positive" /> : <FlaskConical size={15} />}
                          <strong>{test.name || `Test ${index + 1}`}</strong>
                          <Badge tone={passed ? "success" : "muted"} className="badge-sm">{passed ? "Passing" : "Defined"}</Badge>
                        </div>
                        <JsonBlock value={test.inputs || {}} maxHeight={100} />
                      </div>
                    );
                  })}
                  {(detail.tests || []).length === 0 && <EmptyState title="No tests defined" description="Add tests before requesting activation." />}
                </div>
              </Panel>
            </div>

            <div className="grid-2">
              <Panel title="Version history" subtitle="Approval promotes a tested version to production" flush>
                <div className="version-list">
                  {(detail.versions || []).map((version) => (
                    <div key={version.id} className="version-row">
                      <div className="version-marker"><GitBranch size={15} /></div>
                      <div className="version-copy">
                        <div><strong>Version {version.version}</strong><StatusBadge status={version.status} size="sm" /></div>
                        <span>{version.changed_by} · {relativeTime(version.created_at)}</span>
                        <p>{version.changelog || "No changelog"}</p>
                      </div>
                      {canApprove && version.status !== "ACTIVE" && (
                        <Button size="sm" variant="success" icon={<Rocket size={14} />} loading={activating === version.id} onClick={() => activate(version.id)}>Activate</Button>
                      )}
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel title="Execution evidence" subtitle="Recent sandboxed executions" flush>
                <div className="execution-mini-list">
                  {(detail.executions || []).slice(0, 8).map((execution) => (
                    <div key={execution.id} className="execution-mini">
                      <StatusBadge status={execution.status} size="sm" />
                      <div><strong>{money(Object.values(execution.outputs || {})[0] as number, true)}</strong><span>{dateTime(execution.created_at)}</span></div>
                      <span className="mono">{number(execution.duration_ms, 0)} ms</span>
                      <Badge tone="muted" className="badge-sm">{execution.sandboxed ? "Sandbox" : "Formula"}</Badge>
                    </div>
                  ))}
                  {(detail.executions || []).length === 0 && <EmptyState title="No executions yet" />}
                </div>
              </Panel>
            </div>
          </div>
        )}
      </section>

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create business rule"
        subtitle="Drafts are not used in production until approved and activated."
        width="720px"
        footer={<><Button onClick={() => setCreateOpen(false)}>Cancel</Button><Button variant="primary" loading={creating} onClick={createRule}>Create draft</Button></>}
      >
        <div className="form-grid">
          <label className="field"><span>Rule key</span><input value={newRule.key} onChange={(event) => setNewRule({ ...newRule, key: event.target.value })} placeholder="gross_margin" /></label>
          <label className="field"><span>Category</span><input value={newRule.category} onChange={(event) => setNewRule({ ...newRule, category: event.target.value })} /></label>
          <label className="field span-2"><span>Name</span><input value={newRule.name} onChange={(event) => setNewRule({ ...newRule, name: event.target.value })} /></label>
          <label className="field span-2"><span>Description</span><input value={newRule.description} onChange={(event) => setNewRule({ ...newRule, description: event.target.value })} /></label>
          <label className="field span-2"><span>Python implementation</span><textarea className="code-input" rows={14} value={newRule.code} onChange={(event) => setNewRule({ ...newRule, code: event.target.value })} /></label>
          <label className="field span-2"><span>Tests (JSON array)</span><textarea className="code-input" rows={5} value={newRule.tests} onChange={(event) => setNewRule({ ...newRule, tests: event.target.value })} /></label>
        </div>
      </Modal>

      <Modal
        open={draftOpen}
        onClose={() => setDraftOpen(false)}
        title="Save new draft version"
        subtitle="Editing an active rule creates a new version. Production remains on the current approved version until activation."
        width="760px"
        footer={<><Button onClick={() => setDraftOpen(false)}>Cancel</Button><Button variant="primary" loading={savingDraft} onClick={saveDraft}>Save draft & run tests</Button></>}
      >
        <div className="form-grid">
          <label className="field span-2"><span>Code</span><textarea className="code-input" rows={16} value={draft.code} onChange={(event) => setDraft({ ...draft, code: event.target.value })} /></label>
          <label className="field span-2"><span>Tests (JSON)</span><textarea className="code-input" rows={6} value={draft.tests} onChange={(event) => setDraft({ ...draft, tests: event.target.value })} /></label>
          <label className="field span-2"><span>Changelog</span><input value={draft.changelog} onChange={(event) => setDraft({ ...draft, changelog: event.target.value })} placeholder="Why is this version changing?" /></label>
        </div>
      </Modal>
    </div>
  );
}

function CodeViewer({ code }: { code: string }) {
  const lines = code.split("\n");
  return (
    <div className="code-viewer">
      <div className="code-viewer-head">
        <div><span className="code-dot dot-red" /><span className="code-dot dot-amber" /><span className="code-dot dot-green" /></div>
        <span>business_rule.py</span>
        <CopyButton value={code} />
      </div>
      <div className="code-body">
        {lines.map((line, index) => (
          <div key={index} className="code-line">
            <span className="code-number">{index + 1}</span>
            <code>{line || " "}</code>
          </div>
        ))}
      </div>
    </div>
  );
}

function ExcelStudio({ canApprove }: { canApprove: boolean }) {
  const toast = useToast();
  const conversions = useApi(api.conversions, []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ExcelConversion | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [drag, setDrag] = useState(false);

  useEffect(() => {
    if (!selectedId && conversions.data?.length) setSelectedId(conversions.data[0].id);
  }, [conversions.data, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    api
      .conversion(selectedId)
      .then((result) => active && setDetail(result))
      .catch((exc) => toast.push(exc?.message || "Unable to load conversion", "danger"))
      .finally(() => active && setDetailLoading(false));
    return () => {
      active = false;
    };
  }, [selectedId, conversions.data]);

  useInterval(() => {
    if (detail && ["UPLOADED", "TRANSLATED", "INSPECTED"].includes(detail.status)) {
      conversions.refresh();
      api.conversion(detail.id).then(setDetail).catch(() => undefined);
    }
  }, detail && ["UPLOADED", "TRANSLATED", "INSPECTED"].includes(detail.status) ? 4000 : null);

  async function upload(file?: File | null) {
    if (!file) return;
    setUploading(true);
    try {
      const result = await api.uploadConversion(file);
      toast.push("Workbook uploaded. Inspection, translation and validation are running.", "success");
      conversions.refresh();
      setSelectedId(result.conversion.id);
    } catch (exc: any) {
      toast.push(exc?.message || "Upload failed", "danger");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function decide(approved: boolean) {
    if (!detail) return;
    setDeciding(true);
    try {
      const result = await api.approveConversion(detail.id, approved, approved ? "Validation passed; activate converted logic." : "Rejected by reviewer.");
      toast.push(result.message || "Decision recorded", approved ? "success" : "info");
      window.setTimeout(async () => {
        conversions.refresh();
        try {
          setDetail(await api.conversion(detail.id));
        } catch {
          /* ignore */
        }
      }, 3000);
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to record conversion decision", "danger");
    } finally {
      setDeciding(false);
    }
  }

  const validation = detail?.validation_summary;
  const validationPassed = Boolean(validation?.passed);

  return (
    <div className="excel-layout">
      <div className="excel-top-grid">
        <Card
          className={`upload-card ${drag ? "upload-card-active" : ""}`}
          as="section"
        >
          <input ref={inputRef} type="file" accept=".xlsx,.xlsm" hidden onChange={(event) => upload(event.target.files?.[0])} />
          <div
            className="upload-inner"
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => { event.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(event) => { event.preventDefault(); setDrag(false); upload(event.dataTransfer.files?.[0]); }}
          >
            <span className="upload-icon">{uploading ? <RefreshCw size={24} className="spin" /> : <UploadCloud size={24} />}</span>
            <div><strong>{uploading ? "Uploading workbook…" : "Upload an Excel model"}</strong><span>.xlsx or .xlsm · up to 25 MB · formulas, named ranges, cross-sheet dependencies</span></div>
            <Button size="sm" variant="primary" type="button">Choose file</Button>
          </div>
        </Card>
        <Card className="conversion-summary">
          <span className="eyebrow">Conversion engine</span>
          <div className="conversion-capabilities">
            <span><Check size={13} /> IF / IFERROR / IFS</span>
            <span><Check size={13} /> SUMIFS / COUNTIFS</span>
            <span><Check size={13} /> VLOOKUP / INDEX-MATCH</span>
            <span><Check size={13} /> Cross-sheet refs</span>
            <span><Check size={13} /> Named ranges</span>
            <span><Check size={13} /> Excel-engine comparison</span>
          </div>
          <p>Unsupported or ambiguous formulas are flagged for review, never guessed. Activation requires human approval.</p>
        </Card>
      </div>

      <div className="split-layout excel-split">
        <aside className="conversion-list-column">
          <Card className="logic-list-card">
            <div className="logic-list-head"><div><span className="eyebrow">Workbook runs</span><h2>Conversion history</h2></div><Button size="sm" icon={<RefreshCw size={14} />} onClick={conversions.refresh}>Refresh</Button></div>
            {conversions.loading && !conversions.data ? <LoadingBlock lines={7} /> : conversions.error ? <ErrorState message={conversions.error} onRetry={conversions.refresh} /> : (
              <div className="conversion-list">
                {(conversions.data || []).map((conversion) => (
                  <button key={conversion.id} className={`conversion-row ${selectedId === conversion.id ? "conversion-row-active" : ""}`} onClick={() => setSelectedId(conversion.id)}>
                    <div className="conversion-icon"><FileSpreadsheet size={17} /></div>
                    <div><strong>{conversion.filename}</strong><span>{conversion.formula_count} formulas · {relativeTime(conversion.created_at)}</span></div>
                    <StatusBadge status={conversion.status} size="sm" />
                  </button>
                ))}
                {(conversions.data || []).length === 0 && <EmptyState title="No workbooks converted" description="Upload a workbook to begin." />}
              </div>
            )}
          </Card>
        </aside>

        <section className="conversion-detail-column">
          {!detail ? <Card className="detail-placeholder"><EmptyState title="No conversion selected" description="Upload a workbook or select a previous conversion." icon={<FileSpreadsheet size={24} />} /></Card> : (
            <div className="stack-lg">
              <Card className="conversion-head">
                <div className="conversion-head-left">
                  <span className="conversion-file-icon"><FileSpreadsheet size={22} /></span>
                  <div><div className="eyebrow">{detail.status}</div><h2>{detail.filename}</h2><p>{detail.workbook_meta?.sheets?.length || 0} sheets · {detail.formula_count} formulas · {detail.workbook_meta?.named_ranges?.length || 0} named ranges</p></div>
                </div>
                <div className="conversion-head-actions">
                  <StatusBadge status={detail.status} />
                  {detail.report_path && <Button size="sm" icon={<Download size={14} />} onClick={() => api.downloadConversionReport(detail.id, "business_logic_document.md")}>Report</Button>}
                </div>
              </Card>

              {detailLoading && <Card><LoadingBlock lines={4} /></Card>}

              {validation && (
                <Card className={`validation-banner ${validationPassed ? "validation-pass" : "validation-fail"}`}>
                  <div className="validation-icon">{validationPassed ? <BadgeCheck size={26} /> : <AlertTriangle size={26} />}</div>
                  <div className="validation-copy">
                    <div><strong>{validationPassed ? "Validated against Excel calculation engine" : "Validation requires review"}</strong><Badge tone={validationPassed ? "success" : "danger"}>{validation.status}</Badge></div>
                    <p>{validation.message}</p>
                    <div className="validation-metrics">
                      <span>{validation.datasets?.length || 0} test datasets</span>
                      <span>{validation.comparisons?.length || 0} comparisons</span>
                      <span>{validation.mismatches?.length || 0} mismatches</span>
                      <span>Tolerance {validation.tolerance?.absolute} / {validation.tolerance?.relative}</span>
                      <span>{number(validation.duration_ms, 0)} ms</span>
                    </div>
                  </div>
                  {canApprove && detail.status === "AWAITING_APPROVAL" && (
                    <div className="validation-actions">
                      <Button variant="danger" size="sm" icon={<X size={14} />} loading={deciding} onClick={() => decide(false)}>Reject</Button>
                      <Button variant="success" size="sm" icon={<Rocket size={14} />} loading={deciding} onClick={() => decide(true)}>Approve & activate</Button>
                    </div>
                  )}
                </Card>
              )}

              <div className="conversion-tabbed">
                <Panel title="Validation datasets" subtitle="Independent Excel engine vs generated Python" flush>
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead><tr><th>Dataset</th><th>Description</th><th>Status</th><th>Comparisons</th><th>Failed</th></tr></thead>
                      <tbody>
                        {(validation?.datasets || []).map((dataset: any) => (
                          <tr key={dataset.name}>
                            <td><strong>{titleCase(dataset.name)}</strong></td>
                            <td className="cell-summary">{dataset.description}</td>
                            <td><Badge tone={dataset.status === "PASS" ? "success" : "danger"}>{dataset.status}</Badge></td>
                            <td>{dataset.passed + dataset.failed}</td>
                            <td className={dataset.failed ? "negative" : ""}>{dataset.failed}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {validation?.mismatches && validation.mismatches.length > 0 && (
                    <div className="mismatch-list">
                      {validation.mismatches.slice(0, 6).map((mismatch: any) => (
                        <div key={`${mismatch.dataset}-${mismatch.output}`} className="mismatch-row">
                          <Badge tone="danger">{mismatch.status}</Badge>
                          <span>{mismatch.label} · {mismatch.cell}</span>
                          <span>Excel {String(mismatch.excel_value)} → Python {String(mismatch.python_value)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </Panel>
              </div>

              <div className="grid-2">
                <Panel title="Workbook structure" subtitle="Sheets and dependency analysis">
                  <div className="sheet-list">
                    {(detail.workbook_meta?.sheets || []).map((sheet: any) => (
                      <div key={sheet.name} className="sheet-row">
                        <span className="sheet-icon"><Layers size={14} /></span>
                        <div><strong>{sheet.name}</strong><span>{sheet.dimensions} · {sheet.formula_count} formulas · {sheet.constant_count} constants</span></div>
                        {sheet.tables?.length > 0 && <Badge tone="info" className="badge-sm">Table</Badge>}
                        {sheet.pivots > 0 && <Badge tone="warning" className="badge-sm">Pivot</Badge>}
                      </div>
                    ))}
                  </div>
                  <div className="dependency-summary">
                    <DefinitionList items={[
                      { label: "Cross-sheet references", value: detail.workbook_meta?.dependency_summary?.cross_sheet_references ?? detail.workbook_meta?.dependency_summary?.cross_sheet_edges ?? 0 },
                      { label: "Circular references", value: <Badge tone={detail.workbook_meta?.dependency_summary?.cycles?.length ? "danger" : "success"}>{detail.workbook_meta?.dependency_summary?.cycles?.length || 0}</Badge> },
                      { label: "Blocked cells", value: detail.workbook_meta?.dependency_summary?.blocked?.length || 0 },
                      { label: "Named ranges", value: detail.workbook_meta?.named_ranges?.length || 0 },
                    ]} />
                  </div>
                </Panel>
                <Panel title="Inputs & outputs" subtitle="Cell-level lineage retained">
                  <div className="io-section">
                    <span className="schema-label">Converted inputs</span>
                    <div className="io-list">
                      {(detail.workbook_meta?.inputs || []).slice(0, 8).map((input: any) => (
                        <div key={input.alias} className="io-row"><span>{input.label}</span><code>{input.alias}</code><span className="io-cell">{input.cell}</span></div>
                      ))}
                    </div>
                  </div>
                  <div className="io-section">
                    <span className="schema-label">Translated outputs</span>
                    <div className="chip-wrap">
                      {(detail.workbook_meta?.outputs || []).map((output: any) => <span key={output.key} className="chip chip-teal">{output.label}</span>)}
                    </div>
                  </div>
                </Panel>
              </div>

              {detail.unsupported?.length > 0 && (
                <Panel title="Unsupported formulas" subtitle="Excluded from generated logic and flagged for human review" flush>
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead><tr><th>Cell</th><th>Function</th><th>Reason</th><th>Formula</th></tr></thead>
                      <tbody>
                        {detail.unsupported.map((item: any) => (
                          <tr key={item.cell}><td className="mono">{item.cell}</td><td><Badge tone="warning">{item.function || "unknown"}</Badge></td><td>{item.reason}</td><td className="mono cell-summary">{item.formula}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              )}

              <details className="raw-details">
                <summary><FileCode2 size={15} /> Generated Python logic ({detail.generated_code?.split("\n").length || 0} lines)</summary>
                <CodeViewer code={detail.generated_code || ""} />
              </details>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
