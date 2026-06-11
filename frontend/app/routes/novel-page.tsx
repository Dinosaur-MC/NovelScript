import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router";
import { Card, Button, Tag, List, Modal, Spin, Pagination, message, Popconfirm, Empty } from "antd";
import {
  HomeOutlined,
  DeleteOutlined,
  PlusOutlined,
  FileTextOutlined,
  BookOutlined,
  SyncOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  ClockCircleFilled,
  ArrowLeftOutlined,
} from "@ant-design/icons";
import { getNovel, listNovelTasks, type Novel, type NovelTaskItem } from "../api/novels";
import { createTask, deleteTask } from "../api/tasks";
import { useSSE } from "../hooks/useSSE";
import { AppHeader } from "../components/AppHeader";
import { useAuthStore } from "../stores/auth-store";
import { useTaskStore } from "../stores/task-store";
import { useNovelStore } from "../stores/novel-store";
import type { Route } from "./+types/novel-page";

export function meta({}: Route.MetaArgs) {
  return [{ title: "NovelScript — 小说详情" }];
}

const STATUS_MAP: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  pending:       { color: "default",     icon: <ClockCircleFilled />,     label: "待开始" },
  preprocessing: { color: "processing",  icon: <SyncOutlined spin />,     label: "预处理中" },
  converting:    { color: "processing",  icon: <SyncOutlined spin />,     label: "转换中" },
  completed:     { color: "success",     icon: <CheckCircleFilled />,     label: "已完成" },
  failed:        { color: "error",       icon: <CloseCircleFilled />,     label: "失败" },
};

const TASK_PAGE_SIZE = 10;

export default function NovelPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  const [novel, setNovel] = useState<Novel | null>(null);
  const [tasks, setTasks] = useState<NovelTaskItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [taskLoading, setTaskLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const taskStatus = useTaskStore((s) => s.status);

  // Subscribe to SSE for real-time task updates when a task is active
  useSSE(
    useCallback(() => {
      // On task complete: refresh the task list to show the new script
      message.success("转换任务已完成！");
      loadTasks(page);
    }, [page]),
  );

  // Auto-refresh task list when task transitions from active to terminal
  useEffect(() => {
    if (taskStatus === "completed" || taskStatus === "failed") {
      loadTasks(page);
    }
  }, [taskStatus, page, loadTasks]);

  const loadNovel = useCallback(async () => {
    if (!novelId) return;
    try {
      const data = await getNovel(novelId);
      setNovel(data.novel);
    } catch {
      message.error("加载小说失败");
    }
  }, [novelId]);

  const loadTasks = useCallback(async (p: number) => {
    if (!novelId) return;
    setTaskLoading(true);
    try {
      const data = await listNovelTasks(novelId, p, TASK_PAGE_SIZE);
      setTasks(data.tasks);
      setTotal(data.total);
      setPage(data.page);
    } catch {
      message.error("加载任务列表失败");
    } finally {
      setTaskLoading(false);
    }
  }, [novelId]);

  useEffect(() => {
    if (!novelId) return;
    setLoading(true);
    Promise.all([loadNovel(), loadTasks(1)]).finally(() => setLoading(false));
  }, [novelId, loadNovel, loadTasks]);

  const handleCreateTask = async () => {
    if (!novelId) return;
    setCreating(true);
    try {
      const res = await createTask(novelId);
      message.success("转换任务已创建");
      useTaskStore.getState().setTask(res.task_id, novelId, null, "pending");
      loadTasks(page);
    } catch {
      message.error("创建任务失败");
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteTask = async (taskId: string) => {
    try {
      await deleteTask(taskId);
      message.success("任务已删除");
      loadTasks(page);
    } catch {
      message.error("删除任务失败");
    }
  };

  const handleViewScript = (scriptId: string) => {
    navigate(`/workspace/${scriptId}`);
  };

  if (loading) {
    return (
      <div className="ns-dashboard-loading">
        <Spin size="large" />
      </div>
    );
  }

  if (!novel) {
    return (
      <div className="ns-workspace-error">
        <AppHeader>
          <Button icon={<HomeOutlined />} onClick={() => navigate("/")}>返回首页</Button>
        </AppHeader>
        <div className="ns-workspace-error-body">
          <p className="ns-workspace-error-text">小说不存在</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <AppHeader>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/")}>返回</Button>
        <Button icon={<HomeOutlined />} onClick={() => navigate("/dashboard")}>仪表板</Button>
      </AppHeader>

      <div className="ns-dashboard-wrap">
        {/* Novel Info */}
        <div className="ns-page-title" style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h1 style={{ margin: 0 }}>《{novel.title}》</h1>
          {novel.author && <span style={{ color: "var(--color-text-muted)" }}>— {novel.author}</span>}
          <span style={{ color: "var(--color-text-muted)", fontSize: 14 }}>
            <BookOutlined /> {(novel.word_count ?? 0).toLocaleString()} 字
          </span>
        </div>

        {/* Task Management */}
        <section style={{ marginTop: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h2 style={{ margin: 0 }}>转换任务</h2>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleCreateTask}
              loading={creating}
            >
              新建转换任务
            </Button>
          </div>

          {/* Active task live indicator */}
          {taskStatus && taskStatus !== "completed" && taskStatus !== "failed" && taskStatus !== null && (
            <div style={{
              background: "var(--color-bg-elevated)",
              border: "1px solid var(--color-primary)",
              borderRadius: 8, padding: "12px 16px", marginBottom: 16,
              display: "flex", alignItems: "center", gap: 12,
            }}>
              <SyncOutlined spin style={{ color: "var(--color-primary)", fontSize: 20 }} />
              <div style={{ flex: 1 }}>
                <strong>当前转换</strong>
                <span style={{ marginLeft: 8 }}>
                  <Tag color={STATUS_MAP[taskStatus]?.color ?? "default"}>
                    {STATUS_MAP[taskStatus]?.label ?? taskStatus}
                  </Tag>
                </span>
              </div>
            </div>
          )}

          {taskLoading && tasks.length === 0 ? (
            <div style={{ textAlign: "center", padding: 48 }}><Spin /></div>
          ) : tasks.length === 0 ? (
            <Empty description="暂无转换任务" />
          ) : (
            <>
              <List
                dataSource={tasks}
                renderItem={(item) => {
                  const st = STATUS_MAP[item.status] ?? { color: "default", icon: null, label: item.status };
                  return (
                    <List.Item
                      actions={[
                        item.script_id && (
                          <Button
                            key="view"
                            type="link"
                            size="small"
                            icon={<FileTextOutlined />}
                            onClick={() => handleViewScript(item.script_id!)}
                          >
                            查看剧本
                          </Button>
                        ),
                        item.status === "failed" && (
                          <Button
                            key="retry"
                            type="link"
                            size="small"
                            icon={<SyncOutlined />}
                            onClick={async () => {
                              const { resumeTask } = await import("../api/tasks");
                              await resumeTask(item.id);
                              message.success("任务已重试");
                              loadTasks(page);
                            }}
                          >
                            重试
                          </Button>
                        ),
                        (item.status === "completed" || item.status === "failed") && (
                          <Popconfirm
                            key="delete"
                            title="确定删除此任务？"
                            onConfirm={() => handleDeleteTask(item.id)}
                            okText="删除"
                            cancelText="取消"
                            okButtonProps={{ danger: true }}
                          >
                            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        ),
                      ].filter(Boolean)}
                    >
                      <List.Item.Meta
                        avatar={st.icon}
                        title={
                          <span>
                            <Tag color={st.color}>{st.label}</Tag>
                            {item.summary && <span style={{ marginLeft: 8 }}>{item.summary}</span>}
                          </span>
                        }
                        description={
                          <span style={{ fontSize: 12 }}>
                            {item.error_message && <span style={{ color: "var(--color-accent-danger)" }}>{item.error_message}</span>}
                            {item.created_at && (
                              <span style={{ marginLeft: 8 }}>
                                {new Date(item.created_at).toLocaleString()}
                              </span>
                            )}
                          </span>
                        }
                      />
                    </List.Item>
                  );
                }}
              />
              {total > TASK_PAGE_SIZE && (
                <div style={{ textAlign: "center", marginTop: 16 }}>
                  <Pagination
                    current={page}
                    total={total}
                    pageSize={TASK_PAGE_SIZE}
                    onChange={(p) => loadTasks(p)}
                    size="small"
                  />
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}
