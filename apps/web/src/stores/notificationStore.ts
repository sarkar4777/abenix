import { create } from 'zustand';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const WS_URL = API_URL.replace(/^http/, 'ws');

export interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  is_read: boolean;
  link: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
}

interface NotificationState {
  notifications: Notification[];
  unreadCount: number;
  panelOpen: boolean;
  ws: WebSocket | null;
  dashboardUpdate: number;

  setPanelOpen: (open: boolean) => void;
  togglePanel: () => void;
  fetchNotifications: () => Promise<void>;
  fetchUnreadCount: () => Promise<void>;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  connect: (userId: string) => void;
  disconnect: () => void;
}

function getToken(): string {
  return typeof window !== 'undefined'
    ? localStorage.getItem('access_token') || ''
    : '';
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],
  unreadCount: 0,
  panelOpen: false,
  ws: null,
  dashboardUpdate: 0,

  setPanelOpen: (open) => set({ panelOpen: open }),
  togglePanel: () => set((s) => ({ panelOpen: !s.panelOpen })),

  fetchNotifications: async () => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/api/notifications?per_page=50`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      const json = await res.json();
      set({
        notifications: json.data || [],
        unreadCount: json.meta?.unread ?? 0,
      });
    } catch {
    }
  },

  fetchUnreadCount: async () => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/api/notifications/unread-count`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      const json = await res.json();
      set({ unreadCount: json.data?.unread ?? 0 });
    } catch {
    }
  },

  markRead: async (id) => {
    const token = getToken();
    if (!token) return;
    try {
      await fetch(`${API_URL}/api/notifications/${id}/read`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      set((s) => ({
        notifications: s.notifications.map((n) =>
          n.id === id ? { ...n, is_read: true } : n
        ),
        unreadCount: Math.max(0, s.unreadCount - 1),
      }));
    } catch {
    }
  },

  markAllRead: async () => {
    const token = getToken();
    if (!token) return;
    try {
      await fetch(`${API_URL}/api/notifications/read-all`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      set((s) => ({
        notifications: s.notifications.map((n) => ({ ...n, is_read: true })),
        unreadCount: 0,
      }));
    } catch {
    }
  },

  connect: (userId) => {
    const existing = get().ws;
    if (existing && existing.readyState <= WebSocket.OPEN) return;

    const token = getToken();
    if (!token) return;

    const ws = new WebSocket(`${WS_URL}/api/ws/${userId}?token=${token}`);

    let pingInterval: ReturnType<typeof setInterval> | null = null;

    ws.onopen = () => {
      pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping');
      }, 30000);
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.event === 'pong') return;

        if (msg.event === 'notification') {
          set((s) => ({
            notifications: [msg.data as Notification, ...s.notifications],
            unreadCount: s.unreadCount + 1,
          }));
        }

        if (msg.event === 'dashboard_update') {
          set((s) => ({ dashboardUpdate: s.dashboardUpdate + 1 }));
        }

        if (msg.event === 'usage_warning') {
          const warning: Notification = {
            id: `uw-${Date.now()}`,
            type: 'usage_warning',
            title: 'Usage limit approaching',
            message: `${msg.data.percent}% of daily limit used (${msg.data.used}/${msg.data.limit})`,
            is_read: false,
            link: '/settings/billing',
            metadata: msg.data,
            created_at: new Date().toISOString(),
          };
          set((s) => ({
            notifications: [warning, ...s.notifications],
            unreadCount: s.unreadCount + 1,
          }));
        }
      } catch {
      }
    };

    ws.onclose = () => {
      if (pingInterval) clearInterval(pingInterval);
      set({ ws: null });
      setTimeout(() => {
        if (getToken()) get().connect(userId);
      }, 5000);
    };

    ws.onerror = () => {
      ws.close();
    };

    set({ ws });
  },

  disconnect: () => {
    const { ws } = get();
    if (ws) {
      ws.close();
      set({ ws: null });
    }
  },
}));
