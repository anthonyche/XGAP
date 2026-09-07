'use client';

import { useCallback, useEffect, useState } from 'react';
import { flushSync } from 'react-dom';
import {
  AlertTriangle,
  ArrowRight,
  Braces,
  Check,
  Circle,
  Database,
  GitFork,
  LoaderCircle,
  LockKeyhole,
  Play,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Progress,
  ProgressLabel,
  ProgressValue,
} from '@/components/ui/progress';

const CONTROL_URL = 'http://127.0.0.1:8765';
type ClarificationOption = {
  candidate_id: string;
  label: string;
};

type ClarificationQuestion = {
  question_sha256: string;
  sequence: number;
  hole_id: string;
  role: string;
  prompt: string;
  options: ClarificationOption[];
  reason_codes: string[];
};

type ExecutionHandoff = {
  execution_handoff_sha256: string;
  selected_plan_ids: string[];
  selected_plan_count: number;
  expected_remote_calls: number;
  current_query_profile_calls: number;
  execution_order: string;
};

type ClarificationView = {
  session_id: string;
  session_sha256: string;
  status: string;
  terminal: boolean;
  execution_eligible: boolean;
  authority_event_count: number;
  question: ClarificationQuestion | null;
  execution_handoff: ExecutionHandoff | null;
};

type SubmissionPreview = {
  submission_preview_sha256: string;
  selected_plan_ids: string[];
  confirmation_required: boolean;
};

type SubmissionResult = {
  status: string;
  job_id?: string;
  state?: string;
  message?: string;
};

type ControlState = {
  connected: boolean;
  request: {
    text: string;
    sha256: string;
  };
  clarification: ClarificationView;
  submission_preview: SubmissionPreview | null;
  submission_enabled: boolean;
  submission_attempted: boolean;
  submission_result: SubmissionResult | null;
  state_sha256: string;
};

type ModelContextTool = {
  name: string;
  title?: string;
  description: string;
  inputSchema: object;
  annotations?: {
    readOnlyHint?: boolean;
    untrustedContentHint?: boolean;
  };
  execute(input: unknown): Promise<unknown>;
};

declare global {
  interface Document {
    readonly modelContext?: {
      registerTool(
        tool: ModelContextTool,
        options?: { signal?: AbortSignal },
      ): void | Promise<void>;
    };
  }
}

const optionDetails: Record<string, string> = {
  'constraint:single-transfer-at-least-50000': '至少一笔转账达到 50,000',
  'constraint:amount-at-least-50000': '时间窗口内的转账总额达到 50,000',
  'constraint:frequency-at-least-3': '时间窗口内至少发生 3 笔转账',
  'predicate:transferred_to': '以 transferred_to 作为权威 predicate 基准',
  'predicate:paid_to': '以 paid_to 作为权威 predicate 基准',
};

const fallbackOptions: ClarificationOption[] = [
  {
    candidate_id: 'constraint:single-transfer-at-least-50000',
    label: '单笔金额',
  },
  {
    candidate_id: 'constraint:amount-at-least-50000',
    label: '累计金额',
  },
  {
    candidate_id: 'constraint:frequency-at-least-3',
    label: '转账频率',
  },
];

async function readResponse(
  response: Response,
): Promise<Record<string, unknown>> {
  const payload = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    const state = payload.state as ControlState | undefined;
    if (state) return { error: payload.error, state };
    throw new Error(
      typeof payload.error === 'string'
        ? payload.error
        : '本地控制服务请求失败',
    );
  }
  return payload;
}

function assertObject(input: unknown): Record<string, unknown> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new Error('tool input must be an object');
  }
  return input as Record<string, unknown>;
}

function assertExactKeys(input: Record<string, unknown>, keys: string[]) {
  const observed = Object.keys(input).sort();
  const expected = [...keys].sort();
  if (
    observed.length !== expected.length ||
    observed.some((value, index) => value !== expected[index])
  ) {
    throw new Error('tool input fields do not match the action contract');
  }
}

export default function Home() {
  const [state, setState] = useState<ControlState | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingOption, setPendingOption] =
    useState<ClarificationOption | null>(null);
  const [submitOpen, setSubmitOpen] = useState(false);
  const publishState = useCallback((next: ControlState) => {
    flushSync(() => setState(next));
  }, []);

  const refresh = useCallback(async () => {
    setConnectionError(null);
    try {
      const response = await fetch(`${CONTROL_URL}/api/session`, {
        cache: 'no-store',
      });
      const payload = (await readResponse(response)) as unknown as ControlState;
      publishState(payload);
    } catch (error) {
      setState(null);
      setConnectionError(
        error instanceof Error ? error.message : '本地控制服务未连接',
      );
    }
  }, [publishState]);

  const commitChoice = useCallback(
    async (input: {
      sessionSha256: string;
      questionSha256: string;
      candidateId: string;
      confirmed: boolean;
    }) => {
      setBusy(true);
      setActionError(null);
      try {
        const response = await fetch(`${CONTROL_URL}/api/clarification`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_sha256: input.sessionSha256,
            question_sha256: input.questionSha256,
            candidate_id: input.candidateId,
            confirmed: input.confirmed,
          }),
        });
        const payload = await readResponse(response);
        const next = (payload.state ?? payload) as unknown as ControlState;
        publishState(next);
        if (!response.ok) {
          throw new Error(
            typeof payload.error === 'string'
              ? payload.error
              : '权威选择未被接受',
          );
        }
        return {
          status: next.clarification.status,
          sessionSha256: next.clarification.session_sha256,
          authorityEventCount: next.clarification.authority_event_count,
        };
      } catch (error) {
        const message = error instanceof Error ? error.message : '权威选择失败';
        setActionError(message);
        throw error;
      } finally {
        setBusy(false);
      }
    },
    [publishState],
  );

  const submitSelectedSession = useCallback(
    async (input: { previewSha256: string; confirmed: boolean }) => {
      setBusy(true);
      setActionError(null);
      try {
        const response = await fetch(`${CONTROL_URL}/api/submit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            submission_preview_sha256: input.previewSha256,
            confirmed: input.confirmed,
          }),
        });
        const payload = await readResponse(response);
        const next = (payload.state ?? payload) as unknown as ControlState;
        publishState(next);
        if (!response.ok) {
          throw new Error(
            typeof payload.error === 'string'
              ? payload.error
              : '远端提交未被接受',
          );
        }
        return {
          status: next.submission_result?.status ?? 'unknown',
          jobId: next.submission_result?.job_id ?? null,
        };
      } catch (error) {
        const message = error instanceof Error ? error.message : '远端提交失败';
        setActionError(message);
        throw error;
      } finally {
        setBusy(false);
      }
    },
    [publishState],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const reportRegistrationError = () => undefined;

    const choiceTool: ModelContextTool = {
      name: 'commit_clarification_choice',
      title: '确认语义候选',
      description:
        '将当前 XGAP 澄清问题中的一个候选 ID 作为显式用户 authority event 提交。',
      inputSchema: {
        type: 'object',
        properties: {
          sessionSha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
          questionSha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
          candidateId: { type: 'string', minLength: 1, maxLength: 256 },
          confirmed: { const: true },
        },
        required: [
          'sessionSha256',
          'questionSha256',
          'candidateId',
          'confirmed',
        ],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      async execute(raw) {
        const input = assertObject(raw);
        assertExactKeys(input, [
          'sessionSha256',
          'questionSha256',
          'candidateId',
          'confirmed',
        ]);
        if (
          typeof input.sessionSha256 !== 'string' ||
          typeof input.questionSha256 !== 'string' ||
          typeof input.candidateId !== 'string' ||
          input.confirmed !== true
        ) {
          throw new Error('clarification action input is invalid');
        }
        return commitChoice({
          sessionSha256: input.sessionSha256,
          questionSha256: input.questionSha256,
          candidateId: input.candidateId,
          confirmed: true,
        });
      },
    };

    const submitTool: ModelContextTool = {
      name: 'submit_selected_session',
      title: '提交已封存会话',
      description:
        '确认并提交当前 hash-bound XGAP selected-session preview；同一会话只尝试一次。',
      inputSchema: {
        type: 'object',
        properties: {
          previewSha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
          confirmed: { const: true },
        },
        required: ['previewSha256', 'confirmed'],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      async execute(raw) {
        const input = assertObject(raw);
        assertExactKeys(input, ['previewSha256', 'confirmed']);
        if (
          typeof input.previewSha256 !== 'string' ||
          input.confirmed !== true
        ) {
          throw new Error('submission action input is invalid');
        }
        return submitSelectedSession({
          previewSha256: input.previewSha256,
          confirmed: true,
        });
      },
    };

    for (const tool of [choiceTool, submitTool]) {
      try {
        void Promise.resolve(
          context.registerTool(tool, { signal: lifecycle.signal }),
        ).catch(reportRegistrationError);
      } catch {
        reportRegistrationError();
      }
    }
    return () => lifecycle.abort();
  }, [commitChoice, submitSelectedSession]);

  const clarification = state?.clarification;
  const question = clarification?.question;
  const options = question?.options ?? fallbackOptions;
  const connected = Boolean(state?.connected);
  const ready = clarification?.status === 'ready_for_execution_handoff';
  const progress = ready ? 100 : question?.sequence === 2 ? 75 : 50;
  const completedSteps = clarification?.authority_event_count ?? 0;
  const statusLabel = connected ? '本地服务已连接' : '本地服务未连接';
  const heading = ready
    ? '语义选择已封存，可以检查执行计划'
    : (question?.prompt ?? '“密切资金往来”具体指什么？');

  const confirmPendingOption = async () => {
    if (!pendingOption || !clarification || !question) return;
    const selected = pendingOption;
    setPendingOption(null);
    try {
      await commitChoice({
        sessionSha256: clarification.session_sha256,
        questionSha256: question.question_sha256,
        candidateId: selected.candidate_id,
        confirmed: true,
      });
    } catch {
      // The actionable error and latest safe state are already visible.
    }
  };

  const confirmSubmission = async () => {
    const preview = state?.submission_preview;
    if (!preview) return;
    setSubmitOpen(false);
    try {
      await submitSelectedSession({
        previewSha256: preview.submission_preview_sha256,
        confirmed: true,
      });
    } catch {
      // The actionable error and latest safe state are already visible.
    }
  };

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-white/8 bg-background/86 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1480px] items-center justify-between px-5 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-xl border border-cyan-300/20 bg-cyan-300/10 text-cyan-200">
              <GitFork className="size-[18px]" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-[15px] font-semibold tracking-[-0.02em]">
                XGAP
              </p>
              <p className="truncate text-xs text-muted-foreground">
                Clarification workspace
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => void refresh()}
              aria-label="重新连接本地控制服务"
            >
              <RefreshCw className="size-4" aria-hidden="true" />
            </Button>
            <Badge
              variant="outline"
              className={
                connected
                  ? 'h-7 border-emerald-300/25 bg-emerald-300/8 px-2.5 text-emerald-200'
                  : 'h-7 border-amber-300/25 bg-amber-300/8 px-2.5 text-amber-200'
              }
            >
              <Circle className="size-2 fill-current" aria-hidden="true" />
              {statusLabel}
            </Badge>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1480px] gap-5 px-5 py-5 lg:grid-cols-[230px_minmax(0,1fr)_310px] lg:px-8 lg:py-8">
        <aside className="rounded-2xl border border-white/8 bg-card/70 p-4 lg:min-h-[calc(100vh-128px)]">
          <p className="px-2 text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Session flow
          </p>
          <ol className="mt-5 space-y-1" aria-label="澄清步骤">
            {[
              ['确定结构语义', 'relationship-strength'],
              ['确定 predicate 基准', 'transfer-predicate'],
              ['检查并提交', 'sealed handoff'],
            ].map(([label, detail], index) => {
              const step = index + 1;
              const active =
                (step === 1 && completedSteps === 0) ||
                (step === 2 && completedSteps === 1) ||
                (step === 3 && completedSteps >= 2);
              const complete = completedSteps >= step;
              return (
                <li
                  key={detail}
                  className={`flex gap-3 rounded-xl px-3 py-3 ${
                    active ? 'bg-cyan-300/8' : 'text-muted-foreground'
                  }`}
                >
                  <span
                    className={`grid size-6 shrink-0 place-items-center rounded-full text-xs ${
                      active
                        ? 'bg-cyan-300 font-bold text-slate-950'
                        : complete
                          ? 'border border-emerald-300/25 text-emerald-200'
                          : 'border border-white/12'
                    }`}
                  >
                    {complete ? <Check className="size-3.5" /> : step}
                  </span>
                  <div>
                    <p
                      className={
                        active
                          ? 'text-sm font-medium text-cyan-100'
                          : 'text-sm font-medium'
                      }
                    >
                      {label}
                    </p>
                    <p className="mt-1 text-xs leading-5">{detail}</p>
                  </div>
                </li>
              );
            })}
          </ol>

          <div className="mt-8 border-t border-white/8 px-2 pt-5">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <LockKeyhole
                className="size-3.5 text-emerald-300"
                aria-hidden="true"
              />
              当前查询 profiling：0
            </div>
            <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
              <ShieldCheck
                className="size-3.5 text-emerald-300"
                aria-hidden="true"
              />
              hard constraints 已锁定
            </div>
          </div>
        </aside>

        <section className="min-w-0 space-y-5">
          {(connectionError || actionError) && (
            <div
              role="alert"
              className="flex items-start gap-3 rounded-xl border border-amber-300/20 bg-amber-300/[0.055] px-4 py-3 text-sm text-amber-100"
            >
              <AlertTriangle
                className="mt-0.5 size-4 shrink-0"
                aria-hidden="true"
              />
              <span>
                {actionError ??
                  '本地控制服务尚未启动。界面会保持只读，不会生成 authority event。'}
              </span>
            </div>
          )}

          <div className="rounded-2xl border border-white/8 bg-card/70 p-5 shadow-[0_28px_80px_rgba(2,8,23,0.28)] sm:p-7">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <Badge
                  className={
                    ready
                      ? 'bg-emerald-300/12 text-emerald-200'
                      : 'bg-cyan-300/12 text-cyan-200'
                  }
                >
                  {ready
                    ? 'Ready for sealed handoff'
                    : 'Awaiting explicit authority'}
                </Badge>
                <h1 className="mt-4 text-2xl font-semibold tracking-[-0.035em] sm:text-3xl">
                  {heading}
                </h1>
                <p className="mt-2 max-w-2xl text-base leading-7 text-muted-foreground">
                  {ready
                    ? '只会执行已由当前 authority event chain 选中的语义计划。'
                    : '这个选择会改变查询语义；系统不会根据成本、候选顺序或 ontology 距离替你决定。'}
                </p>
              </div>
              <div className="rounded-xl border border-white/8 bg-black/15 px-3 py-2 text-right">
                <p className="text-xs text-muted-foreground">
                  Authority events
                </p>
                <p className="mt-1 font-mono text-sm text-cyan-200">
                  {completedSteps} / 2
                </p>
              </div>
            </div>

            <Progress value={progress} className="mt-7">
              <ProgressLabel>语义澄清</ProgressLabel>
              <ProgressValue>{() => `${progress}%`}</ProgressValue>
            </Progress>

            <div className="mt-7 rounded-xl border border-white/8 bg-slate-950/45 p-4 sm:p-5">
              <div className="flex items-start gap-3">
                <Braces
                  className="mt-0.5 size-4 shrink-0 text-cyan-300"
                  aria-hidden="true"
                />
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                    Original query
                  </p>
                  <p className="mt-2 text-base leading-7 text-slate-100">
                    {state?.request.text ??
                      '查找过去一个月与 Alice 有密切资金往来的高风险公司。'}
                  </p>
                </div>
              </div>
            </div>

            {!ready && (
              <div
                className="mt-6 space-y-3"
                aria-describedby="connection-note"
              >
                {options.map((item, index) => (
                  <Button
                    key={item.candidate_id}
                    variant="outline"
                    disabled={!connected || busy || !question}
                    onClick={() => setPendingOption(item)}
                    className="h-auto w-full justify-between border-white/10 bg-white/[0.025] px-4 py-4 text-left opacity-100 disabled:opacity-55"
                  >
                    <span className="flex min-w-0 items-center gap-4">
                      <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/5 font-mono text-xs text-muted-foreground">
                        {String.fromCharCode(65 + index)}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[15px] font-semibold text-slate-100">
                          {item.label}
                        </span>
                        <span className="mt-1 block whitespace-normal text-sm font-normal leading-5 text-muted-foreground">
                          {optionDetails[item.candidate_id] ??
                            '选择这个有界语义候选'}
                        </span>
                        <span className="mt-2 block truncate font-mono text-xs font-normal text-slate-500">
                          {item.candidate_id}
                        </span>
                      </span>
                    </span>
                    {busy ? (
                      <LoaderCircle className="ml-3 size-4 shrink-0 animate-spin text-cyan-300" />
                    ) : (
                      <ArrowRight
                        className="ml-3 size-4 shrink-0 text-slate-600"
                        aria-hidden="true"
                      />
                    )}
                  </Button>
                ))}
              </div>
            )}

            {ready && clarification?.execution_handoff && (
              <div className="mt-6 space-y-4">
                <div className="rounded-xl border border-emerald-300/15 bg-emerald-300/[0.04] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-emerald-100">
                      {clarification.execution_handoff.selected_plan_count}{' '}
                      个语义计划已封存
                    </p>
                    <span className="font-mono text-xs text-emerald-200/75">
                      {clarification.execution_handoff.expected_remote_calls}{' '}
                      remote calls
                    </span>
                  </div>
                  <ol className="mt-4 space-y-2">
                    {clarification.execution_handoff.selected_plan_ids.map(
                      (planId, index) => (
                        <li
                          key={planId}
                          className="flex gap-3 font-mono text-xs leading-5 text-slate-300"
                        >
                          <span className="text-emerald-300">{index + 1}.</span>
                          <span className="break-all">{planId}</span>
                        </li>
                      ),
                    )}
                  </ol>
                </div>

                {state?.submission_result ? (
                  <div className="rounded-xl border border-white/10 bg-white/[0.025] p-4 text-sm">
                    <p className="font-semibold">
                      提交状态：{state.submission_result.status}
                    </p>
                    {state.submission_result.job_id && (
                      <p className="mt-2 font-mono text-cyan-200">
                        Slurm job {state.submission_result.job_id}
                      </p>
                    )}
                    {state.submission_result.message && (
                      <p className="mt-2 text-muted-foreground">
                        {state.submission_result.message}
                      </p>
                    )}
                  </div>
                ) : (
                  <Button
                    className="w-full"
                    disabled={!state?.submission_enabled || busy}
                    onClick={() => setSubmitOpen(true)}
                  >
                    <Play className="size-4" aria-hidden="true" />
                    {state?.submission_enabled
                      ? '检查并提交到 CWRU'
                      : '远端提交未启用'}
                  </Button>
                )}
              </div>
            )}

            <p
              id="connection-note"
              className="mt-5 text-sm text-muted-foreground"
            >
              {connected
                ? '自由文本不会成为 authority；每个选择都会绑定当前 session 与 question hash。'
                : '连接本地 XGAP 控制服务后才能提交选择；当前界面保持只读。'}
            </p>
          </div>
        </section>

        <aside className="space-y-5">
          <section className="rounded-2xl border border-white/8 bg-card/70 p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold">Execution boundary</h2>
              <Database className="size-4 text-cyan-300" aria-hidden="true" />
            </div>
            <dl className="mt-5 space-y-4 text-sm">
              {[
                ['Semantic authority', 'Explicit user event'],
                ['Physical estimate', 'Family memory'],
                ['Remote tools', 'Neo4j + Fuseki'],
                ['Retry', '0'],
              ].map(([term, value]) => (
                <div
                  key={term}
                  className="flex items-center justify-between gap-4"
                >
                  <dt className="text-muted-foreground">{term}</dt>
                  <dd className="text-right text-slate-200">{value}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="rounded-2xl border border-emerald-300/15 bg-emerald-300/[0.035] p-5">
            <div className="flex items-center gap-2 text-emerald-200">
              <Check className="size-4" aria-hidden="true" />
              <h2 className="text-sm font-semibold">Protected invariants</h2>
            </div>
            <ul className="mt-4 space-y-3 text-sm leading-6 text-muted-foreground">
              <li>时间窗口与 Alice 绑定不可放松</li>
              <li>候选显示顺序不构成 authority</li>
              <li>提交前必须生成 hash-bound handoff</li>
              <li>浏览器不直接访问后端或模型</li>
            </ul>
          </section>

          <section className="rounded-2xl border border-white/8 bg-card/70 p-5">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Session seal
            </p>
            <div className="mt-4 space-y-3 font-mono text-xs text-slate-400">
              <p className="break-all">
                session ·{' '}
                {clarification?.session_sha256?.slice(0, 16) ?? 'waiting'}
              </p>
              <p className="break-all">
                question ·{' '}
                {question?.question_sha256.slice(0, 16) ??
                  (ready ? 'complete' : 'pending')}
              </p>
              <p className="break-all">
                handoff ·{' '}
                {clarification?.execution_handoff?.execution_handoff_sha256.slice(
                  0,
                  16,
                ) ?? 'unavailable'}
              </p>
            </div>
          </section>
        </aside>
      </div>

      <AlertDialog
        open={pendingOption !== null}
        onOpenChange={(open) => !open && setPendingOption(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认这个语义选择？</AlertDialogTitle>
            <AlertDialogDescription>
              “{pendingOption?.label}”将作为显式 authority event
              写入当前会话。这个动作不能在同一事件链中撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>返回</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void confirmPendingOption()}
              disabled={busy}
            >
              确认选择
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={submitOpen} onOpenChange={setSubmitOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>提交已封存的执行会话？</AlertDialogTitle>
            <AlertDialogDescription>
              系统将通过固定 E5D 接口提交一次 Slurm
              作业。同一会话不会自动重试，也不会把凭据发送到浏览器。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>返回</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void confirmSubmission()}
              disabled={busy}
            >
              确认提交
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}
