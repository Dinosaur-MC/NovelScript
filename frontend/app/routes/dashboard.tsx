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
      <div
        style={{
          height: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 16,
          backgroundColor: "var(--color-bg-canvas)",
        }}
      >
        <p style={{ color: "var(--color-text-muted)", fontSize: 16 }}>请先登录</p>
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
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "var(--color-bg-canvas)",
        color: "var(--color-text-primary)",
        padding: 32,
      }}
    >
      {/* Top Banner */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 32,
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 600, margin: 0 }}>仪表板</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
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
              <div style={{ fontSize: 13 }}>
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: "var(--color-text-muted)", fontSize: 11, marginBottom: 2 }}>用户名</div>
                  <div style={{ color: "var(--color-text-primary)", fontWeight: 600 }}>{user.username}</div>
                </div>
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: "var(--color-text-muted)", fontSize: 11, marginBottom: 2 }}>邮箱</div>
                  <div style={{ color: "var(--color-text-primary)" }}>{user.email ?? "—"}</div>
                </div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ color: "var(--color-text-muted)", fontSize: 11, marginBottom: 2 }}>角色</div>
                  <div style={{ color: "var(--color-text-primary)" }}>{user.role === "admin" ? "管理员" : "用户"}</div>
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
            <span
              style={{
                fontSize: 13,
                color: "var(--color-text-secondary)",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
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
        <div style={{ textAlign: "center", padding: 64 }}>
          <Spin size="large" />
          <p style={{ color: "var(--color-text-muted)", marginTop: 16 }}>加载中...</p>
        </div>
      ) : (
        <>
          {/* Stats */}
          <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
            <Col xs={12} sm={6}>
              <Card size="small" style={{ backgroundColor: "var(--color-bg-elevated)", borderColor: "var(--color-border-subtle)" }}>
                <Statistic
                  title="小说总数"
                  value={stats.novels}
                  prefix={<BookOutlined style={{ color: "var(--color-accent-primary)" }} />}
                  valueStyle={{ color: "var(--color-text-primary)" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" style={{ backgroundColor: "var(--color-bg-elevated)", borderColor: "var(--color-border-subtle)" }}>
                <Statistic
                  title="剧本总数"
                  value={stats.scripts}
                  prefix={<FileTextOutlined style={{ color: "var(--color-accent-primary)" }} />}
                  valueStyle={{ color: "var(--color-text-primary)" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" style={{ backgroundColor: "var(--color-bg-elevated)", borderColor: "var(--color-border-subtle)" }}>
                <Statistic
                  title="已完成"
                  value={stats.completed}
                  prefix={<CheckCircleFilled style={{ color: "var(--color-accent-success)" }} />}
                  valueStyle={{ color: "var(--color-accent-success)" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" style={{ backgroundColor: "var(--color-bg-elevated)", borderColor: "var(--color-border-subtle)" }}>
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
          <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>最近任务</h2>
          {recent.length === 0 ? (
            <p style={{ color: "var(--color-text-muted)" }}>暂无任务</p>
          ) : (
            <List
              dataSource={recent}
              renderItem={(item) => {
                const tagInfo = STATUS_TAG[item.status] ?? { color: "default", label: item.status };
                return (
                  <List.Item
                    style={{
                      padding: "10px 16px",
                      backgroundColor: "var(--color-bg-elevated)",
                      border: "1px solid var(--color-border-subtle)",
                      borderRadius: 8,
                      marginBottom: 8,
                    }}
                  >
                    <List.Item.Meta
                      title={
                        <span style={{ color: "var(--color-text-primary)" }}>
                          《{item.novelTitle}》
                        </span>
                      }
                      description={
                        <span style={{ color: "var(--color-text-secondary)", fontSize: 12 }}>
                          {item.time}
                        </span>
                      }
                    />
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <span style={{ color: "var(--color-text-secondary)", fontSize: 12 }}>
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
