import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router";
import { Card, Tag, Button, Modal, Input, Upload, message, Popconfirm, Tabs, Dropdown } from "antd";
import {
    PlusOutlined,
    UploadOutlined,
    CheckCircleFilled,
    CloseCircleFilled,
    SyncOutlined,
    ClockCircleFilled,
    SearchOutlined,
    DeleteOutlined,
    EditOutlined,
    DashboardOutlined,
    FireOutlined,
    BookOutlined,
    FileTextOutlined,
} from "@ant-design/icons";
import { listNovels, uploadNovel, uploadNovelFile, updateNovel, deleteNovel } from "../../api/novels";
import { listScripts, createScript, type ScriptLight, deleteScript } from "../../api/scripts";
import { createTask } from "../../api/tasks";
import type { Novel } from "../../api/novels";
import { useAuthStore } from "../../stores/auth-store";
import { AppHeader } from "../AppHeader";

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

const STATUS_COLOR: Record<string, string> = {
    completed: "success",
    preprocessing: "processing",
    converting: "processing",
    failed: "error",
    pending: "default",
};

/** Truncate summary to a display-friendly snippet. */
function snippet(text: string | null): string {
    if (!text) return "";
    return text.length > 60 ? text.slice(0, 60) + "…" : text;
}

/** Extract some character/location badge names from a script's summary. */
function entityBadges(text: string | null): string[] {
    if (!text) return [];
    // Look for 《》-wrapped names, or capitalized Chinese names (2-4 chars)
    const names = text.match(/《(.+?)》|([一-鿿]{2,4})(?=[,，。、\s])/g) || [];
    return [...new Set(names.map((n) => n.replace(/[《》]/g, "")))].filter(Boolean).slice(0, 3);
}

export function HomePage() {
    const navigate = useNavigate();
    const blockNav = useRef(false);
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
    const authLoaded = useAuthStore((s) => s.loaded);
    const [searchText, setSearchText] = useState("");
    const [tab, setTab] = useState<"all" | "novels" | "scripts">("all");
    const [tagFilter, setTagFilter] = useState<string[]>([]);

    // Collect all unique entity names from script summaries for tag filters
    const allTags = [...new Set(scripts.flatMap((s) => entityBadges(s.summary)))].slice(0, 10);

    const load = useCallback(async () => {
        const currentUser = useAuthStore.getState().user;
        if (!currentUser) {
            setLoading(false);
            return;
        }
        setLoading(true);
        try {
            const [novelsRes, scriptsRes] = await Promise.all([listNovels(1, 100), listScripts(undefined, undefined, 1, 100)]);
            setNovels(novelsRes.items);
            setScripts(scriptsRes.items);
        } catch {
            message.error("加载数据失败");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (authLoaded) load();
    }, [authLoaded, load]);

    // ── Build derived data ──────────────────────────────────────────

    const scriptsByNovel: Record<string, ScriptLight[]> = {};
    for (const s of scripts) {
        const key = s.novel_id ?? "_unlinked";
        (scriptsByNovel[key] ??= []).push(s);
    }

    // Novel → most recent script status (for status badge)
    const novelStatus = (n: Novel): string => {
        const ss = scriptsByNovel[n.id] ?? [];
        if (ss.length === 0) return "";
        const running = ss.find((s) => s.status === "preprocessing" || s.status === "converting");
        if (running) return running.status;
        const failed = ss.find((s) => s.status === "failed");
        if (failed) return "failed";
        const done = ss.find((s) => s.status === "completed");
        if (done) return "completed";
        return ss[0]?.status ?? "";
    };

    // Recent items: latest 8 across novels + scripts, merged by updated_at
    const recentItems = [
        ...novels.map((n) => ({
            type: "novel" as const,
            id: n.id,
            title: n.title,
            desc: `${n.word_count?.toLocaleString() ?? 0} 字 · 第${scriptsByNovel[n.id]?.length ?? 0}次转换`,
            updated: n.updated_at,
            status: novelStatus(n),
            badges: [] as string[],
        })),
        ...scripts.map((s) => ({
            type: "script" as const,
            id: s.script_id,
            title: s.title || "剧本",
            desc: s.summary || `共 ${s.scene_count} 个场景`,
            updated: s.updated_at,
            status: "",
            badges: entityBadges(s.summary),
        })),
    ]
        .sort((a, b) => (b.updated ?? "").localeCompare(a.updated ?? ""))
        .slice(0, 8);

    // Filtered items
    const novelFiltered = novels.filter((n) => !searchText || n.title.includes(searchText));
    const scriptFiltered = scripts.filter((s) => {
        if (searchText && !s.title?.includes(searchText) && !s.summary?.includes(searchText)) return false;
        if (tagFilter.length > 0 && !entityBadges(s.summary).some((b) => tagFilter.includes(b))) return false;
        return true;
    });

    // ── Actions ─────────────────────────────────────────────────────

    const handlePasteUpload = async () => {
        if (!pasteText.trim()) return;
        setUploading(true);
        try {
            const upRes = await uploadNovel(pasteText.trim(), uploadTitle || undefined);
            message.success(upRes.task_id ? "上传成功，转换任务已创建" : "上传成功");
            setUploadOpen(false);
            setPasteText("");
            setUploadTitle("");
            load();
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
            message.success(upRes.task_id ? "上传成功，转换任务已创建" : "上传成功");
            setUploadOpen(false);
            setUploadTitle("");
            load();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "上传失败");
        } finally {
            setUploading(false);
        }
        return false;
    };

    const handleBlankScript = async () => {
        try {
            const res = await createScript("未命名剧本", "standalone");
            message.success("空白剧本已创建");
            navigate(`/workspace/${res.script_id}`);
        } catch {
            message.error("创建剧本失败");
        }
    };

    const handleNewConversion = async (novelId: string) => {
        try {
            await createTask(novelId);
            message.success("转换任务已创建");
            load(); // Refresh list — Script will appear when pipeline completes
        } catch {
            message.error("创建任务失败");
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

    // ── Card renderers ──────────────────────────────────────────────

    const renderNovelCard = (n: Novel) => {
        const st = novelStatus(n);
        return (
            <Card
                key={n.id}
                hoverable
                size="small"
                className="ns-workspace-card ns-workspace-card-novel"
                onClick={() => {
                    if (blockNav.current) {
                        blockNav.current = false;
                        return;
                    }
                    const scr = scriptsByNovel[n.id]?.[0];
                    if (scr) navigate(`/workspace/${scr.script_id}`);
                }}
                title={
                    <div className="ns-workspace-card-header">
                        <span className="ns-workspace-card-title">《{n.title}》</span>
                        <span onClick={(e) => e.stopPropagation()}>
                            <Popconfirm
                                title="确定删除此小说及其所有剧本？"
                                onConfirm={() => handleDeleteNovel(n.id)}
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
                            <Button
                                type="text"
                                size="small"
                                icon={<EditOutlined />}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    handleRenameClick(n);
                                }}
                            />
                        </span>
                    </div>
                }
            >
                <div className="ns-workspace-card-meta">
                    <span className="ns-workspace-card-stat">
                        <BookOutlined /> {(n.word_count ?? 0).toLocaleString()} 字
                    </span>
                    {n.author && <span className="ns-workspace-card-stat">{n.author}</span>}
                </div>
                {st && <Tag color={STATUS_COLOR[st] || "default"}>{STATUS_LABEL[st] || st}</Tag>}
                {!st && (
                    <Button
                        size="small"
                        type="dashed"
                        icon={<PlusOutlined />}
                        onClick={(e) => {
                            e.stopPropagation();
                            handleNewConversion(n.id);
                        }}
                    >
                        开始转换
                    </Button>
                )}
            </Card>
        );
    };

    const renderScriptCard = (s: ScriptLight) => (
        <Card
            key={s.script_id}
            hoverable
            size="small"
            className="ns-workspace-card ns-workspace-card-script"
            onClick={() => {
                if (blockNav.current) {
                    blockNav.current = false;
                    return;
                }
                navigate(`/workspace/${s.script_id}`);
            }}
            title={
                <div className="ns-workspace-card-header">
                    <span className="ns-workspace-card-title">{s.title || "剧本"}</span>
                    <span onClick={(e) => e.stopPropagation()}>
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
            }
        >
            <p className="ns-workspace-card-snippet">{snippet(s.summary)}</p>
            <div className="ns-workspace-card-footer">
                <div className="ns-workspace-card-badges">
                    {s.scene_count > 0 && <Tag>{s.scene_count} 个场景</Tag>}
                    {s.source_type === "forked" && <Tag color="purple">副本</Tag>}
                    {entityBadges(s.summary).map((b) => (
                        <Tag key={b} color="blue">
                            {b}
                        </Tag>
                    ))}
                </div>
            </div>
        </Card>
    );

    const renderRecentItem = (item: (typeof recentItems)[number]) => (
        <div
            key={`${item.type}-${item.id}`}
            className="ns-workspace-recent-item"
            onClick={() => {
                if (item.type === "script") {
                    navigate(`/workspace/${item.id}`);
                    return;
                }
                const linked = scriptsByNovel[item.id]?.[0];
                if (linked) navigate(`/workspace/${linked.script_id}`);
            }}
            style={{ cursor: item.type === "script" || scriptsByNovel[item.id]?.length ? "pointer" : "default" }}
        >
            <div className="ns-workspace-recent-item-type">
                {item.type === "novel" ? <BookOutlined /> : <FileTextOutlined />}
                <span>{item.type === "novel" ? "小说" : "剧本"}</span>
            </div>
            <div className="ns-workspace-recent-item-body">
                <span className="ns-workspace-recent-item-title">{item.title}</span>
                <span className="ns-workspace-recent-item-desc">{snippet(item.desc)}</span>
            </div>
            {item.type === "novel" && item.status && (
                <Tag color={STATUS_COLOR[item.status] || "default"} style={{ flexShrink: 0 }}>
                    {STATUS_LABEL[item.status] || item.status}
                </Tag>
            )}
            {item.type === "script" && item.badges.length > 0 && (
                <div className="ns-workspace-recent-item-badges">
                    {item.badges.slice(0, 2).map((b) => (
                        <Tag key={b} color="blue" style={{ fontSize: 10 }}>
                            {b}
                        </Tag>
                    ))}
                </div>
            )}
        </div>
    );

    // ── Render ──────────────────────────────────────────────────────

    if (loading) {
        return (
            <div className="ns-workspace-loading">
                <div className="ns-spinner" />
                <span className="ns-workspace-loading-text">加载中...</span>
            </div>
        );
    }

    return (
        <>
            <AppHeader>
                <Button icon={<DashboardOutlined />} onClick={() => navigate("/dashboard")}>
                    仪表板
                </Button>
                <Dropdown
                    menu={{
                        items: [
                            { key: "blank", label: "新建空白剧本", icon: <FileTextOutlined /> },
                            { key: "upload", label: "从小说转换", icon: <UploadOutlined /> },
                        ],
                        onClick: ({ key }) => {
                            if (key === "blank") handleBlankScript();
                            else setUploadOpen(true);
                        },
                    }}
                >
                    <Button type="primary" size="small" icon={<PlusOutlined />}>
                        新建剧本
                    </Button>
                </Dropdown>
            </AppHeader>

            <div className="ns-workspace-page">
                <header className="ns-page-title">
                    <h1>创作空间</h1>
                </header>

                {/* Search + Filter */}
                <div className="ns-workspace-search-bar">
                    <Input
                        prefix={<SearchOutlined style={{ color: "var(--color-text-muted)" }} />}
                        placeholder="搜索小说名称或剧本内容..."
                        value={searchText}
                        onChange={(e) => setSearchText(e.target.value)}
                        allowClear
                        style={{ flex: 1, maxWidth: 420 }}
                    />
                    {allTags.length > 0 && (
                        <div className="ns-workspace-tag-filter">
                            {allTags.map((tag) => (
                                <Tag.CheckableTag
                                    key={tag}
                                    checked={tagFilter.includes(tag)}
                                    onChange={(checked) =>
                                        setTagFilter(checked ? [...tagFilter, tag] : tagFilter.filter((t) => t !== tag))
                                    }
                                    style={{ fontSize: 11 }}
                                >
                                    {tag}
                                </Tag.CheckableTag>
                            ))}
                            {tagFilter.length > 0 && (
                                <Button type="link" size="small" onClick={() => setTagFilter([])}>
                                    清除
                                </Button>
                            )}
                        </div>
                    )}
                </div>

                {/* Recent updates */}
                {recentItems.length > 0 && (
                    <section className="ns-workspace-section">
                        <h2 className="ns-workspace-section-title">
                            <FireOutlined /> 最近更新
                        </h2>
                        <div className="ns-workspace-recent-list">{recentItems.map(renderRecentItem)}</div>
                    </section>
                )}

                {/* Tabs: Novels / Scripts */}
                <section className="ns-workspace-section">
                    <div className="ns-workspace-section-tabs">
                        <h2 className="ns-workspace-section-title">全部内容</h2>
                        <Tabs
                            activeKey={tab}
                            onChange={(k) => setTab(k as typeof tab)}
                            size="small"
                            style={{ marginBottom: 0 }}
                            items={[
                                { key: "all", label: "全部" },
                                { key: "novels", label: `小说 (${novelFiltered.length})` },
                                { key: "scripts", label: `剧本 (${scriptFiltered.length})` },
                            ]}
                        />
                    </div>

                    {(tab === "all" || tab === "novels") && novelFiltered.length > 0 && (
                        <>
                            <h3 className="ns-workspace-sub-title">
                                <BookOutlined /> 小说
                            </h3>
                            <div className="ns-workspace-card-grid">{novelFiltered.map(renderNovelCard)}</div>
                        </>
                    )}

                    {(tab === "all" || tab === "scripts") && (
                        <>
                            <h3 className="ns-workspace-sub-title">
                                <FileTextOutlined /> 剧本
                            </h3>
                            <div className="ns-workspace-card-grid">
                                {scriptFiltered.map(renderScriptCard)}
                                {scriptFiltered.length === 0 && (
                                    <div className="ns-workspace-empty-hint">暂无剧本。从小说转换或新建空白剧本</div>
                                )}
                            </div>
                        </>
                    )}

                    {novelFiltered.length === 0 && scriptFiltered.length === 0 && (
                        <div className="ns-workspace-empty-hint">
                            {novels.length === 0
                                ? user
                                    ? "还没有小说或剧本，点击上方「新建剧本」开始吧"
                                    : "请先登录"
                                : "没有匹配的小说或剧本，请调整搜索条件"}
                        </div>
                    )}
                </section>

                {/* Upload Modal */}
                <Modal
                    title="从小说转换 — 上传小说文件"
                    open={uploadOpen}
                    onCancel={() => {
                        setUploadOpen(false);
                        setUploadTitle("");
                    }}
                    footer={null}
                    destroyOnHidden
                >
                    <div style={{ marginBottom: 12 }}>
                        <label className="ns-workspace-upload-label">小说标题（选填，留空则自动从正文提取）</label>
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
                        <Button type="primary" onClick={handlePasteUpload} loading={uploading} style={{ marginTop: 8 }} block>
                            提交文本
                        </Button>
                    </div>
                    <div className="ns-workspace-upload-or">或</div>
                    <Upload.Dragger accept=".txt,.md" maxCount={1} beforeUpload={handleFileUpload} showUploadList={false}>
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
                    <div className="ns-workspace-rename-form">
                        <div>
                            <label className="ns-workspace-upload-label">标题</label>
                            <Input
                                value={renameTitle}
                                onChange={(e) => setRenameTitle(e.target.value)}
                                placeholder="小说标题"
                            />
                        </div>
                        <div>
                            <label className="ns-workspace-upload-label">作者</label>
                            <Input
                                value={renameAuthor}
                                onChange={(e) => setRenameAuthor(e.target.value)}
                                placeholder="作者（选填）"
                            />
                        </div>
                    </div>
                </Modal>
            </div>
        </>
    );
}
