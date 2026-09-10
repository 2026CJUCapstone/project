import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Header } from './Header';
import { useCompilerStore } from '../store/compilerStore';
vi.mock('./AuthModal', () => ({ AuthModal: () => null }));
vi.mock('./ProfileStatsPanel', () => ({ ProfileStatsPanel: () => null }));
const initial = useCompilerStore.getState();
beforeEach(() => { localStorage.clear(); useCompilerStore.setState(initial, true); });
afterEach(() => { cleanup(); useCompilerStore.setState(initial, true); });

it('blocks editor actions before the current editor has loaded its saved code', () => {
  render(<MemoryRouter initialEntries={['/ide']}><Header /></MemoryRouter>);
  expect(screen.getByTitle('실행 언어 선택')).toBeDisabled();
  expect(screen.getByTitle('저장')).toBeDisabled();
  expect(screen.getByTestId('compile-button')).toBeDisabled();
  expect(screen.getByTestId('compile-run-button')).toBeDisabled();
  act(() => useCompilerStore.getState().setEditorReady(true));
  expect(screen.getByTitle('실행 언어 선택')).toBeEnabled();
  expect(screen.getByTitle('저장')).toBeEnabled();
  expect(screen.getByTestId('compile-button')).toBeEnabled();
  expect(screen.getByTestId('compile-run-button')).toBeEnabled();
  act(() => useCompilerStore.getState().setEditorReady(false));
  expect(screen.getByTitle('실행 언어 선택')).toBeDisabled();
});
