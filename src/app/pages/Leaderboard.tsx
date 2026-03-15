import { useState, useMemo } from 'react';
import { Trophy, Medal, Crown } from 'lucide-react';

type UserRank = {
  rank: number;
  username: string;
  score: number;
  avatar: string;
  trend: 'up' | 'down' | 'same';
};

// Generate 100 mock users
const generateMockData = (baseScore: number): UserRank[] => {
  let currentScore = baseScore;
  return Array.from({ length: 100 }, (_, i) => {
    if (i > 0) currentScore -= Math.floor(Math.random() * 50 + 10);
    return {
      rank: i + 1,
      username: `User_${Math.floor(Math.random() * 10000)}`,
      score: currentScore,
      avatar: `https://api.dicebear.com/7.x/avataaars/svg?seed=${i}&backgroundColor=transparent`,
      trend: i % 5 === 0 ? 'up' : i % 7 === 0 ? 'down' : 'same',
    };
  });
};

export function Leaderboard() {
  const [activeTab, setActiveTab] = useState<'monthly' | 'weekly'>('monthly');
  
  const monthlyData = useMemo(() => generateMockData(15000), []);
  const weeklyData = useMemo(() => generateMockData(5000), []);

  const data = activeTab === 'monthly' ? monthlyData : weeklyData;

  // Mock "My Profile" data for the header
  const myRankData = {
    rank: 42,
    username: "MyAwesomeCode",
    score: activeTab === 'monthly' ? 8450 : 2100,
    avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=myprofile&backgroundColor=transparent",
  };

  const getRankIcon = (rank: number) => {
    switch (rank) {
      case 1: return <Crown className="text-yellow-400" size={24} />;
      case 2: return <Medal className="text-gray-300" size={24} />;
      case 3: return <Medal className="text-amber-600" size={24} />;
      default: return <span className="font-bold text-gray-500 w-6 text-center">{rank}</span>;
    }
  };

  return (
    <div className="w-full h-full flex flex-col bg-gray-50 dark:bg-[#121212] overflow-hidden transition-colors duration-200">
      <div className="relative flex flex-col items-center justify-center py-8 bg-white dark:bg-[#1e1e1e] border-b border-gray-200 dark:border-[#333] shrink-0 transition-colors duration-200">
        <div className="flex items-center gap-3 mb-5">
          <Trophy className="text-yellow-600 dark:text-yellow-500" size={32} />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white tracking-wide">리더보드</h1>
        </div>
        
        <div className="flex bg-gray-100 dark:bg-[#0d0d0d] p-1.5 rounded-lg border border-gray-200 dark:border-[#333] transition-colors duration-200">
          <button
            onClick={() => setActiveTab('monthly')}
            className={`px-8 py-2 rounded-md text-base font-semibold transition-all ${
              activeTab === 'monthly' ? 'bg-white dark:bg-[#2d2d2d] text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'
            }`}
          >
            월간 랭킹
          </button>
          <button
            onClick={() => setActiveTab('weekly')}
            className={`px-8 py-2 rounded-md text-base font-semibold transition-all ${
              activeTab === 'weekly' ? 'bg-white dark:bg-[#2d2d2d] text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'
            }`}
          >
            주간 랭킹
          </button>
        </div>

        {/* My Profile inline display on the right */}
        <div className="absolute right-8 top-1/2 -translate-y-1/2 flex items-center gap-4 bg-white dark:bg-[#252525] px-6 py-3 rounded-xl border border-gray-200 dark:border-[#333] shadow-sm transition-colors duration-200">
          <img src={myRankData.avatar} alt="My Avatar" className="w-12 h-12 rounded-full bg-gray-50 dark:bg-[#1e1e1e] border-2 border-gray-200 dark:border-[#444]" />
          <div className="flex flex-col">
            <span className="text-base font-bold text-gray-800 dark:text-gray-100">{myRankData.username}</span>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-sm font-bold text-yellow-600 dark:text-yellow-500">#{myRankData.rank}</span>
              <span className="w-1.5 h-1.5 rounded-full bg-gray-300 dark:bg-[#555]"></span>
              <span className="text-sm text-blue-600 dark:text-blue-400 font-mono font-bold">{myRankData.score.toLocaleString()} 점</span>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden p-6 relative">
        <div className="max-w-4xl mx-auto space-y-2 pb-10">
          <div className="grid grid-cols-[80px_1fr_120px] px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200 dark:border-[#333] mb-4 transition-colors duration-200">
            <div className="text-center">순위</div>
            <div>사용자</div>
            <div className="text-right">점수</div>
          </div>
          
          {data.map((user) => (
            <div 
              key={`${activeTab}-${user.rank}`} 
              className={`grid grid-cols-[80px_1fr_120px] items-center px-6 py-3 rounded-xl border transition-all ${
                user.rank <= 3 
                  ? 'bg-white dark:bg-[#1a1a1a] border-gray-200 dark:border-[#333] hover:border-blue-500/50 hover:bg-gray-50 dark:hover:bg-[#252525] shadow-sm' 
                  : 'bg-transparent border-transparent hover:bg-white dark:hover:bg-[#1a1a1a] hover:border-gray-200 dark:hover:border-[#333]'
              }`}
            >
              <div className="flex justify-center items-center">
                {getRankIcon(user.rank)}
              </div>
              <div className="flex items-center gap-4">
                <img src={user.avatar} alt="avatar" className="w-10 h-10 rounded-full bg-gray-100 dark:bg-[#2d2d2d]" />
                <span className={`font-semibold ${user.rank <= 3 ? 'text-gray-900 dark:text-white text-lg' : 'text-gray-600 dark:text-gray-300'}`}>
                  {user.username}
                </span>
              </div>
              <div className="text-right font-mono font-bold text-blue-600 dark:text-blue-400">
                {user.score.toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}