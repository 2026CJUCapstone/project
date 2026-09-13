import { useId, useState } from 'react';
import { OutputConsole } from './OutputConsole';
import { CustomTestPanel, type CustomTestSample } from './CustomTestPanel';

export function RunOutputPanel({ samples, scopeKey }: { samples?: CustomTestSample[]; scopeKey: string }) {
  const [tab, setTab] = useState<'console' | 'test'>('console');
  const id = useId();
  return <div className="flex h-full min-h-0 min-w-0 flex-col">
    <div role="tablist" aria-label="실행 도구" className="flex shrink-0 gap-1 border-b border-gray-300 px-2 dark:border-[#333]">
      {(['console', 'test'] as const).map(value => <button key={value} type="button" role="tab"
        id={id + value + '-tab'} aria-controls={id + value} aria-selected={tab === value}
        onClick={() => setTab(value)} className={`px-3 py-2 text-xs ${tab === value ? 'border-b-2 border-blue-500 text-blue-500' : 'text-gray-500'}`}>
        {value === 'console' ? '콘솔' : '사용자 테스트'}
      </button>)}
    </div>
    <div role="tabpanel" id={id + 'console'} aria-labelledby={id + 'console-tab'} hidden={tab !== 'console'} className="min-h-0 flex-1"><OutputConsole /></div>
    <div role="tabpanel" id={id + 'test'} aria-labelledby={id + 'test-tab'} hidden={tab !== 'test'} className="min-h-0 flex-1 overflow-y-auto p-2">
      <CustomTestPanel samples={samples} scopeKey={scopeKey} />
    </div>
  </div>;
}
