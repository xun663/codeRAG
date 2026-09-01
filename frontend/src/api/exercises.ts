import client from './client';

export interface ExerciseResponse {
  id: string;
  type: 'concept_match' | 'code_fill' | 'output_predict' | 'error_diagnose';
  question: string;
  options: Record<string, string>;
  difficulty: string;
  priority: string;
  topic: string | null;
  tags: string[] | null;
  is_new: boolean;
  sm2_state: SM2State | null;
}

export interface SM2State {
  interval: number;
  ease_factor: number;
  repetitions: number;
  due_date: string;
  is_mastered: boolean;
  is_weak: boolean;
}

export interface SessionStartResponse {
  session_id: string;
  exercises: ExerciseResponse[];
  total_available: number;
  stats: ExerciseStats | null;
}

export interface ExerciseStats {
  kb_id: string;
  total_exercises: number;
  attempted: number;
  mastered: number;
  weak_points: number;
  wrong_count: number;
  due_for_review: number;
  new_available: number;
  overall_accuracy: number;
}

export interface AnswerSubmitResponse {
  correct: boolean;
  correct_answer: string;
  explanation: string | null;
  sm2_state: SM2State;
}

export interface GenerateResponse {
  kb_id: string;
  total_chunks: number;
  processed: number;
  exercises_created: number;
  errors: number;
}

export interface GenerateAsyncResponse {
  kb_id: string;
  task_id: string;
  status: string;
}

export interface TaskStatusResponse {
  task_id: string;
  status: string;
  result: GenerateResponse | null;
}

// ── API calls ──────────────────────────────────────────────────────

export function generateExercises(kbId: string, limit?: number): Promise<GenerateResponse> {
  return client.post('/exercises/generate', { kb_id: kbId, limit }).then((res) => res.data);
}

/** Submit exercise generation as a background Celery task. */
export function generateExercisesAsync(kbId: string, limit?: number): Promise<GenerateAsyncResponse> {
  return client.post('/exercises/generate-async', { kb_id: kbId, limit }).then((res) => res.data);
}

/** Poll the status of an exercise generation task. */
export function getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
  return client.get(`/exercises/tasks/${taskId}`).then((res) => res.data);
}

export function startSession(
  kbId: string,
  opts?: { topic?: string; limit?: number; mode?: 'new' | 'due' | 'review' | 'wrong' | 'all' }
): Promise<SessionStartResponse> {
  return client.post('/exercises/sessions/start', {
    kb_id: kbId,
    topic: opts?.topic,
    limit: opts?.limit ?? 10,
    mode: opts?.mode ?? 'all',
  }).then((res) => res.data);
}

export function submitAnswer(exerciseId: string, selected: string): Promise<AnswerSubmitResponse> {
  return client.post('/exercises/sessions/answer', { exercise_id: exerciseId, selected }).then((res) => res.data);
}

export function getStats(kbId: string): Promise<ExerciseStats> {
  return client.get(`/exercises/stats/${kbId}`).then((res) => res.data);
}
