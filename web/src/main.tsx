import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type RecordNode = {
  id: string;
  kind: string;
  created: number;
  origin: string;
  body: Record<string, any>;
};
type Overview = {
  identity: { name: string; role: string };
  agents: RecordNode[];
  departments: RecordNode[];
  runs: RecordNode[];
  schedules: RecordNode[];
  tools: RecordNode[];
  mode: string;
  policy: Record<string, any>;
};
type Detail = {
  run: RecordNode;
  nodes: RecordNode[];
  edges: { src: string; dst: string; reason: string }[];
  metrics: Record<string, number>;
};
const pages = ["Operations", "Departments", "Schedules", "Governance"] as const;
const titles: Record<string, string> = {
  peer: "Respond to peer request",
  plan: "Allocate audit work",
  inspect: "Inspect versioned contract",
  draft: "Draft compatibility report",
  review: "Reproduce the contract check",
  correct: "Correct the report",
  verify: "Verify the revision",
  ticket: "Record sandbox ticket",
  meeting: "Convene departmental meeting",
};
const clock = (s: number) => new Date(s * 1000).toLocaleString();
const brand = (
  <span className="brand">
    <i aria-hidden="true">
      <b />
      <b />
      <b />
      <b />
    </i>
    Compartment
  </span>
);
function Status({ value }: { value: string }) {
  return (
    <span
      className={
        "status " +
        (value === "completed" || value === "accepted"
          ? "good"
          : /blocked|approval|failed/.test(value)
            ? "warn"
            : "")
      }
    >
      {value.replaceAll("_", " ")}
    </span>
  );
}
function App() {
  const [replacement, setReplacement] = useState(""),
    [confirmCancel, setConfirmCancel] = useState(false);
  const [token, setToken] = useState(""),
    [entry, setEntry] = useState(""),
    [data, setData] = useState<Overview>(),
    [detail, setDetail] = useState<Detail>(),
    [rid, setRid] = useState(""),
    [page, setPage] = useState<string>("Operations"),
    [tab, setTab] = useState("Tasks"),
    [err, setErr] = useState(""),
    [busy, setBusy] = useState(false),
    [selected, select] = useState(""),
    [artifact, setArtifact] = useState<any>(),
    [newRun, setNewRun] = useState(false),
    [objective, setObjective] = useState(
      "Audit the Inventory v2 integration against its versioned response contract.",
    ),
    [interval, setIntervalValue] = useState(86400),
    [dept, setDept] = useState("planning"),
    [agentId, setAgent] = useState(""),
    [instructions, setInstructions] = useState(""),
    [available, setAvailable] = useState(true),
    [agentTools, setAgentTools] = useState<string[]>([]),
    [attendees, setAttendees] = useState<string[]>([
      "planning-rep",
      "quality-rep",
    ]),
    [policy, setPolicy] = useState(""),
    [showMeeting, setShowMeeting] = useState(false),
    [agenda, setAgenda] = useState("Review the current audit dependency.");
  const api = useCallback(
    async (path: string, method = "GET", body?: any) => {
      const res = await fetch("/api/v1/" + path, {
        method,
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({ detail: "Request failed" }));
        throw Error(
          typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
        );
      }
      return res;
    },
    [token],
  );
  const refresh = useCallback(async () => {
    const o: Overview = await (await api("overview")).json();
    setData(o);
    if (rid) {
      const d: Detail = await (await api("runs/" + rid)).json();
      setDetail(d);
    }
  }, [api, rid]);
  useEffect(() => {
    if (!token) return;
    let active = true;
    const tick = () =>
      refresh().catch((e) => {
        if (active) setErr(e.message);
      });
    tick();
    const id = window.setInterval(tick, 2500);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [token, refresh]);
  async function act(fn: () => Promise<any>) {
    if (busy) return;
    setBusy(true);
    setErr("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function openRun(id: string) {
    setDetail(undefined);
    setRid(id);
    setTab("Tasks");
    select("");
    setArtifact(undefined);
    setConfirmCancel(false);
  }
  function inspect(n: RecordNode) {
    select(n.id);
    setArtifact(undefined);
  }
  useEffect(() => {
    const node = detail?.nodes.find((n) => n.id === selected);
    if (!node || node.kind !== "evidence") return;
    let active = true;
    api("evidence/" + node.id)
      .then((r) => r.json())
      .then((v) => {
        if (active) setArtifact(v);
      })
      .catch((e) => {
        if (active) setErr(e.message);
      });
    return () => {
      active = false;
    };
  }, [api, selected, rid, detail?.nodes.find((n) => n.id === selected)?.kind]);
  const button = (label: string, fn: () => Promise<any>, style = "") => (
    <button disabled={busy} className={style} onClick={() => act(fn)}>
      {label}
    </button>
  );
  if (!data)
    return (
      <main className="login">
        {brand}
        <h1>Operator access</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setErr("");
            setToken(entry.trim());
            if (token === entry.trim())
              refresh().catch((e) => setErr(e.message));
          }}
        >
          <label>
            Operator token
            <input
              type="password"
              autoComplete="off"
              required
              value={entry}
              onChange={(e) => setEntry(e.target.value)}
            />
          </label>
          <button className="primary">Open console</button>
        </form>
        {err && <p role="alert">{err}</p>}
      </main>
    );
  const tasks = detail?.nodes.filter((n) => n.kind === "task") ?? [],
    issues =
      detail?.nodes.filter(
        (n) => n.kind === "pushback" && n.body.status === "open",
      ) ?? [],
    isEditor = data.identity.role !== "viewer";
  const current = detail?.nodes.find((n) => n.id === selected),
    find = (id: string) => detail?.nodes.find((n) => n.id === id);
  const label = (n: RecordNode) =>
    n.body.statement ||
    n.body.name ||
    titles[n.body.step] ||
    n.body.type ||
    n.body.category ||
    n.body.verdict ||
    n.kind.replace("_", " ");
  const groups: Record<string, string[]> = {
    Tasks: ["task"],
    Meetings: ["meeting", "meeting_event"],
    Handoffs: ["request", "escalation"],
    Evidence: ["evidence", "claim", "execution", "acceptance"],
    Decisions: ["requirement", "pushback", "decision", "approval", "intent"],
    Lineage: [],
  };
  return (
    <div className="app">
      <aside>
        {brand}
        <nav>
          {pages.map((p, i) => (
            <button
              key={p}
              aria-current={page === p ? "page" : undefined}
              onClick={() => {
                setPage(p);
                setErr("");
              }}
            >
              <span aria-hidden="true">{["▤", "▦", "◷", "⌘"][i]}</span>
              {p}
            </button>
          ))}
        </nav>
        <footer>
          <b>{data.identity.name}</b>
          <small>
            {data.identity.role} · {data.mode} model
          </small>
          <button
            onClick={() => {
              setToken("");
              setEntry("");
              setData(undefined);
              openRun("");
            }}
          >
            Sign out
          </button>
        </footer>
      </aside>
      <main>
        <header>
          <div className="crumb">
            Workspace <span>/</span> {page}
          </div>
          <div className="service">
            <i /> Control plane online
          </div>
        </header>
        {err && (
          <div role="alert" className="error">
            {err}
            <button onClick={() => setErr("")}>Dismiss</button>
          </div>
        )}
        {page === "Operations" && (
          <>
            <div className="heading">
              <div>
                <h1>{rid ? "Operation detail" : "Operations"}</h1>
                <p>
                  {rid
                    ? detail?.run.body.objective
                    : "Coordinate assignments, review decisions, and inspect execution evidence."}
                </p>
              </div>
              {rid ? (
                <button onClick={() => openRun("")}>All operations</button>
              ) : (
                isEditor && (
                  <button
                    className="primary"
                    onClick={() => setNewRun(!newRun)}
                  >
                    ＋ New audit
                  </button>
                )
              )}
            </div>
            {newRun && !rid && (
              <form
                className="panel form"
                onSubmit={(e) => {
                  e.preventDefault();
                  act(async () => {
                    const r = await (
                      await api("runs", "POST", { objective })
                    ).json();
                    setNewRun(false);
                    openRun(r.id);
                  });
                }}
              >
                <h2>Integration change audit</h2>
                <label>
                  Operation objective
                  <textarea
                    required
                    maxLength={2000}
                    value={objective}
                    onChange={(e) => setObjective(e.target.value)}
                  />
                </label>
                <p>
                  Inspect the Inventory v2 sandbox, review the ticket conflict,
                  and verify the corrected report.
                </p>
                <button disabled={busy} className="primary">
                  Start audit
                </button>
              </form>
            )}
            {!rid && (
              <>
                <div className="stats">
                  {[
                    ["Departments", data.departments.length],
                    ["Configured agents", data.agents.length],
                    [
                      "Active operations",
                      data.runs.filter((r) => r.body.status === "active")
                        .length,
                    ],
                    ["Worker slots", data.policy.workers],
                  ].map(([l, v]) => (
                    <div key={l}>
                      <small>{l}</small>
                      <strong>{v}</strong>
                    </div>
                  ))}
                </div>
                <section className="panel">
                  <h2>Operation history</h2>
                  {data.runs.length === 0 ? (
                    <div className="empty">
                      <h3>No operations yet</h3>
                      <p>
                        Start an integration change audit to populate the task
                        graph.
                      </p>
                    </div>
                  ) : (
                    [...data.runs].reverse().map((r) => (
                      <button
                        className="row"
                        key={r.id}
                        onClick={() => openRun(r.id)}
                      >
                        <span>
                          <b>{r.body.objective}</b>
                          <small>{clock(r.created)}</small>
                        </span>
                        <Status value={r.body.status} />
                      </button>
                    ))
                  )}
                </section>
              </>
            )}
            {rid && detail && (
              <>
                <div className="runbar">
                  <Status value={detail.run.body.status} />
                  <code>{rid.slice(0, 8)}</code>
                  {isEditor &&
                    ["active", "paused"].includes(detail.run.body.status) &&
                    button(
                      detail.run.body.status === "paused" ? "Resume" : "Pause",
                      () =>
                        api("runs/" + rid + "/intervene", "POST", {
                          command:
                            detail.run.body.status === "paused"
                              ? "resume"
                              : "pause",
                        }),
                    )}
                  {isEditor &&
                    detail.run.body.status === "active" &&
                    button("Checkpoint", () =>
                      api("runs/" + rid + "/intervene", "POST", {
                        command: "checkpoint",
                      }),
                    )}
                  {isEditor &&
                    ["active", "paused"].includes(detail.run.body.status) &&
                    (confirmCancel ? (
                      button(
                        "Confirm cancellation",
                        async () => {
                          await api("runs/" + rid + "/intervene", "POST", {
                            command: "cancel",
                          });
                          setConfirmCancel(false);
                        },
                        "danger",
                      )
                    ) : (
                      <button onClick={() => setConfirmCancel(true)}>
                        Cancel run
                      </button>
                    ))}
                  {isEditor &&
                    detail.run.body.status === "awaiting acceptance" &&
                    button(
                      "Accept reviewed audit",
                      () => api("runs/" + rid + "/accept", "POST"),
                      "primary",
                    )}
                  {detail.run.body.status === "accepted" &&
                    button(
                      "Download evidence",
                      async () => {
                        const url = URL.createObjectURL(
                          await (await api("runs/" + rid + "/bundle")).blob(),
                        );
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = "compartment-" + rid + ".zip";
                        a.click();
                        setTimeout(() => URL.revokeObjectURL(url), 1000);
                      },
                      "primary",
                    )}
                </div>
                {issues.map((n) => (
                  <section className="issue" key={n.id}>
                    <small>Pushback · {n.body.severity}</small>
                    <h2>{n.body.question}</h2>
                    {n.body.quotes?.map((q: string) => (
                      <blockquote key={q}>{q}</blockquote>
                    ))}
                    {isEditor &&
                      n.body.alternatives?.map((c: string) => (
                        <React.Fragment key={c}>
                          {button(
                            (
                              {
                                request_ticket: "Request ticket approval",
                                omit_ticket: "Omit ticket",
                                use_audit_scope: "Use audit scope",
                                cancel_operation: "Cancel operation",
                                recheck_policy: "Recheck policy",
                                drop_handoff: "Drop handoff",
                              } as Record<string, string>
                            )[c],
                            () =>
                              api("pushback/" + n.id + "/resolve", "POST", {
                                choice: c,
                              }),
                          )}
                        </React.Fragment>
                      ))}
                  </section>
                ))}
                {tasks
                  .filter((t) => t.body.state === "pending approval")
                  .map((t) => (
                    <section className="issue" key={t.id}>
                      <small>Action approval</small>
                      <h2>{t.body.action.parameters.title}</h2>
                      <p>
                        Open one ticket in {t.body.action.target} for this
                        operation.
                      </p>
                      {isEditor &&
                        button("Approve exact ticket", () =>
                          api("approvals/" + t.id, "POST", t.body.action),
                        )}
                    </section>
                  ))}
                <div className="metricline">
                  <span>
                    {detail.metrics.completed}/{detail.metrics.tasks} tasks
                    completed
                  </span>
                  <span>{detail.metrics.open_conflicts} open conflicts</span>
                  <span>
                    {detail.metrics.retries}{" "}
                    {detail.metrics.retries === 1 ? "retry" : "retries"}
                  </span>
                  <span>{detail.metrics.reserved_microusd} µUSD reserved</span>
                </div>
                <div className="tabs">
                  {Object.keys(groups).map((k) => (
                    <button
                      key={k}
                      aria-selected={k === tab}
                      onClick={() => {
                        setTab(k);
                        select("");
                      }}
                    >
                      {k}
                    </button>
                  ))}
                </div>
                <section className="panel">
                  <h2>{tab}</h2>
                  {tab === "Meetings" &&
                    isEditor &&
                    detail.run.body.status === "active" && (
                      <>
                        <button onClick={() => setShowMeeting(!showMeeting)}>
                          Convene meeting
                        </button>
                        {showMeeting && (
                          <>
                            <input
                              value={agenda}
                              aria-label="Meeting agenda"
                              onChange={(e) => setAgenda(e.target.value)}
                            />
                            <label>
                              Meeting participants
                              <select
                                multiple
                                size={7}
                                value={attendees}
                                onChange={(e) =>
                                  setAttendees(
                                    Array.from(
                                      e.target.selectedOptions,
                                      (o) => o.value,
                                    ),
                                  )
                                }
                              >
                                {data.departments.map((d) => (
                                  <optgroup key={d.id} label={d.body.name}>
                                    {data.agents
                                      .filter((a) => a.body.department === d.id)
                                      .map((a) => (
                                        <option key={a.id} value={a.id}>
                                          {a.body.title}
                                        </option>
                                      ))}
                                  </optgroup>
                                ))}
                              </select>
                            </label>
                            {button("Invite participants", async () => {
                              await api("runs/" + rid + "/meetings", "POST", {
                                agenda,
                                participants: attendees,
                              });
                              setShowMeeting(false);
                            })}
                          </>
                        )}
                      </>
                    )}
                  {tab === "Lineage"
                    ? detail.edges.map((e) => (
                        <div className="edge" key={JSON.stringify(e)}>
                          <button onClick={() => inspect(find(e.src)!)}>
                            {label(find(e.src)!)}
                          </button>
                          <em>{e.reason} →</em>
                          <button onClick={() => inspect(find(e.dst)!)}>
                            {label(find(e.dst)!)}
                          </button>
                        </div>
                      ))
                    : detail.nodes
                        .filter((n) => groups[tab].includes(n.kind))
                        .map((n) => (
                          <button
                            className={
                              "row " + (n.id === selected ? "selected" : "")
                            }
                            key={n.id}
                            onClick={() => inspect(n)}
                          >
                            <span>
                              <b>{label(n)}</b>
                              <small>
                                {n.body.owner || n.origin} · {clock(n.created)}
                              </small>
                            </span>
                            {n.body.state || n.body.status ? (
                              <Status value={n.body.state || n.body.status} />
                            ) : (
                              <code>{n.id.slice(0, 8)} ↗</code>
                            )}
                          </button>
                        ))}
                </section>
                {current && (
                  <section className="panel inspect">
                    <h2>{label(current)}</h2>
                    <pre>
                      {current.kind === "evidence" && !artifact
                        ? "Loading evidence…"
                        : JSON.stringify(artifact ?? current.body, null, 2)}
                    </pre>
                    {detail.edges
                      .filter((e) => e.src === selected || e.dst === selected)
                      .map((e) => {
                        const other = find(e.src === selected ? e.dst : e.src);
                        return (
                          other && (
                            <button
                              key={JSON.stringify(e)}
                              onClick={() => inspect(other)}
                            >
                              {e.reason} · {label(other)}
                            </button>
                          )
                        );
                      })}
                    {current.kind === "task" &&
                      isEditor &&
                      ["failed", "blocked", "queued", "waiting"].includes(
                        current.body.state,
                      ) &&
                      !current.body.intent && (
                        <div className="intervene">
                          {button("Retry task", () =>
                            api("runs/" + rid + "/intervene", "POST", {
                              command: "retry",
                              task: current.id,
                            }),
                          )}
                          <select
                            aria-label="Replacement agent"
                            value={replacement}
                            onChange={(e) => setReplacement(e.target.value)}
                          >
                            <option value="">Select replacement</option>
                            {data.agents
                              .filter(
                                (a) =>
                                  a.body.department ===
                                  data.agents.find(
                                    (a) => a.id === current.body.owner,
                                  )?.body.department,
                              )
                              .map((a) => (
                                <option key={a.id} value={a.id}>
                                  {a.body.title}
                                </option>
                              ))}
                          </select>
                          {replacement &&
                            button("Reassign", () =>
                              api("runs/" + rid + "/intervene", "POST", {
                                command: "reassign",
                                task: current.id,
                                agent: replacement,
                              }),
                            )}
                        </div>
                      )}
                    {current.kind === "task" &&
                      current.body.intent &&
                      current.body.state === "blocked" &&
                      isEditor &&
                      button("Reconcile ticket", () =>
                        api("tasks/" + current.id + "/reconcile", "POST"),
                      )}
                  </section>
                )}
              </>
            )}
          </>
        )}
        {page === "Departments" && (
          <>
            <h1>Departments</h1>
            <div className="split">
              <section className="panel">
                <h2>Organization</h2>
                {data.departments.map((d) => (
                  <button
                    className={"row " + (dept === d.id ? "selected" : "")}
                    key={d.id}
                    onClick={() => {
                      setDept(d.id);
                      setAgent("");
                    }}
                  >
                    <b>{d.body.name}</b>
                    <small>5 agents</small>
                  </button>
                ))}
              </section>
              <section className="panel">
                <h2>
                  {data.departments.find((d) => d.id === dept)?.body.name}
                </h2>
                <p>
                  {data.departments.find((d) => d.id === dept)?.body.mission}
                </p>
                {data.agents
                  .filter((a) => a.body.department === dept)
                  .map((a) => (
                    <button
                      className="row"
                      key={a.id}
                      onClick={() => {
                        setAgent(a.id);
                        setInstructions(a.body.instructions);
                        setAvailable(a.body.available);
                        setAgentTools(a.body.tools);
                      }}
                    >
                      <span>
                        <b>{a.body.title}</b>
                        <small>{a.id}</small>
                      </span>
                      <Status
                        value={a.body.available ? "available" : "absent"}
                      />
                    </button>
                  ))}
              </section>
            </div>
            {agentId && (
              <section className="panel form">
                <h2>{agentId}</h2>
                <label>
                  Role instructions
                  <textarea
                    value={instructions}
                    onChange={(e) => setInstructions(e.target.value)}
                  />
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={available}
                    onChange={(e) => setAvailable(e.target.checked)}
                  />{" "}
                  Available
                </label>
                <fieldset>
                  <legend>Permitted tools</legend>
                  {data.tools.map((t) => (
                    <label key={t.id}>
                      <input
                        type="checkbox"
                        disabled={data.identity.role !== "admin"}
                        checked={agentTools.includes(t.body.name)}
                        onChange={(e) =>
                          setAgentTools(
                            e.target.checked
                              ? [...agentTools, t.body.name]
                              : agentTools.filter((n) => n !== t.body.name),
                          )
                        }
                      />{" "}
                      {t.body.name}
                    </label>
                  ))}
                </fieldset>
                {data.identity.role === "admin" &&
                  button("Save identity", () =>
                    api("agents/" + agentId, "PUT", {
                      instructions,
                      available,
                      tools: agentTools,
                    }),
                  )}
              </section>
            )}
          </>
        )}
        {page === "Schedules" && (
          <>
            <h1>Schedules</h1>
            <section className="panel form">
              <h2>Recurring integration audit</h2>
              <label>
                Interval in seconds
                <input
                  type="number"
                  min={60}
                  value={interval}
                  onChange={(e) => setIntervalValue(Number(e.target.value))}
                />
              </label>
              {isEditor &&
                button(
                  "Schedule audit",
                  () =>
                    api("schedules", "POST", {
                      interval,
                      due: Date.now() / 1000 + interval,
                    }),
                  "primary",
                )}
            </section>
            <section className="panel">
              <h2>Scheduled operations</h2>
              {data.schedules.length === 0 ? (
                <p>No recurring work scheduled.</p>
              ) : (
                data.schedules.map((s) => (
                  <div className="row" key={s.id}>
                    <b>{s.body.type}</b>
                    <span>
                      {s.body.enabled
                        ? "Next due " + clock(s.body.due)
                        : "Paused"}
                    </span>
                    {isEditor &&
                      button(
                        s.body.enabled ? "Pause schedule" : "Resume schedule",
                        () =>
                          api("schedules/" + s.id, "PATCH", {
                            enabled: !s.body.enabled,
                          }),
                      )}
                  </div>
                ))
              )}
            </section>
          </>
        )}
        {page === "Governance" && (
          <>
            <h1>Governance</h1>
            <section className="panel form">
              <h2>Execution policy</h2>
              <pre>{JSON.stringify(data.policy, null, 2)}</pre>
              {data.identity.role === "admin" && (
                <>
                  <label>
                    Policy changes
                    <textarea
                      placeholder="Enter a JSON policy update"
                      value={policy}
                      onChange={(e) => setPolicy(e.target.value)}
                    />
                  </label>
                  {button("Apply policy", () =>
                    api("policy", "PUT", {
                      ...data.policy,
                      ...JSON.parse(policy),
                    }),
                  )}
                  {button(
                    data.policy.stopped
                      ? "Clear emergency stop"
                      : "Emergency stop",
                    () =>
                      api("policy", "PUT", {
                        ...data.policy,
                        stopped: !data.policy.stopped,
                      }),
                    "danger",
                  )}
                </>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
