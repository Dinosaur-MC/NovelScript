import { useState, useEffect, useCallback } from "react";

// Guard against popconfirm portal clicks leaking to card onClick
const blockNav = { current: false } as { current: boolean };
import { useNavigate } from "react-router";
import { Card, Tag, Button, Modal, Input, Upload, Collapse, message, Select, Avatar, Popover, Popconfirm } from "antd";
import {
  PlusOutlined,
  UploadOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  SyncOutlined,
  ClockCircleFilled,
  SearchOutlined,
  UserOutlined,
  LogoutOutlined,
  DeleteOutlined,
  EditOutlined,
  DashboardOutlined,
} from "@ant-design/icons";
import { listNovels, uploadNovel, uploadNovelFile, updateNovel, deleteNovel } from "../../api/novels";
import { listScripts, type ScriptLight, deleteScript } from "../../api/scripts";
import { createTask } from "../../api/tasks";
import type { Novel } from "../../api/novels";
import { useAuthStore } from "../../stores/auth-store";
import { logout } from "../../api/auth";

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircleFilled style={{ color: "var(--color-accent-success)" }} />,
  preprocessing: <SyncOutlined spin style={{ color: "var(--color-accent-warning)" }} />,
  converting: <SyncOutlined spin style={{ color: "var(--color-accent-warning)" }} />,
  failed: <CloseCircleFilled style={{ color: "var(--color-accent-danger)" }} />,
  pending: <ClockCircleFilled style={{ color: "var(--color-text-muted)" }} />,
};

const STATUS_LABEL: Record<string, string> = {
  completed: "已完成",
  preprocessing: "预处理中",
  converting: "转换中",
  failed: "失败",
  pending: "待开始",
};

export function HomePage() {
  const navigate = useNavigate();
  const [novels, setNovels] = useState<Novel[]>([]);
  const [scripts, setScripts] = useState<ScriptLight[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploading, setUploading] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [renameAuthor, setRenameAuthor] = useState("");
  const user = useAuthStore((s) => s.user);
  const clearUser = useAuthStore((s) => s.clearUser);
  const authLoaded = useAuthStore((s) => s.loaded);

  const load = useCallback(async () => {
    // Don't fetch data for unauthenticated users — skip the API calls
    const currentUser = useAuthStore.getState().user;
    if (!currentUser) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [novelsRes, scriptsRes] = await Promise.all([
        listNovels(1, 100),
        listScripts(undefined, undefined, 1, 100),
      ]);
      setNovels(novelsRes.items);
      setScripts(scriptsRes.items);
    } catch {
      message.error("加载数据失败");
    } finally {
      setLoading(false);
    }
  }, []);

  // Wait for auth check to complete before loading data (prevents racing the token check)
  useEffect(() => {
    if (!authLoaded) return;
    load();
  }, [authLoaded, load]);

  // Group scripts by novel_id
  const scriptsByNovel: Record<string, ScriptLight[]> = {};
  for (const s of scripts) {
    (scriptsByNovel[s.novel_id] ??= []).push(s);
  }

  // Search & filter
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const filteredNovels = novels.filter((n) => {
    if (searchText && !n.title.includes(searchText)) return false;
    if (statusFilter === "with_scripts") {
      return scriptsByNovel[n.id]?.length > 0;
    }
    if (statusFilter === "without_scripts") {
      return !scriptsByNovel[n.id] || scriptsByNovel[n.id].length === 0;
    }
    return true;
  });

  const handlePasteUpload = async () => {
    if (!pasteText.trim()) return;
    setUploading(true);
    try {
      const upRes = await uploadNovel(pasteText.trim(), uploadTitle || undefined);
      await createTask(upRes.novel_id);
      message.success("上传成功，转换任务已创建");
      setUploadOpen(false);
      setPasteText("");
      setUploadTitle("");
      load(); // need server data for new novel + task
    } catch (err) {
      message.error(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    setUploading(true);
    try {
      const upRes = await uploadNovelFile(file, uploadTitle || undefined);
      await createTask(upRes.novel_id);
      message.success("上传成功，转换任务已创建");
      setUploadOpen(false);
      setUploadTitle("");
      load(); // need server data for new novel + task
    } catch (err) {
      message.error(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
    return false;
  };

  const handleNewScript = async (novelId: string) => {
    try {
      const res = await createTask(novelId);
      message.success("转换任务已创建");
      // Append locally instead of full reload
      setScripts((prev) => [
        ...prev,
        {
          script_id: res.task_id, novel_id: novelId, status: "pending",
          progress: 0, summary: null, scene_count: 0,
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        },
      ]);
    } catch {
      message.error("创建任务失败");
    }
  };

  const handleRenameClick = (novel: Novel) => {
    setRenameId(novel.id);
    setRenameTitle(novel.title);
    setRenameAuthor(novel.author ?? "");
    setRenameOpen(true);
  };

  const handleRenameSubmit = async () => {
    if (!renameId) return;
    try {
      await updateNovel(renameId, { title: renameTitle, author: renameAuthor || undefined });
      message.success("小说信息已更新");
      setRenameOpen(false);
      setNovels((prev) =>
        prev.map((n) => (n.id === renameId ? { ...n, title: renameTitle, author: renameAuthor || null } : n)),
      );
    } catch {
      message.error("更新失败");
    }
  };

  const handleDeleteNovel = async (novelId: string) => {
    blockNav.current = true;
    try {
      await deleteNovel(novelId);
      message.success("小说已删除");
      setNovels((prev) => prev.filter((n) => n.id !== novelId));
      setScripts((prev) => prev.filter((s) => s.novel_id !== novelId));
    } catch {
      message.error("删除失败");
    }
  };

  const handleDeleteScript = async (scriptId: string) => {
    blockNav.current = true;
    try {
      await deleteScript(scriptId);
      message.success("剧本已删除");
      setScripts((prev) => prev.filter((s) => s.script_id !== scriptId));
    } catch {
      message.error("删除失败");
    }
  };

  if (loading) {
    return (
      <div className="ns-home-loading">
        <div className="ns-spinner" />
        <span className="ns-home-loading-text">加载中...</span>
      </div>
    );
  }

  return (
    <div className="ns-home-wrap">
      {/* Header */}
      <div className="ns-home-header">
        <h1>NovelScript 析幕</h1>
        <div className="ns-home-header-actions">
          {user ? (
            <>
              <Button
                icon={<DashboardOutlined />}
                onClick={() => navigate("/dashboard")}
              >
                仪表板
              </Button>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setUploadOpen(true)}
              >
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
            </>
          ) : (
            <Button
              type="primary"
              size="large"
              icon={<UserOutlined />}
              onClick={() => navigate("/login")}
            >
              登录
            </Button>
          )}
        </div>
      </div>

      {/* Search & Filter */}
      <div className="ns-home-search">
        <Input
          prefix={<SearchOutlined style={{ color: "var(--color-text-muted)" }} />}
          placeholder="搜索小说名称..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          allowClear
          style={{ flex: 1 }}
        />
        <Select
          value={statusFilter}
          onChange={(v) => setStatusFilter(v)}
          style={{ width: 160 }}
          options={[
            { value: "all", label: "全部小说" },
            { value: "with_scripts", label: "已有剧本" },
            { value: "without_scripts", label: "暂无剧本" },
          ]}
        />
      </div>

      {/* Novel groups */}
      {filteredNovels.length === 0 ? (
        <div className="ns-home-empty">
          <p className="ns-home-empty-text">
            {novels.length === 0
              ? user
                ? "还没有小说，点击上方上传第一部小说开始吧"
                : "还没有小说，请先登录"
              : "没有匹配的小说，请调整搜索条件"}
          </p>
          {novels.length === 0 && user && (
            <Button size="large" type="primary" onClick={() => setUploadOpen(true)}>
              上传小说
            </Button>
          )}
          {novels.length === 0 && !user && (
            <Button size="large" type="primary" onClick={() => navigate("/login")}>
              登录
            </Button>
          )}
        </div>
      ) : (
        <Collapse
          defaultActiveKey={filteredNovels.map((n) => n.id)}
          items={filteredNovels.map((novel) => {
            const novelScripts = scriptsByNovel[novel.id] ?? [];
            return {
              key: novel.id,
              label: (
                <div className="ns-home-novel-label">
                  <span className="ns-home-novel-title">
                    《{novel.title}》
                    <span className="ns-home-novel-meta">
                      ({novel.word_count?.toLocaleString() ?? 0} 字)
                    </span>
                  </span>
                  <span onClick={(e) => e.stopPropagation()}>
                    <Popconfirm
                      title="确定删除此小说及其所有剧本？"
                      onConfirm={() => handleDeleteNovel(novel.id)}
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                    >
                      <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()} />
                    </Popconfirm>
                    <Button type="text" size="small" icon={<EditOutlined />} onClick={(e) => { e.stopPropagation(); handleRenameClick(novel); }} />
                  </span>
                </div>
              ),
              children: (
                <div className="ns-home-script-grid">
                  {novelScripts.length === 0 && (
                    <div
                      className="ns-home-new-script-card"
                      onClick={() => handleNewScript(novel.id)}
                    >
                      <span className="ns-home-new-script-title">
                        开始转换
                      </span>
                      <span className="ns-home-new-script-desc">
                        将小说转换为剧本
                      </span>
                    </div>
                  )}
                  {novelScripts.map((s) => (
                    <Card
                      key={s.script_id}
                      hoverable
                      size="small"
                      className="ns-home-script-card-explicit"
                      onClick={() => {
                        if (blockNav.current) { blockNav.current = false; return; }
                        navigate(`/workspace/${s.script_id}`);
                      }}
                    >
                      <div className="ns-home-script-card-row">
                        <span className="ns-home-script-card-title">
                          {s.summary?.slice(0, 20) || "剧本"}
                        </span>
                        <span className="ns-home-script-card-status">
                          {STATUS_ICON[s.status] ?? null}
                          <Popconfirm
                            title="确定删除？"
                            onConfirm={() => handleDeleteScript(s.script_id)}
                            okText="删除"
                            cancelText="取消"
                            okButtonProps={{ danger: true }}
                          >
                            <Button
                              type="text"
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </Popconfirm>
                        </span>
                      </div>
                      <div className="ns-home-script-card-meta">
                        <span>{s.scene_count} 个场景</span>
                        <Tag
                          color={
                            s.status === "completed" ? "success"
                            : s.status === "failed" ? "error"
                            : s.status === "converting" || s.status === "preprocessing" ? "processing"
                            : "default"
                          }
                          style={{ marginLeft: 8, fontSize: 11 }}
                        >
                          {STATUS_LABEL[s.status] ?? s.status}
                        </Tag>
                      </div>
                    </Card>
                  ))}
                  {novelScripts.length > 0 && (
                    <Card
                      hoverable
                      size="small"
                      className="ns-home-plus-card"
                      onClick={() => handleNewScript(novel.id)}
                    >
                      <PlusOutlined style={{ marginRight: 6 }} />
                      新建剧本
                    </Card>
                  )}
                </div>
              ),
            };
          })}
        />
      )}

      {/* Upload Modal */}
      <Modal
        title="上传小说"
        open={uploadOpen}
        onCancel={() => { setUploadOpen(false); setUploadTitle(""); }}
        footer={null}
        destroyOnHidden
      >
        <div style={{ marginBottom: 12 }}>
          <label className="ns-home-upload-label">
            小说标题（选填，留空则自动从正文提取）
          </label>
          <Input
            value={uploadTitle}
            onChange={(e) => setUploadTitle(e.target.value)}
            placeholder="例如：红楼梦"
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <Input.TextArea
            rows={8}
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            placeholder="在此粘贴小说正文..."
          />
          <Button
            type="primary"
            onClick={handlePasteUpload}
            loading={uploading}
            style={{ marginTop: 8 }}
            block
          >
            提交文本
          </Button>
        </div>
        <div className="ns-home-upload-or">
          或
        </div>
        <Upload.Dragger
          accept=".txt,.md"
          maxCount={1}
          beforeUpload={handleFileUpload}
          showUploadList={false}
        >
          <p className="ant-upload-drag-icon">
            <UploadOutlined />
          </p>
          <p>点击或拖拽上传 .txt / .md 文件</p>
        </Upload.Dragger>
      </Modal>

      {/* Rename Modal */}
      <Modal
        title="编辑小说信息"
        open={renameOpen}
        onCancel={() => setRenameOpen(false)}
        onOk={handleRenameSubmit}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <div className="ns-home-rename-form">
          <div>
            <label className="ns-home-upload-label">
              标题
            </label>
            <Input
              value={renameTitle}
              onChange={(e) => setRenameTitle(e.target.value)}
              placeholder="小说标题"
            />
          </div>
          <div>
            <label className="ns-home-upload-label">
              作者
            </label>
            <Input
              value={renameAuthor}
              onChange={(e) => setRenameAuthor(e.target.value)}
              placeholder="作者（选填）"
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}
