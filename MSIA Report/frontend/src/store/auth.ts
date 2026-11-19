import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { exchangeOtkApi, getMeApi, loginApi, logoutApi, type User } from '@/api/auth';
import { setAuthToken, setOnUnauthorized } from '@/api/client';

const AUTH_STORAGE_KEY = 'msia-auth';

// 鉴权状态
export interface AuthState {
  token: string | null;
  user: User | null;
  loading: boolean;
  rememberMe: boolean;
  lastLoginUsername: string | null;
  savedPassword: string | null;
  // 设置 token（同步到 api client）
  setToken: (token: string | null) => void;
  // 登录
  login: (username: string, password: string, rememberMe?: boolean) => Promise<void>;
  // OIDC 回调: 一次性码换本地 JWT（不保存密码, 不参与 autoLogin;
  // Keycloak SSO 会话负责下次免密, 与本地"记住密码"机制解耦）
  loginWithOtk: (otk: string) => Promise<void>;
  // 自动登录（同一台电脑可直接恢复上次登录）
  autoLogin: () => Promise<boolean>;
  // 登出
  logout: (keepAutoLogin?: boolean) => Promise<void>;
  // 加载当前用户信息
  loadUser: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      loading: false,
      rememberMe: true,
      lastLoginUsername: null,
      savedPassword: null,

      setToken: (token) => {
        setAuthToken(token);
        set({ token });
      },

      login: async (username, password, rememberMe = true) => {
        const res = await loginApi(username, password);
        setAuthToken(res.access_token);
        set({
          token: res.access_token,
          user: res.user,
          rememberMe,
          lastLoginUsername: rememberMe ? username : null,
          savedPassword: rememberMe ? password : null,
        });
      },

      loginWithOtk: async (otk) => {
        const res = await exchangeOtkApi(otk);
        setAuthToken(res.access_token);
        // OIDC 会话不落密码: autoLogin 不会用它重登, Keycloak SSO 会话负责免密
        set({
          token: res.access_token,
          user: res.user,
          rememberMe: false,
          lastLoginUsername: null,
          savedPassword: null,
        });
      },

      autoLogin: async () => {
        const { savedPassword, lastLoginUsername, rememberMe } = get();
        if (!rememberMe || !savedPassword || !lastLoginUsername) {
          return false;
        }
        try {
          const res = await loginApi(lastLoginUsername, savedPassword);
          setAuthToken(res.access_token);
          set({ token: res.access_token, user: res.user });
          return true;
        } catch {
          set({ savedPassword: null, rememberMe: false, lastLoginUsername: null });
          return false;
        }
      },

      logout: async (keepAutoLogin = false) => {
        try {
          await logoutApi();
        } catch {
          // 即使登出接口失败也清理本地状态
        } finally {
          const currentUsername = get().lastLoginUsername;
          const currentPassword = get().savedPassword;
          setAuthToken(null);
          set({
            token: null,
            user: null,
            loading: false,
            rememberMe: Boolean(keepAutoLogin),
            lastLoginUsername: keepAutoLogin ? currentUsername : null,
            savedPassword: keepAutoLogin ? currentPassword : null,
          });
          if (!keepAutoLogin && typeof window !== 'undefined') {
            window.localStorage.removeItem(AUTH_STORAGE_KEY);
          }
        }
      },

      loadUser: async () => {
        set({ loading: true });
        try {
          const user = await getMeApi();
          set({ user });
        } finally {
          set({ loading: false });
        }
      },
    }),
    {
      name: 'msia-auth',
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        rememberMe: state.rememberMe,
        lastLoginUsername: state.lastLoginUsername,
        savedPassword: state.savedPassword,
      }),
      onRehydrateStorage: () => (state) => {
        if (state?.token) {
          setAuthToken(state.token);
        }
      },
    }
  )
);

// 401 时由 axios 拦截器调用: 清除持久化的失效 token/user, 防止登录页
// 据残留 token 跳回看板形成 401 → 刷新死循环
// (保留已保存的账号密码, 登录页可用其自动登录恢复会话)
setOnUnauthorized(() => {
  useAuthStore.setState({ token: null, user: null, loading: false });
  setAuthToken(null);
});
