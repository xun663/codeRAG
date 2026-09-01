import client from './client';

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserResponse {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface RegisterData {
  username: string;
  email: string;
  password: string;
  display_name?: string;
}

export interface LoginData {
  username: string;
  password: string;
}

export function login(data: LoginData): Promise<TokenResponse> {
  return client.post('/auth/login', data).then((res) => res.data);
}

export function register(data: RegisterData): Promise<UserResponse> {
  return client.post('/auth/register', data).then((res) => res.data);
}

export function refreshToken(refreshToken: string): Promise<TokenResponse> {
  return client.post('/auth/refresh', { refresh_token: refreshToken }).then((res) => res.data);
}

export function getMe(): Promise<UserResponse> {
  return client.get('/auth/me').then((res) => res.data);
}
