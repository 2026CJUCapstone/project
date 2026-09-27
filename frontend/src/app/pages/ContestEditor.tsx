import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { getCurrentUser } from '../services/authApi';
import { getAuthOwner, subscribeAuthIdentity } from '../services/authIdentity';
import { DIFFICULTY_LEVELS, isStoredHiddenTestCase, type HiddenTestCase, type TestCase } from '../services/problemApi';
import { contestPageRequest, contestRequest, type Contest, type ContestManage, type ContestWrite, type NewContestProblem } from '../services/contestApi';
import { JudgePolicyEditor } from '../components/JudgePolicyEditor';
import { ProblemAuthoringPanel } from '../components/ProblemAuthoringPanel';
import { StoredHiddenTestReference } from '../components/StoredHiddenTestReference';
import { HiddenTestFileUpload } from '../components/HiddenTestFileUpload';
import { ReferenceSolutionValidationPanel } from '../components/ReferenceSolutionValidationPanel';

const inputClass = 'w-full rounded border border-slate-300 bg-white px-3 py-2 text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-white';
const kstInput = (value: string) => new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 16);
function getAuthScope(): string {
  if (typeof window === 'undefined') return 'guest';
  const token = window.localStorage.getItem('authToken');
  return token && token !== 'undefined' && token !== 'null' ? `${getAuthOwner()}:${token}` : 'guest';
}
const newProblem = (): NewContestProblem => ({ title: '', description: '', difficulty: 'iron5', tags: [], points: 100,
  testCases: [{ input: '', expectedOutput: '' }], hiddenTestCases: [] });
const newContestForm = (): ContestWrite => ({title:'',description:'',startsAt:new Date(Date.now()+3600000).toISOString(),endsAt:new Date(Date.now()+10800000).toISOString(),published:false,problems:[]});
const editorSession = (scope: string, contestId?: string) => `${scope}\u0000${contestId ?? 'new'}`;
type Cases = TestCase[];
function CaseEditor({ label, cases, onChange }: { label: string; cases: Cases; onChange: (cases: Cases) => void }) {
  return <fieldset className="space-y-2 rounded border border-slate-300 p-3 dark:border-slate-600"><legend className="px-1">{label}</legend>
    {cases.map((tc, i) => <div key={i} className="flex items-start gap-2"><textarea aria-label={`${label} ${i + 1} 입력`} placeholder="입력" className={inputClass} value={tc.input} onChange={e => onChange(cases.map((c,n) => n === i ? {...c,input:e.target.value} : c))} /><textarea aria-label={`${label} ${i + 1} 출력`} placeholder="기대 출력" className={inputClass} value={tc.expectedOutput} onChange={e => onChange(cases.map((c,n) => n === i ? {...c,expectedOutput:e.target.value} : c))} /><button type="button" aria-label={`${label} ${i + 1} 삭제`} onClick={() => onChange(cases.filter((_,n) => n !== i))}>삭제</button></div>)}
    <button type="button" className="text-blue-500" onClick={() => onChange([...cases,{input:'',expectedOutput:''}])}>+ 테스트 추가</button>
  </fieldset>;
}
type HiddenCases = HiddenTestCase[];
function HiddenCaseEditor({ cases, onChange, uploadTargetKey, uploadDisabled = false, onStoredUploaded, onUploadBusyChange }: {
  cases: HiddenCases; onChange: (cases: HiddenCases) => void; uploadTargetKey?: string; uploadDisabled?: boolean;
  onStoredUploaded?: (testCase: HiddenTestCase) => void; onUploadBusyChange?: (busy: boolean) => void;
}) {
  return <fieldset className="space-y-2 rounded border border-slate-300 p-3 dark:border-slate-600"><legend className="px-1">숨겨진 테스트</legend>
    {cases.map((tc, i) => isStoredHiddenTestCase(tc) ? <StoredHiddenTestReference key={i} testCase={tc} ordinal={i + 1} label="숨겨진 테스트" canRemove onRemove={() => onChange(cases.filter((_, n) => n !== i))} /> : <div key={i} className="flex items-start gap-2"><textarea aria-label={`숨겨진 테스트 ${i + 1} 입력`} placeholder="입력" className={inputClass} value={tc.input} onChange={e => onChange(cases.map((c,n) => n === i && !isStoredHiddenTestCase(c) ? {...c,input:e.target.value} : c))} /><textarea aria-label={`숨겨진 테스트 ${i + 1} 출력`} placeholder="기대 출력" className={inputClass} value={tc.expectedOutput} onChange={e => onChange(cases.map((c,n) => n === i && !isStoredHiddenTestCase(c) ? {...c,expectedOutput:e.target.value} : c))} /><button type="button" aria-label={`숨겨진 테스트 ${i + 1} 삭제`} onClick={() => onChange(cases.filter((_,n) => n !== i))}>삭제</button></div>)}
    <button type="button" className="text-blue-500" onClick={() => onChange([...cases,{input:'',expectedOutput:''}])}>+ 테스트 추가</button>
    {uploadTargetKey && onStoredUploaded && <HiddenTestFileUpload targetKey={uploadTargetKey} disabled={uploadDisabled} onBusyChange={onUploadBusyChange} onUploaded={onStoredUploaded} />}
  </fieldset>;
}

const hiddenUploadTarget = (session: string, index: number, problem: ContestWrite['problems'][number]) => `${session}\u0001${index}\u0001${problem.problemId ?? 'new'}\u0001${problem.newProblem?.title ?? ''}`;

export function ContestEditor() {
  const { contestId } = useParams(); const navigate = useNavigate();
  const authScope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  const session = editorSession(authScope, contestId);
  const [form,setForm] = useState<ContestWrite>(newContestForm);
  const [library,setLibrary] = useState<{id:string;title:string;points:number}[]>([]);
  const [libraryTotal,setLibraryTotal] = useState(0);
  const [selected,setSelected] = useState('');
  const [authoring,setAuthoring] = useState<NonNullable<ContestManage['authoring']>>({});
  const [savedValidation,setSavedValidation] = useState<Record<string, { policy: NewContestProblem['judgePolicy']; authoring?: NonNullable<ContestManage['authoring']>[string] }>>({});
  const [authorizedSession,setAuthorizedSession] = useState<string | null>(null);
  const [ready,setReady] = useState(false); const [error,setError] = useState(''); const [saving,setSaving] = useState(false);
  const [uploadingTargets,setUploadingTargets] = useState<Record<string, true>>({});
  const sessionEpochRef = useRef(0);
  const loadMoreControllerRef = useRef<AbortController | null>(null);
  const submitControllerRef = useRef<AbortController | null>(null);
  const requestIsCurrent = (epoch: number, scope: string) => sessionEpochRef.current === epoch && getAuthScope() === scope;
  useEffect(() => {
    const epoch = sessionEpochRef.current + 1;
    sessionEpochRef.current = epoch;
    let cancelled = false;
    const controller = new AbortController();
    loadMoreControllerRef.current?.abort();
    submitControllerRef.current?.abort();
    // A route or account belongs to a separate private editing session. Never
    // allow the prior session's draft, library or authoring record to reappear.
    setForm(newContestForm()); setLibrary([]); setLibraryTotal(0); setSelected(''); setAuthoring({}); setSavedValidation({});
    setSaving(false); setUploadingTargets({}); setReady(false); setAuthorizedSession(null); setError('');
    const active = () => !cancelled && requestIsCurrent(epoch, authScope);
    void (async () => {
      try {
        const user = await getCurrentUser();
        if (!active()) return;
        if (user.role !== 'admin') throw new Error('관리자만 대회를 만들 수 있습니다.');
        const page = await contestPageRequest<{id:string;title:string;points:number}>('/library', 50, 0, controller.signal);
        if (!active()) return; setLibrary(page.items); setLibraryTotal(page.total);
        if (contestId) {
          const data = await contestRequest<ContestManage>(`/${contestId}/manage`, 'GET', undefined, controller.signal);
          if (!['draft','upcoming'].includes(data.state)) throw new Error('시작한 대회는 수정할 수 없습니다.');
          if (!active()) return;
          setForm(data);
          setAuthoring(data.authoring ?? {});
          setSavedValidation(Object.fromEntries(data.problems.flatMap(problem => problem.contestProblemId ? [[problem.contestProblemId, {
            policy: problem.newProblem?.judgePolicy,
            authoring: problem.problemId ? data.authoring?.[problem.problemId] : undefined,
          }]] : [])));
        }
        if (!active()) return;
        setAuthorizedSession(session); setReady(true);
      } catch (e) { if (active() && !(e instanceof DOMException && e.name === 'AbortError')) setError((e as Error).message); }
    })();
    return () => {
      cancelled = true;
      controller.abort();
      loadMoreControllerRef.current?.abort();
      submitControllerRef.current?.abort();
      // Unmounting without a scope change must fence late saves too. A new
      // effect increments again, so no prior request can match its epoch.
      if (sessionEpochRef.current === epoch) sessionEpochRef.current = epoch + 1;
    };
  }, [contestId, authScope, session]);
  const patchProblem = (index: number, changes: Partial<NewContestProblem>) => setForm(f => ({...f,problems:f.problems.map((p,i) => i === index ? {...p,newProblem:{...p.newProblem!,...changes}} : p)}));
  const move = (index:number, delta:number) => setForm(f => {
    const problems = [...f.problems]; const next = index+delta;
    if (next < 0 || next >= problems.length) return f;
    [problems[index],problems[next]]=[problems[next],problems[index]];
    return {...f,problems};
  });
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (Object.keys(uploadingTargets).length) {
      setError('숨김 테스트 파일 업로드가 끝난 뒤 대회를 저장할 수 있습니다.');
      return;
    }
    const epoch = sessionEpochRef.current;
    const scope = authScope;
    if (authorizedSession !== session || !requestIsCurrent(epoch, scope)) return;
    submitControllerRef.current?.abort();
    const controller = new AbortController();
    submitControllerRef.current = controller;
    setSaving(true); setError('');
    try {
      const body: ContestWrite = {
        title: form.title,
        description: form.description,
        startsAt: form.startsAt,
        endsAt: form.endsAt,
        published: form.published,
        problems: form.problems.map(({ contestProblemId: _contestProblemId, ...p }) => p.newProblem ? {...p, newProblem: {
          ...p.newProblem, tags: p.newProblem.tags.map(t => t.trim()).filter(Boolean),
        }} : p),
      };
      const saved = await contestRequest<Contest>(contestId ? `/${contestId}` : '',contestId ? 'PUT' : 'POST',body,controller.signal);
      if (!requestIsCurrent(epoch, scope) || submitControllerRef.current !== controller) return;
      navigate(`/contests/${saved.id}`);
    } catch (e) { if (requestIsCurrent(epoch, scope) && submitControllerRef.current === controller && !(e instanceof DOMException && e.name === 'AbortError')) setError((e as Error).message); }
    finally { if (requestIsCurrent(epoch, scope) && submitControllerRef.current === controller) setSaving(false); }
  };
  const loadMore = async () => {
    const epoch = sessionEpochRef.current;
    const scope = authScope;
    if (authorizedSession !== session || !requestIsCurrent(epoch, scope)) return;
    loadMoreControllerRef.current?.abort();
    const controller = new AbortController();
    loadMoreControllerRef.current = controller;
    try {
      const page = await contestPageRequest<{id:string;title:string;points:number}>('/library',50,library.length,controller.signal);
      if (!requestIsCurrent(epoch, scope) || loadMoreControllerRef.current !== controller) return;
      setLibrary(items=>[...items,...page.items]); setLibraryTotal(page.total);
    } catch(e) { if (requestIsCurrent(epoch, scope) && loadMoreControllerRef.current === controller && !(e instanceof DOMException && e.name === 'AbortError')) setError((e as Error).message); }
  };
  return <main className="h-full w-full min-w-0 overflow-y-auto bg-slate-50 p-6 text-slate-900 dark:bg-[#0d1118] dark:text-slate-100"><div className="mx-auto max-w-4xl space-y-6">
    <Link className="text-blue-500" to={contestId ? `/contests/${contestId}` : '/contests'}>← 돌아가기</Link><h1 className="text-3xl font-bold">{contestId ? '대회 관리' : '대회 만들기'}</h1>
    {error && <p role="alert" className="text-red-500">{error}</p>}
    {ready && authorizedSession === session && <form onSubmit={submit} className="space-y-5">
      <label className="block">대회 제목<input required maxLength={120} className={inputClass} value={form.title} onChange={e => setForm({...form,title:e.target.value})} /></label>
      <label className="block">설명 및 규칙 (Markdown)<textarea rows={4} className={inputClass} value={form.description} onChange={e => setForm({...form,description:e.target.value})} /></label>
      <div className="grid gap-4 sm:grid-cols-2"><label>시작 시각 (KST)<input type="datetime-local" required className={inputClass} value={kstInput(form.startsAt)} onChange={e => { if(e.target.value) setForm({...form,startsAt:new Date(`${e.target.value}+09:00`).toISOString()}); }} /></label><label>종료 시각 (KST)<input type="datetime-local" required className={inputClass} value={kstInput(form.endsAt)} onChange={e => { if(e.target.value) setForm({...form,endsAt:new Date(`${e.target.value}+09:00`).toISOString()}); }} /></label></div>
      <section className="space-y-4"><h2 className="text-xl font-semibold">문제 구성</h2><p className="text-sm text-slate-500">신규 문제는 시작 전 비공개이며, 종료 후 일반 문제 목록에 자동 공개됩니다.</p>
        {form.problems.map((p,index) => {
          const uploadTargetKey = hiddenUploadTarget(session, index, p);
          const appendStoredHiddenTest = (testCase: HiddenTestCase) => setForm(current => {
            const target = current.problems[index];
            if (!target?.newProblem || hiddenUploadTarget(session, index, target) !== uploadTargetKey) return current;
            return {...current, problems: current.problems.map((item, itemIndex) => itemIndex === index && item.newProblem ? {...item, newProblem: {...item.newProblem, hiddenTestCases: [...item.newProblem.hiddenTestCases, testCase]}} : item)};
          });
          const setUploadBusy = (busy: boolean) => setUploadingTargets(current => {
            const next = {...current};
            if (busy) next[uploadTargetKey] = true;
            else delete next[uploadTargetKey];
            return next;
          });
          return <article key={index} className="space-y-3 rounded-xl border border-slate-300 p-4 dark:border-slate-700">
          <div className="flex flex-wrap items-center gap-3"><strong className="text-blue-500">{String.fromCharCode(65+index)}</strong><span>{p.newProblem ? '신규 문제' : library.find(q=>q.id===p.problemId)?.title || p.problemId}</span>
            <button type="button" onClick={()=>move(index,-1)} disabled={index===0}>↑</button><button type="button" onClick={()=>move(index,1)} disabled={index===form.problems.length-1}>↓</button><button type="button" className="text-red-500" onClick={()=>setForm({...form,problems:form.problems.filter((_,i)=>i!==index)})}>제거</button></div>
          <label className="block">대회 배점<input type="number" min={1} max={100000} required className={inputClass} value={p.points} onChange={e=>setForm({...form,problems:form.problems.map((v,i)=>i===index?{...v,points:Number(e.target.value)}:v)})} /></label>
          {p.newProblem && <>
            <label className="block">문제 제목<input required className={inputClass} value={p.newProblem.title} onChange={e=>patchProblem(index,{title:e.target.value})} /></label>
            <label className="block">문제 설명 (Markdown)<textarea rows={5} required className={inputClass} value={p.newProblem.description} onChange={e=>patchProblem(index,{description:e.target.value})} /></label>
            <div className="grid gap-3 sm:grid-cols-2"><label>난이도<select className={inputClass} value={p.newProblem.difficulty} onChange={e=>patchProblem(index,{difficulty:e.target.value})}>{DIFFICULTY_LEVELS.map(d=><option key={d} value={d}>{d}</option>)}</select></label><label>일반 문제 점수<input required min={0} type="number" className={inputClass} value={p.newProblem.points} onChange={e=>patchProblem(index,{points:Number(e.target.value)})} /></label></div>
            <label className="block">태그 (쉼표 구분)<input className={inputClass} value={p.newProblem.tags.join(',')} onChange={e=>patchProblem(index,{tags:e.target.value.split(',')})} /></label>
            <CaseEditor label="공개 예제" cases={p.newProblem.testCases} onChange={testCases=>patchProblem(index,{testCases})} />
            <HiddenCaseEditor cases={p.newProblem.hiddenTestCases} onChange={hiddenTestCases=>patchProblem(index,{hiddenTestCases})} uploadTargetKey={uploadTargetKey} uploadDisabled={saving} onStoredUploaded={appendStoredHiddenTest} onUploadBusyChange={setUploadBusy} />
            <JudgePolicyEditor policy={p.newProblem.judgePolicy} onReplace={judgePolicy=>patchProblem(index,{judgePolicy})} />
          </>}
          {p.problemId ? <ProblemAuthoringPanel problemId={p.problemId} isAdmin={authorizedSession === session} initialRecord={authoring[p.problemId]} /> : <details className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-950"><summary className="cursor-pointer font-semibold">출처·검수 기록</summary><p className="mt-2 text-slate-600 dark:text-slate-300">신규 문제의 출처와 검수 기록은 대회를 저장해 문제 ID가 만들어진 뒤에 작성할 수 있습니다.</p></details>}
          <ReferenceSolutionValidationPanel contestId={contestId} contestProblemId={p.contestProblemId} policy={p.contestProblemId ? savedValidation[p.contestProblemId]?.policy : undefined} authoring={p.contestProblemId ? savedValidation[p.contestProblemId]?.authoring : undefined} isAdmin={authorizedSession === session} />
        </article>;
        })}
        <div className="flex flex-wrap gap-2"><select aria-label="기존 문제 선택" className={`${inputClass} max-w-md`} value={selected} onChange={e=>setSelected(e.target.value)}><option value="">기존 공개 문제 선택</option>{library.filter(p=>!form.problems.some(cp=>cp.problemId===p.id)).map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select><button type="button" disabled={!selected || form.problems.length>=26} onClick={()=>{const p=library.find(p=>p.id===selected)!;setForm({...form,problems:[...form.problems,{problemId:p.id,points:Math.max(1,p.points)}]});setSelected('');}} className="rounded border px-3 py-2">기존 문제 추가</button>{library.length < libraryTotal && <button type="button" className="rounded border px-3 py-2" onClick={()=>void loadMore()}>문제 더 보기 ({library.length}/{libraryTotal})</button>}<button type="button" disabled={form.problems.length>=26} className="rounded border px-3 py-2" onClick={()=>setForm({...form,problems:[...form.problems,{points:100,newProblem:newProblem()}]})}>신규 문제 추가</button></div>
      </section>
      <label className="flex items-center gap-2"><input type="checkbox" checked={form.published} onChange={e=>setForm({...form,published:e.target.checked})} />대회 공개 및 참가 신청 받기</label>
      <button disabled={saving || Object.keys(uploadingTargets).length > 0} className="rounded bg-blue-600 px-6 py-3 font-semibold text-white">{saving ? '저장 중…' : Object.keys(uploadingTargets).length ? '파일 업로드 완료 대기' : '대회 저장'}</button>
    </form>}
  </div></main>;
}
