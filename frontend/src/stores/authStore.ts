import { create } from 'zustand';
import type { UserResponse, LoginData, RegisterData } from '@/api/auth';
import * as authApi from '@/api/auth';
import { storage } from '@/utils/storage';

interface AuthState {
  user: UserResponse | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;

  login: (credentials: LoginData) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
  initialize: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: false,
  error: null,

  login: async (credentials: LoginData) => {
    set({ isLoading: true, error: null });
    try {
      const tokens = await authApi.login(credentials);
      storage.set('accessToken', tokens.access_token);
      storage.set('refreshToken', tokens.refresh_token);

      const user = await authApi.getMe();
      set({ user, isAuthenticated: true, isLoading: false });
    } catch (err: any) {
      const message = err?.response?.data?.error || err?.message || 'Login failed';
      set({ error: message, isLoading: false });
      throw err;
    }
  },

  register: async (data: RegisterData) => {
    set({ isLoading: true, error: null });
    try {
      await authApi.register(data);
      set({ isLoading: false });
    } catch (err: any) {
      const message = err?.response?.data?.error || err?.message || 'Registration failed';
      set({ error: message, isLoading: false });
      throw err;
    }
  },

  logout: () => {
    storage.remove('accessToken');
    storage.remove('refreshToken');
    set({ user: null, isAuthenticated: false });
  },

  fetchUser: async () => {
    try {
      const user = await authApi.getMe();
      set({ user, isAuthenticated: true });
    } catch {
      get().logout();
    }
  },

  initialize: async () => {
    const token = storage.get('accessToken');
    if (!token) {
      set({ isAuthenticated: false, isLoading: false });
      return;
    }
    set({ isLoading: true });
    await get().fetchUser();
    set({ isLoading: false });
  },
}));
