import { useState, useEffect, createContext, useContext, useCallback, type ReactNode } from 'react';
import { IconCircleCheck, IconCircleX, IconInfoCircle, IconX } from '@tabler/icons-react';

interface ToastItem {
  id: string;
  type: 'success' | 'error' | 'info';
  message: string;
}

interface ToastContextType {
  showToast: (type: 'success' | 'error' | 'info', message: string) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return context;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const showToast = useCallback((type: 'success' | 'error' | 'info', message: string) => {
    const id = crypto.randomUUID();
    setToasts(prev => [...prev, { id, type, message }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  // Auto dismiss after 1.5 seconds
  useEffect(() => {
    if (toasts.length === 0) return;

    const timers = toasts.map(toast => {
      return setTimeout(() => {
        dismissToast(toast.id);
      }, 1500);
    });

    return () => {
      timers.forEach(t => clearTimeout(t));
    };
  }, [toasts, dismissToast]);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {/* Global Toast Container */}
      <div className="fixed top-4 right-4 z-[200] flex flex-col gap-2">
        {toasts.map(toast => (
          <div
            key={toast.id}
            className={`px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 min-w-[280px] animate-in slide-in-from-top fade-in duration-300 ${
              toast.type === 'success' ? 'bg-[#10B981] text-white' :
              toast.type === 'error' ? 'bg-[#E11D48] text-white' :
              'bg-[#00ADA6] text-white'
            }`}
          >
            {toast.type === 'success' && <IconCircleCheck size={18} />}
            {toast.type === 'error' && <IconCircleX size={18} />}
            {toast.type === 'info' && <IconInfoCircle size={18} />}
            <span className="flex-1 text-sm font-medium">{toast.message}</span>
            <button
              onClick={() => dismissToast(toast.id)}
              className="p-1 hover:bg-white/20 rounded-full transition-colors"
            >
              <IconX size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
