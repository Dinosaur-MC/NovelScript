import { useNavigate } from "react-router";
import { Button, Card, Row, Col, Tag } from "antd";
import {
  RocketOutlined,
  ThunderboltOutlined,
  NodeIndexOutlined,
  CodeOutlined,
  ExportOutlined,
  SafetyCertificateOutlined,
  BookOutlined,
  FileTextOutlined,
  ArrowRightOutlined,
} from "@ant-design/icons";

/** Single feature card */
function FeatureCard({
  icon,
  title,
  desc,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <Card className="nl-feature-card" bordered={false}>
      <div className="nl-feature-icon">{icon}</div>
      <h3 className="nl-feature-title">{title}</h3>
      <p className="nl-feature-desc">{desc}</p>
    </Card>
  );
}

/** Pipeline stage */
function PipelineStage({
  step,
  label,
  icon,
}: {
  step: number;
  label: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="nl-pipeline-stage">
      <div className="nl-pipeline-icon">{icon}</div>
      <span className="nl-pipeline-step">0{step}</span>
      <span className="nl-pipeline-label">{label}</span>
    </div>
  );
}

export function Landing() {
  const navigate = useNavigate();

  return (
    <div className="nl-page">

      {/* ═══════════ Navigation ═══════════ */}
      <nav className="ns-app-header nl-nav--transparent">
        <div className="ns-app-header-left">
          <span className="ns-app-header-brand">NovelScript <span className="ns-app-header-sub">析幕</span></span>
        </div>
        <div className="ns-app-header-right">
          <Button type="text" onClick={() => navigate("/login")}>登录</Button>
          <Button type="primary" onClick={() => navigate("/workspace")}>开始使用</Button>
        </div>
      </nav>

      {/* ═══════════ Hero ═══════════ */}
      <section className="nl-hero">
        <div className="nl-hero-bg" />
        <div className="nl-hero-body">
          <h1 className="nl-hero-title">
            将小说<span className="nl-hero-accent">转化为结构化剧本</span>
          </h1>
          <p className="nl-hero-sub">
            AI 驱动的长篇小说到 Fountain 1.1 / YAML 剧本转换引擎。
            支持中文长篇，自研确定性管道保证输出质量。
          </p>
          <div className="nl-hero-actions">
            <Button type="primary" size="large" icon={<RocketOutlined />} onClick={() => navigate("/login")}>
              立即体验
            </Button>
            <Button size="large" onClick={() => navigate("/workspace")}>
              进入创作空间
            </Button>
          </div>
          <div className="nl-hero-stats">
            <div className="nl-stat"><strong>8</strong> 管道阶段</div>
            <div className="nl-stat"><strong>Fountain 1.1</strong> 格式兼容</div>
            <div className="nl-stat"><strong>20</strong> 节点知识图谱</div>
            <div className="nl-stat"><strong>384K</strong> 输出令牌</div>
          </div>
        </div>
      </section>

      {/* ═══════════ Pipeline ═══════════ */}
      <section className="nl-section">
        <h2 className="nl-section-title">智能转换流水线</h2>
        <p className="nl-section-sub">从原始文本到完整剧本，八阶段确定性处理</p>

        <div className="nl-pipeline-row">
          <PipelineStage step={1} label="智能分章" icon={<BookOutlined />} />
          <span className="nl-pipeline-arrow">→</span>
          <PipelineStage step={2} label="章节摘要" icon={<FileTextOutlined />} />
          <span className="nl-pipeline-arrow">→</span>
          <PipelineStage step={3} label="向量索引" icon={<NodeIndexOutlined />} />
          <span className="nl-pipeline-arrow">→</span>
          <PipelineStage step={4} label="知识图谱" icon={<ThunderboltOutlined />} />
        </div>
        <div className="nl-pipeline-row" style={{ marginTop: 0 }}>
          <PipelineStage step={5} label="剧本转换" icon={<CodeOutlined />} />
          <span className="nl-pipeline-arrow">→</span>
          <PipelineStage step={6} label="后处理" icon={<SafetyCertificateOutlined />} />
          <span className="nl-pipeline-arrow">→</span>
          <PipelineStage step={7} label="一致性优化" icon={<ExportOutlined />} />
          <span className="nl-pipeline-arrow">→</span>
          <PipelineStage step={8} label="叙事梗概" icon={<FileTextOutlined />} />
        </div>

        <p className="nl-pipeline-note">
          第 6 阶段为完全确定性处理（无 LLM），包含 ID 分配、场标标准化、元素类型修正、微场景合并等规则化清理。
          所有 LLM 阶段均支持指数退避重试与阶段级故障容忍。
        </p>
      </section>

      {/* ═══════════ Features ═══════════ */}
      <section className="nl-section">
        <h2 className="nl-section-title">核心特性</h2>
        <p className="nl-section-sub">为长篇小说创作量身打造</p>

        <Row gutter={[20, 20]} justify="center" style={{ maxWidth: 960, margin: "0 auto" }}>
          <Col xs={24} sm={12}>
            <FeatureCard
              icon={<RocketOutlined />}
              title="AI 驱动"
              desc="基于 DeepSeek V4 系列模型，支持百万 token 上下文，整本小说一次转换"
            />
          </Col>
          <Col xs={24} sm={12}>
            <FeatureCard
              icon={<NodeIndexOutlined />}
              title="知识图谱"
              desc="自动构建角色、地点、事件关系网络，支持可视化浏览和 AI 增强编辑"
            />
          </Col>
          <Col xs={24} sm={12}>
            <FeatureCard
              icon={<CodeOutlined />}
              title="双向溯源"
              desc="每个剧本元素精确锚定至原文段落，一键跳转原文和 YAML 源"
            />
          </Col>
          <Col xs={24} sm={12}>
            <FeatureCard
              icon={<ExportOutlined />}
              title="标准导出"
              desc="YAML / JSON / Fountain 1.1 三大格式，兼容主流剧本编辑工具"
            />
          </Col>
          <Col xs={24} sm={12}>
            <FeatureCard
              icon={<ThunderboltOutlined />}
              title="确定性管道"
              desc="严格验证 + Pydantic V2 校验，所有 LLM 输出通过严格模式检查"
            />
          </Col>
          <Col xs={24} sm={12}>
            <FeatureCard
              icon={<SafetyCertificateOutlined />}
              title="AI 协作编辑"
              desc="内置 GraphRAG 增强的 AI 助手，支持对话式编辑和 JSON Patch 操作"
            />
          </Col>
        </Row>
      </section>

      {/* ═══════════ CTA ═══════════ */}
      <section className="nl-cta">
        <h2 className="nl-cta-title">准备好了吗？</h2>
        <p className="nl-cta-sub">上传小说，几分钟内获得完整的结构化剧本</p>
        <Button type="primary" size="large" icon={<ArrowRightOutlined />} onClick={() => navigate("/login")}>
          开始转换
        </Button>
      </section>

      {/* ═══════════ Footer ═══════════ */}
      <footer className="nl-footer">
        <span>NovelScript 析幕</span>
        <span className="nl-footer-divider">|</span>
        <span>AI 驱动的剧本转换系统</span>
        <span className="nl-footer-divider">|</span>
        <span>Fountain 1.1 · YAML · JSON</span>
      </footer>
    </div>
  );
}
