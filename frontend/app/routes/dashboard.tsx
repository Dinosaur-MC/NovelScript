import { useState, useEffect } from "react";
import { useNavigate } from "react-router";
import { Card, Statistic, Row, Col, Button, List, Tag, Spin } from "antd";
import {
  BookOutlined,
  FileTextOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  SyncOutlined,
  HomeOutlined,
  EditOutlined,
  NumberOutlined,
} from "@ant-design/icons";
import { getDashboard, type RecentTask, type RecentScript, type RecentNovel } from "../api/dashboard";
import type { Route } from "./+types/dashboard";
import { useAuthStore } from "../stores/auth-store";
import { AppHeader } from "../components/AppHeader";

export function meta({}: Route.MetaArgs) {
  return [{ title: "仪表板 — NovelScript 析幕" }];
}

interface Stats {
  novels: number;
  scripts: number;
  inProgress: number;
  completed: number;
  failed: number;
}

const STATUS_TAG: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待开始" },
  preprocessing: { color: "processing", label: "预处理中" },
  converting: { color: "processing", label: "转换中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

const SCRIPT_STATUS_TAG: Record<string, { color: string; label: string }> = {
  draft: { color: "default", label: "草稿" },
  editing: { color: "processing", label: "编辑中" },
  completed: { color: "success", label: "已完成" },
};

const SCRIPT_SOURCE_LABEL: Record<string, string> = {
  generated: "AI 生成",
  forked: "复刻",
  standalone: "独立创作",
};

export default function Dashboard() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const authLoaded = useAuthStore((s) => s.loaded);

  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<Stats>({
    novels: 0, scripts: 0, inProgress: 0, completed: 0, failed: 0,
  });
  const [recentTasks, setRecentTasks] = useState<RecentTask[]>([]);
  const [recentScripts, setRecentScripts] = useState<RecentScript[]>([]);
  const [recentNovels, setRecentNovels] = useState<RecentNovel[]>([]);

  useEffect(() => {
    if (!authLoaded) return;
    if (!user) { setLoading(false); return; }
    (async () => {
      setLoading(true);
      try {
        const dashboard = await getDashboard();
        setStats({
          novels: dashboard.stats.novels,
          scripts: dashboard.stats.scripts,
          inProgress: dashboard.stats.in_progress,
          completed: dashboard.stats.completed,
          failed: dashboard.stats.failed,
        });
        setRecentTasks(dashboard.recent_tasks);
        setRecentScripts(dashboard.recent_scripts);
        setRecentNovels(dashboard.recent_novels);
      } catch {
        // silently handle — stats show zeros
      } finally {
        setLoading(false);
      }
    })();
  }, [authLoaded, user]);

  if (!authLoaded) {
    return (
      <div className="ns-dashboard-loading">
        <Spin size="large" />
        <p className="ns-dashboard-loading-text">加载中...</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="ns-dashboard-guest">
        <p className="ns-dashboard-guest-text">请先登录</p>
        <Button type="primary" size="large" onClick={() => navigate("/login")}>登录</Button>
        <Button type="link" onClick={() => navigate("/")}>返回首页</Button>
      </div>
    );
  }

  return (
    <>
      <AppHeader>
        <Button icon={<HomeOutlined />} onClick={() => navigate("/workspace")}>返回创作空间</Button>
      </AppHeader>

      <div className="ns-dashboard-wrap">
        <div className="ns-page-title"><h1>仪表板</h1></div>

        {loading ? (
          <div className="ns-dashboard-loading">
            <Spin size="large" />
            <p className="ns-dashboard-loading-text">加载中...</p>
          </div>
        ) : (
          <>
            <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
              <Col xs={12} sm={6}>
                <Card size="small" className="ns-dashboard-stat-card">
                  <Statistic title="小说总数" value={stats.novels}
                    prefix={<BookOutlined style={{ color: "var(--color-accent-primary)" }} />}
                    valueStyle={{ color: "var(--color-text-primary)" }} />
                </Card>
              </Col>
              <Col xs={12} sm={6}>
                <Card size="small" className="ns-dashboard-stat-card">
                  <Statistic title="剧本总数" value={stats.scripts}
                    prefix={<FileTextOutlined style={{ color: "var(--color-accent-primary)" }} />}
                    valueStyle={{ color: "var(--color-text-primary)" }} />
                </Card>
              </Col>
              <Col xs={12} sm={6}>
                <Card size="small" className="ns-dashboard-stat-card">
                  <Statistic title="已完成" value={stats.completed}
                    prefix={<CheckCircleFilled style={{ color: "var(--color-accent-success)" }} />}
                    valueStyle={{ color: "var(--color-accent-success)" }} />
                </Card>
              </Col>
              <Col xs={12} sm={6}>
                <Card size="small" className="ns-dashboard-stat-card">
                  <Statistic title="进行中 / 失败"
                    value={`${stats.inProgress} / ${stats.failed}`}
                    prefix={stats.failed > 0
                      ? <CloseCircleFilled style={{ color: "var(--color-accent-danger)" }} />
                      : <SyncOutlined style={{ color: "var(--color-accent-warning)" }} />}
                    valueStyle={{
                      color: stats.failed > 0 ? "var(--color-accent-danger)" : "var(--color-accent-warning)",
                      fontSize: 20,
                    }} />
                </Card>
              </Col>
            </Row>

            <h2 className="ns-dashboard-recent-title">最近任务</h2>
            {recentTasks.length === 0 ? (
              <p className="ns-dashboard-recent-empty">暂无任务</p>
            ) : (
              <List dataSource={recentTasks} renderItem={(item) => {
                const tagInfo = STATUS_TAG[item.status] ?? { color: "default", label: item.status };
                return (
                  <List.Item className="ns-dashboard-task-item"
                    onClick={() => navigate(`/workspace/${item.task_id}`)}
                    style={{ cursor: "pointer" }}>
                    <List.Item.Meta
                      title={<span className="ns-dashboard-task-title">《{item.novel_title}》</span>}
                      description={<span className="ns-dashboard-task-time">{item.created_at?.slice(0, 16).replace("T", " ") ?? "—"}</span>} />
                    <div className="ns-dashboard-task-progress">
                      <span className="ns-dashboard-task-pct">{item.progress}%</span>
                      <Tag color={tagInfo.color}>{tagInfo.label}</Tag>
                    </div>
                  </List.Item>
                );
              }} />
            )}

            <Row gutter={[24, 16]} style={{ marginTop: 32 }}>
              <Col xs={24} md={12}>
                <h2 className="ns-dashboard-recent-title">最近剧本</h2>
                {recentScripts.length === 0 ? (
                  <p className="ns-dashboard-recent-empty">暂无剧本</p>
                ) : (
                  <List dataSource={recentScripts} renderItem={(item) => {
                    const tag = SCRIPT_STATUS_TAG[item.status] ?? { color: "default", label: item.status };
                    return (
                      <List.Item className="ns-dashboard-task-item"
                        onClick={() => navigate(`/workspace/${item.script_id}`)}
                        style={{ cursor: "pointer" }}>
                        <List.Item.Meta
                          title={<span className="ns-dashboard-task-title">{item.title}</span>}
                          description={<span style={{ fontSize: 12 }}>
                            {SCRIPT_SOURCE_LABEL[item.source_type] ?? item.source_type}
                            {" · "}<NumberOutlined style={{ marginRight: 2 }} />{item.scene_count} 场
                            {" · "}{item.updated_at?.slice(0, 10) ?? "—"}
                          </span>} />
                        <Tag color={tag.color}>{tag.label}</Tag>
                      </List.Item>
                    );
                  }} />
                )}
              </Col>
              <Col xs={24} md={12}>
                <h2 className="ns-dashboard-recent-title">最近小说</h2>
                {recentNovels.length === 0 ? (
                  <p className="ns-dashboard-recent-empty">暂无小说</p>
                ) : (
                  <List dataSource={recentNovels} renderItem={(item) => (
                    <List.Item className="ns-dashboard-task-item">
                      <List.Item.Meta
                        title={<span className="ns-dashboard-task-title">《{item.title}》</span>}
                        description={<span style={{ fontSize: 12 }}>
                          <EditOutlined style={{ marginRight: 4 }} />{(item.word_count ?? 0).toLocaleString()} 字
                          {" · "}{item.updated_at?.slice(0, 10) ?? "—"}
                        </span>} />
                      <Tag>{item.status === "draft" ? "草稿" : item.status}</Tag>
                    </List.Item>
                  )} />
                )}
              </Col>
            </Row>
          </>
        )}
      </div>
    </>
  );
}
