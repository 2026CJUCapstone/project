import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CodeEditor } from './CodeEditor';
import { getAuthOwner, setAuthToken } from '../services/authIdentity';
import { acceptProjectRevision, getProjectBaseRevision, saveCodeProject } from '../services/projectApi';
import { useCompilerStore } from '../store/compilerStore';

vi.mock('@monaco-editor/react', async () => {
  const { useEffect, useRef } = await import('react');
  return {
    useMonaco: () => null,
    default: ({ value, onChange, onMount }: any) => {
      const current = useRef(value);
      current.current = value;
      useEffect(() => {
        onMount({ getValue: () => current.current, setValue: (next: string) => { current.current = next; },
          onDidChangeCursorSelection: () => undefined });
      }, []);
      return <textarea aria-label="test editor" value={value} onChange={event => onChange(event.target.value)} />;
    },
  };
});

const initial = useCompilerStore.getState();
const token = (sub: string) => `header.${btoa(JSON.stringify({ sub }))}.signature`;
const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  localStorage.clear();
  useCompilerStore.setState({ ...initial, codeStorageOwner: 'guest' }, true);
  vi.useFakeTimers();
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset().mockImplementation(async () => new Response(null, { status: 404 }));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function mountEditor() {
  await act(async () => { render(<MemoryRouter><CodeEditor /></MemoryRouter>); });
}

it('enables editor controls only after hydration and clears readiness on unmount', async () => {
  expect(useCompilerStore.getState().isEditorReady).toBe(false);
  await mountEditor();
  expect(useCompilerStore.getState().isEditorReady).toBe(true);
  cleanup();
  expect(useCompilerStore.getState().isEditorReady).toBe(false);
});

it('isolates account/guest drafts and never migrates legacy drafts into an account', () => {
  const store = useCompilerStore.getState();
  localStorage.setItem('b-compiler-editor-code:main', 'unknown legacy owner');
  expect(store.loadCode('main')).toBe('unknown legacy owner');
  store.setCodeStorageOwner('account:alice');
  expect(store.loadCode('main')).toBeNull();
  store.saveCode('alice secret', 'main');
  store.setCodeStorageOwner('account:bob');
  expect(store.loadCode('main')).toBeNull();
  store.saveCode('bob code', 'main');
  store.setCodeStorageOwner('account:alice');
  expect(store.loadCode('main')).toBe('alice secret');
  store.setCodeStorageOwner('guest');
  expect(store.loadCode('main')).toBe('unknown legacy owner');
});

it('preserves an edit immediately when unmounted before the remote debounce', async () => {
  await mountEditor();
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'last keystroke' } });
  cleanup();
  expect(useCompilerStore.getState().loadCode('main')).toBe('last keystroke');
  expect(fetchMock).not.toHaveBeenCalled();
});

it('cancels account A autosave on account B login and does not POST A code with B credentials', async () => {
  setAuthToken(token('alice'));
  useCompilerStore.getState().setCodeStorageOwner(getAuthOwner());
  useCompilerStore.getState().saveCode('alice secret', 'main');
  await mountEditor();
  expect(screen.getByRole('textbox')).toHaveValue('alice secret');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'alice final edit' } });
  await act(async () => { setAuthToken(token('bob')); });
  expect(screen.getByRole('textbox')).not.toHaveValue('alice final edit');
  await act(async () => { vi.advanceTimersByTime(2100); });
  const writes = fetchMock.mock.calls.filter(([, options]) => options?.method === 'PUT');
  expect(writes).toHaveLength(0);
  // A manually invoked save with stale editor ownership is rejected too.
  expect(await saveCodeProject('main', { code:'alice secret', language:'python', title:'main' }, 'account:alice')).toBeNull();
  useCompilerStore.getState().setCodeStorageOwner('account:alice');
  expect(useCompilerStore.getState().loadCode('main')).toBe('alice final edit');
});

it('ignores a late project read from a previous account', async () => {
  let resolveAlice!: (response: Response) => void;
  fetchMock.mockImplementationOnce(() => new Promise(resolve => { resolveAlice = resolve; }));
  setAuthToken(token('alice'));
  await mountEditor();
  await act(async () => { setAuthToken(token('bob')); });
  await act(async () => {
    resolveAlice(new Response(JSON.stringify({ code:'late alice secret', language:'python', updatedAt:'2030-01-01T00:00:00Z' })));
  });
  expect(screen.getByRole('textbox')).not.toHaveValue('late alice secret');
  expect(useCompilerStore.getState().codeStorageOwner).toBe('account:bob');
});

function prepareDraft(user: string, revision = 'base') {
  setAuthToken(token(user));
  const store = useCompilerStore.getState();
  store.setCodeStorageOwner(getAuthOwner());
  store.setLanguage('python');
  store.saveCode('local edit', 'main');
  acceptProjectRevision('main', getAuthOwner(), revision);
}

const project = (code: string, revision: string) => ({ id: 'project', scope: 'main', title: 'main', code,
  revision, language: 'python', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' });
const jsonResponse = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const writes = () => fetchMock.mock.calls.filter(([, options]) => options?.method === 'PUT');

it('stops autosave for stale local drafts and only loads server code after an explicit choice', async () => {
  prepareDraft('conflict-load');
  fetchMock.mockImplementation(async () => jsonResponse(project('other device', 'remote-v2')));
  await mountEditor();
  expect(screen.getByRole('alert')).toHaveTextContent('자동저장을 멈췄으니');
  expect(screen.getByRole('textbox')).toHaveValue('local edit');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'continued local edit' } });
  await act(async () => { vi.advanceTimersByTime(2100); });
  expect(writes()).toHaveLength(0);
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '서버 코드 불러오기' })); });
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByRole('textbox')).toHaveValue('other device');
  expect(getProjectBaseRevision('main', getAuthOwner())).toBe('remote-v2');
  await act(async () => { vi.advanceTimersByTime(2100); });
  expect(writes()).toHaveLength(0);
});

it('uses the displayed revision for an explicit overwrite and rejects a second remote change', async () => {
  prepareDraft('conflict-race');
  let remote = project('other device', 'remote-v2');
  fetchMock.mockImplementation(async (_url, options) => options?.method === 'PUT'
    ? jsonResponse({ detail: 'changed again' }, 409) : jsonResponse(remote));
  await mountEditor();
  remote = project('newer remote edit', 'remote-v3');
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '현재 코드로 덮어쓰기' })); });
  expect(JSON.parse(writes()[0][1]!.body as string)).toMatchObject({ code: 'local edit', expectedRevision: 'remote-v2' });
  expect(screen.getByRole('alert')).toHaveTextContent('newer remote edit');
  expect(screen.getByRole('textbox')).toHaveValue('local edit');
  fetchMock.mockImplementation(async (_url, options) => options?.method === 'PUT'
    ? jsonResponse(project('local edit', 'saved-v4')) : jsonResponse(remote));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '현재 코드로 덮어쓰기' })); });
  expect(JSON.parse(writes()[1][1]!.body as string).expectedRevision).toBe('remote-v3');
  expect(screen.queryByRole('alert')).toBeNull();
  expect(getProjectBaseRevision('main', getAuthOwner())).toBe('saved-v4');
});

it('does not resurrect a remotely deleted project without the user choosing to recreate it', async () => {
  prepareDraft('conflict-deleted');
  await mountEditor();
  expect(screen.getByRole('alert')).toHaveTextContent('서버에서 삭제된 코드');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'retained local' } });
  await act(async () => { vi.advanceTimersByTime(2100); });
  expect(writes()).toHaveLength(0);
  fetchMock.mockImplementation(async () => jsonResponse(project('retained local', 'recreated')));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '현재 코드를 서버에 다시 저장' })); });
  expect(JSON.parse(writes()[0][1]!.body as string)).toMatchObject({ code: 'retained local', expectedRevision: null });
  expect(screen.queryByRole('alert')).toBeNull();
});

it('keeps a loaded tab base revision when another tab changes browser storage', () => {
  prepareDraft('separate-tab');
  localStorage.setItem('b-compiler-project-revision:account%3Aseparate-tab:main', 'another-tab-revision');
  expect(getProjectBaseRevision('main', getAuthOwner())).toBe('base');
});
