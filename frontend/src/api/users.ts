import client from './client';

export interface UserInfo {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

/** 按用户名模糊搜索用户（知识库成员分享用）。 */
export function searchUsers(q: string): Promise<UserInfo[]> {
  return client.get('/users/search', { params: { q } }).then((res) => res.data);
}
