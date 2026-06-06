import { Progress, Button } from "antd";
import { SyncOutlined } from "@ant-design/icons";
import { useTaskStore } from "../../stores/task-store";
import { resumeTask } from "../../api/tasks";

export function StatusBar() {
  const progress = useTaskStore((s) => s.progress);
  const status = useTaskStore((s) => s.status);
  const taskId = useTaskStore((s) => s.taskId);
  const error = useTaskStore((s) => s.errorMessage);

  const handleResume = async () => {
    if (!taskId) return;
    await resumeTask(taskId);
  };

  return (
    <footer
      style={{
        height: 32,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 16px",
        backgroundColor: "var(--color-bg-surface)",
        borderTop: "1px solid var(--color-border-subtle)",
        flexShrink: 0,
        gap: 16,
      }}
    >
      {/* Left: progress */}
      <div style={{ flex: 1, maxWidth: 300 }}>
        {(status === "preprocessing" || status === "converting") && (
          <Progress
            percent={progress}
            size="small"
            status={status === "converting" ? "active" : "normal"}
            strokeColor="var(--color-accent-primary)"
          />
        )}
      </div>

      {/* Center: error */}
      {error && (
        <span style={{ color: "var(--color-accent-danger)", fontSize: 12, flex: 1 }}>
          {error}
        </span>
      )}

      {/* Right: resume */}
      {status === "failed" && taskId && (
        <Button size="small" icon={<SyncOutlined />} onClick={handleResume}>
          重试
        </Button>
      )}
    </footer>
  );
}
