import { useState } from 'react';
import { BuilderPage } from './builder/BuilderPage';
import { StrategyList } from './builder/StrategyList';

/** The Strategy Lab (Mission 13): the builder over the workspace strategy, with the saved
 * strategies beside it. */
export function LabPage() {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className={'lab-page builder-layout' + (collapsed ? ' list-collapsed' : '')} id="lab-page">
      <BuilderPage />
      <StrategyList collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
    </div>
  );
}
