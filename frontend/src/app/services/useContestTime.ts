import { useEffect, useState } from 'react';

/** Advance server UTC locally between polls, independent of the client's clock skew. */
export function useContestTime(serverTime: string) {
  const [anchor, setAnchor] = useState(() => ({ server: Date.parse(serverTime), local: Date.now() }));
  const [now, setNow] = useState(Date.now());
  useEffect(() => { setAnchor({ server: Date.parse(serverTime), local: Date.now() }); }, [serverTime]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return anchor.server + Math.max(0, now - anchor.local);
}
