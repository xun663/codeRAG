/**
 * 安全 localStorage 封装。
 *
 * 手机 Safari 隐私模式 / 第三方存储受限 / 非安全上下文等场景下，直接访问
 * `window.localStorage` 会抛 SecurityError "The operation is insecure"，
 * 导致 axios 请求拦截器、登录态读取等同步崩溃（例：注册请求直接被拦截器搞挂）。
 *
 * 这里统一 try/catch 并降级到内存 Map：存储被拦截时应用仍可用
 * （会话内状态保留，跨刷新不持久——可接受降级），而不是整个功能挂掉。
 */

const memory = new Map<string, string>();

function getValue(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return memory.get(key) ?? null;
  }
}

function setValue(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
    return;
  } catch {
    // 存储被拦截 → 降级内存
  }
  memory.set(key, value);
}

function removeValue(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // 存储被拦截 → 仅清内存
  }
  memory.delete(key);
}

export const storage = {
  get: getValue,
  set: setValue,
  remove: removeValue,
};
