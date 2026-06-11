import { request } from "./client";

export interface RecentTask {
  task_id: string;
  script_id: string | null;
  novel_title: string;
  status: string;
  progress: number;
  created_at: string | null;
}

export interface RecentScript {
  script_id: string;
  title: string;
  source_type: string;
  status: string;
  scene_count: number;
  updated_at: string | null;
}

export interface RecentNovel {
  id: string;
  title: string;
  word_count: number;
  status: string;
  updated_at: string | null;
}

export interface DashboardData {
  stats: {
    novels: number;
    scripts: number;
    in_progress: number;
    completed: number;
    failed: number;
  };
  recent_tasks: RecentTask[];
  recent_scripts: RecentScript[];
  recent_novels: RecentNovel[];
}

export function getDashboard() {
  return request<DashboardData>("/dashboard");
}
