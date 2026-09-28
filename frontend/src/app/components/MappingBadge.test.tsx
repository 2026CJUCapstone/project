import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ASTGraph, SourceRange } from '../services/compilerApi';
import { MappingBadge } from './MappingBadge';

const range: SourceRange = { startLine: 1, startColumn: 1, endLine: 1, endColumn: 2, astNodeId: 'node' };

function ast(type: string): ASTGraph {
  return { nodes: [{ id: 'node', type, label: 'node', children: [] }], edges: [] };
}

describe('MappingBadge', () => {
  it('marks a direct expression mapping as exact', () => {
    render(<MappingBadge ranges={[range]} ast={ast('Ident')} />);

    expect(screen.getByText('표현식 연결')).toHaveAttribute('data-mapping-quality', 'expression');
  });

  it('marks a direct statement mapping', () => {
    render(<MappingBadge ranges={[range]} ast={ast('Return')} />);

    expect(screen.getByText('문장 범위')).toHaveAttribute('data-mapping-quality', 'statement');
  });

  it('marks generated and unavailable source mappings without inventing a range', () => {
    const { rerender } = render(<MappingBadge generated generatedReason="lowering" />);
    expect(screen.getByText('컴파일러 생성 · 소스 없음')).toHaveAttribute('data-mapping-quality', 'generated');
    expect(screen.getByText('컴파일러 생성 · 소스 없음')).toHaveAttribute('title', expect.stringContaining('lowering'));

    rerender(<MappingBadge />);
    expect(screen.getByText('소스 연결 없음')).toHaveAttribute('data-mapping-quality', 'unavailable');
  });

  it('marks approximate legacy positions instead of reporting them as direct mappings', () => {
    render(<MappingBadge ranges={[range]} ast={ast('Ident')} approximate />);

    expect(screen.getByText('근사 연결')).toHaveAttribute('data-mapping-quality', 'approximate');
  });
});
