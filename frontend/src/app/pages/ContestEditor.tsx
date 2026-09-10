import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { getCurrentUser } from '../services/authApi';
import { DIFFICULTY_LEVELS } from '../services/problemApi';
import { contestPageRequest, contestRequest, type Contest, type ContestWrite, type NewContestProblem } from '../services/contestApi';

const inputClass = 'w-full rounded border border-slate-300 bg-white px-3 py-2 text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-white';
const kstInput = (value: string) => new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 16);
const newProblem = (): NewContestProblem => ({ title: '', description: '', difficulty: 'iron5', tags: [], points: 100,
  testCases: [{ input: '', expectedOutput: '' }], hiddenTestCases: [] });
type Cases = NewContestProblem['testCases'];
function CaseEditor({ label, cases, onChange }: { label: string; cases: Cases; onChange: (cases: Cases) => void }) {
  return <fieldset className="space-y-2 rounded border border-slate-300 p-3 dark:border-slate-600"><legend className="px-1">{label}</legend>
    {cases.map((tc, i) => <div key={i} className="flex items-start gap-2"><textarea aria-label={`${label} ${i + 1} 입력`} placeholder="입력" className={inputClass} value={tc.input} onChange={e => onChange(cases.map((c,n) => n === i ? {...c,input:e.target.value} : c))} /><textarea aria-label={`${label} ${i + 1} 출력`} placeholder="기대 출력" className={inputClass} value={tc.expectedOutput} onChange={e => onChange(cases.map((c,n) => n === i ? {...c,expectedOutput:e.target.value} : c))} /><button type="button" aria-label={`${label} ${i + 1} 삭제`} onClick={() => onChange(cases.filter((_,n) => n !== i))}>삭제</button></div>)}
    <button type="button" className="text-blue-500" onClick={() => onChange([...cases,{input:'',expectedOutput:''}])}>+ 테스트 추가</button>
  </fieldset>;
}

export function ContestEditor() {
  const { contestId } = useParams(); const navigate = useNavigate();
  const [form,setForm] = useState<ContestWrite>(() => ({title:'',description:'',startsAt:new Date(Date.now()+3600000).toISOString(),endsAt:new Date(Date.now()+10800000).toISOString(),published:false,problems:[]}));
  const [library,setLibrary] = useState<{id:string;title:string;points:number}[]>([]);
  const [libraryTotal,setLibraryTotal] = useState(0);
  const [selected,setSelected] = useState('');
  const [ready,setReady] = useState(false); const [error,setError] = useState(''); const [saving,setSaving] = useState(false);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const user = await getCurrentUser();
        if (user.role !== 'admin') throw new Error('관리자만 대회를 만들 수 있습니다.');
        const page = await contestPageRequest<{id:string;title:string;points:number}>('/library', 50, 0);
        if (cancelled) return; setLibrary(page.items); setLibraryTotal(page.total);
        if (contestId) {
          const data = await contestRequest<ContestWrite & Contest>(`/${contestId}/manage`);
          if (!['draft','upcoming'].includes(data.state)) throw new Error('시작한 대회는 수정할 수 없습니다.');
          if (cancelled) return; setForm(data);
        }
        setReady(true);
      } catch (e) { if (!cancelled) setError((e as Error).message); }
    })();
    return () => { cancelled = true; };
  }, [contestId]);
  const patchProblem = (index: number, changes: Partial<NewContestProblem>) => setForm(f => ({...f,problems:f.problems.map((p,i) => i === index ? {...p,newProblem:{...p.newProblem!,...changes}} : p)}));
  const move = (index:number, delta:number) => setForm(f => {
    const problems = [...f.problems]; const next = index+delta;
    if (next < 0 || next >= problems.length) return f;
    [problems[index],problems[next]]=[problems[next],problems[index]];
    return {...f,problems};
  });
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setError('');
    try {
      const body = {...form, problems: form.problems.map(p => p.newProblem ? {...p, newProblem: {
        ...p.newProblem, tags: p.newProblem.tags.map(t => t.trim()).filter(Boolean),
      }} : p)};
      const saved = await contestRequest<Contest>(contestId ? `/${contestId}` : '',contestId ? 'PUT' : 'POST',body);
      navigate(`/contests/${saved.id}`);
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  };
  return <main className="h-full w-full min-w-0 overflow-y-auto bg-slate-50 p-6 text-slate-900 dark:bg-[#0d1118] dark:text-slate-100"><div className="mx-auto max-w-4xl space-y-6">
    <Link className="text-blue-500" to={contestId ? `/contests/${contestId}` : '/contests'}>← 돌아가기</Link><h1 className="text-3xl font-bold">{contestId ? '대회 관리' : '대회 만들기'}</h1>
    {error && <p role="alert" className="text-red-500">{error}</p>}
    {ready && <form onSubmit={submit} className="space-y-5">
      <label className="block">대회 제목<input required maxLength={120} className={inputClass} value={form.title} onChange={e => setForm({...form,title:e.target.value})} /></label>
      <label className="block">설명 및 규칙 (Markdown)<textarea rows={4} className={inputClass} value={form.description} onChange={e => setForm({...form,description:e.target.value})} /></label>
      <div className="grid gap-4 sm:grid-cols-2"><label>시작 시각 (KST)<input type="datetime-local" required className={inputClass} value={kstInput(form.startsAt)} onChange={e => { if(e.target.value) setForm({...form,startsAt:new Date(`${e.target.value}+09:00`).toISOString()}); }} /></label><label>종료 시각 (KST)<input type="datetime-local" required className={inputClass} value={kstInput(form.endsAt)} onChange={e => { if(e.target.value) setForm({...form,endsAt:new Date(`${e.target.value}+09:00`).toISOString()}); }} /></label></div>
      <section className="space-y-4"><h2 className="text-xl font-semibold">문제 구성</h2><p className="text-sm text-slate-500">신규 문제는 시작 전 비공개이며, 종료 후 일반 문제 목록에 자동 공개됩니다.</p>
        {form.problems.map((p,index) => <article key={index} className="space-y-3 rounded-xl border border-slate-300 p-4 dark:border-slate-700">
          <div className="flex flex-wrap items-center gap-3"><strong className="text-blue-500">{String.fromCharCode(65+index)}</strong><span>{p.newProblem ? '신규 문제' : library.find(q=>q.id===p.problemId)?.title || p.problemId}</span>
            <button type="button" onClick={()=>move(index,-1)} disabled={index===0}>↑</button><button type="button" onClick={()=>move(index,1)} disabled={index===form.problems.length-1}>↓</button><button type="button" className="text-red-500" onClick={()=>setForm({...form,problems:form.problems.filter((_,i)=>i!==index)})}>제거</button></div>
          <label className="block">대회 배점<input type="number" min={1} max={100000} required className={inputClass} value={p.points} onChange={e=>setForm({...form,problems:form.problems.map((v,i)=>i===index?{...v,points:Number(e.target.value)}:v)})} /></label>
          {p.newProblem && <>
            <label className="block">문제 제목<input required className={inputClass} value={p.newProblem.title} onChange={e=>patchProblem(index,{title:e.target.value})} /></label>
            <label className="block">문제 설명 (Markdown)<textarea rows={5} required className={inputClass} value={p.newProblem.description} onChange={e=>patchProblem(index,{description:e.target.value})} /></label>
            <div className="grid gap-3 sm:grid-cols-2"><label>난이도<select className={inputClass} value={p.newProblem.difficulty} onChange={e=>patchProblem(index,{difficulty:e.target.value})}>{DIFFICULTY_LEVELS.map(d=><option key={d} value={d}>{d}</option>)}</select></label><label>일반 문제 점수<input required min={0} type="number" className={inputClass} value={p.newProblem.points} onChange={e=>patchProblem(index,{points:Number(e.target.value)})} /></label></div>
            <label className="block">태그 (쉼표 구분)<input className={inputClass} value={p.newProblem.tags.join(',')} onChange={e=>patchProblem(index,{tags:e.target.value.split(',')})} /></label>
            <CaseEditor label="공개 예제" cases={p.newProblem.testCases} onChange={testCases=>patchProblem(index,{testCases})} />
            <CaseEditor label="숨겨진 테스트" cases={p.newProblem.hiddenTestCases} onChange={hiddenTestCases=>patchProblem(index,{hiddenTestCases})} />
          </>}
        </article>)}
        <div className="flex flex-wrap gap-2"><select aria-label="기존 문제 선택" className={`${inputClass} max-w-md`} value={selected} onChange={e=>setSelected(e.target.value)}><option value="">기존 공개 문제 선택</option>{library.filter(p=>!form.problems.some(cp=>cp.problemId===p.id)).map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select><button type="button" disabled={!selected || form.problems.length>=26} onClick={()=>{const p=library.find(p=>p.id===selected)!;setForm({...form,problems:[...form.problems,{problemId:p.id,points:Math.max(1,p.points)}]});setSelected('');}} className="rounded border px-3 py-2">기존 문제 추가</button>{library.length < libraryTotal && <button type="button" className="rounded border px-3 py-2" onClick={async()=>{try{const page=await contestPageRequest<{id:string;title:string;points:number}>('/library',50,library.length);setLibrary(items=>[...items,...page.items]);setLibraryTotal(page.total);}catch(e){setError((e as Error).message);}}}>문제 더 보기 ({library.length}/{libraryTotal})</button>}<button type="button" disabled={form.problems.length>=26} className="rounded border px-3 py-2" onClick={()=>setForm({...form,problems:[...form.problems,{points:100,newProblem:newProblem()}]})}>신규 문제 추가</button></div>
      </section>
      <label className="flex items-center gap-2"><input type="checkbox" checked={form.published} onChange={e=>setForm({...form,published:e.target.checked})} />대회 공개 및 참가 신청 받기</label>
      <button disabled={saving} className="rounded bg-blue-600 px-6 py-3 font-semibold text-white">{saving?'저장 중…':'대회 저장'}</button>
    </form>}
  </div></main>;
}
