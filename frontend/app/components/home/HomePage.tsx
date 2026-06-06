import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router";
import { Card, Tag, Button, Modal, Input, Upload, Collapse, message, Select, Avatar } from "antd";
import {
  PlusOutlined,
  UploadOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  SyncOutlined,
  ClockCircleFilled,
  SearchOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { listNovels, uploadNovel, uploadNovelFile } from "../../api/novels";
import { listScripts, type ScriptLight } from "../../api/scripts";
import { createTask } from "../../api/tasks";
import type { Novel } from "../../api/novels";
import { useAuthStore } from "../../stores/auth-store";

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
  const [uploading, setUploading] = useState(false);
  const user = useAuthStore((s) => s.user);

  const load = useCallback(async () => {
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

  useEffect(() => { load(); }, [load]);

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
      const upRes = await uploadNovel(pasteText.trim());
      const taskRes = await createTask(upRes.novel_id);
      message.success("上传成功！");
      setUploadOpen(false);
      setPasteText("");
      navigate(`/workspace/${taskRes.task_id}`);
    } catch {
      message.error("上传失败");
    } finally {
      setUploading(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    setUploading(true);
    try {
      const upRes = await uploadNovelFile(file);
      const taskRes = await createTask(upRes.novel_id);
      message.success("上传成功！");
      setUploadOpen(false);
      navigate(`/workspace/${taskRes.task_id}`);
    } catch {
      message.error("上传失败");
    } finally {
      setUploading(false);
    }
    return false; // prevent default Upload behavior
  };

  const handleNewScript = async (novelId: string) => {
    try {
      const taskRes = await createTask(novelId);
      navigate(`/workspace/${taskRes.task_id}`);
    } catch {
      message.error("创建任务失败");
    }
  };

  if (loading) {
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
        <div className="ns-spinner" />
        <span style={{ color: "var(--color-text-secondary)", fontSize: 14 }}>加载中...</span>
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
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 32,
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 600, margin: 0 }}>NovelScript 析幕</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {user ? (
            <>
              <span style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
                <Avatar
                  size="small"
                  icon={<UserOutlined />}
                  style={{ backgroundColor: "var(--color-accent-primary)", marginRight: 8 }}
                />
                {user.username}
              </span>
              <Button
                type="primary"
                size="large"
                icon={<PlusOutlined />}
                onClick={() => setUploadOpen(true)}
              >
                上传新小说
              </Button>
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
      <div
        style={{
          display: "flex",
          gap: 12,
          marginBottom: 24,
          maxWidth: 640,
        }}
      >
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
        <div
          style={{
            textAlign: "center",
            padding: 64,
            color: "var(--color-text-muted)",
          }}
        >
          <p style={{ fontSize: 16, marginBottom: 16 }}>
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
                <span style={{ fontWeight: 600, fontSize: 15 }}>
                  《{novel.title}》
                  <span style={{ color: "var(--color-text-secondary)", marginLeft: 8, fontSize: 12 }}>
                    ({novel.word_count?.toLocaleString() ?? 0} 字)
                  </span>
                </span>
              ),
              children: (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12, padding: "8px 0" }}>
                  {novelScripts.map((s) => (
                    <Card
                      key={s.script_id}
                      hoverable
                      size="small"
                      style={{
                        width: 220,
                        backgroundColor: "var(--color-bg-elevated)",
                        borderColor: "var(--color-border-subtle)",
                      }}
                      onClick={() => navigate(`/workspace/${s.script_id}`)}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontWeight: 600, fontSize: 13 }}>
                          {s.summary?.slice(0, 20) || "剧本"}
                        </span>
                        {STATUS_ICON[s.status] ?? null}
                      </div>
                      <div style={{ marginTop: 4, fontSize: 12, color: "var(--color-text-secondary)" }}>
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
                  <Card
                    hoverable
                    size="small"
                    style={{
                      width: 220,
                      backgroundColor: "transparent",
                      borderColor: "var(--color-border-emphasis)",
                      borderStyle: "dashed",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      minHeight: 80,
                    }}
                    onClick={() => handleNewScript(novel.id)}
                  >
                    <PlusOutlined style={{ marginRight: 6 }} />
                    新建剧本
                  </Card>
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
        onCancel={() => setUploadOpen(false)}
        footer={null}
        destroyOnHidden
      >
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
        <div style={{ textAlign: "center", color: "var(--color-text-muted)", marginBottom: 8 }}>
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
    </div>
  );
}
