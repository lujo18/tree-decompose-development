// Global contracts for the Tree Decompose Development Engine itself.
// This file is a template. Replace with contracts for your target project.

export interface User {
  id: string;
  email: string;
  name: string;
  createdAt: Date;
}

export interface Project {
  id: string;
  ownerId: string;
  name: string;
  template: ProjectTemplate;
  status: ProjectStatus;
}

export enum ProjectStatus {
  Draft = "draft",
  Building = "building",
  Deployed = "deployed",
  Failed = "failed",
}

export interface ProjectTemplate {
  id: string;
  name: string;
  stack: string;
  defaultConfig: Record<string, unknown>;
}

export interface DeploymentHook {
  id: string;
  projectId: string;
  provider: "vercel" | "railway" | "netlify";
  config: Record<string, unknown>;
}

export interface BillingSubscription {
  id: string;
  userId: string;
  stripeCustomerId: string;
  plan: string;
  status: "active" | "canceled" | "past_due";
}

export interface AuthSession {
  token: string;
  user: User;
  expiresAt: Date;
}

export function validateSession(token: string): Promise<AuthSession | null>;
export function createProject(ownerId: string, templateId: string, name: string): Promise<Project>;
export function deployProject(projectId: string): Promise<DeploymentHook>;
