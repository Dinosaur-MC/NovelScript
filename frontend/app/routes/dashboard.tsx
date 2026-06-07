import { useState, useEffect } from "react";
import { useNavigate } from "react-router";
import { Card, Statistic, Row, Col, Button, List, Tag, Spin, Avatar, Popover } from "antd";
import {
  BookOutlined,
  FileTextOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  SyncOutlined,
  PlusOutlined,
  HomeOutlined,
  UserOutlined,
  LogoutOutlined,
} from "@ant-design/icons";
import { listNovels } from "../api/novels";
import { listScripts } from "../api/scripts";
import { listTasks } from "../api/tasks";
import type { Route } from "./+types/dashboard";
import { useAuthStore } from "../stores/auth-store";
import { logout } from "../api/auth";

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

interface RecentItem {
  key: string;
  novelTitle: string;
  status: string;
  progress: number;
  time: string;
}

const STATUS_TAG: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待开始" },
  preprocessing: { color: "processing", label: "预处理中" },
  converting: { color: "processing", label: "转换中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

export default function Dashboard() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const clearUser = useAuthStore((s) => s.clearUser);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<Stats>({ novels: 0, scripts: 0, inProgress: 0, completed: 0, failed: 0 });
  const [recent, setRecent] = useState<RecentItem[]>([]);

  useEffect(() => {
    if (!user) return;
    (async () => {
      setLoading(true);
      try {
        const [novelsRes, scriptsRes, tasksRes] = await Promise.all([
          listNovels(1, 200),
          listScripts(undefined, undefined, 1, 200),
          listTasks(undefined, undefined, 1, 200),
        ]);

        const tasks = tasksRes.tasks;
        setStats({
          novels: novelsRes.total,
          scripts: scriptsRes.total,
          inProgress: tasks.filter((t) => t.status === "preprocessing" || t.status === "converting").length,
          completed: tasks.filter((t) => t.status === "completed").length,
          failed: tasks.filter((t) => t.status === "failed").length,
        });

        // Recent items: latest 10 tasks with novel title lookup
        const novelMap = new Map(novelsRes.items.map((n) => [n.id, n.title]));
        setRecent(
          tasks.slice(0, 10).map((t) => ({
            key: t.id,
            novelTitle: novelMap.get(t.novel_id) ?? "未知小说",
            status: t.status,
            progress: t.progress,
            time: t.created_at?.slice(0, 16).replace("T", " ") ?? "—",
          })),
        );
      } catch {
        // silently handle — stats will show zeros
      } finally {
        setLoading(false);
      }
    })();
  }, [user]);

  if (!user) {
    return (
      <div className="ns-dashboard-guest">
        <p className="ns-dashboard-guest-text">请先登录</p>
        <Button type="primary" size="large" onClick={() => navigate("/login")}>
          登录
        </Button>
        <Button type="link" onClick={() => navigate("/")}>
          返回首页
        </Button>
      </div>
    );
  }

  return (
    <div className="ns-dashboard-wrap">
      {/* Top Banner */}
      <div className="ns-dashboard-banner">
        <h1>仪表板</h1>
        <div className="ns-dashboard-banner-actions">
          <Button icon={<HomeOutlined />} onClick={() => navigate("/")}>
            返回首页
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate("/")}>
            上传新小说
          </Button>
          <Popover
            trigger="click"
            placement="bottomRight"
            overlayStyle={{ width: 220 }}
            content={
              <div className="ns-popover-wrap">
                <div className="ns-popover-field">
                  <div className="ns-popover-label">用户名</div>
                  <div className="ns-popover-value ns-popover-value--strong">{user.username}</div>
                </div>
                <div className="ns-popover-field">
                  <div className="ns-popover-label">邮箱</div>
                  <div className="ns-popover-value">{user.email ?? "—"}</div>
                </div>
                <div className="ns-popover-field--last">
                  <div className="ns-popover-label">角色</div>
                  <div className="ns-popover-value">{user.role === "admin" ? "管理员" : "用户"}</div>
                </div>
                <Button
                  block
                  danger
                  size="small"
                  icon={<LogoutOutlined />}
                  onClick={() => { logout().catch(() => {}); clearUser(); navigate("/"); }}
                >
                  退出登录
                </Button>
              </div>
            }
          >
            <span className="ns-popover-user-trigger">
              <Avatar
                size="small"
                icon={<UserOutlined />}
                style={{ backgroundColor: "var(--color-accent-primary)" }}
              />
              {user.username}
            </span>
          </Popover>
        </div>
      </div>

      {loading ? (
        <div className="ns-dashboard-loading">
          <Spin size="large" />
          <p className="ns-dashboard-loading-text">加载中...</p>
        </div>
      ) : (
        <>
          {/* Stats */}
          <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
            <Col xs={12} sm={6}>
              <Card size="small" className="ns-dashboard-stat-card">
                <Statistic
                  title="小说总数"
                  value={stats.novels}
                  prefix={<BookOutlined style={{ color: "var(--color-accent-primary)" }} />}
                  valueStyle={{ color: "var(--color-text-primary)" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" className="ns-dashboard-stat-card">
                <Statistic
                  title="剧本总数"
                  value={stats.scripts}
                  prefix={<FileTextOutlined style={{ color: "var(--color-accent-primary)" }} />}
                  valueStyle={{ color: "var(--color-text-primary)" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" className="ns-dashboard-stat-card">
                <Statistic
                  title="已完成"
                  value={stats.completed}
                  prefix={<CheckCircleFilled style={{ color: "var(--color-accent-success)" }} />}
                  valueStyle={{ color: "var(--color-accent-success)" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" className="ns-dashboard-stat-card">
                <Statistic
                  title="进行中 / 失败"
                  value={`${stats.inProgress} / ${stats.failed}`}
                  prefix={
                    stats.failed > 0
                      ? <CloseCircleFilled style={{ color: "var(--color-accent-danger)" }} />
                      : <SyncOutlined style={{ color: "var(--color-accent-warning)" }} />
                  }
                  valueStyle={{
                    color: stats.failed > 0 ? "var(--color-accent-danger)" : "var(--color-accent-warning)",
                    fontSize: 20,
                  }}
                />
              </Card>
            </Col>
          </Row>

          {/* Recent Tasks */}
          <h2 className="ns-dashboard-recent-title">最近任务</h2>
          {recent.length === 0 ? (
            <p className="ns-dashboard-recent-empty">暂无任务</p>
          ) : (
            <List
              dataSource={recent}
              renderItem={(item) => {
                const tagInfo = STATUS_TAG[item.status] ?? { color: "default", label: item.status };
                return (
                  <List.Item
                    className="ns-dashboard-task-item"
                  >
                    <List.Item.Meta
                      title={
                        <span className="ns-dashboard-task-title">
                          《{item.novelTitle}》
                        </span>
                      }
                      description={
                        <span className="ns-dashboard-task-time">
                          {item.time}
                        </span>
                      }
                    />
                    <div className="ns-dashboard-task-progress">
                      <span className="ns-dashboard-task-pct">
                        {item.progress}%
                      </span>
                      <Tag color={tagInfo.color}>{tagInfo.label}</Tag>
                    </div>
                  </List.Item>
                );
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
