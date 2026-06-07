import { Progress, Button } from "antd";
import { SyncOutlined } from "@ant-design/icons";
import { useTaskStore } from "../../stores/task-store";
import { resumeTask } from "../../api/tasks";

export function StatusBar() {
  const progress = useTaskStore((s) => s.progress);
  const status = useTaskStore((s) => s.status);
  const stage = useTaskStore((s) => s.stage);
  const taskId = useTaskStore((s) => s.taskId);
  const error = useTaskStore((s) => s.errorMessage);

  const STAGE_LABEL: Record<string, string> = {
    starting: "启动中",
    chunking: "分章中",
    graphrag: "图谱构建中",
    rag: "索引构建中",
    converting: "转换中",
    optimizing: "优化中",
    assembling: "组装中",
  };

  const handleResume = async () => {
    if (!taskId) return;
    await resumeTask(taskId);
  };

  return (
    <footer className="ns-statusbar">
      {/* Left: progress */}
      <div className="ns-statusbar-progress">
        {(status === "preprocessing" || status === "converting") && (
          <>
            <Progress
              percent={progress}
              size="small"
              status={status === "converting" ? "active" : "normal"}
              strokeColor="var(--color-accent-primary)"
              style={{ flex: 1 }}
            />
            {stage && STAGE_LABEL[stage] && (
              <span className="ns-statusbar-stage">
                {STAGE_LABEL[stage]}
              </span>
            )}
          </>
        )}
      </div>

      {/* Center: error */}
      {error && (
        <span className="ns-statusbar-error">
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
