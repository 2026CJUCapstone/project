import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { User, LogOut, Settings, ChevronDown } from 'lucide-react';

interface UserProfileProps {
  username: string;
  avatarUrl: string;
  onLogout: () => void;
}

export function UserProfile({ username, avatarUrl, onLogout }: UserProfileProps) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger className="flex items-center gap-2 px-2 py-1.5 hover:bg-gray-100 dark:hover:bg-[#2d2d2d] border border-transparent hover:border-gray-200 dark:hover:border-[#444] rounded-md transition-all outline-none">
        <img 
          src={avatarUrl} 
          alt={username} 
          className="w-7 h-7 rounded-full object-cover border border-gray-200 dark:border-[#444]" 
        />
        <span className="text-sm font-medium text-gray-700 dark:text-gray-200 hidden sm:block">{username}</span>
        <ChevronDown size={14} className="text-gray-500 dark:text-gray-400" />
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content 
          className="min-w-[200px] bg-white dark:bg-[#1e1e1e] border border-gray-200 dark:border-[#333] rounded-lg p-1.5 shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-150 data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=closed]:zoom-out-95" 
          sideOffset={8} 
          align="end"
        >
          <div className="px-3 py-2.5 mb-1.5 border-b border-gray-200 dark:border-[#333]">
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">로그인된 계정</p>
            <p className="text-sm font-bold text-gray-900 dark:text-gray-100 truncate">{username}</p>
          </div>
          
          <DropdownMenu.Item className="flex items-center gap-3 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#2d2d2d] rounded-md cursor-pointer outline-none transition-colors">
            <User size={16} className="text-gray-500 dark:text-gray-400" /> 내 프로필
          </DropdownMenu.Item>
          
          <DropdownMenu.Item className="flex items-center gap-3 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#2d2d2d] rounded-md cursor-pointer outline-none transition-colors">
            <Settings size={16} className="text-gray-500 dark:text-gray-400" /> 설정
          </DropdownMenu.Item>
          
          <DropdownMenu.Separator className="h-[1px] bg-gray-200 dark:bg-[#333] my-1.5" />
          
          <DropdownMenu.Item 
            className="flex items-center gap-3 px-3 py-2 text-sm font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 hover:text-red-700 dark:hover:text-red-300 rounded-md cursor-pointer outline-none transition-colors"
            onClick={onLogout}
          >
            <LogOut size={16} /> 로그아웃
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
