import React, { useEffect } from 'react';
import {
  Card, Button, Typography, Tag, Space, Progress,
  Radio, App, Row, Col, Statistic, Divider,
  Alert,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined,
  TrophyOutlined, BookOutlined, ExclamationCircleOutlined,
  ReloadOutlined, PlayCircleOutlined, DatabaseOutlined,
  ArrowRightOutlined, ClockCircleOutlined,
  StarOutlined, ThunderboltOutlined, RocketOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import KBSelectorModal from '@/components/Chat/KBSelectorModal';
import MarkdownRenderer from '@/components/common/MarkdownRenderer';
import * as exercisesApi from '@/api/exercises';
import * as kbsApi from '@/api/kbs';
import { useAuthStore } from '@/stores/authStore';
import type { ExerciseResponse, ExerciseStats } from '@/api/exercises';
import type { KBResponse } from '@/api/kbs';

const { Text, Title } = Typography;

// ── Type labels ────────────────────────────────────────────────────
const TYPE_LABELS: Record<string, string> = {
  concept_match: 'Concept',
  code_fill: 'Code Fill',
  output_predict: 'Output Predict',
  error_diagnose: 'Error Diagnosis',
};
const TYPE_COLORS: Record<string, string> = {
  concept_match: 'blue',
  code_fill: 'green',
  output_predict: 'orange',
  error_diagnose: 'red',
};
const DIFFICULTY_COLORS: Record<string, string> = {
  easy: 'green', medium: 'orange', hard: 'red',
};

const QuizPage: React.FC = () => {
  const { message } = App.useApp();
  useTranslation();  // Initialize i18n
  const { user } = useAuthStore();

  // KB selection
  const [showKBSelector, setShowKBSelector] = React.useState(false);
  const [selectedKB, setSelectedKB] = React.useState<KBResponse | null>(null);
  const [kbMap, setKbMap] = React.useState<Record<string, KBResponse>>({});

  // 出题权限：官方库（platform）仅 admin 可生成；个人库可生成（后端再按 owner/写权限校验）
  const canGenerate = !selectedKB || selectedKB.scope !== 'platform' || user?.role === 'admin';

  // Session state
  const [exercises, setExercises] = React.useState<ExerciseResponse[]>([]);
  const [currentIndex, setCurrentIndex] = React.useState(0);
  const [selectedOption, setSelectedOption] = React.useState<string>('');
  const [feedback, setFeedback] = React.useState<exercisesApi.AnswerSubmitResponse | null>(null);
  const [stats, setStats] = React.useState<ExerciseStats | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [genResult, setGenResult] = React.useState<exercisesApi.GenerateResponse | null>(null);
  const [sessionActive, setSessionActive] = React.useState(false);
  const [sessionDone, setSessionDone] = React.useState(false);
  const [score, setScore] = React.useState({ correct: 0, total: 0 });

  // Load KB list
  useEffect(() => {
    kbsApi.listKBs({ page: 1, pageSize: 50 }).then((res) => {
      const map: Record<string, KBResponse> = {};
      for (const kb of res.items || []) map[kb.id] = kb;
      setKbMap(map);
    }).catch(() => {});
  }, []);

  // Start session with mode
  const handleStartSession = async (mode: 'new' | 'due' | 'review' | 'wrong' | 'all' = 'all') => {
    if (!selectedKB) return;
    setLoading(true);
    try {
      const resp = await exercisesApi.startSession(selectedKB.id, { limit: 10, mode });
      setExercises(resp.exercises);
      setStats(resp.stats);
      setCurrentIndex(0);
      setFeedback(null);
      setSelectedOption('');
      setScore({ correct: 0, total: 0 });
      setSessionActive(true);
      setSessionDone(false);
    } catch {
      message.error('Failed to start session');
    }
    setLoading(false);
  };

  // Submit answer
  const handleSubmit = async () => {
    if (!selectedOption || !exercises[currentIndex]) return;

    const ex = exercises[currentIndex];
    try {
      const resp = await exercisesApi.submitAnswer(ex.id, selectedOption);
      setFeedback(resp);

      const newScore = {
        correct: score.correct + (resp.correct ? 1 : 0),
        total: score.total + 1,
      };
      setScore(newScore);
    } catch {
      message.error('Failed to submit answer');
    }
  };

  // Next question
  const handleNext = () => {
    if (currentIndex + 1 >= exercises.length) {
      setSessionDone(true);
      // Refresh stats
      if (selectedKB) {
        exercisesApi.getStats(selectedKB.id).then(setStats).catch(() => {});
      }
    } else {
      setCurrentIndex(currentIndex + 1);
      setFeedback(null);
      setSelectedOption('');
    }
  };

  // Poll task until completion (for async generation)
  const pollTask = async (taskId: string, kbId: string): Promise<void> => {
    for (let i = 0; i < 120; i++) {  // max 120 polls × 3s = 6 min
      await new Promise((r) => setTimeout(r, 3000));
      const task = await exercisesApi.getTaskStatus(taskId);
      if (task.status === 'SUCCESS' && task.result) {
        setGenResult(task.result);
        if (task.result.exercises_created > 0) {
          message.success(`已从 ${task.result.processed} 个切片生成 ${task.result.exercises_created} 道题`);
        }
        if (task.result.errors > 0) {
          message.warning(`${task.result.errors} 个切片处理失败`);
        }
        const s = await exercisesApi.getStats(kbId);
        setStats(s);
        return;
      }
      if (task.status === 'FAILURE') {
        throw new Error(task.result?.errors ? `生成失败` : 'Task failed');
      }
      // 'PENDING' / 'STARTED' / 'RETRY' → keep polling
    }
    throw new Error('Task timed out');
  };

  // Generate exercises
  const handleGenerate = async (limit?: number) => {
    if (!selectedKB) return;
    setGenerating(true);
    setGenResult(null);
    try {
      // 统一走异步 Celery 任务：同步生成 LLM 耗时长（约 15s/chunk），
      // 小批量也会撞上前端 axios 30s 硬超时，故"生成 20 道"也走异步轮询
      const asyncResp = await exercisesApi.generateExercisesAsync(selectedKB.id, limit);
      message.info(`后台生成任务已提交，处理中请稍候...`);
      await pollTask(asyncResp.task_id, selectedKB.id);
    } catch {
      message.error('Generation failed');
    }
    setGenerating(false);
  };

  const handleGenerate20 = () => handleGenerate(20);
  const handleGenerateAll = () => handleGenerate(undefined);

  // KB selection handlers
  const handleKBSelect = async (kbId: string | null) => {
    setShowKBSelector(false);
    if (kbId && kbMap[kbId]) {
      const kb = kbMap[kbId];
      setSelectedKB(kb);
      // Load stats immediately on selection
      try {
        const s = await exercisesApi.getStats(kbId);
        setStats(s);
      } catch { setStats(null); }
    }
  };

  // ── Render: Welcome / KB Selection ───────────────────────────────
  if (!sessionActive) {
    return (
      <div style={{ maxWidth: 600, margin: '40px auto', padding: '0 16px' }}>
        <Card>
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <div style={{ textAlign: 'center' }}>
              <BookOutlined style={{ fontSize: 48, color: '#1677ff' }} />
              <Title level={3} style={{ marginTop: 16 }}>知识复习</Title>
              <Text type="secondary">
                基于知识库自动生成练习题，通过 SM-2 间隔重复算法优化学习效果。
              </Text>
            </div>

            <Divider />

            {/* KB selector */}
            <div>
              <Text strong>选择知识库：</Text>
              <Card
                size="small"
                style={{
                  marginTop: 8, cursor: 'pointer',
                  border: selectedKB ? '2px solid #1677ff' : '1px dashed #d9d9d9',
                  background: selectedKB ? '#f0f5ff' : '#fafafa',
                }}
                onClick={() => setShowKBSelector(true)}
              >
                {selectedKB ? (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <Text strong><DatabaseOutlined /> {selectedKB.name}</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {selectedKB.doc_count} docs · {selectedKB.chunk_count} chunks
                      </Text>
                    </div>
                    <Tag color="blue">{selectedKB.kb_type || 'general'}</Tag>
                  </div>
                ) : (
                  <Text type="secondary">点击选择知识库...</Text>
                )}
              </Card>
            </div>

            {/* Learning Mode Cards */}
            {stats && stats.total_exercises > 0 ? (
              <>
                <Divider />
                {/* Stats row — 移动端 2 列 */}
                <Row gutter={[8, 8]}>
                  <Col xs={12} sm={6}>
                    <Statistic title="新题" value={stats.new_available}
                      prefix={<StarOutlined />} valueStyle={{ color: '#1890ff', fontSize: 18 }} />
                  </Col>
                  <Col xs={12} sm={6}>
                    <Statistic title="待复习" value={stats.due_for_review}
                      prefix={<ClockCircleOutlined />} valueStyle={{ color: '#fa8c16', fontSize: 18 }} />
                  </Col>
                  <Col xs={12} sm={6}>
                    <Statistic title="已掌握" value={stats.mastered}
                      prefix={<TrophyOutlined />} valueStyle={{ color: '#52c41a', fontSize: 18 }} />
                  </Col>
                  <Col xs={12} sm={6}>
                    <Statistic title="薄弱" value={stats.weak_points}
                      prefix={<ExclamationCircleOutlined />} valueStyle={{ color: '#ff4d4f', fontSize: 18 }} />
                  </Col>
                </Row>

                <Divider />

                {/* Mode 1: Continue Learning (New) */}
                <Button
                  type="primary" size="large" block
                  icon={<StarOutlined />}
                  onClick={() => handleStartSession('new')}
                  loading={loading}
                  disabled={stats.new_available === 0}
                >
                  继续学习（{stats.new_available} 道新题）
                </Button>

                {/* Mode 2: Active Review (Past attempts) */}
                <Button
                  size="large" block
                  icon={<ReloadOutlined />}
                  onClick={() => handleStartSession('review')}
                  loading={loading}
                  disabled={stats.attempted === 0}
                  style={{ marginTop: 8 }}
                >
                  复习旧题（已答 {stats.attempted} 道）
                </Button>

                {/* Mode 3.5: 错题本 — 收集答错过至少一次的题目，方便回顾 */}
                <Button
                  size="large" block
                  danger
                  icon={<ExclamationCircleOutlined />}
                  onClick={() => handleStartSession('wrong')}
                  loading={loading}
                  disabled={!stats.wrong_count || stats.wrong_count === 0}
                  style={{ marginTop: 8 }}
                >
                  {stats.wrong_count > 0
                    ? `错题本（${stats.wrong_count} 道答错，点击回顾）`
                    : '错题本（暂无错题）'}
                </Button>

                {/* Mode 3: SM-2 Passive Review */}
                <Button
                  size="large" block
                  icon={<ClockCircleOutlined />}
                  onClick={() => handleStartSession('due')}
                  loading={loading}
                  disabled={stats.due_for_review === 0}
                  style={{ marginTop: 8 }}
                >
                  {stats.due_for_review > 0
                    ? `SM-2 间隔复习（${stats.due_for_review} 道今日到期）`
                    : 'SM-2 间隔复习（暂无到期题目）'}
                </Button>

                {/* Generate more — 官方库仅 admin 可见 */}
                {canGenerate && (
                  <div style={{ textAlign: 'center', marginTop: 12 }}>
                    <Space size={8}>
                      <Button size="small" onClick={handleGenerate20} loading={generating}>
                        生成 20 道
                      </Button>
                      <Button size="small" onClick={handleGenerateAll} loading={generating}>
                        全部生成
                      </Button>
                    </Space>
                    {genResult && genResult.exercises_created > 0 && (
                      <Text type="success" style={{ fontSize: 12, marginLeft: 8 }}>
                        +{genResult.exercises_created}
                      </Text>
                    )}
                  </div>
                )}
              </>
            ) : stats && stats.total_exercises === 0 ? (
              <>
                {canGenerate ? (
                  <>
                    <Alert
                      type="info" showIcon
                      message="暂无练习题"
                      description="该知识库尚未生成练习题。点击下方按钮，LLM 将为知识切片自动生成选择题。"
                      style={{ marginTop: 8 }}
                    />
                    {genResult && (
                      <Alert
                        type={genResult.exercises_created > 0 ? 'success' : 'warning'}
                        showIcon
                        message={`已从 ${genResult.processed} 个切片生成 ${genResult.exercises_created} 道题`}
                        description={genResult.errors > 0 ? `${genResult.errors} 个切片失败，已跳过` : undefined}
                        style={{ marginTop: 8 }}
                      />
                    )}
                    <Space style={{ width: '100%', justifyContent: 'center' }}>
                      <Button
                        type="primary" size="large"
                        icon={<ThunderboltOutlined />}
                        onClick={handleGenerate20}
                        loading={generating}
                      >
                        生成 20 道
                      </Button>
                      <Button
                        size="large"
                        icon={<RocketOutlined />}
                        onClick={handleGenerateAll}
                        loading={generating}
                      >
                        全部生成
                      </Button>
                    </Space>
                  </>
                ) : (
                  <Alert
                    type="warning" showIcon
                    message="该官方知识库暂无练习题"
                    description="官方库的练习题由管理员统一生成，生成后全员可复习。如需补充题目，请联系管理员。"
                    style={{ marginTop: 8 }}
                  />
                )}
              </>
            ) : (
              <Button
                type="primary" size="large" block
                icon={<PlayCircleOutlined />}
                onClick={() => handleStartSession()}
                loading={loading}
                disabled={!selectedKB}
              >
                开始复习
              </Button>
            )}
          </Space>
        </Card>

        <KBSelectorModal
          open={showKBSelector}
          onSelect={handleKBSelect}
          onCancel={() => setShowKBSelector(false)}
          showPureLLM={false}
        />
      </div>
    );
  }

  // ── Render: Session Done ─────────────────────────────────────────
  if (sessionDone) {
    const pct = score.total > 0 ? Math.round((score.correct / score.total) * 100) : 0;
    return (
      <div style={{ maxWidth: 600, margin: '40px auto', padding: '0 16px' }}>
        <Card>
          <div style={{ textAlign: 'center' }}>
            <TrophyOutlined style={{ fontSize: 64, color: pct >= 80 ? '#52c41a' : '#faad14' }} />
            <Title level={2} style={{ marginTop: 16 }}>
              {pct >= 80 ? 'Great Job!' : pct >= 50 ? 'Keep Going!' : 'Practice Makes Perfect'}
            </Title>
            <Progress type="circle" percent={pct} size={120} />
            <div style={{ marginTop: 24 }}>
              <Text>正确：{score.correct} / {score.total}</Text>
            </div>
          </div>

          {stats && (
            <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
              <Col xs={12} sm={8}><Statistic title="已掌握" value={stats.mastered} prefix={<TrophyOutlined />} /></Col>
              <Col xs={12} sm={8}><Statistic title="薄弱点" value={stats.weak_points} prefix={<ExclamationCircleOutlined />} valueStyle={{ color: '#ff4d4f' }} /></Col>
              <Col xs={12} sm={8}><Statistic title="正确率" value={`${Math.round(stats.overall_accuracy * 100)}%`} /></Col>
            </Row>
          )}

          <Space style={{ marginTop: 24, width: '100%', justifyContent: 'center' }}>
            <Button icon={<ReloadOutlined />} onClick={() => handleStartSession()} loading={loading}>
              新一轮
            </Button>
            <Button type="primary" onClick={() => setSessionActive(false)}>
              切换知识库
            </Button>
          </Space>
        </Card>
      </div>
    );
  }

  // ── Render: Active Exercise ──────────────────────────────────────
  const currentEx = exercises[currentIndex];
  if (!currentEx) return null;
  const progress = ((currentIndex + (feedback ? 1 : 0)) / exercises.length) * 100;

  return (
    <div style={{ maxWidth: 700, margin: '20px auto', padding: '0 16px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Space wrap>
          <Tag color="blue" style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            <DatabaseOutlined /> {selectedKB?.name || 'KB'}
          </Tag>
          <Text type="secondary">{currentIndex + 1} / {exercises.length}</Text>
        </Space>
        <Space>
          <Text type="secondary">Score: {score.correct}/{score.total}</Text>
        </Space>
      </div>
      <Progress percent={progress} showInfo={false} style={{ marginBottom: 16 }} />

      {/* Exercise card */}
      <Card
        title={
          <Space wrap>
            <Tag color={TYPE_COLORS[currentEx.type] || 'default'}>
              {TYPE_LABELS[currentEx.type] || currentEx.type}
            </Tag>
            <Tag color={DIFFICULTY_COLORS[currentEx.difficulty] || 'default'}>
              {currentEx.difficulty}
            </Tag>
            {currentEx.topic && <Tag>{currentEx.topic}</Tag>}
            {currentEx.is_new && <Tag color="green">新题</Tag>}
            {currentEx.sm2_state?.is_weak && <Tag color="red">薄弱点</Tag>}
          </Space>
        }
      >
        {/* Question */}
        <div style={{ marginBottom: 20 }}>
          <MarkdownRenderer content={currentEx.question} />
        </div>

        {/* Options */}
        <Radio.Group
          value={selectedOption}
          onChange={(e) => setSelectedOption(e.target.value)}
          style={{ width: '100%' }}
          disabled={!!feedback}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            {Object.entries(currentEx.options).map(([key, value]) => {
              let optionStyle: React.CSSProperties = {
                padding: '10px 14px', borderRadius: 8, width: '100%',
                border: '1px solid #d9d9d9', cursor: 'pointer',
              };
              if (feedback) {
                if (key === currentEx.options[feedback.correct_answer as keyof typeof currentEx.options] ? key : '') {
                  // correct answer highlight will be handled below
                }
                if (key === feedback.correct_answer) {
                  optionStyle = { ...optionStyle, border: '2px solid #52c41a', background: '#f6ffed' };
                } else if (key === selectedOption && !feedback.correct) {
                  optionStyle = { ...optionStyle, border: '2px solid #ff4d4f', background: '#fff2f0' };
                }
              } else if (key === selectedOption) {
                optionStyle = { ...optionStyle, border: '2px solid #1677ff', background: '#f0f5ff' };
              }

              return (
                <div key={key} style={optionStyle} onClick={() => !feedback && setSelectedOption(key)}>
                  <Radio value={key} style={{ marginRight: 8 }}>
                    <Text strong>{key}.</Text>
                  </Radio>
                  <Text>{value}</Text>
                </div>
              );
            })}
          </Space>
        </Radio.Group>

        {/* Feedback */}
        {feedback && (
          <Card
            size="small"
            style={{
              marginTop: 16,
              background: feedback.correct ? '#f6ffed' : '#fff2f0',
              border: `1px solid ${feedback.correct ? '#b7eb8f' : '#ffccc7'}`,
            }}
          >
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space>
                {feedback.correct
                  ? <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 20 }} />
                  : <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />
                }
                <Text strong style={{ color: feedback.correct ? '#52c41a' : '#ff4d4f' }}>
                  {feedback.correct ? '回答正确！' : `回答错误 — 正确答案是 ${feedback.correct_answer}`}
                </Text>
              </Space>
              {feedback.explanation && (
                <MarkdownRenderer content={feedback.explanation} />
              )}
              <Divider style={{ margin: '12px 0' }} />
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <ClockCircleOutlined style={{ color: '#1677ff' }} />
                <Text>
                  {feedback.sm2_state.interval === 0
                    ? '明天'
                    : `下次复习：${feedback.sm2_state.interval} 天后`}
                </Text>
                {feedback.sm2_state.is_mastered && <Tag color="green">已掌握</Tag>}
                {feedback.sm2_state.is_weak && <Tag color="red">薄弱 — 需要加强</Tag>}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  （重复 {feedback.sm2_state.repetitions} 次 · EF: {feedback.sm2_state.ease_factor}）
                </Text>
              </div>
            </Space>
          </Card>
        )}

        {/* Action buttons */}
        <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end' }}>
          {!feedback ? (
            <Button
              type="primary" size="large"
              icon={<ArrowRightOutlined />}
              onClick={handleSubmit}
              disabled={!selectedOption}
            >
              提交答案
            </Button>
          ) : (
            <Button type="primary" size="large" onClick={handleNext}>
              {currentIndex + 1 >= exercises.length ? '查看成绩' : '下一题'}
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
};

export default QuizPage;
