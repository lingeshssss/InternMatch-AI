"use client";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowUpRight,
  Search,
  Sparkles,
  ShieldCheck,
  Bookmark,
  LayoutGrid,
  BriefcaseBusiness,
  UserRound,
  Bell,
  SlidersHorizontal,
  MapPin,
  Clock3,
  Check,
  X,
  ChevronRight,
  FileText,
  RefreshCw,
  Moon,
  Sun,
  LogOut,
  ExternalLink,
  Bot,
  CircleHelp,
  GraduationCap,
  Upload,
} from "lucide-react";
import { Button, Modal } from "../components/ui";

// Same-origin API: the reverse proxy routes /api/* to FastAPI, so cookies stay first-party.
const API = "/api";
async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(API + path, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...options.headers },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: `Server unavailable (HTTP ${response.status})` }));
    throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  }
  return response.json();
}
type Requirement = {
  kind: string;
  mandatory: boolean;
  quote: string;
  student: string;
  result: "PASS" | "FAIL" | "UNKNOWN";
  explanation: string;
  source_url: string;
  verified_at: string;
  origin?: "model" | "scanner" | "manual";
};
type Eligibility = { status: string; requirements: Requirement[]; disclosures: string[]; verified_at: string };
type Fit = { score: number | null; explanation: string; components?: Record<string, number>; evidence?: Record<string, string> };
type Details = {
  opportunity_type?: string | null;
  internship_start?: string | null;
  internship_term?: string | null;
  compensation?: string | null;
  deadline?: string | null;
  extraction_status?: "pending" | "ready" | "failed";
  provenance?: { model?: string; quality?: { validator_version?: string; unreviewed_signals?: number } };
};
type Job = {
  id: string;
  company: string;
  title: string;
  location?: string;
  url: string;
  details: Details;
  retrieved_at: string;
  first_seen_at: string;
  eligibility: Eligibility;
  fit: Fit | null;
  saved: boolean;
  text?: string;
  content_hash?: string;
  status?: string;
  access_status?: string;
  extraction_error?: string;
  changed_since_saved?: boolean;
  evidence?: { id: string; quote: string; start: number; end: number; content_hash: string; source_url: string; retrieved_at: string }[];
};
type AppRecord = {
  id: string;
  job_id: string;
  title: string;
  company: string;
  url: string;
  stage: string;
  notes: string;
  application_date: string | null;
  resume_id: string | null;
  interview_dates: string[];
  follow_up: string | null;
  contacts: string;
};
type Notice = { id: string; data: Record<string, string>; read: boolean; created_at: string };
type Profile = Record<string, unknown>;
type Resume = {
  id: string;
  filename: string;
  confirmed: boolean;
  created_at: string;
  extraction: Profile;
  extraction_status: "pending" | "ready" | "failed";
  extraction_error: string | null;
  provenance: { model?: string; not_filled?: string[] } | null;
};
type SystemStatus = {
  ai?: { provider: string; ready: boolean; llm_model?: string; embedding_model?: string; error?: string | null; fallback?: string | null; note?: string };
  worker?: { running: boolean; last_heartbeat: string | null };
  tasks?: { kind: string; status: string; count: number }[];
  discovery_sources?: { greenhouse: string[]; lever: string[] };
  email?: boolean;
};
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const terms = (() => {
  const year = new Date().getFullYear();
  return [year, year + 1, year + 2, year + 3].flatMap((y) => ["Spring", "Summer", "Fall"].map((s) => `${s} ${y}`));
})();
const stages = ["Discovered", "Saved", "Applied", "Assessment", "Interview", "Offer", "Rejected"];
const date = (v?: string | null) => (v ? new Date(v).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "Not specified");
const badgeClass = (s: string) =>
  s === "Verified Eligible" || s === "PASS" ? "" : s === "Ineligible" || s === "FAIL" ? "fail" : s === "Unverified" ? "unverified" : "unknown";
function Status({ value }: { value: string }) {
  return (
    <span className={"badge " + badgeClass(value)}>
      {value === "Verified Eligible" || value === "PASS" ? (
        <ShieldCheck size={12} />
      ) : value === "FAIL" || value === "Ineligible" ? (
        <X size={12} />
      ) : (
        <CircleHelp size={12} />
      )}{" "}
      {value}
    </span>
  );
}

export default function Home() {
  const [user, setUser] = useState<{ id: string; email: string } | null>(null),
    [loading, setLoading] = useState(true),
    [register, setRegister] = useState(false);
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [toast, setToast] = useState("");
  const [page, setPage] = useState("Discover"),
    [mode, setMode] = useState("strict"),
    [q, setQ] = useState(""),
    [sort, setSort] = useState("recent"),
    [company, setCompany] = useState(""),
    [location, setLocation] = useState(""),
    [skill, setSkill] = useState(""),
    [season, setSeason] = useState(""),
    [arrangement, setArrangement] = useState(""),
    [advanced, setAdvanced] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]),
    [counts, setCounts] = useState<Record<string, number>>({}),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [truncated, setTruncated] = useState(false),
    [selected, setSelected] = useState<Job | null>(null),
    [compare, setCompare] = useState<Job[]>([]),
    [comparing, setComparing] = useState(false);
  const [applications, setApplications] = useState<AppRecord[]>([]),
    [editApp, setEditApp] = useState<AppRecord | null>(null),
    [table, setTable] = useState(false),
    [notices, setNotices] = useState<Notice[]>([]),
    [resumes, setResumes] = useState<Resume[]>([]),
    [runs, setRuns] = useState<{ id: string; status: string; started_at: string; details: unknown }[]>([]);
  const [profile, setProfile] = useState<Profile>({}),
    [draftResume, setDraftResume] = useState<string | null>(null),
    [system, setSystem] = useState<SystemStatus>({}),
    [savedJobs, setSavedJobs] = useState<Job[]>([]),
    [savedTotal, setSavedTotal] = useState(0),
    [notFilled, setNotFilled] = useState<string[]>([]),
    [dark, setDark] = useState(false);
  const [prefs, setPrefs] = useState<{ in_app: boolean; email: boolean; digest: string; preferred_companies: string[] }>({
    in_app: true,
    email: false,
    digest: "daily",
    preferred_companies: [],
  });
  const [question, setQuestion] = useState(""),
    [answer, setAnswer] = useState<{
      answer: string;
      citations: { job_id: string; company: string; title: string; url: string; eligibility: Eligibility }[];
      method: string;
    } | null>(null);
  const announce = (text: string) => {
    setToast(text);
    window.setTimeout(() => setToast(""), 5000);
  };
  const action = async (fn: () => Promise<void>) => {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    api("/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setLoading(false));
    const saved = localStorage.getItem("internmatch-theme") === "dark";
    setDark(saved);
    document.body.classList.toggle("dark", saved);
  }, []);
  useEffect(() => {
    // Whenever the session ends (sign out, deletion, expiry) the form returns to sign-in mode.
    if (!user) setRegister(false);
  }, [user]);
  const refresh = useCallback(async () => {
    const params = new URLSearchParams({
      mode: page === "Saved" ? "explore" : mode,
      q,
      sort,
      company,
      location,
      skill,
      season,
      arrangement,
      offset: String(offset),
    });
    const data = await api("/jobs?" + params);
    setJobs(data.items);
    setCounts(data.counts);
    setTotal(data.total);
    setTruncated(data.truncated);
    setSavedTotal(data.saved_total ?? 0);
    if (page === "Saved") {
      const saved = await api("/saved");
      setSavedJobs(saved.items);
      setSavedTotal(saved.total);
    }
  }, [page, mode, q, sort, company, location, skill, season, arrangement, offset]);
  useEffect(() => {
    if (!user) return;
    let active = true;
    const timer = setTimeout(() => {
      refresh().catch((e) => active && setError(e.message));
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [user, refresh]);
  const loadPrivate = useCallback(async () => {
    const values = await Promise.all([
      api("/profile"),
      api("/applications"),
      api("/notifications"),
      api("/resumes"),
      api("/notification-preferences"),
      api("/discovery"),
      api("/status"),
    ]);
    setProfile(values[0]);
    setApplications(values[1]);
    setNotices(values[2]);
    setResumes(values[3]);
    setPrefs(values[4]);
    setRuns(values[5]);
    setSystem(values[6]);
  }, []);
  useEffect(() => {
    if (user) loadPrivate().catch((e) => setError(e.message));
  }, [user, loadPrivate]);
  useEffect(() => {
    setOffset(0);
  }, [mode, q, sort, company, location, skill, season, arrangement, page]);
  const openJob = async (id: string) => {
    const detail = await api("/jobs/" + id);
    setSelected({ ...detail, fit: [...jobs, ...savedJobs].find((j) => j.id === id)?.fit || null });
  };
  const saveJob = async (job: Job) => {
    await api("/jobs/" + job.id + "/saved", { method: job.saved ? "DELETE" : "PUT" });
    await refresh();
    announce(job.saved ? "Opportunity removed from saved" : "Opportunity saved");
  };
  const track = async (job: Job) => {
    await api("/applications/" + job.id, {
      method: "PUT",
      body: JSON.stringify({ stage: "Applied", application_date: new Date().toISOString().slice(0, 10) }),
    });
    await loadPrivate();
    announce("Marked as applied in your tracker");
  };
  const setField = (key: string, value: unknown) => setProfile((p) => ({ ...p, [key]: value }));
  const saveProfile = async () => {
    await api(draftResume ? "/resumes/" + draftResume + "/confirm" : "/profile", { method: draftResume ? "POST" : "PUT", body: JSON.stringify(profile) });
    setDraftResume(null);
    setNotFilled([]);
    await loadPrivate();
    await refresh();
    announce("Confirmed qualifications saved. Eligibility will use these values.");
  };
  const reviewResume = (r: Resume) => {
    // Only values the resume actually supplied fill fields; existing confirmed values (standing, term, authorization) are kept.
    const found = Object.fromEntries(Object.entries(r.extraction).filter(([k, v]) => k !== "weights" && v !== null && !(Array.isArray(v) && v.length === 0)));
    if (r.extraction_status === "ready") setProfile((p) => ({ ...p, ...found }));
    setNotFilled(r.provenance?.not_filled || []);
    setDraftResume(r.id);
  };
  const uploadResume = async (f: File) => {
    const form = new FormData();
    form.append("file", f);
    let result: Resume = await api("/resumes", { method: "POST", body: form });
    if (result.extraction_status === "pending") announce("Resume stored. Extracting with your configured AI provider…");
    // Local models can take a minute or more; poll the queued extraction instead of holding the request open.
    for (let i = 0; result.extraction_status === "pending" && i < 120; i++) {
      await sleep(3000);
      result = await api("/resumes/" + result.id);
    }
    await api("/resumes").then(setResumes);
    if (result.extraction_status === "ready") {
      reviewResume(result);
      announce("Extraction ready for your review. Nothing has been confirmed.");
    } else {
      setDraftResume(result.id);
      setError(
        (result.extraction_error || "Extraction is still pending; check back later.") +
          " Your resume is stored. You can enter your qualifications manually below and confirm them.",
      );
    }
  };
  const monthField = (key: string, label: string) => (
    <label className="field" key={key}>
      {label}
      <input
        className="input"
        type="month"
        value={String(profile[key] ?? "").slice(0, 7)}
        onChange={(e) => setField(key, e.target.value ? e.target.value + "-01" : null)}
      />
    </label>
  );
  const field = (key: string, label: string, type = "text") => (
    <label className="field" key={key}>
      {label}
      <input
        className="input"
        type={type}
        value={String(profile[key] ?? "")}
        step={type === "number" ? "0.01" : undefined}
        min={type === "number" ? 0 : undefined}
        max={key === "gpa" ? 4 : undefined}
        onChange={(e) => setField(key, e.target.value ? (type === "number" ? Number(e.target.value) : e.target.value) : null)}
      />
    </label>
  );
  const listField = (key: string, label: string) => (
    <label className="field" key={key}>
      {label}
      <textarea
        className="input"
        placeholder="One item per line. Leave blank if not provided."
        value={((profile[key] as string[]) || []).join("\n")}
        onChange={(e) => setField(key, e.target.value ? e.target.value.split("\n") : null)}
      />
    </label>
  );
  if (loading) return <div className="min-h-screen grid place-items-center muted">Preparing your workspace…</div>;
  if (!user)
    return (
      <div className="auth-shell">
        <section className="auth-story">
          <div className="brand">
            <span className="brand-mark">
              <Sparkles size={20} />
            </span>
            InternMatch <small>AI</small>
          </div>
          <h1>
            Your next chapter.
            <br />
            Backed by evidence.
          </h1>
          <p>Find internships that fit your qualifications. Understand every requirement. Make your next move with clarity.</p>
          <div className="mt-10 flex items-center gap-3 text-sm">
            <ShieldCheck size={20} />
            <span>Real sources. Clear eligibility. No guesswork.</span>
          </div>
        </section>
        <section className="auth-form">
          <div className="eyebrow">Your opportunity starts here</div>
          <h2 className="mt-4">{register ? "Create your account" : "Welcome back."}</h2>
          <p className="muted mt-3">{register ? "Build a profile that reflects what you actually bring." : "Sign in to your internship workspace."}</p>
          {error && (
            <div role="alert" className="error mt-5">
              {error}
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                const u = await api(register ? "/auth/register" : "/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
                setUser(u);
                setPassword("");
              });
            }}
          >
            <label className="field">
              Email address
              <input required type="email" className="input" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label className="field">
              Password
              <input
                required
                minLength={12}
                maxLength={128}
                type="password"
                className="input"
                autoComplete={register ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <span className="help">At least 12 characters.</span>
            </label>
            <Button disabled={busy}>
              {busy ? "Please wait…" : register ? "Create account" : "Sign in"}
              <ArrowUpRight size={15} />
            </Button>
          </form>
          <button
            className="mt-6 text-sm"
            onClick={() => {
              setRegister(!register);
              setError("");
            }}
          >
            {register ? "Already have an account? Sign in" : "New here? Create an account"}
          </button>
          <p className="help mt-8">Your profile is private. Resume extractions are only used after you confirm them.</p>
        </section>
      </div>
    );
  const visible = page === "Saved" ? savedJobs : jobs;
  const nav = [
    { name: "Discover", icon: LayoutGrid },
    { name: "Saved", icon: Bookmark },
    { name: "Applications", icon: BriefcaseBusiness },
    { name: "AI Analyst", icon: Bot },
    { name: "Profile", icon: UserRound },
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Sparkles size={19} />
          </span>
          InternMatch <small>AI</small>
        </div>
        <p className="nav-label">YOUR WORKSPACE</p>
        <nav>
          {nav.map((n) => (
            <button
              key={n.name}
              className={"nav-item " + (page === n.name ? "active" : "")}
              onClick={() => {
                setPage(n.name);
                setError("");
              }}
            >
              <n.icon size={18} />
              {n.name}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="flex items-center gap-2 mb-3">
            <ShieldCheck size={16} />
            <strong>Evidence comes first.</strong>
          </div>
          <p className="leading-relaxed">Every eligibility decision starts with the employer’s own words.</p>
          <button className="nav-item mt-6" onClick={() => setPage("Settings")}>
            <SlidersHorizontal size={16} />
            Settings & sources
          </button>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div className="crumb">
            Your workspace <span className="mx-3">/</span>
            <span style={{ color: "var(--text)" }}>{page}</span>
          </div>
          <div className="mobile-logo brand">
            InternMatch <small>AI</small>
          </div>
          <div className="top-actions">
            <span className="hidden lg:block text-xs muted">An intentional next step.</span>
            <button
              aria-label="Toggle color theme"
              className="icon-button"
              onClick={() => {
                setDark(!dark);
                document.body.classList.toggle("dark", !dark);
                localStorage.setItem("internmatch-theme", dark ? "light" : "dark");
              }}
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button
              aria-label="Notifications"
              className="icon-button relative"
              onClick={() => {
                setPage("Notifications");
                action(loadPrivate);
              }}
            >
              <Bell size={18} />
              {notices.some((n) => !n.read) && <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-indigo-500" />}
            </button>
            <button className="avatar" aria-label="Your profile" onClick={() => setPage("Profile")}>
              {user.email.slice(0, 1).toUpperCase()}
            </button>
          </div>
        </header>
        <div className="content">
          {error && (
            <div className="error flex justify-between" role="alert">
              <span>{error}</span>
              <button onClick={() => setError("")} aria-label="Dismiss error">
                <X size={15} />
              </button>
            </div>
          )}
          {(page === "Discover" || page === "Saved") && (
            <>
              <div className="hero">
                <div>
                  <div className="eyebrow">A little clarity. A lot of possibility.</div>
                  <h1 className="page-heading">{page === "Saved" ? "Your shortlist." : "Find your next beginning."}</h1>
                  <p className="muted text-[13px]">
                    {page === "Saved"
                      ? "Good opportunities deserve a second look."
                      : "Internships aligned with your qualifications, grounded in employer evidence."}
                  </p>
                </div>
                <Button
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      await api("/discovery", { method: "POST" });
                      announce("Discovery queued. The worker will update results.");
                      await loadPrivate();
                    })
                  }
                >
                  <RefreshCw size={14} />
                  Refresh opportunities
                </Button>
              </div>
              <div className="stats">
                {[
                  { label: "Verified eligible", value: counts["Verified Eligible"] || 0, icon: ShieldCheck, foot: "Every stated mandatory rule satisfied" },
                  { label: "Potential matches", value: counts["Potentially Eligible"] || 0, icon: Sparkles, foot: "A few details still need clarification" },
                  { label: "Saved", value: savedTotal, icon: Bookmark, foot: "Your personal opportunity shortlist" },
                  { label: "Applications", value: applications.length, icon: BriefcaseBusiness, foot: "Keep your next steps moving" },
                ].map((s) => (
                  <div className="stat" key={s.label}>
                    <div className="stat-title">
                      {s.label}
                      <s.icon size={16} />
                    </div>
                    <div className="stat-number">{s.value}</div>
                    <div className="stat-foot">{s.foot}</div>
                  </div>
                ))}
              </div>
              <div className="notice">
                <ShieldCheck size={19} className="shrink-0" />
                <div>
                  <strong>Confidence begins with evidence.</strong>
                  <p className="mt-1 leading-relaxed">
                    Strict Match shows only opportunities with all stated mandatory requirements satisfied. Unknown information stays unknown. Technical fit
                    never overrides eligibility.
                  </p>
                </div>
              </div>
              <div className="flex justify-between items-end">
                <div className="tabs">
                  {[
                    ["strict", "Strict Match"],
                    ["potential", "Potential Match"],
                    ["explore", "Explore"],
                  ].map(([v, l]) => (
                    <button className={"tab " + (mode === v ? "active" : "")} key={v} onClick={() => setMode(v)}>
                      {l}
                      <span className="count">
                        {v === "strict"
                          ? counts["Verified Eligible"] || 0
                          : v === "potential"
                            ? (counts["Verified Eligible"] || 0) + (counts["Potentially Eligible"] || 0)
                            : Object.values(counts).reduce((a, b) => a + b, 0)}
                      </span>
                    </button>
                  ))}
                </div>
                <div className="text-xs muted mb-8 hidden md:block">{total} opportunities</div>
              </div>
              <div className="filters">
                <div className="search">
                  <Search size={16} />
                  <input
                    aria-label="Search internship titles"
                    className="input"
                    placeholder="Search roles, discover possibilities…"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                  />
                </div>
                <select className="input" aria-label="Sort opportunities" value={sort} onChange={(e) => setSort(e.target.value)}>
                  <option value="recent">Most recent</option>
                  <option value="fit">Best fit</option>
                  <option value="deadline">Deadline approaching</option>
                  <option value="company">Company name</option>
                </select>
                <Button className="secondary" onClick={() => setAdvanced(!advanced)}>
                  <SlidersHorizontal size={14} />
                  Filters
                </Button>
                {compare.length > 0 && <Button onClick={() => setComparing(true)}>Compare ({compare.length})</Button>}
              </div>
              {advanced && (
                <div className="panel form-grid mb-6">
                  {[
                    ["Company", company, setCompany],
                    ["Location", location, setLocation],
                    ["Required skill", skill, setSkill],
                    ["Internship season (source text)", season, setSeason],
                  ].map(([label, v, setter]) => (
                    <label className="field" key={String(label)}>
                      {String(label)}
                      <input className="input" value={String(v)} onChange={(e) => (setter as (v: string) => void)(e.target.value)} />
                    </label>
                  ))}
                  <label className="field">
                    Work arrangement
                    <select className="input" value={arrangement} onChange={(e) => setArrangement(e.target.value)}>
                      <option value="">Any arrangement</option>
                      {["Remote", "Hybrid", "In-person"].map((x) => (
                        <option key={x}>{x}</option>
                      ))}
                    </select>
                  </label>
                  <div className="help">
                    Filters search source text. They do not establish eligibility. For freshman-friendly eligibility, confirm your standing at internship start
                    in Profile.
                  </div>
                </div>
              )}
              {truncated && <p className="help mb-4">Showing a bounded candidate set of 1,000 postings. Narrow your filters to see additional matches.</p>}
              {visible.length === 0 ? (
                <div className="empty">
                  <div className="empty-icon">
                    <Search size={24} />
                  </div>
                  <h2>
                    {page === "Saved"
                      ? "Your shortlist starts here."
                      : mode === "strict"
                        ? "Your next match is worth verifying."
                        : "No opportunities in this view yet."}
                  </h2>
                  <p>
                    {mode === "strict"
                      ? "No verified opportunities match this view. Complete your confirmed profile, configure employer sources, or explore postings with unresolved requirements."
                      : "Connect public employer feeds in environment settings and run discovery. Real opportunities will appear here after retrieval; no sample openings are shown."}
                  </p>
                  <div className="flex justify-center gap-3">
                    <Button onClick={() => setPage("Profile")}>
                      Complete your profile <ChevronRight size={14} />
                    </Button>
                    <Button className="secondary" onClick={() => (page === "Saved" ? setPage("Discover") : setMode("explore"))}>
                      {page === "Saved" ? "Discover internships" : "Explore all postings"}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="grid-jobs">
                  {visible.map((job) => (
                    <article className="job-card" key={job.id}>
                      <div className="flex justify-between items-center">
                        <div className="flex items-center gap-3">
                          <div className="company-icon">{job.company.slice(0, 1).toUpperCase()}</div>
                          <div>
                            <strong className="text-sm">{job.company}</strong>
                            <p className="text-[10px] muted mt-1">
                              {job.details.opportunity_type
                                ? job.details.opportunity_type.charAt(0).toUpperCase() + job.details.opportunity_type.slice(1)
                                : "Type not specified"}{" "}
                              · Employer source
                            </p>
                          </div>
                        </div>
                        <button
                          className="icon-button"
                          aria-label={job.saved ? "Unsave opportunity" : "Save opportunity"}
                          onClick={() => action(() => saveJob(job))}
                        >
                          <Bookmark size={18} fill={job.saved ? "currentColor" : "none"} />
                        </button>
                      </div>
                      <h2 className="job-title">
                        <button className="text-left" onClick={() => action(() => openJob(job.id))}>
                          {job.title}
                        </button>
                      </h2>
                      <div className="job-meta">
                        <span>
                          <MapPin size={12} />
                          {job.location || "Location not specified"}
                        </span>
                        <span>
                          <Clock3 size={12} />
                          {job.details.internship_start ? date(job.details.internship_start) : "Dates not specified"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between mt-5 gap-2">
                        <Status value={job.eligibility.status} />
                        {job.changed_since_saved && <span className="badge unknown">Changed since saved</span>}
                        <span className="text-xs muted">
                          {job.fit?.score != null ? (
                            <>
                              <strong style={{ color: "var(--accent)" }}>{job.fit.score}</strong> / 100 fit
                            </>
                          ) : (
                            "Fit not calculated"
                          )}
                        </span>
                      </div>
                      <div className="job-evidence">
                        <span>
                          <ShieldCheck size={12} className="inline mr-1" />
                          {job.eligibility.requirements.filter((r) => r.mandatory).length} mandatory requirements evaluated
                        </span>
                        <span>{date(job.retrieved_at)}</span>
                      </div>
                      {job.details.compensation && <p className="text-xs muted mb-4">{job.details.compensation}</p>}
                      <div className="job-footer">
                        <Button className="secondary" onClick={() => action(() => openJob(job.id))}>
                          View evidence <ArrowUpRight size={13} />
                        </Button>
                        <div className="flex items-center gap-3">
                          <label className="text-[10px] muted flex items-center gap-1">
                            <input
                              type="checkbox"
                              checked={compare.some((j) => j.id === job.id)}
                              onChange={(e) => setCompare(e.target.checked ? [...compare, job].slice(-3) : compare.filter((j) => j.id !== job.id))}
                            />
                            Compare
                          </label>
                          <a href={job.url} target="_blank" rel="noopener noreferrer" aria-label="Open original application">
                            <ExternalLink size={15} />
                          </a>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              <div className="flex justify-between items-center mt-6 text-xs muted">
                <span>Original sources. Transparent decisions.</span>
                <div className="flex gap-2">
                  <Button className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 30))}>
                    Previous
                  </Button>
                  <Button className="secondary" disabled={offset + 30 >= total} onClick={() => setOffset(offset + 30)}>
                    Next
                  </Button>
                </div>
              </div>
            </>
          )}
          {page === "Profile" && (
            <>
              <div className="hero">
                <div className="eyebrow">Your story, accurately represented</div>
                <h1 className="page-heading">A profile with purpose.</h1>
              </div>
              <div className="notice">
                <GraduationCap size={21} />
                <p>
                  Only confirmed information is used for eligibility. Leave unknown fields blank. Academic standing at internship start is an explicit override;
                  it is never inferred from graduation year.
                </p>
              </div>
              {draftResume && (
                <div className="notice" data-testid="resume-review">
                  <FileText size={20} />
                  <div>
                    <p>
                      Reviewing a resume. Check every field below and confirm it before it becomes part of your profile. Extracted values are drafts; standing,
                      term and preferences are never filled automatically.
                    </p>
                    {notFilled.length > 0 && <p className="mt-2">Not filled because the value was not found verbatim in your resume: {notFilled.join(", ")}.</p>}
                  </div>
                </div>
              )}
              <div className="panel">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    action(saveProfile);
                  }}
                >
                  <div className="section-title">Education & identity</div>
                  <div className="form-grid">
                    {field("full_name", "Full name")}
                    {field("university", "University")}
                    {field("degree", "Degree designation (exact, confirmed)")}
                    {field("major", "Major")}
                    {field("minor", "Minor")}
                    {monthField("graduation", "Expected graduation (month)")}
                    {field("gpa", "GPA (4.0 scale only)", "number")}
                    {field("standing", "Current standing")}
                    {field("standing_as_of", "Standing as of", "date")}
                    <label className="field">
                      Confirmed standing at internship start
                      <select className="input" value={String(profile.standing_at_start ?? "")} onChange={(e) => setField("standing_at_start", e.target.value || null)}>
                        <option value="">Not provided</option>
                        {["freshman", "rising sophomore", "sophomore", "rising junior", "junior", "rising senior", "senior"].map((x) => (
                          <option key={x}>{x}</option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      Internship term that standing applies to
                      <select className="input" value={String(profile.standing_term ?? "")} onChange={(e) => setField("standing_term", e.target.value || null)}>
                        <option value="">Not provided</option>
                        {terms.map((t) => (
                          <option key={t}>{t}</option>
                        ))}
                      </select>
                      <span className="help">Only compared with postings whose own evidence names the same term. Never carried to other terms.</span>
                    </label>
                    {field("target_start", "Preferred internship start (search preference only)", "date")}
                    {field("season", "Internship season")}
                    {listField("skills", "Technical skills")}
                    {listField("certifications", "Verified certifications")}
                    {listField("projects", "Projects & accomplishments")}
                    {listField("experience", "Professional experience")}
                    {listField("research", "Research experience")}
                    {listField("titles", "Preferred job titles")}
                    {listField("industries", "Preferred industries")}
                    {listField("locations", "Preferred locations")}
                    {listField("arrangements", "Preferred work arrangements")}
                    {field("compensation_min", "Minimum compensation preference", "number")}
                  </div>
                  <hr className="divider" />
                  <div className="section-title">Voluntary eligibility information</div>
                  <p className="help mb-5">
                    Only supply these details if you want them evaluated against explicit employer requirements. They are not inferred from your name, school,
                    or location.
                  </p>
                  <div className="form-grid">
                    {[
                      ["work_authorization", "Authorized to work in the United States"],
                      ["sponsorship_required", "Sponsorship required"],
                    ].map(([key, label]) => (
                      <label className="field" key={key}>
                        {label}
                        <select
                          className="input"
                          value={profile[key] === true ? "true" : profile[key] === false ? "false" : ""}
                          onChange={(e) => setField(key, e.target.value === "" ? null : e.target.value === "true")}
                        >
                          <option value="">Not provided</option>
                          <option value="true">Yes</option>
                          <option value="false">No</option>
                        </select>
                      </label>
                    ))}
                    {field("citizenship", "Citizenship (optional)")}
                  </div>
                  <hr className="divider" />
                  <div className="section-title">Fit scoring weights</div>
                  <p className="help mb-4">Weights must sum to 1. Missing qualifications contribute zero. Fit never changes eligibility.</p>
                  <div className="form-grid">
                    {Object.entries((profile.weights as Record<string, number>) || {}).map(([key, v]) => (
                      <label key={key} className="field capitalize">
                        {key}
                        <input
                          className="input"
                          type="number"
                          min="0"
                          max="1"
                          step="0.01"
                          value={v}
                          onChange={(e) => setField("weights", { ...(profile.weights as object), [key]: Number(e.target.value) })}
                        />
                      </label>
                    ))}
                  </div>
                  <Button className="mt-6" disabled={busy}>
                    {" "}
                    <Check size={15} />
                    {draftResume ? "Confirm reviewed resume qualifications" : "Confirm & save profile"}
                  </Button>
                </form>
              </div>
              <section className="panel mt-6">
                <div className="flex justify-between items-center gap-4">
                  <div>
                    <h2 className="section-title mb-1">Your resume library</h2>
                    <p className="help">
                      PDF or DOCX, up to 5 MB. Encrypted storage.{" "}
                      {system.ai?.ready
                        ? `Extraction runs on ${system.ai.provider === "ollama" ? "your local model" : "the configured hosted provider"}.`
                        : "AI extraction is unavailable; you can still upload and enter details manually."}
                    </p>
                  </div>
                  <label className="button secondary cursor-pointer">
                    <Upload size={14} />
                    Upload resume
                    <input
                      className="sr-only"
                      type="file"
                      accept=".pdf,.docx"
                      disabled={busy}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) action(() => uploadResume(f));
                        e.target.value = "";
                      }}
                    />
                  </label>
                </div>
                {resumes.map((r) => (
                  <div className="flex justify-between border-t mt-5 pt-5 gap-3" style={{ borderColor: "var(--line)" }} key={r.id}>
                    <div>
                      <strong>{r.filename}</strong>
                      <p className="help">
                        {date(r.created_at)} ·{" "}
                        {r.confirmed
                          ? "Confirmed"
                          : r.extraction_status === "pending"
                            ? "Extracting…"
                            : r.extraction_status === "failed"
                              ? "Extraction unavailable — enter details manually"
                              : "Awaiting review"}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        className="secondary"
                        onClick={() => {
                          reviewResume(r);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        Review
                      </Button>
                      <a className="button secondary" href={API + "/resumes/" + r.id + "/download"}>
                        Download
                      </a>
                      <Button
                        className="ghost"
                        onClick={() =>
                          action(async () => {
                            await api("/resumes/" + r.id, { method: "DELETE" });
                            await loadPrivate();
                          })
                        }
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                ))}
              </section>
            </>
          )}
          {page === "Applications" && (
            <>
              <div className="hero">
                <div>
                  <div className="eyebrow">One step at a time</div>
                  <h1 className="page-heading">Your application journey.</h1>
                  <p className="muted">A clear view of where you are, and what comes next.</p>
                </div>
                <Button className="secondary" onClick={() => setTable(!table)}>
                  {table ? "Kanban view" : "Table view"}
                </Button>
              </div>
              {applications.length === 0 ? (
                <div className="empty">
                  <div className="empty-icon">
                    <BriefcaseBusiness size={24} />
                  </div>
                  <h2>A place for every next step.</h2>
                  <p>Mark an opportunity as applied from its evidence view. Your progress, notes, resume version, and reminders will live here.</p>
                  <Button onClick={() => setPage("Discover")}>Discover opportunities</Button>
                </div>
              ) : table ? (
                <div className="panel table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Company / role</th>
                        <th>Stage</th>
                        <th>Applied</th>
                        <th>Follow-up</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {applications.map((a) => (
                        <tr key={a.id}>
                          <td>
                            <strong>{a.company}</strong>
                            <p className="mt-1">{a.title}</p>
                          </td>
                          <td>{a.stage}</td>
                          <td>{date(a.application_date)}</td>
                          <td>{date(a.follow_up)}</td>
                          <td>
                            <Button className="secondary" onClick={() => setEditApp(a)}>
                              Edit
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="kanban">
                  {stages.map((s) => (
                    <section className="kanban-column" key={s}>
                      <h2 className="text-xs font-semibold">
                        {s}
                        <span className="count">{applications.filter((a) => a.stage === s).length}</span>
                      </h2>
                      {applications
                        .filter((a) => a.stage === s)
                        .map((a) => (
                          <button className="kanban-card text-left w-full" key={a.id} onClick={() => setEditApp(a)}>
                            <span className="text-xs muted">{a.company}</span>
                            <p className="font-semibold mt-2 text-sm">{a.title}</p>
                            {a.follow_up && <p className="help">Follow up {date(a.follow_up)}</p>}
                          </button>
                        ))}
                    </section>
                  ))}
                </div>
              )}
            </>
          )}
          {page === "AI Analyst" && (
            <>
              <div className="eyebrow">Answers with a source</div>
              <h1 className="page-heading">Ask. Inspect. Understand.</h1>
              <p className="muted mb-7">Retrieve stored employer evidence. No invented openings or eligibility claims.</p>
              <div className="panel">
                <form
                  className="flex gap-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    action(async () => setAnswer(await api("/analyst", { method: "POST", body: JSON.stringify({ query: question }) })));
                  }}
                >
                  <input
                    className="input"
                    aria-label="Ask about stored opportunities"
                    required
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    placeholder="Find cybersecurity internships…"
                  />
                  <Button disabled={busy}>
                    <Search size={16} />
                    Find evidence
                  </Button>
                </form>
                <p className="help">
                  Current capability: extractive keyword retrieval over the stored catalogue. Full conversational reasoning and web search are not connected.
                </p>
                {answer && (
                  <div className="mt-6">
                    <p className="leading-relaxed">{answer.answer}</p>
                    {answer.citations.map((c) => (
                      <div className="evidence-row" key={c.job_id}>
                        <button className="font-semibold text-left" onClick={() => action(() => openJob(c.job_id))}>
                          {c.company} — {c.title}
                        </button>
                        <div className="mt-3">
                          <Status value={c.eligibility.status} />
                        </div>
                        {c.eligibility.requirements
                          .filter((r) => r.mandatory)
                          .slice(0, 3)
                          .map((r, i) => (
                            <blockquote key={i}>
                              {r.quote}
                              <p className="mt-2">
                                <strong>{r.result}</strong> · {r.explanation}
                              </p>
                            </blockquote>
                          ))}
                        <a className="text-xs underline" href={c.url} target="_blank" rel="noopener noreferrer">
                          Original employer posting ↗
                        </a>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
          {page === "Notifications" && (
            <>
              <div className="eyebrow">Stay in the know</div>
              <h1 className="page-heading">Updates that matter.</h1>
              <div className="panel mt-6">
                {notices.length === 0 ? (
                  <p className="muted">No notifications yet. New verified matches and saved-posting updates will appear here.</p>
                ) : (
                  notices.map((n) => (
                    <div className="evidence-row flex justify-between gap-3" key={n.id}>
                      <div>
                        <span className="eyebrow">{n.data.type.replaceAll("_", " ")}</span>
                        <h2 className="font-semibold mt-2">{n.data.title || "Application reminder"}</h2>
                        <p className="help">
                          {date(n.created_at)} {n.data.deadline && "· Deadline " + date(n.data.deadline)}
                        </p>
                        {n.data.job_id && (
                          <button className="text-xs underline mt-2" onClick={() => action(() => openJob(n.data.job_id))}>
                            View source evidence
                          </button>
                        )}
                      </div>
                      {!n.read && (
                        <Button
                          className="secondary"
                          onClick={() =>
                            action(async () => {
                              await api("/notifications/" + n.id + "/read", { method: "PUT" });
                              await loadPrivate();
                            })
                          }
                        >
                          Mark read
                        </Button>
                      )}
                    </div>
                  ))
                )}
              </div>
            </>
          )}
          {page === "Settings" && (
            <>
              <div className="eyebrow">Make it yours</div>
              <h1 className="page-heading">Settings & sources.</h1>
              <div className="panel mt-6">
                <h2 className="section-title">Integration status</h2>
                <div className="flex justify-between py-3 gap-3">
                  <span>AI extraction & embeddings</span>
                  <span className={"badge " + (system.ai?.ready ? "" : "unknown")} data-testid="ai-status">
                    {system.ai?.ready ? `${system.ai.provider} ready` : system.ai ? `${system.ai.provider}: not ready` : "Unknown"}
                  </span>
                </div>
                {system.ai && (
                  <p className="help">
                    {system.ai.llm_model && <>Extraction model: {system.ai.llm_model}. Embedding model: {system.ai.embedding_model}. </>}
                    {system.ai.error}
                    {system.ai.fallback ? ` Hosted fallback enabled: ${system.ai.fallback}.` : " No hosted fallback."}
                  </p>
                )}
                {[
                  ["Background worker", system.worker?.running, system.worker?.running ? "Running" : "Not running"],
                  [
                    "Public ATS discovery sources",
                    !!(system.discovery_sources?.greenhouse.length || system.discovery_sources?.lever.length),
                    [...(system.discovery_sources?.greenhouse || []).map((x) => "Greenhouse: " + x), ...(system.discovery_sources?.lever || []).map((x) => "Lever: " + x)].join(", ") ||
                      "Not configured",
                  ],
                  ["Email delivery", system.email, system.email ? "Configured · live verification required" : "Not configured"],
                ].map(([label, on, text]) => (
                  <div className="flex justify-between py-3 gap-3" key={String(label)}>
                    <span>{String(label)}</span>
                    <span className={"badge " + (on ? "" : "unknown")}>{String(text)}</span>
                  </div>
                ))}
                {!!system.tasks?.length && (
                  <p className="help">Task queue: {system.tasks.map((t) => `${t.kind} ${t.status}: ${t.count}`).join(" · ")}</p>
                )}
                <p className="help">
                  Configure credentials securely in server environment settings. Public feeds use operator-reviewed GREENHOUSE_BOARDS and LEVER_SITES identifiers. No
                  arbitrary URL crawling or access-control bypass is enabled.
                </p>
              </div>
              <form
                className="panel mt-6"
                onSubmit={(e) => {
                  e.preventDefault();
                  action(async () => {
                    await api("/notification-preferences", { method: "PUT", body: JSON.stringify(prefs) });
                    announce("Notification preferences saved");
                  });
                }}
              >
                <h2 className="section-title">Notification preferences</h2>
                <div className="flex flex-col gap-5">
                  <label className="flex gap-3">
                    <input type="checkbox" checked={prefs.in_app} onChange={(e) => setPrefs({ ...prefs, in_app: e.target.checked })} />
                    In-app opportunity alerts
                  </label>
                  <label className="flex gap-3">
                    <input type="checkbox" checked={prefs.email} onChange={(e) => setPrefs({ ...prefs, email: e.target.checked })} />
                    Email digest (requires configured SMTP)
                  </label>
                  <label className="field">
                    Digest frequency
                    <select className="input" value={prefs.digest} onChange={(e) => setPrefs({ ...prefs, digest: e.target.value })}>
                      <option value="daily">Daily</option>
                      <option value="weekly">Weekly</option>
                    </select>
                  </label>
                  <label className="field">
                    Preferred companies, one per line
                    <textarea
                      className="input"
                      value={prefs.preferred_companies.join("\n")}
                      onChange={(e) => setPrefs({ ...prefs, preferred_companies: e.target.value.split("\n").filter(Boolean) })}
                    />
                  </label>
                </div>
                <Button className="mt-5" disabled={busy}>
                  Save preferences
                </Button>
              </form>
              <div className="panel mt-6">
                <h2 className="section-title">Discovery history</h2>
                {runs.length === 0 ? (
                  <p className="muted">No discovery runs recorded. Configure sources and start the worker.</p>
                ) : (
                  runs.map((r) => (
                    <div key={r.id} className="evidence-row">
                      <div className="flex justify-between">
                        <span>{date(r.started_at)}</span>
                        <strong>{r.status}</strong>
                      </div>
                      <pre className="text-xs whitespace-pre-wrap muted mt-3">{JSON.stringify(r.details, null, 2)}</pre>
                    </div>
                  ))
                )}
              </div>
              <div className="panel mt-6">
                <h2 className="section-title">Privacy & account</h2>
                <p className="help mb-5">
                  Profiles and resume documents are encrypted at rest. Uploaded resumes are retained until you delete them or delete your account. Audit logs
                  and notifications expire after 90 days. Exports contain sensitive personal information; store them securely.
                </p>
                <div className="flex flex-wrap gap-3">
                  <Button
                    className="secondary"
                    onClick={() =>
                      action(async () => {
                        const result = await api("/account/export");
                        const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = "internmatch-export.json";
                        a.click();
                        URL.revokeObjectURL(url);
                      })
                    }
                  >
                    Export my data
                  </Button>
                  <Button
                    className="secondary"
                    onClick={() =>
                      action(async () => {
                        await api("/auth/logout", { method: "POST" });
                        setUser(null);
                      })
                    }
                  >
                    <LogOut size={14} />
                    Sign out
                  </Button>
                  <Button
                    className="secondary"
                    onClick={() => {
                      if (window.confirm("Permanently delete your account, resumes, profile, and applications?"))
                        action(async () => {
                          await api("/account", { method: "DELETE" });
                          setUser(null);
                        });
                    }}
                  >
                    Delete account
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </main>
      {toast && !selected && !comparing && !editApp && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
      {selected && (
        <Modal title={selected.title} onClose={() => setSelected(null)} toast={toast}>
          <div className="flex justify-between items-center mt-4 gap-3">
            <span className="muted">{selected.company}</span>
            <Status value={selected.eligibility.status} />
          </div>
          <p className="help mt-4">Verified {date(selected.retrieved_at)} · Eligibility and technical fit are separate decisions.</p>
          {selected.eligibility.disclosures.map((d, i) => (
            <div className="notice mt-4 mb-0" key={i}>
              {d}
            </div>
          ))}
          {selected.extraction_error && <div className="notice mt-4">{selected.extraction_error}</div>}
          {selected.details?.extraction_status === "pending" && (
            <div className="notice mt-4">Requirement extraction is queued. Until it completes and passes source validation, this posting stays Unverified.</div>
          )}
          <div className="mt-6">
            <h3 className="section-title">Requirement-by-requirement evidence</h3>
            {selected.eligibility.requirements.length === 0 && (
              <p className="muted">No source-validated requirements are available. This posting cannot be verified eligible.</p>
            )}
            {selected.eligibility.requirements.map((r, i) => (
              <div className="evidence-row" key={i}>
                <div className="flex justify-between">
                  <strong className="capitalize">
                    {r.kind.replaceAll("_", " ")} <span className="text-xs font-normal muted">· {r.mandatory ? "Mandatory" : "Preferred"}</span>
                  </strong>
                  <Status value={r.result} />
                </div>
                <blockquote>“{r.quote}”</blockquote>
                {r.origin === "scanner" && <p className="help">Detected by a deterministic source scan, not by the model. It stays unresolved until reviewed.</p>}
                <p className="text-sm">
                  <strong>Your qualification:</strong> {r.student}
                </p>
                <p className="muted text-xs mt-2">{r.explanation}</p>
                <a className="text-xs underline mt-3 inline-block" href={r.source_url} target="_blank" rel="noopener noreferrer">
                  Employer source · {date(r.verified_at)} ↗
                </a>
              </div>
            ))}
          </div>
          <div className="mt-6">
            <h3 className="section-title">Technical & professional fit</h3>
            {selected.fit ? (
              <>
                <p className="text-2xl font-semibold">
                  {selected.fit.score ?? "Not available"}
                  <span className="text-xs muted font-normal"> / 100</span>
                </p>
                <p className="help">{selected.fit.explanation}</p>
                {Object.entries(selected.fit.components || {}).map(([k, v]) => (
                  <p className="text-xs muted mt-2 capitalize" key={k}>
                    {k}: {v} · {selected.fit?.evidence?.[k]}
                  </p>
                ))}
              </>
            ) : (
              <p className="help">No semantic score has been calculated. Requires a configured embedding provider and confirmed profile.</p>
            )}
            <Button
              className="secondary mt-3"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  const fit = await api("/jobs/" + selected.id + "/match", { method: "POST" });
                  setSelected({ ...selected, fit });
                  await refresh();
                })
              }
            >
              Calculate semantic fit
            </Button>
          </div>
          <details className="mt-6">
            <summary className="cursor-pointer text-sm font-semibold">Original retrieved job description</summary>
            <pre className="source-text mt-4">{selected.text}</pre>
            <p className="help">
              Source content SHA-256 {selected.content_hash?.slice(0, 12)}… · retrieved {date(selected.retrieved_at)}
              {selected.details.provenance?.model &&
                ` · extracted by ${selected.details.provenance.model}, checked against source by validator v${selected.details.provenance.quality?.validator_version}`}
            </p>
          </details>
          <div className="flex flex-wrap gap-3 mt-7">
            <a className="button" target="_blank" rel="noopener noreferrer" href={selected.url}>
              Original application <ArrowUpRight size={14} />
            </a>
            <Button className="secondary" onClick={() => action(() => track(selected))}>
              Mark as applied
            </Button>
            <Button className="secondary" onClick={() => action(() => saveJob(selected))}>
              <Bookmark size={14} />
              Save
            </Button>
            <Button
              className="ghost"
              onClick={() =>
                action(async () => {
                  await api("/jobs/" + selected.id + "/saved?hidden=true", { method: "PUT" });
                  setSelected(null);
                  await refresh();
                })
              }
            >
              Hide posting
            </Button>
          </div>
        </Modal>
      )}
      {comparing && (
        <Modal title="Compare your opportunities" onClose={() => setComparing(false)} toast={toast}>
          <div className="table-wrap mt-6">
            <table>
              <thead>
                <tr>
                  <th>Opportunity</th>
                  {compare.map((j) => (
                    <th key={j.id}>
                      {j.company}
                      <p className="mt-2 font-normal">{j.title}</p>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Eligibility</td>
                  {compare.map((j) => (
                    <td key={j.id}>
                      <Status value={j.eligibility.status} />
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>Fit score</td>
                  {compare.map((j) => (
                    <td key={j.id}>{j.fit?.score ?? "Not calculated"}</td>
                  ))}
                </tr>
                <tr>
                  <td>Location</td>
                  {compare.map((j) => (
                    <td key={j.id}>{j.location || "Not specified"}</td>
                  ))}
                </tr>
                <tr>
                  <td>Compensation</td>
                  {compare.map((j) => (
                    <td key={j.id}>{j.details.compensation || "Not specified"}</td>
                  ))}
                </tr>
                <tr>
                  <td>Deadline</td>
                  {compare.map((j) => (
                    <td key={j.id}>{date(j.details.deadline)}</td>
                  ))}
                </tr>
                <tr>
                  <td>Mandatory rules</td>
                  {compare.map((j) => (
                    <td key={j.id}>{j.eligibility.requirements.filter((r) => r.mandatory).length}</td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </Modal>
      )}
      {editApp && (
        <Modal title="Update your application" onClose={() => setEditApp(null)} toast={toast}>
          <p className="muted mt-3 mb-6">
            {editApp.company} · {editApp.title}
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                await api("/applications/" + editApp.job_id, { method: "PUT", body: JSON.stringify(editApp) });
                setEditApp(null);
                await loadPrivate();
                announce("Application updated");
              });
            }}
          >
            <div className="form-grid">
              <label className="field">
                Stage
                <select className="input" value={editApp.stage} onChange={(e) => setEditApp({ ...editApp, stage: e.target.value })}>
                  {stages.map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Resume version
                <select className="input" value={editApp.resume_id || ""} onChange={(e) => setEditApp({ ...editApp, resume_id: e.target.value || null })}>
                  <option value="">Not specified</option>
                  {resumes.map((r) => (
                    <option value={r.id} key={r.id}>
                      {r.filename} · {date(r.created_at)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Application date
                <input
                  className="input"
                  type="date"
                  value={editApp.application_date || ""}
                  onChange={(e) => setEditApp({ ...editApp, application_date: e.target.value || null })}
                />
              </label>
              <label className="field">
                Follow-up reminder
                <input
                  className="input"
                  type="date"
                  value={editApp.follow_up || ""}
                  onChange={(e) => setEditApp({ ...editApp, follow_up: e.target.value || null })}
                />
              </label>
              <label className="field wide">
                Notes
                <textarea className="input" value={editApp.notes} onChange={(e) => setEditApp({ ...editApp, notes: e.target.value })} />
              </label>
              <label className="field">
                Interview dates (ISO timestamp per line)
                <textarea
                  className="input"
                  value={editApp.interview_dates.join("\n")}
                  onChange={(e) => setEditApp({ ...editApp, interview_dates: e.target.value.split("\n").filter(Boolean) })}
                />
              </label>
              <label className="field">
                Relevant contacts
                <textarea className="input" value={editApp.contacts} onChange={(e) => setEditApp({ ...editApp, contacts: e.target.value })} />
              </label>
            </div>
            <Button className="mt-6" disabled={busy}>
              Save application
            </Button>
          </form>
        </Modal>
      )}
    </div>
  );
}
